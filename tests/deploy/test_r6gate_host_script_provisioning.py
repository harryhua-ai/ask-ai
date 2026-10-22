"""R6v3(G3 阻塞 2/3):宿主 update.sh 受信分发、锁内自验与零 rollout 中止。

权威依据:
- Role A R6 离线审查(2026-10-20,阻塞 2):宿主 ~/ask-ai 非 git 仓库,
  update.sh 不随主干/镜像自动升级 ⇒ provision_host_script 步骤(先于迁移)
  受信分发与能力钉扎;
- Role A R6v2 实体 ZIP 审查 REQUEST_CHANGES(2026-10-20,阻塞 3):provision
  的 flock 只在其 SSH 会话持有;步骤5 在进入自身 flock 前做哈希复核 ⇒
  复核与执行间有竞争窗,不能宣称"所有脚本不匹配都在任何 mutation 前中止"。
  修复(R6v3):workflow deploy 步删除锁外预复核与外层 flock 包装;update.sh
  新增 ``--pinned-update-sh-sha256``,在【自身 flock 持有区间内】(内部锁
  获取 [1.1/6] 后、任何 mutation 之前,[1.2/6])自验自身文件 sha256 ==
  钉扎值,不匹配 ⇒ 零 rollout fail-closed ——「校验 + 执行」在同一锁持有
  区间内原子完成。
- 诚实语义(不夸大,写入 update.sh 头注):DB migration 由冻结镜像一次性
  容器执行、【不依赖宿主 update.sh】⇒ 迁移与部署之间的宿主脚本漂移只会
  导致 rollout 被 [1.2/6] fail-closed 拒绝(migration 本身不受宿主脚本
  影响);手动 break-glass 未传 --pinned-update-sh-sha256 时不做哈希自验,
  由 evaluator 证据门独立兜底。

本沙箱走真实执行路径:从 deploy-production.yml 机械提取 provision_host_script
与 deploy 两步的真实 run 文本执行(fake ssh / fake docker / fake curl /
fake flock);preflight 与 migrate 以保形桩替代 —— 真实 preflight 行为由
T-SEC/T-WV/T-RT 沙箱覆盖,整改证据全链验证由
test_r6gate_remediation_evidence 覆盖;本文件证明:步骤真实顺序、provision
全部故障注入在迁移前 fail-closed、迁移零调用、锁内自验失败零 rollout、
部署阶段消费钉扎脚本与整改证据(R6v3 非对称签名 + 钉扎公钥)。

红线:全部离线确定性;密钥/工件为测试自造信任根(RSA-2048 test-only 常量);
不连生产、不 push、不改门值;测试信任根绝不宣称生产已整改。
"""

from __future__ import annotations

import base64
import hashlib
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

import sys  # noqa: E402

_here = str(Path(__file__).resolve().parent)
if _here not in sys.path:
    sys.path.insert(0, _here)

from remediation_v3_trust_root import (  # noqa: E402
    ATTACKER_RSA_PRIVATE_KEY_PEM_FULL,
    RsaTrustRoot,
)

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
            '  remote_cmd="$(printf "%s" "$remote_cmd" | sed "s|TRUSTED_UPDATE_SH_B64=\'[^\']*\'|TRUSTED_UPDATE_SH_B64=\'${TSL_PROVISION_B64_OVERRIDE}\'|" )"\n'
            "fi\n"
            # 锁内自验失败注入(deploy 步专用:仅当远端命令含 R6v3
            # pinned 旗标时才把 PROVISION_SHA256 替换为污染值)⇒
            # update.sh [1.2/6] 自验不匹配 ⇒ 零 rollout
            'if [ -n "${TSL_DEPLOY_SHA_OVERRIDE:-}" ] && printf "%s" "$script" | grep -qF -- \'pinned-update-sh-sha256 "$PROVISION_SHA256"\'; then\n'
            '  remote_cmd="$(printf "%s" "$remote_cmd" | sed "s|PROVISION_SHA256=\'[^\']*\'|PROVISION_SHA256=\'${TSL_DEPLOY_SHA_OVERRIDE}\'|" )"\n'
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
            "  exec)\n"
            '    # deployed-version 守卫事实读取:docker exec <cid> cat /app/RELEASE.json\n'
            '    # 或 /app/deploy/prod/compatibility.json(已部署回滚声明;按 cat\n'
            '    # 目标路径区分,与真实容器布局一致)\n'
            '    case " ${args[*]} " in\n'
            '      *" /app/deploy/prod/compatibility.json "*)\n'
            '        if [ "${TSL_COMPAT_INCOMPATIBLE:-}" = "1" ]; then\n'
            '          printf \'{"version":1,"rollback":{"previous_compatible":false,"remediation_gate":"%s"}}\' "${TSL_COMPAT_GATE:-gate-token-x}"\n'
            '        else\n'
            '          printf \'{"version":1,"rollback":{"previous_compatible":true}}\'\n'
            '        fi ;;\n'
            '      *)\n'
            '        printf \'{"version":"%s","git_sha":"%s"}\' \\\n'
            '          "${TSL_DEPLOYED_VERSION:-${TSL_FAKE_VERSION:-1.0.0}}" "${TSL_FAKE_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;\n'
            "    esac ;;\n"
            "  compose)\n"
            '    sub=""\n'
            '    for i in "${!args[@]}"; do case "${args[$i]}" in ps|exec|run) sub="${args[$i]}"; break;; esac; done\n'
            '    if [ "$sub" = "ps" ]; then echo fakecid00000001; exit 0; fi\n'
            "    exit 0 ;;\n"
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
        pubkey_b64: str | None = None,
        compat_incompatible: bool = True,
    ) -> dict:
        """按 workflow 真实顺序执行 preflight → provision → migrate → deploy。"""
        env = self.base_env()
        env["TSL_COMPAT_INCOMPATIBLE"] = "1" if compat_incompatible else "0"
        if preflight_fail:
            env["TSL_PREFLIGHT_FAIL"] = "1"
        # 记录/工件/验证公钥均经 secret 通道(env;非秘密材料);R6v3 起无任何
        # 审批**私钥**通道(旧宿主 .env HMAC 通道已删除)
        env["REMEDIATION_EVIDENCE_B64"] = (
            base64.b64encode(json.dumps(evidence).encode()).decode()
            if evidence is not None
            else ""
        )
        env["REMEDIATION_ARTIFACT_B64"] = (
            base64.b64encode(artifact or b"").decode() if artifact is not None else ""
        )
        env["REMEDIATION_PUBKEY_B64"] = pubkey_b64 or ""
        # 旧宿主脚本种子(历史版本:不含 R6v3 能力)
        old_script = "#!/bin/bash\necho old-host-update-sh\n"
        (self.prod / "update.sh").write_text(old_script, encoding="utf-8")
        os.chmod(self.prod / "update.sh", 0o750)
        old_hash = hashlib.sha256(old_script.encode()).hexdigest()

        results = {}
        for step_id in ("preflight", "provision_host_script", "migrate", "deploy"):
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

    def remote_out_from(self, offset: int) -> str:
        if not self.remote_out.exists():
            return ""
        return self.remote_out.read_bytes()[offset:].decode("utf-8", errors="replace")

    def remote_out_offset(self) -> int:
        return (
            self.remote_out.stat().st_size if self.remote_out.exists() else 0
        )


# --------------------------------------------------------------------------- #
# 测试信任根(R6v3:RSA-2048 测试密钥对;经生产签发工具同路签发;
# 公钥经 secret 通道 env 形态传递 —— 生产同路,零宿主 .env 私钥通道)
# --------------------------------------------------------------------------- #
def _make_evidence(
    tag: str = TAG, sha: str = FAKE_SHA, gate: str = GATE
) -> tuple[dict, bytes, str]:
    import tempfile

    tr = RsaTrustRoot(Path(tempfile.mkdtemp(prefix="tsl-tr-")))
    rec = tr.signed(gate=gate, target_tag=tag, release_sha=sha)
    pubkey_b64 = tr.pubkey_b64()
    return rec, tr.artifact.read_bytes(), pubkey_b64


def _attacker_trust_root() -> RsaTrustRoot:
    import tempfile

    return RsaTrustRoot(
        Path(tempfile.mkdtemp(prefix="tsl-atk-")),
        pem=ATTACKER_RSA_PRIVATE_KEY_PEM_FULL,
        label="attacker",
    )


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


# --------------------------------------------------------------------------- #
# 行为矩阵
# --------------------------------------------------------------------------- #


def test_p01_old_host_script_provisioned_and_full_path_succeeds(sandbox):
    """P-01:旧宿主脚本(无 R6v3 能力)→ provision 原子替换为受信工件 →
    迁移恰 1 次 → 部署消费钉扎脚本(锁内自验通过)+ R6v3 整改证据全链
    (RSA 签名 + 钉扎公钥)真实放行。"""
    record, artifact, pubkey_b64 = _make_evidence()
    res = sandbox.run_pipeline(
        evidence=record, artifact=artifact, pubkey_b64=pubkey_b64
    )
    assert res["preflight"].returncode == 0
    assert res["provision_host_script"].returncode == 0, res["provision_host_script"].stderr
    assert res["migrate"].returncode == 0
    assert res["deploy"].returncode == 0, res["deploy"].stderr + res["deploy"].stdout
    # 宿主脚本 = 受信工件(内容级钉扎;旧脚本已被原子替换)
    assert sandbox.host_script_hash() == sandbox.trusted_hash()
    assert sandbox.host_script_text() == UPDATE_SH_SRC.read_text(encoding="utf-8")
    # 迁移恰一次;真实 update.sh 完整执行(部署横幅;锁内自验通过;不兼容门
    # 在证据全链有效下真实放行 —— 行为级证明:记录/工件/公钥三通道被消费)
    assert sandbox.migrate_count() == 1
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "=== ask-ai 部署:" in out, out[-500:]
    assert "兼容性 preflight 通过" in out, out[-800:]
    assert "宿主脚本身份自验通过" in out, out[-800:]
    assert "backend 健康" in out
    assert out.count("HOST SCRIPT PROVISIONED") == 1


def test_p01b_stale_host_script_without_provision_fails(sandbox):
    """P-01b 负例对照:跳过 provision 的陈旧宿主脚本(真实旧版形态:严格
    参数词表、无 R6v3 能力)不接受 ``--pinned-update-sh-sha256`` 等新参数
    ⇒ 部署入口 fail-closed(能力缺口的真实后果;诚实边界:deploy 步在
    R6v3 不再做锁外哈希复核,陈旧任意脚本的哈希防线 = workflow 恒定先行的
    provision 步 + 脚本自身锁内自验,本用例钉住的是词表防线)。"""
    record, artifact, pubkey_b64 = _make_evidence()
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["REMEDIATION_EVIDENCE_B64"] = base64.b64encode(json.dumps(record).encode()).decode()
    env["REMEDIATION_ARTIFACT_B64"] = base64.b64encode(artifact).decode()
    env["REMEDIATION_PUBKEY_B64"] = pubkey_b64
    stale = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'for a in "$@"; do case "$a" in --*) echo "❌ 未知选项: $a" >&2; exit 2 ;; esac; done\n'
        'echo stale-host-update-sh\n'
    )
    (sandbox.prod / "update.sh").write_text(stale)
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0, "陈旧宿主脚本必须因未知参数失败(fail-closed)"
    assert "未知选项" in sandbox.remote_out.read_text(encoding="utf-8")


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
    拒绝安装,旧脚本原状。"""
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


def test_p05_retired_evidence_channel_is_inert(sandbox):
    """P-05(2026-10-22 退役):证据通道整体退出发布链 —— 攻击者自造密钥
    签发的"证据"不再被任何部署面消费;部署结果只由 forward/redeploy 语义
    (deployed-version 守卫)与冻结镜像 evaluator 判定。"""
    atk = _attacker_trust_root()
    record = atk.signed(gate=GATE, target_tag=TAG, release_sha=FAKE_SHA)
    res = sandbox.run_pipeline(
        evidence=record,
        artifact=atk.artifact.read_bytes(),
        pubkey_b64=_make_evidence()[2],
    )
    assert res["deploy"].returncode == 0, "退役通道对部署零影响(前向/重部署照常放行)"
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "=== ask-ai 部署:" in out


def test_p05b_evidence_without_pubkey_inert(sandbox):
    """P-05b(退役):证据/公钥通道缺省与否不改变部署语义(零消费面)。"""
    record, artifact, _ = _make_evidence()
    res = sandbox.run_pipeline(evidence=record, artifact=artifact, pubkey_b64="")
    assert res["deploy"].returncode == 0
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "=== ask-ai 部署:" in out


def test_p05c_older_target_refused_by_host_guard(sandbox):
    """P-05c(新):目标旧于已部署 ⇒ update.sh [1.3/6] deployed-version 守卫
    在任何 rollout mutation 前 fail-closed(宿主侧第二道,覆盖历史 ref
    dispatch 的旧 workflow 调用路径)。"""
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    # update.sh 的已部署事实 = 运行中 backend 容器 RELEASE.json(sandbox shim)
    env["TSL_DEPLOYED_VERSION"] = "9.9.9"  # 已部署比目标(1.0.0)新 ⇒ 旧版回退
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0, "旧版回退必须被宿主守卫拒绝"
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "deployed-version 回滚守卫" in out and "零 rollout" in out


def test_p05d_marker_container_conflict_fails_closed(sandbox):
    """P-05d(通道复审修正):宿主部署标记与运行中 backend 容器版本互相矛盾
    ⇒ [1.3/6] 守卫零 rollout fail-closed(绝不静默择一继续)——标记过期/
    容器被非通道方式更换/DR 换栈都属于部署状态真值自相矛盾。"""
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["TSL_DEPLOYED_VERSION"] = "1.0.0"   # 容器事实(docker exec shim)
    # 宿主标记故意写成另一个版本(= 标记过期/容器被手工更换的矛盾形态)
    (sandbox.prod / ".deployed-release.json").write_text(json.dumps({
        "tag": "v9.9.9", "version": "9.9.9",
        "git_sha": "c" * 40, "previous_compatible": False,
        "updated_at": "2026-10-22T00:00:00Z",
    }), encoding="utf-8")
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0, "双源冲突必须 fail-closed"
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "部署状态双源冲突" in out
    assert "9.9.9" in out and "1.0.0" in out, "冲突两值都必须可见(可对账)"
    assert "部署完成" not in out and "up -d backend" not in out, "零 rollout"


def test_p05e_marker_container_consistent_proceeds(sandbox):
    """P-05e:标记与容器一致 ⇒ 无冲突,守卫按既有语义放行(择源不变)。"""
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["TSL_DEPLOYED_VERSION"] = "1.0.0"   # 容器事实 = 目标同版本(重部署)
    (sandbox.prod / ".deployed-release.json").write_text(json.dumps({
        "tag": TAG, "version": "1.0.0",
        "git_sha": "c" * 40, "previous_compatible": False,
        "updated_at": "2026-10-22T00:00:00Z",
    }), encoding="utf-8")
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode == 0, r_dep.stderr
    out = sandbox.remote_out.read_text(encoding="utf-8")
    assert "部署状态双源冲突" not in out
    assert "deployed-version 回滚守卫" in out
    assert "=== ask-ai 部署:" in out


def test_p06_post_provision_drift_detected_by_locked_selfverify(sandbox):
    """P-06(R6v3 阻塞 3):provision 之后、部署之前宿主脚本被篡改 ⇒
    update.sh【锁内自验】([1.2/6],任何 rollout mutation 前)拒绝,
    零 rollout。诚实边界演示:迁移已在独立步骤完成(冻结镜像执行,不依赖
    宿主脚本),宿主漂移只阻断 rollout。"""
    record, artifact, pubkey_b64 = _make_evidence()
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["REMEDIATION_EVIDENCE_B64"] = base64.b64encode(json.dumps(record).encode()).decode()
    env["REMEDIATION_ARTIFACT_B64"] = base64.b64encode(artifact).decode()
    env["REMEDIATION_PUBKEY_B64"] = pubkey_b64
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0
    r_mig = sandbox.run_step("migrate", env)
    assert r_mig.returncode == 0
    # provision/migrate 与 deploy 之间的漂移注入(模拟安装后被篡改)
    with open(sandbox.prod / "update.sh", "a", encoding="utf-8") as fh:
        fh.write("\n# TAMPERED\n")
    offset = sandbox.remote_out_offset()
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0
    tail = sandbox.remote_out_from(offset)
    assert "锁内自验失败" in tail
    assert "零 rollout" in tail
    # 诚实语义:迁移已发生(不受宿主脚本影响);rollout 被 fail-closed 拒绝
    assert sandbox.migrate_count() == 1
    assert "拉取镜像" not in tail, "自验失败 ⇒ 零 rollout([2/6] 不得执行)"
    assert "backend 健康" not in tail
    assert "部署完成" not in tail


def test_p10_pinned_hash_pollution_zero_rollout(sandbox):
    """P-10(R6v3 新增故障注入):锁内自验的钉扎值被污染 ⇒ update.sh 在
    [1.2/6] 中止且零 rollout(update.sh 无 rollout 执行痕迹/无健康检查)。"""
    record, artifact, pubkey_b64 = _make_evidence()
    env = sandbox.base_env()
    env["TSL_COMPAT_INCOMPATIBLE"] = "1"
    env["REMEDIATION_EVIDENCE_B64"] = base64.b64encode(json.dumps(record).encode()).decode()
    env["REMEDIATION_ARTIFACT_B64"] = base64.b64encode(artifact).decode()
    env["REMEDIATION_PUBKEY_B64"] = pubkey_b64
    env["TSL_DEPLOY_SHA_OVERRIDE"] = "e" * 64  # 钉扎值污染(注入)
    (sandbox.prod / "update.sh").write_text("#!/bin/bash\necho old\n")
    os.chmod(sandbox.prod / "update.sh", 0o750)
    r_prov = sandbox.run_step("provision_host_script", env)
    assert r_prov.returncode == 0, "provision 用真实 git 权威哈希,不受注入影响"
    offset = sandbox.remote_out_offset()
    r_dep = sandbox.run_step("deploy", env)
    assert r_dep.returncode != 0
    tail = sandbox.remote_out_from(offset)
    assert "锁内自验失败" in tail, tail[-600:]
    # 零 rollout:任何 mutation 之前中止(无 pull/up/health 痕迹)
    assert "拉取镜像" not in tail
    assert "更新 backend" not in tail
    assert "backend 健康" not in tail
    assert "部署完成" not in tail
    assert sandbox.migrate_count() == 0, "本用例只跑 provision+deploy,迁移未发生"


def test_p11_workflow_step_order_provision_before_migrate():
    """真实 workflow 步骤序:preflight → provision_host_script → migrate →
    deploy(宿主脚本身份/能力验证严格先于任何 mutation)。"""
    ids = _step_ids()
    assert ids.index("preflight") < ids.index("provision_host_script")
    assert ids.index("provision_host_script") < ids.index("migrate")
    assert ids.index("migrate") < ids.index("deploy")


def test_p12_provision_step_mechanics():
    """provision 步骤机制面:git 权威解析 + 工作区完整性对照 + 宿主哈希核对
    + 能力断言(证据 + R6v3 锁内自验) + 语法校验 + 同目录原子 rename +
    安装后复核 + 宿主锁。"""
    text = _step_text("provision_host_script")
    assert 'git show "$RELEASE_SHA:deploy/prod/update.sh"' in text
    assert "TRUSTED_HASH" in text and "WORKTREE_HASH" in text
    assert "脏树/篡改" in text
    assert ".update-sh.provision." in text, "必须使用目标同目录临时件(原子 rename 前提)"
    assert "grep -q 'ASKAI_DEPLOYED_VERSION_GUARD_V1'" in text, "能力断言必须独立于哈希(回滚守卫标记)"
    assert "grep -q -- '--pinned-update-sh-sha256'" in text, "R6v3 锁内自验能力必须断言"
    assert "bash -n" in text
    assert 'mv -f "$TMP_INST" "$TARGET"' in text
    assert "安装后哈希不匹配" in text
    assert "askai-deploy.lock" in text, "必须持有与部署同一把宿主锁"


def test_p13_deploy_step_ownership_in_update_sh_and_retired_channels():
    """deploy 步:锁外预复核已删(逻辑移入 update.sh 锁内)、外层 flock 已
    删;钉扎哈希经 env 前缀传入;证据/公钥通道零残留(2026-10-22 退役)。"""
    text = _step_text("deploy")
    assert "--pinned-update-sh-sha256" in text
    assert "PROVISION_SHA256" in text
    assert "受信工件不一致" not in text
    assert "HOST_SH_HASH" not in text
    assert "flock -w 0 /tmp/askai-deploy.lock" not in text
    assert "flock -w 0 " not in text
    # 退役通道零残留
    assert "--remediation-evidence-file" not in text
    assert "--remediation-evidence-artifact" not in text
    assert "--remediation-approval-public-key-file" not in text
    assert "REMEDIATION_PUBKEY_B64" not in text
    channel = "secrets." + "PREFLIGHT_REMEDIATION_" + "APPROVAL_KEY"
    assert channel not in text
    assert "APPROVAL_KEY_B64" not in text
    assert "askai-approval-pubkey" not in text


def test_p14_update_sh_locked_selfverify_mechanics():
    """update.sh 机制面:内部 flock([1.1/6])→ 锁内自验([1.2/6])→
    诚实语义头注(migration 不依赖宿主脚本 / break-glass 边界)。"""
    text = UPDATE_SH_SRC.read_text(encoding="utf-8")
    assert 'PINNED_UPDATE_SH_SHA256=""' in text
    assert "--pinned-update-sh-sha256" in text
    assert 'exec 9>"${TMPDIR:-/tmp}/askai-deploy.lock"' in text
    assert 'flock -w 0 9' in text
    assert "[1.1/6]" in text and "[1.2/6]" in text
    # 自验在锁获取之后、任何 mutation([2/6] pull)之前
    lock_idx = text.rindex("[1.1/6]")
    verify_idx = text.rindex("[1.2/6]")
    pull_idx = text.rindex("[2/6] 拉取镜像")
    assert lock_idx < verify_idx < pull_idx
    # 钉扎值形状校验 + 实测 sha256 比对 + 零 rollout 文案
    assert 'python3 -c \'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())\' "$0"' in text
    assert "锁内自验失败" in text and "零 rollout" in text
    # 诚实边界头注(migration 由冻结镜像执行;break-glass 未钉扎时由
    # evaluator 证据门独立兜底)
    assert "不依赖本宿主脚本" in text
    assert "evaluator" in text and "证据门" in text
