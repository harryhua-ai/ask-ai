"""R6v2(G3 阻塞 2):宿主 update.sh 受信分发与 mutation 前能力钉扎。

权威依据:Role A R6 离线审查 REQUEST_CHANGES(2026-10-20,阻塞 2):
生产宿主 ~/ask-ai 非 git 仓库,update.sh 不随主干/镜像自动升级;R6 只改了
源码树副本;workflow 顺序 preflight(3) → migrate(4) → 宿主 update.sh(5),
旧宿主脚本若到步骤5 才因未知参数失败,已过 migration 边界。修复 = 新增
provision_host_script 步骤(3.6,先于迁移):受信工件 = 冻结发行树
$RELEASE_SHA 内的 deploy/prod/update.sh(git 权威解析),经 SSH stdin 以
base64 安全分发 → 同目录 0600 临时件 → 宿主侧 SHA256 核对(传输中断/截断
⇒ 拒绝)→ 能力断言(--remediation-evidence-file 支持)→ bash -n → 同目录
原子 rename 安装(无半更新窗口)→ 安装后哈希复核;步骤5 执行前再复验宿主
哈希(防 provision 后漂移)。任何失败 ⇒ 迁移之前中止。

本沙箱走真实执行路径:从 deploy-production.yml 机械提取 provision_host_script
与 deploy 两步的真实 run 文本执行(fake ssh / fake docker / fake curl /
fake nvidia-smi / fake flock);preflight 与 migrate 以保形桩替代 —— 真实
preflight 行为由 test_r3gate_*(T-SEC/T-WV/T-RT)沙箱覆盖,本文件证明:
步骤真实顺序、provision 全部故障注入在迁移前 fail-closed、迁移零调用、
部署阶段消费钉扎脚本与整改证据。

红线:全部离线确定性;密钥/工件为测试自造信任根;不连生产、不 push、
不改门值;测试信任根绝不宣称生产已整改。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
EVALUATOR_SRC = REPO / "scripts" / "release_preflight.py"
UPDATE_SH_SRC = REPO / "deploy" / "prod" / "update.sh"

TAG = "v1.0.0"
GATE = "gate-token-x"
FAKE_SHA = "b" * 40


def _step_text(step_id: str) -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["deploy"]["steps"]
    return [s for s in steps if s.get("id") == step_id][0]["run"]


def _step_ids() -> list[str]:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [s.get("id") for s in wf["jobs"]["deploy"]["steps"] if s.get("id")]


class Sandbox:
    """受控多步沙箱:fake 宿主文件系统 + fake ssh/docker/curl/nvidia-smi。"""

    def __init__(self, tmp: Path):
        self.base = tmp
        self.host = tmp / "host"
        self.askai = self.host / "ask-ai"
        self.prod = self.askai / "deploy" / "prod"
        self.runner = tmp / "runner"
        self.bin = tmp / "bin"
        self.logs = tmp / "logs"
        for d in (self.prod, self.runner, self.bin, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        self.ssh_argv = self.logs / "ssh_argv.log"
        self.update_argv = self.logs / "update_argv.log"
        self.remote_out = self.logs / "remote_out.log"
        self.migrate_log = self.logs / "migrate.log"
        self._write_shims()
        # fake 宿主仓库骨架(~/ask-ai)
        (self.askai / ".env").write_text(
            "BACKEND_PORT=18000\n", encoding="utf-8"
        )
        (self.prod / "docker-compose.yml").write_text(
            "services: {}\n", encoding="utf-8"
        )
        # 受信工件快照仓:tmp git 仓库提交当前 update.sh 工作树内容,
        # RELEASE_SHA 指向该提交(真实 repo HEAD 可能落后于工作树 —— 脏树
        # 守卫会正确拒绝;测试需要自洽的"冻结树")
        self.snapshot = tmp / "snapshot-repo"
        self.snapshot.mkdir()
        (self.snapshot / "deploy" / "prod").mkdir(parents=True)
        shutil.copy2(UPDATE_SH_SRC, self.snapshot / "deploy" / "prod" / "update.sh")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "add", "-A"],
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "snap"],
        ):
            subprocess.run(cmd, cwd=str(self.snapshot), check=True, capture_output=True)
        self.release_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(self.snapshot),
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    # ------------------------------------------------------------------ shims
    def _write_shims(self) -> None:
        self._shim_paths: list[Path] = []
        # fake flock:fd 形态(flock -w 0 9)⇒ exit 0;文件+命令形态
        # (flock -w 0 FILE CMD...)⇒ 执行命令(update.sh 原语必须真跑)
        (self.bin / "flock").write_text(
            "#!/bin/bash\n"
            'if [ "$#" -ge 4 ] && [ "$1" = "-w" ] && [ "$2" = "0" ]; then\n'
            "  shift 3\n"
            '  case "$1" in\n'
            '    *[!0-9]*) exec "$@" ;;\n'
            "    *) exit 0 ;;\n"
            "  esac\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (self.bin / "nvidia-smi").write_text(
            "#!/bin/bash\necho 1000\n", encoding="utf-8"
        )
        # macOS BSD mktemp 不支持 'prefix.XXXXXX.suffix' 模板(GNU 支持,
        # 生产 Linux 无此问题);沙箱垫片生成同目录唯一文件并打印路径
        (self.bin / "mktemp").write_text(
            "#!/bin/bash\n"
            'args=()\n'
            'for a in "$@"; do case "$a" in -*) ;; *) args+=("$a") ;; esac; done\n'
            't="${args[0]:-${TMPDIR:-/tmp}/askai-mk.XXXXXXXX}"\n'
            'd="$(dirname "$t")"\n'
            'n=0\n'
            'while :; do\n'
            '  f="$d/askai-mk.$$.$n.$RANDOM"\n'
            '  [ -e "$f" ] || { touch "$f"; printf "%s\\n" "$f"; exit 0; }\n'
            '  n=$((n+1))\n'
            "done\n",
            encoding="utf-8",
        )
        (self.bin / "curl").write_text(
            '#!/bin/bash\nprintf \'{"version":"%s"}\' "${TSL_FAKE_VERSION:-1.0.0}"\n',
            encoding="utf-8",
        )
        # mv 注入点:默认透传;TSL_FAIL_MV=1 时确定性失败(安装失败注入)
        (self.bin / "mv").write_text(
            "#!/bin/bash\n"
            'if [ -n "${TSL_FAIL_MV:-}" ]; then echo "fake mv: injection failure" >&2; exit 1; fi\n'
            'exec /bin/mv "$@"\n',
            encoding="utf-8",
        )
        (self.bin / "ssh").write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$TSL_SSH_ARGV_LOG"\n'
            'remote_cmd="${@: -1}"\n'
            'script="$(cat)"\n'
            'echo "SCRIPT_LEN:${#script}" >> "$TSL_SSH_ARGV_LOG"\n'
            # 传输中断注入 1:连接在 env 前缀(含受信工件 base64)传输中途断开
            # ⇒ 命令串被截断 ⇒ 远端执行失败(fail-closed,零远端 mutation)
            'if [ -n "${TSL_SSH_TRUNCATE_CMD:-}" ]; then remote_cmd="${remote_cmd:0:$TSL_SSH_TRUNCATE_CMD}"; fi\n'
            # 传输中断注入 2:受信工件 base64 尾部被截(常见网络截断形态)⇒
            # 远端 base64 解码失败/内容截断 ⇒ 宿主侧哈希核对拒绝
            'if [ -n "${TSL_PROVISION_B64_OVERRIDE:-}" ]; then\n'
            '  remote_cmd="$(printf "%s" "$remote_cmd" | sed "s|TRUSTED_UPDATE_SH_B64=\'[^\']*\'|TRUSTED_UPDATE_SH_B64=\'${TSL_PROVISION_B64_OVERRIDE}\'|")"\n'
            "fi\n"
            'if [ -n "${TSL_SSH_FAIL:-}" ]; then echo "fake ssh: connection lost" >&2; exit 255; fi\n'
            f'cd "{self.askai}"\n'
            'printf "%s" "$script" | PATH="$TSL_FAKE_BIN:$PATH" bash -c "$remote_cmd" \\\n'
            '  >> "$TSL_REMOTE_OUT" 2>&1\n',
            encoding="utf-8",
        )
        (self.bin / "docker").write_text(
            "#!/bin/bash\n"
            'args=()\n'
            'while [ $# -gt 0 ]; do args+=("$1"); shift; done\n'
            'case "${args[0]}" in\n'
            "  pull) exit 0 ;;\n"
            "  create) echo fakecid00000000 ;;\n"
            "  rm) exit 0 ;;\n"
            "  cp)\n"
            '    src="${args[1]}"; dest="${args[$((${#args[@]} - 1))]}"\n'
            '    case "$src" in\n'
            '      *RELEASE.json)\n'
            '        printf \'{"version":"%s","git_sha":"%s","compatibility_contract":true}\' \\\n'
            '          "${TSL_FAKE_VERSION:-1.0.0}" "${TSL_FAKE_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" > "$dest" ;;\n'
            '      *release_preflight.py) cp "$TSL_EVALUATOR_SRC" "$dest" ;;\n'
            '      *compatibility.json)\n'
            '        if [ "${TSL_COMPAT_INCOMPATIBLE:-}" = "1" ]; then\n'
            '          printf \'{"version":1,"config":[],"host":[],"topology":[],"dependencies":[],"rollback":{"previous_compatible":false,"remediation_gate":"%s"}}\' \\\n'
            '            "${TSL_COMPAT_GATE:-gate-token-x}" > "$dest"\n'
            "        else\n"
            '          printf \'{"version":1,"config":[],"host":[],"topology":[],"dependencies":[],"rollback":{"previous_compatible":true}}\' > "$dest"\n'
            "        fi ;;\n"
            "      *) exit 1 ;;\n"
            "    esac ;;\n"
            "  inspect)\n"
            '    echo "ghcr.io/harryhua-ai/ask-ai:${TSL_FAKE_TAG:-v1.0.0}" ;;\n'
            "  compose)\n"
            '    case "${args[2]}" in\n'
            '      ps) if [ "${args[3]}" = "-q" ]; then echo fakecid00000001; else exit 0; fi ;;\n'
            "      *) exit 0 ;;\n"
            "    esac ;;\n"
            '  *) echo "fake docker: unexpected $*" >&2; exit 1 ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        for shim in self.bin.iterdir():
            os.chmod(shim, 0o755)

    # ------------------------------------------------------------------ env
    def base_env(self) -> dict:
        env = dict(os.environ)
        env.update(
            {
                "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                "RUNNER_TEMP": str(self.runner),
                "TSL_FAKE_BIN": str(self.bin),
                "TSL_SSH_ARGV_LOG": str(self.ssh_argv),
                "TSL_REMOTE_OUT": str(self.remote_out),
                "TSL_UPDATE_ARGV_LOG": str(self.update_argv),
                "TSL_MIGRATE_LOG": str(self.migrate_log),
                "TSL_EVALUATOR_SRC": str(EVALUATOR_SRC),
                "TSL_FAKE_VERSION": TAG[1:],  # RELEASE.json version 无 v 前缀
                "TSL_FAKE_TAG": TAG,  # 镜像 ref 带完整 v 前缀 tag
                "TSL_FAKE_SHA": FAKE_SHA,
                "SSH_KEY": "fake-key-material",
                "SSH_HOST": "tesla-t4.fake.invalid",
                "SSH_USER": "ubuntu",
                "SSH_KNOWN_HOSTS_B64": base64.b64encode(
                    b"tesla-t4.fake.invalid ssh-ed25519 AAAAFAKE\n"
                ).decode(),
                "DEPLOY_TAG": TAG,
                "RELEASE_SHA": self.release_sha,
                # 宿主侧 ~/ask-ai 必须解析到沙箱(绝不触碰真实用户 HOME)
                "HOME": str(self.host),
            }
        )
        return env

    # ------------------------------------------------------------- step runs
    def run_step(self, step_id: str, env: dict, timeout: int = 120):
        if step_id == "preflight":
            # 保形桩:真实 preflight 行为由 T-SEC/T-WV/T-RT 沙箱覆盖;此处只
            # 提供"成功/失败"语义以证明顺序与 abort 语义。
            run = 'if [ -n "${TSL_PREFLIGHT_FAIL:-}" ]; then echo "stub preflight fail" >&2; exit 2; fi\necho PREFLIGHT_STUB_OK\n'
        elif step_id == "migrate":
            # 迁移调用计数桩(保持其在真实步骤序中的位置)
            run = 'echo "MIGRATE_INVOKED" >> "$TSL_MIGRATE_LOG"\n'
        else:
            run = _step_text(step_id)
        script = self.logs / f"step_{step_id}.sh"
        script.write_text(run, encoding="utf-8")
        proc = subprocess.run(  # noqa: S603 - 固定词表 argv
            ["/bin/bash", str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(self.snapshot),
            check=False,
        )
        return proc

    def run_pipeline(
        self,
        *,
        preflight_fail: bool = False,
        evidence: dict | None = None,
        artifact: bytes | None = None,
        approval_key_b64: str | None = None,
        compat_incompatible: bool = True,
    ) -> dict:
        """按 workflow 真实顺序执行 preflight → provision → migrate → deploy。"""
        env = self.base_env()
        env["TSL_COMPAT_INCOMPATIBLE"] = "1" if compat_incompatible else "0"
        if preflight_fail:
            env["TSL_PREFLIGHT_FAIL"] = "1"
        # 记录 + 工件经 secret 通道(env);审批密钥经宿主 .env(生产同路)
        env["REMEDIATION_EVIDENCE_B64"] = (
            base64.b64encode(json.dumps(evidence).encode()).decode()
            if evidence is not None
            else ""
        )
        env["REMEDIATION_ARTIFACT_B64"] = (
            base64.b64encode(artifact or b"").decode() if artifact is not None else ""
        )
        if approval_key_b64:
            env_path = self.askai / ".env"
            env_path.write_text(
                env_path.read_text(encoding="utf-8")
                + f"PREFLIGHT_REMEDIATION_APPROVAL_KEY={approval_key_b64}\n",
                encoding="utf-8",
            )
        # 旧宿主脚本种子(历史版本:不含 R6v2 能力)
        old_script = "#!/bin/bash\necho old-host-update-sh\n"
        (self.prod / "update.sh").write_text(old_script, encoding="utf-8")
        os.chmod(self.prod / "update.sh", 0o750)
        old_hash = hashlib.sha256(old_script.encode()).hexdigest()

        results = {}
        for step_id in ("preflight", "provision_host_script", "migrate", "deploy"):
            if step_id == "deploy" and evidence is not None:
                # 部署步的 secret 通道在 env 中已设;保持
                pass
            proc = self.run_step(step_id, env)
            results[step_id] = proc
            if proc.returncode != 0:
                break
        results["old_host_hash"] = old_hash
        return results

    # ------------------------------------------------------------- assertions
    def host_script_text(self) -> str:
        return (self.prod / "update.sh").read_text(encoding="utf-8")

    def host_script_hash(self) -> str:
        return hashlib.sha256(self.host_script_text().encode()).hexdigest()

    def trusted_hash(self) -> str:
        r = subprocess.run(  # noqa: S603
            ["git", "show", f"{self.release_sha}:deploy/prod/update.sh"],
            cwd=str(self.snapshot), capture_output=True, check=True,
        )
        return hashlib.sha256(r.stdout).hexdigest()

    def migrate_count(self) -> int:
        if not self.migrate_log.exists():
            return 0
        return len(
            [ln for ln in self.migrate_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        )

    def update_argv_text(self) -> str:
        return (
            self.update_argv.read_text(encoding="utf-8")
            if self.update_argv.exists()
            else ""
        )


# --------------------------------------------------------------------------- #
# 测试信任根(记录 + 工件;密钥经宿主 .env 通道 —— 生产同路)
# --------------------------------------------------------------------------- #
def _make_evidence(key: bytes) -> tuple[dict, bytes]:
    from scripts.release_preflight import _approval_hmac_hex

    artifact = b"recovery-drill-evidence-bundle (test trust root)\n"
    digest = hashlib.sha256(artifact).hexdigest()
    record = {
        "version": 2,
        "gate": GATE,
        "target_tag": TAG,
        "release_sha": FAKE_SHA,  # update.sh 以镜像内 RELEASE.json git_sha 绑定
        "evidence_digest": digest,
        "evidence_ref": "recovery-drill/test/bundle",
        "recorded_at": "2026-10-20T12:00:00+00:00",
        "recorded_by": "role-a",
        "not_after": "2099-01-01T00:00:00+00:00",
        "approval": {
            "approved_by": "role-a",
            "approved_at": "2026-10-20T12:00:00+00:00",
            "hmac_sha256": "0" * 64,
        },
    }
    record["approval"]["hmac_sha256"] = _approval_hmac_hex(key, record)
    return record, artifact


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


# --------------------------------------------------------------------------- #
# 行为矩阵
# --------------------------------------------------------------------------- #


def test_p01_old_host_script_provisioned_and_full_path_succeeds(sandbox):
    """P-01:旧宿主脚本(无 R6v2 能力)→ provision 原子替换为受信工件 →
    迁移恰 1 次 → 部署消费钉扎脚本 + 整改证据全链通过。"""
    key = os.urandom(48)
    record, artifact = _make_evidence(key)
    res = sandbox.run_pipeline(
        evidence=record,
        artifact=artifact,
        approval_key_b64=base64.b64encode(key).decode(),
    )
    assert res["preflight"].returncode == 0
    assert res["provision_host_script"].returncode == 0, res["provision_host_script"].stderr
    assert res["deploy"].returncode == 0, res["deploy"].stderr + res["deploy"].stdout
    # 宿主脚本 = 受信工件(内容级钉扎;旧脚本已被原子替换)
    assert sandbox.host_script_hash() == sandbox.trusted_hash()
    assert sandbox.host_script_text() == UPDATE_SH_SRC.read_text(encoding="utf-8")
    # 迁移恰一次;真实 update.sh 完整执行(部署横幅)+ 不兼容门在证据
    # 全链有效下真实放行(行为级证明:证据双通道被消费)
    assert sandbox.migrate_count() == 1
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "=== ask-ai 部署:" in out, out[-500:]
    assert "兼容性 preflight 通过" in out, out[-800:]
    assert "backend 健康" in out
    assert sandbox.remote_out.read_text(encoding="utf-8").count("HOST SCRIPT PROVISIONED") == 1

def test_p01b_stale_host_script_without_provision_fails(sandbox):
    """P-01b 负例对照:跳过 provision 的陈旧宿主脚本不接受 R6v2 参数 ⇒
    部署在 update.sh 入口 fail-closed(能力缺口的真实后果)。"""
    key = os.urandom(48)
    record, artifact = _make_evidence(key)
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["REMEDIATION_EVIDENCE_B64"] = base64.b64encode(json.dumps(record).encode()).decode()
    env["REMEDIATION_ARTIFACT_B64"] = base64.b64encode(artifact).decode()
    env_path = sandbox.askai / ".env"
    env_path.write_text(
        env_path.read_text(encoding="utf-8")
        + f"PREFLIGHT_REMEDIATION_APPROVAL_KEY={base64.b64encode(key).decode()}\n",
        encoding="utf-8",
    )
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0, "陈旧宿主脚本必须因未知参数失败(fail-closed)"


def test_p02_transfer_truncation_aborts_before_migration(sandbox):
    """P-02a:连接在受信工件(env 前缀 base64)传输中途断开 ⇒ 远端执行失败
    ⇒ provision 非零、旧脚本原状、迁移零调用(任何 mutation 之前)。"""
    env = sandbox.base_env()
    env["TSL_SSH_FAIL"] = "1"  # 连接中断:远端命令根本未执行
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    old_text = sandbox.host_script_text()
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode != 0
    assert sandbox.host_script_text() == old_text, "中断后旧脚本必须原状保留"
    assert sandbox.migrate_count() == 0


def test_p02b_truncated_artifact_hash_mismatch_rejected(sandbox):
    """P-02b:受信工件 base64 尾部截断(网络截断形态)⇒ 宿主侧 SHA256 核对
    拒绝安装,旧脚本原状(直接执行 provision 远端脚本文本验证该分支)。"""
    env = sandbox.base_env()
    good_b64 = base64.b64encode(
        subprocess.run(
            ["git", "show", f"{sandbox.release_sha}:deploy/prod/update.sh"],
            cwd=str(sandbox.snapshot), capture_output=True, check=True,
        ).stdout
    ).decode()
    env["TSL_PROVISION_B64_OVERRIDE"] = good_b64[:-40]  # 尾部截断(网络截断形态)
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    old_text = sandbox.host_script_text()
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode != 0
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert ("哈希不匹配" in out) or ("解码失败" in out) or ("传输为空" in out), out[-400:]
    assert sandbox.host_script_text() == old_text
    assert sandbox.migrate_count() == 0


def test_p02c_wrong_pinned_hash_rejected_direct(sandbox):
    """P-02c:钉扎哈希与工件不一致(哈希核对分支直验)⇒ 拒绝安装,
    旧脚本原状。"""
    good_b64 = base64.b64encode(
        subprocess.run(
            ["git", "show", f"{sandbox.release_sha}:deploy/prod/update.sh"],
            cwd=str(sandbox.snapshot), capture_output=True, check=True,
        ).stdout
    ).decode()
    env = sandbox.base_env()
    env["PROVISION_SHA256"] = "f" * 64  # 钉扎值被污染/错误
    env["TRUSTED_UPDATE_SH_B64"] = good_b64
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    old_text = sandbox.host_script_text()
    # 直接执行 workflow 内嵌远端脚本(provision ssh 调用的 stdin 体)
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["deploy"]["steps"]
    prov_run = [s for s in steps if s.get("id") == "provision_host_script"][0]["run"]
    m = __import__("re").search(r"<<'REMOTE'\n(.*)\n\s*REMOTE\n", prov_run + "\n", __import__("re").DOTALL)
    assert m, "provision 步骤未找到内嵌远端脚本"
    remote = m.group(1)
    script = sandbox.logs / "prov_remote.sh"
    script.write_text(remote + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True, text=True, timeout=60,
        env={**env, "PATH": f"{sandbox.bin}:/usr/bin:/bin", "HOME": str(sandbox.host)},
        cwd=str(sandbox.askai), check=False,
    )
    assert proc.returncode != 0
    assert "哈希不匹配" in proc.stderr or "哈希不匹配" in proc.stdout
    assert sandbox.host_script_text() == old_text


def test_p03_install_failure_atomic_no_half_state(sandbox):
    """P-03:原子安装注入失败(mv 失败)→ 迁移零调用,旧脚本原状,
    无半更新态(同目录临时件被 trap 清扫)。"""
    env = sandbox.base_env()
    env["TSL_FAIL_MV"] = "1"
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    old_text = sandbox.host_script_text()
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode != 0
    assert sandbox.host_script_text() == old_text
    assert sandbox.migrate_count() == 0
    leftovers = [p.name for p in sandbox.prod.iterdir() if p.name.startswith(".update-sh.provision.")]
    assert leftovers == [], f"安装临时件必须被确定性清扫: {leftovers}"


def test_p04_preflight_failure_zero_migration(sandbox):
    """P-04:preflight 失败 ⇒ 后续全部未达,迁移调用次数严格为零。"""
    res = sandbox.run_pipeline(preflight_fail=True)
    assert res["preflight"].returncode == 2
    assert "provision_host_script" not in res, "preflight 失败后不得继续 provision"
    assert sandbox.migrate_count() == 0


def test_p05_host_gate_rejects_invalid_evidence(sandbox):
    """P-05:宿主脚本正确但整改证据无效(自填 HMAC)⇒ update.sh 内
    evaluator fail-closed,部署拒绝(宿主侧回退门真实拦截)。"""
    key = os.urandom(48)
    record, artifact = _make_evidence(key)
    record["approval"]["hmac_sha256"] = "c" * 64  # 自填伪 HMAC
    res = sandbox.run_pipeline(
        evidence=record,
        artifact=artifact,
        approval_key_b64=base64.b64encode(key).decode(),
    )
    assert res["deploy"].returncode != 0, "无效证据必须被宿主侧 evaluator 拒绝"
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "审批无效" in out or "兼容性 preflight 未通过" in out


def test_p06_post_provision_drift_detected_before_deploy(sandbox):
    """P-06:provision 之后、部署之前宿主脚本被篡改 ⇒ 步骤5 前置复验拒绝。"""
    key = os.urandom(48)
    record, artifact = _make_evidence(key)
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["REMEDIATION_EVIDENCE_B64"] = base64.b64encode(json.dumps(record).encode()).decode()
    env["REMEDIATION_ARTIFACT_B64"] = base64.b64encode(artifact).decode()
    env_path = sandbox.askai / ".env"
    env_path.write_text(
        env_path.read_text(encoding="utf-8")
        + f"PREFLIGHT_REMEDIATION_APPROVAL_KEY={base64.b64encode(key).decode()}\n",
        encoding="utf-8",
    )
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0
    # provision 与 deploy 之间的漂移注入(模拟 provisioning 后被篡改)
    with open(sandbox.prod / "update.sh", "a", encoding="utf-8") as fh:
        fh.write("\n# TAMPERED\n")
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0
    assert "受信工件不一致" in sandbox.remote_out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 静态接线:真实 workflow 步骤序 + provision/deploy 关键机制
# --------------------------------------------------------------------------- #


def test_p07_workflow_step_order_provision_before_migrate():
    """真实 workflow 步骤序:preflight → provision_host_script → migrate →
    deploy(宿主脚本身份/能力验证严格先于任何 mutation)。"""
    ids = _step_ids()
    assert ids.index("preflight") < ids.index("provision_host_script")
    assert ids.index("provision_host_script") < ids.index("migrate")
    assert ids.index("migrate") < ids.index("deploy")


def test_p08_provision_step_mechanics():
    """provision 步骤机制面:git 权威解析 + 工作区完整性对照 + 宿主哈希核对
    + 能力断言 + 语法校验 + 同目录原子 rename + 安装后复核 + 宿主锁。"""
    text = _step_text("provision_host_script")
    assert 'git show "$RELEASE_SHA:deploy/prod/update.sh"' in text
    assert "TRUSTED_HASH" in text and "WORKTREE_HASH" in text
    assert "脏树/篡改" in text
    assert ".update-sh.provision." in text, "必须使用目标同目录临时件(原子 rename 前提)"
    assert "grep -q -- '--remediation-evidence-file'" in text, "能力断言必须独立于哈希"
    assert "bash -n" in text
    assert 'mv -f "$TMP_INST" "$TARGET"' in text
    assert "安装后哈希不匹配" in text
    assert "askai-deploy.lock" in text, "必须持有与部署同一把宿主锁"


def test_p09_deploy_step_reverify_and_evidence_channels():
    """deploy 步骤:执行前复验宿主哈希 + 证据记录/工件双通道 + 审批密钥
    不经 SSH 传输(经宿主 .env)。"""
    text = _step_text("deploy")
    assert "PROVISION_SHA256" in text and "受信工件不一致" in text
    assert "--remediation-evidence-file" in text
    assert "--remediation-evidence-artifact" in text
    assert "APPROVAL_KEY_B64" not in text
    assert "secrets.PREFLIGHT_REMEDIATION_APPROVAL_KEY" not in text
