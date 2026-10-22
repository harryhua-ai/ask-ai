"""r3gate R3-2:deploy-production.yml preflight 步骤的 SSH 凭据生命周期。

A 复审裁决(R2 = PARTIAL/CORRECTION REQUIRED)要点:R2 候选先把隔离 DSN
(PREFLIGHT_ISOLATION_PG_DSN secret)经 stdin 写入远端
``$HOME/.askai_preflight_iso_dsn`` —— SSH 中断/远程 trap 未装好/清理连接
失败时可残留**含密文件**,不能声称全程零文件写入。

R3-2 首选方案 = **消除而非清理**:CI→SSH 只传非秘密参数(冻结 tag + A 带
外钉扎的非秘密信任锚);preflight 评估器经既有 compose 机制(``exec -T
backend``)在**运行中生产 backend 容器**内执行,DB DSN 组件与 Weaviate 目标
经容器自身 env(POSTGRES_*/WEAVIATE_*)继承 —— 零新增含密文件、零凭据过
SSH、R2 的含密文件路径整体移除。

本文件 T-SEC-01..10 全部走**真实执行路径**:从 deploy-production.yml 机械
提取 preflight 步骤 run 脚本,以 fake ssh / fake docker(compose)shim +
受控临时 RUNNER_TEMP / 远端 HOME / 远端 TMPDIR / 容器根 逐项故障注入:
- T-SEC-01 正常执行无残留凭据文件;
- T-SEC-02 远程执行前失败(known_hosts 钉扎缺失);
- T-SEC-03 SSH 连接中断(远端 SIGKILL,trap 未及执行)→ 无任何含密残留,
  且下一轮运行的确定性清扫回收非秘密工件;
- T-SEC-04 远程进程异常退出(容器内 evaluator 非零)→ fail-closed + 确定性
  清除;
- T-SEC-05 可处理信号终止(SIGTERM)→ trap 清理 runner 侧 SSH 材料;
- T-SEC-06 preflight 超时(看门狗到点杀 SSH)→ 有界 fail-closed;
- T-SEC-07 凭据/锚缺失 → ssh 零调用 fail-closed;
- T-SEC-08 凭据读取/写入权限不足 → fail-closed 无远端副作用;
- T-SEC-09 全进程 argv/stdout/stderr 扫描无测试密钥材料;
- T-SEC-10 结束后临时目录无含密文件 + R2 含密路径已从设计中消失。

红线:全部离线确定性;密钥/锚均为测试自造假材料(R3SEC-*/R3TST-*);不连
生产、不 push、不改门值;断言的是"设计中不存在含密文件写入路径",而非
仅脚本字符串。
"""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
EVALUATOR_SRC = REPO / "scripts" / "release_preflight.py"

_FAKE_KEY = (
    # 假私钥材料(拼接避免仓库文件出现连续 PEM 头字面量;扫描规则要求零命中)
    "-----BEGIN OPENSSH " "PRIVATE" " " "KEY-----\n"
    "R3SEC-FAKEKEY-DO-NOT-USE b3BlbnNzaC1rZXktdjEAAAAA\n"
    "R3SEC-FAKEKEY-TAIL zzzzzzzzzzzzzzzzzzzz\n"
    "-----END OPENSSH " "PRIVATE" " " "KEY-----\n"
)
_FAKE_HOST = "tesla-t4.fake.invalid"
_FAKE_KH = f"{_FAKE_HOST} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKER3TST\n"
_IDENTITY_JSON = json.dumps({
    "version": 2,
    "pg_system_id": "7400000000000000004",
    "weaviate_cluster_hostname": "fake-node.invalid",
    "weaviate_image_digest": "sha256:fakeimage0000000000000000000000000000000000000000000000000000000000",
    "weaviate_volume_name": "fake-t4_weaviate_data",
    "uploads_volume_name": "fake-t4_uploads_data",
    "uploads_mount_path": "/app/data/uploads",
    "uploads_sources_dir": "/app/data/uploads/data-sources",
    "uploads_unknown_guard": "/app/deploy/prod/uploads-unknown-guard.tsv",
})


def _preflight_run_text() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["deploy"]["steps"]
    return [s for s in steps if s.get("id") == "preflight"][0]["run"]


class Sandbox:
    """受控执行沙箱:runner / 远端 HOME / 远端 TMPDIR / 容器根 / fake bin。"""

    def __init__(self, tmp: Path):
        self.base = tmp
        self.runner = tmp / "runner"          # RUNNER_TEMP(KEY/KH 落点)
        self.remote_home = tmp / "remote-home"
        self.remote_tmp = tmp / "remote-tmp"  # 远端 TMPDIR(锚/评估器临时件)
        self.container = tmp / "container"    # 容器根(exec 写入/清除的模拟)
        self.bin = tmp / "bin"
        self.logs = tmp / "logs"
        for d in (
            self.runner, self.remote_home / "ask-ai" / "deploy" / "prod",
            self.remote_tmp / "container-tmp", self.container / "tmp",
            self.bin, self.logs,
        ):
            d.mkdir(parents=True, exist_ok=True)
        # fake docker 的容器 tmp 根 = 容器内 /tmp
        (self.remote_home / "ask-ai" / "deploy" / "prod").mkdir(
            parents=True, exist_ok=True
        )
        self.ssh_argv = self.logs / "ssh_argv.log"
        self.docker_argv = self.logs / "docker_argv.log"
        self.eval_argv = self.logs / "eval_argv.log"
        self.container_tmp = self.remote_tmp / "container-tmp"
        self._write_shims()

    # ------------------------------------------------------------------ shims
    def _write_shims(self) -> None:
        (self.bin / "flock").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        # fake docker:pull/create/rm/cp(冻结镜像工件提取,含身份事实+上传守卫)/
        # inspect(控制面三问:Image/Mounts/Config.Env)/compose(ps 定位 + exec:
        # cat=deployed-version 读取、sh=工件写入与容器内哈希、rm、python3=评估器)
        (self.bin / "docker").write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$TSL_DOCKER_ARGV_LOG"\n'
            "args=()\n"
            'while [ $# -gt 0 ]; do args+=("$1"); shift; done\n'
            'case "${args[0]}" in\n'
            "  pull)\n"
            '    if [ -n "${TSL_DOCKER_PULL_FAIL:-}" ]; then\n'
            '      echo "fake docker pull failed" >&2; exit "${TSL_DOCKER_PULL_FAIL}"\n'
            "    fi\n    exit 0 ;;\n"
            "  create) echo fakecid00000000 ;;\n"
            "  rm) exit 0 ;;\n"
            "  cp)\n"
            '    src="${args[1]}"; dest="${args[$((${#args[@]} - 1))]}"\n'
            '    case "$src" in\n'
            '      *RELEASE.json)\n'
            '        printf \'{"version":"1.0.0","git_sha":"%s","compatibility_contract":true}\' \\\n'
            '          "${TSL_FAKE_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" > "$dest" ;;\n'
            '      *release_preflight.py) cp "$TSL_EVALUATOR_SRC" "$dest" ;;\n'
            '      *compatibility.json)\n'
            '        printf \'{"version":1,"config":[],"host":[],"topology":[],"dependencies":[],"rollback":{"previous_compatible":true}}\' \\\n'
            '          > "$dest" ;;\n'
            '      *production-identity.json)\n'
            '        if [ "${TSL_IDENTITY_MISSING:-}" = "1" ]; then exit 1; fi\n'
            '        printf \'%s\' "$TSL_IDENTITY_JSON" > "$dest" ;;\n'
            '      *uploads-unknown-guard.tsv)\n'
            '        printf \'%s\' "$TSL_GUARD_CONTENT" > "$dest" ;;\n'
            "      *) exit 1 ;;\n"
            "    esac ;;\n"
            "  inspect)\n"
            '    fmt="${args[@]:2}"\n'
            '    case "$fmt" in\n'
            '      *.Image*) echo "sha256:fakeimage0000000000000000000000000000000000000000000000000000000000" ;;\n'
            "      *Mounts*) if [ \"${args[1]}\" = \"fake-backend-cid\" ]; then echo \"${TSL_UP_VOLS:-fake-t4_uploads_data=/app/data/uploads }\"; else echo \"${TSL_CP_VOLS:-fake-t4_weaviate_data=/var/lib/weaviate }\"; fi ;;\n"
            '      *Config.Env*) printf \'%s\\n\' "${TSL_CP_ENV:-CLUSTER_HOSTNAME=fake-node.invalid}" ;;\n'
            '      *) echo "fake docker inspect: unknown fmt" >&2; exit 1 ;;\n'
            "    esac ;;\n"
            "  compose)\n"
            '    if [ "${TSL_PS_EMPTY:-}" = "1" ]; then exit 0; fi\n'
            '    sub=""\n'
            '    for i in "${!args[@]}"; do case "${args[$i]}" in ps|exec) sub="${args[$i]}"; break;; esac; done\n'
            '    if [ "$sub" = "ps" ]; then\n'
            '      svc="${args[@]: -1}"\n'
            '      if [ "$svc" = "backend" ]; then echo fake-backend-cid; else echo fake-wv-cid; fi\n'
            '      exit 0\n'
            '    fi\n'
            '    exec_idx=-1; svc_idx=-1\n'
            '    for i in "${!args[@]}"; do\n'
            '      if [ "${args[$i]}" = "exec" ]; then exec_idx=$i; fi\n'
            '      if [ "$exec_idx" -ge 0 ] && [ "${args[$i]}" = "backend" ]; then svc_idx=$i; break; fi\n'
            "    done\n"
            '    if [ "$svc_idx" -lt 0 ]; then echo "fake compose: no backend exec" >&2; exit 1; fi\n'
            '    cmd=("${args[@]:$((svc_idx + 1))}")\n'
            '    case "${cmd[0]}" in\n'
            "      cat)\n"
            '        # deployed-version 事实读取:运行中 backend /app/RELEASE.json\n'
            '        if [ "${TSL_DEPLOYED_UNREADABLE:-}" = "1" ]; then exit 1; fi\n'
            '        printf \'{"version":"%s","git_sha":"deployed0sha"}\' "${TSL_DEPLOYED_VERSION:-1.0.0}" ;;\n'
            "      sh)\n"
            '        case "${cmd[2]}" in\n'
            '          "if [ -L "*)\n'
            '            p="$(printf "%s" "${cmd[2]}" | sed -n "s/^if \\[ -L \\([^ ]*\\) .*/\\1/p")"\n'
            '            if [ -L "$TSL_CONTAINER_ROOT$p" ]; then echo __G3_SYMLINK__\n'
            '            elif [ -f "$TSL_CONTAINER_ROOT$p" ]; then\n'
            '              if command -v sha256sum >/dev/null 2>&1; then sha256sum "$TSL_CONTAINER_ROOT$p"; else shasum -a 256 "$TSL_CONTAINER_ROOT$p"; fi | cut -d\' \' -f1\n'
            '            else echo __G3_ABSENT__; fi\n'
            '            ;;\n'
            '          "cat > "*)\n'
            '            target="${cmd[2]#cat > }"\n'
            '            mkdir -p "$TSL_CONTAINER_ROOT$(dirname "$target")"\n'
            '            cat > "$TSL_CONTAINER_ROOT$target"\n'
            '            ;;\n'
            '          sha256sum*)\n'
            '            raw="${cmd[2]#sha256sum }"\n'
            '            f="${raw%% *}"\n'
            '            if [ -n "${TSL_TAMPER:-}" ]; then\n'
            '              echo "deadbeef00000000000000000000000000000000000000000000000000000000  $f"\n'
            '            elif [ -f "$TSL_CONTAINER_ROOT$f" ]; then\n'
            '              if command -v sha256sum >/dev/null 2>&1; then sha256sum "$TSL_CONTAINER_ROOT$f"; else shasum -a 256 "$TSL_CONTAINER_ROOT$f"; fi | sed "s#$TSL_CONTAINER_ROOT##"\n'
            '            else\n'
            '              exit 1\n'
            '            fi ;;\n'
            '          *)\n'
            '            echo "fake compose sh: unexpected: ${cmd[2]}" >&2; exit 1 ;;\n'
            '        esac ;;\n'
            "      rm)\n"
            '        shift_args=("${cmd[@]:2}")\n'
            '        for p in "${shift_args[@]}"; do\n'
            '          rm -f "$TSL_CONTAINER_ROOT$p" 2>/dev/null || true\n'
            "        done ;;\n"
            "      python3)\n"
            '        printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '        exit "${TSL_EVAL_RC:-0}"\n'
            "        ;;\n"
            "      *)\n"
            '        printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '        exit "${TSL_EVAL_RC:-0}"\n'
            "        ;;\n"
            "    esac ;;\n"
            '  *) echo "fake docker: unexpected $*" >&2; exit 1 ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        (self.bin / "ssh").write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$TSL_SSH_ARGV_LOG"\n'
            'remote_cmd="${@: -1}"\n'
            'case "${TSL_SSH_MODE:-execute}" in\n'
            "  hang) sleep 60 ;;\n"
            "  refuse) echo 'ssh: connect to host: Connection refused (fake)' >&2; exit 255 ;;\n"
            "  execute|interrupt)\n"
            '    prefix="${remote_cmd%bash -s}"\n'
            '    cat > "$TSL_SANDBOX/remote_script_captured.sh"\n'
            '    eval "export ${prefix}"\n'
            '    export HOME="$TSL_REMOTE_HOME"\n'
            '    export TMPDIR="$TSL_REMOTE_TMP"\n'
            '    export PATH="$TSL_FAKEBIN:$PATH"\n'
            '    if [ "${TSL_SSH_MODE}" = "interrupt" ]; then\n'
            '      # 连接中断语义:后台启动远端脚本;待非密临时件(评估器/manifest/\n'
            '      # 身份事实/守卫)全部落盘(以 deployed-version 读取出现为界)后,\n'
            '      # 直接 SIGKILL 远端脚本 pid —— kill 不可捕获,EXIT trap 绝不执行,\n'
            '      # 残留可确定性观察(#183 时序竞速替代)。\n'
            '      TSL_INTERRUPT_HOLD=1 bash "$TSL_SANDBOX/remote_script_captured.sh" & pid=$!\n'
            '      i=0\n'
            '      while [ "$i" -lt 600 ] && kill -0 "$pid" 2>/dev/null; do\n'
            '        # 注入点 = 首个 backend exec(容器预清扫):此时全部非密\n'
            '        # 宿主临时件(评估器/manifest/身份事实/守卫)已落盘,且\n'
            '        # 其后仍有完整容器写核+评估器序列 —— 快慢 runner 均可\n'
            '        # 确定性命中(kill 不加额外等待,防脚本先行跑完)\n'
            '        if grep -q "exec -T backend" "$TSL_DOCKER_ARGV_LOG" 2>/dev/null; then\n'
            '          break\n'
            '        fi\n'
            '        sleep 0.05; i=$((i + 1))\n'
            '      done\n'
            '      kill -9 "$pid" 2>/dev/null\n'
            '      wait "$pid" 2>/dev/null\n'
            '      exit 255\n'
            "    fi\n"
            '    bash "$TSL_SANDBOX/remote_script_captured.sh"\n'
            "    exit $?\n"
            "    ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        (self.bin / "stat").write_text(
            "#!/bin/bash\n"
            "if [ \"$1\" = \"-c\" ]; then\n"
            "    if /usr/bin/stat --version >/dev/null 2>&1; then\n"
            "        exec /usr/bin/stat \"$@\"\n"
            "    fi\n"
            "    if [ \"$2\" = \"%n|%s|%Y\" ]; then\n"
            "        shift 2\n"
            "        exec /usr/bin/stat -f \'%N|%z|%m\' \"$@\"\n"
            "    fi\n"
            "fi\n"
            "exec /usr/bin/stat \"$@\"\n",
            encoding="utf-8",
        )
        (self.bin / "sha256sum").write_text(
            "#!/bin/bash\n"
            "if [ -x /usr/bin/sha256sum ]; then exec /usr/bin/sha256sum \"$@\"; fi\n"
            "if [ -x /bin/sha256sum ]; then exec /bin/sha256sum \"$@\"; fi\n"
            "exec /usr/bin/shasum -a 256 \"$@\"\n",
            encoding="utf-8",
        )
        for shim in ("flock", "docker", "ssh", "stat", "sha256sum"):
            (self.bin / shim).chmod(0o755)

    # ------------------------------------------------------------------ env
    def step_env(self, *, ssh_mode: str = "execute", **overrides) -> dict:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.base / "runner-home"),
            "RUNNER_TEMP": str(self.runner),
            "TSL_SANDBOX": str(self.base),
            "TSL_FAKEBIN": str(self.bin),
            "TSL_REMOTE_HOME": str(self.remote_home),
            "TSL_REMOTE_TMP": str(self.remote_tmp),
            "TSL_CONTAINER_ROOT": str(self.container),
            "TSL_SSH_ARGV_LOG": str(self.ssh_argv),
            "TSL_DOCKER_ARGV_LOG": str(self.docker_argv),
            "TSL_EVAL_ARGV_LOG": str(self.eval_argv),
            "TSL_EVALUATOR_SRC": str(EVALUATOR_SRC),
            "TSL_SSH_MODE": ssh_mode,
            "SSH_KEY": _FAKE_KEY,
            "SSH_HOST": _FAKE_HOST,
            "SSH_USER": "deployer",
            "SSH_KNOWN_HOSTS_B64": base64.b64encode(_FAKE_KH.encode()).decode(),
            "DEPLOY_TAG": "v1.0.0",
            "TSL_IDENTITY_JSON": _IDENTITY_JSON,
            "TSL_GUARD_CONTENT": "retained/keep.txt\t" + "bb" * 32 + "\n",
        }
        (self.base / "runner-home").mkdir(exist_ok=True)
        env.update(overrides)
        return env

    def run_step(self, env: dict, timeout: int = 90):
        script = self.base / "preflight_step.sh"
        script.write_text(_preflight_run_text(), encoding="utf-8")
        out_file = self.logs / "step_stdout.log"
        err_file = self.logs / "step_stderr.log"
        with open(out_file, "w") as fo, open(err_file, "w") as fe:
            proc = subprocess.Popen(  # noqa: S603 - 固定词表 argv
                ["bash", str(script)], stdout=fo, stderr=fe, env=env,
                cwd=str(self.base), start_new_session=True,
            )
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=10)
                raise
        return rc, out_file.read_text(encoding="utf-8"), err_file.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ 断言工具
    def scan_sandbox(self, needle: str) -> list[str]:
        """扫描沙箱所有文件内容,返回含 needle 的文件路径列表。"""
        hits: list[str] = []
        for p in self.base.rglob("*"):
            if not p.is_file() or p.is_symlink():
                continue
            try:
                if needle in p.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(p))
            except OSError:
                continue
        return hits

    def leftovers(self, directory: Path, pattern: str) -> list[str]:
        # askai-deploy.lock = 部署锁本体(migrate/deploy 步共用的常驻空文件,
        # flock 语义要求其持久存在),非 preflight 工件,排除。
        return [
            str(p) for p in directory.glob(pattern)
            if p.name != "askai-deploy.lock"
        ]


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


# --------------------------------------------------------------------------- #
# T-SEC-01:正常执行无残留凭据文件
# --------------------------------------------------------------------------- #


def test_tsec01_happy_path_no_credential_files_anywhere(sandbox):
    rc, out, err = sandbox.run_step(sandbox.step_env())
    assert rc == 0, f"happy path 应成功: {out}\n{err}"
    assert "PREFLIGHT PASS:v1.0.0" in out
    # 真实执行路径:ssh/docker/容器内 evaluator 全部被调用
    assert sandbox.ssh_argv.exists() and sandbox.docker_argv.exists()
    eval_argv = sandbox.eval_argv.read_text(encoding="utf-8")
    assert "--verify-upload-isolation" in eval_argv
    assert "--isolation-pg-dsn-parts" in eval_argv, "DSN 必须经容器自身 env 组件通道"
    assert "--isolation-trust-anchor-file /tmp/askai-production-identity.json" in eval_argv
    assert "--isolation-weaviate-url-env WEAVIATE_URL" in eval_argv
    # 无任何含密文件:SSH 私钥材料在沙箱零存在(trap 已清;从未写远端)
    assert sandbox.scan_sandbox("R3SEC-FAKEKEY") == [], "SSH 私钥材料绝不落任何文件"
    # 容器侧工件已被确定性清除
    assert sandbox.leftovers(sandbox.container / "tmp", "askai-*") == []
    # 远端(锚/评估器/manifest 均非秘密)也被 trap 清除
    assert sandbox.leftovers(sandbox.remote_tmp, "askai-*") == []


def test_tsec01_design_has_no_secret_file_path_or_dsn_env(sandbox):
    """R2 含密文件路径在设计中消失:**可执行路径**(preflight run 脚本与捕获
    的远端脚本)无 .askai_preflight_iso_dsn 写入、无 CI 侧 DSN secret env;
    步骤级注释中对该历史路径的说明性提及不算实现。"""
    run = _preflight_run_text()
    assert ".askai_preflight_iso_dsn" not in run, "R2 含密文件路径必须整体移除"
    assert "PREFLIGHT_ISOLATION_PG_DSN" not in run, "CI 侧 DSN secret 必须移除(消除而非清理)"
    assert "ISOLATION_DSN" not in run
    assert "isolation-pg-dsn-file" not in run
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    preflight = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("id") == "preflight"][0]
    assert "ISOLATION_DSN" not in preflight["env"]
    assert "PREFLIGHT_ISOLATION_PG_DSN" not in str(preflight["env"])
    assert "TRUST_ANCHOR_B64" not in str(preflight["env"]), "锚 secret 已退出(2026-10-22 通道)"
    assert "PREFLIGHT_" not in str(preflight["env"]), "四项 PREFLIGHT_* secret 全部退出"
    assert preflight["env"]["SSH_KEY"] == "${{ secrets.PROD_DEPLOY_SSH_KEY }}", "SSH 凭据通道保留"
    # 捕获的远端脚本:绝不出现远端含密文件写入(cat > $HOME/...)
    sandbox.run_step(sandbox.step_env())
    remote = (sandbox.base / "remote_script_captured.sh").read_text(encoding="utf-8")
    assert "iso_dsn" not in remote, "远端脚本绝不写任何含密 DSN 文件"
    assert "PGPASSWORD" not in remote


# --------------------------------------------------------------------------- #
# T-SEC-02:远程执行前失败(known_hosts 钉扎缺失)
# --------------------------------------------------------------------------- #


def test_tsec02_failure_before_remote_execution_no_ssh_no_residue(sandbox):
    bad_kh = base64.b64encode(f"other.host.invalid ssh-ed25519 AAAAFAKE\n".encode()).decode()
    rc, out, err = sandbox.run_step(
        sandbox.step_env(SSH_KNOWN_HOSTS_B64=bad_kh)
    )
    assert rc != 0 and rc != 0  # fail-closed
    assert "known_hosts" in err
    assert not sandbox.ssh_argv.exists(), "SSH 绝不被调用"
    assert sandbox.leftovers(sandbox.runner, "prod_deploy_key") == [], "密钥文件已清理"
    assert sandbox.leftovers(sandbox.remote_tmp, "askai-*") == []


# --------------------------------------------------------------------------- #
# T-SEC-03:SSH 连接中断(远端 SIGKILL,trap 未执行)
# --------------------------------------------------------------------------- #


def test_tsec03_connection_interrupt_no_secret_residue_and_deterministic_sweep(sandbox):
    rc, out, err = sandbox.run_step(sandbox.step_env(ssh_mode="interrupt"))
    assert rc != 0, "连接中断必须 fail-closed"
    # 中断残留(非秘密工件:锚/评估器/manifest)确实存在 —— 证明注入真实发生
    stranded = sandbox.leftovers(sandbox.remote_tmp, "askai-*")
    assert stranded, "SIGKILL 后 trap 未执行的残留应存在(证明中断注入真实)"
    # 残留内容扫描:绝不含任何秘密材料(SSH 私钥/含凭据 DSN 形态)
    assert sandbox.scan_sandbox("R3SEC-FAKEKEY") == []
    dsn_with_creds = re.compile(r"postgres(ql)?://[^\s/:@]+:[^\s/@]+@")
    for p in stranded:
        content = Path(p).read_text(encoding="utf-8", errors="ignore")
        assert not dsn_with_creds.search(content), f"残留文件 {p} 不得含含凭据 DSN"
        assert "BEGIN OPENSSH" not in content
    # 确定性清扫:下一轮正常执行开始时回收全部残留(最小有效期)
    stranded_before = set(stranded)
    rc2, out2, err2 = sandbox.run_step(sandbox.step_env())
    assert rc2 == 0, f"第二轮应成功: {out2}\n{err2}"
    still_there = [p for p in stranded_before if Path(p).exists()]
    assert still_there == [], f"确定性清扫必须回收上一轮残留: {still_there}"


# --------------------------------------------------------------------------- #
# T-SEC-04:远程进程异常退出(容器内 evaluator 非零)
# --------------------------------------------------------------------------- #


def test_tsec04_remote_evaluator_failure_fails_closed_and_cleans(sandbox):
    rc, out, err = sandbox.run_step(sandbox.step_env(TSL_EVAL_RC="2"))
    assert rc != 0, "容器内评估器非零 → 整步 fail-closed"
    assert "部署中止" in err
    # host/远端临时件已清;容器侧工件被 rm -f 清除
    assert sandbox.leftovers(sandbox.remote_tmp, "askai-*") == []
    assert sandbox.leftovers(sandbox.container / "tmp", "askai-*") == []
    assert sandbox.scan_sandbox("R3SEC-FAKEKEY") == []


# --------------------------------------------------------------------------- #
# T-SEC-05:可处理信号终止(SIGTERM → trap 清理 runner 侧 SSH 材料)
# --------------------------------------------------------------------------- #


def test_tsec05_sigterm_cleanup_traps_run(sandbox):
    script = sandbox.base / "preflight_step.sh"
    script.write_text(_preflight_run_text(), encoding="utf-8")
    env = sandbox.step_env(ssh_mode="hang")  # 挂住的 ssh = 可被信号打断的真实窗口
    proc = subprocess.Popen(  # noqa: S603
        ["bash", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, cwd=str(sandbox.base), start_new_session=True,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if sandbox.ssh_argv.exists():
            break
        time.sleep(0.05)
    assert sandbox.ssh_argv.exists(), "ssh 应已启动(挂住窗口)"
    key_file = sandbox.runner / "prod_deploy_key"
    assert key_file.exists(), "执行窗口内密钥文件存在(真实路径)"
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    rc = proc.wait(timeout=30)
    assert rc != 0, "SIGTERM → 非零退出(绝不伪装成功)"
    assert not key_file.exists(), "trap cleanup 必须清除 SSH 私钥文件"
    assert sandbox.leftovers(sandbox.runner, "prod_known_hosts") == []
    # 远端无任何文件被写入(hang 模式 ssh 未执行远端脚本)
    assert sandbox.leftovers(sandbox.remote_tmp, "askai-*") == []


# --------------------------------------------------------------------------- #
# T-SEC-06:preflight 超时(看门狗有界 fail-closed)
# --------------------------------------------------------------------------- #


def test_tsec06_watchdog_bounds_hung_preflight(sandbox):
    started = time.monotonic()
    rc, out, err = sandbox.run_step(
        sandbox.step_env(ssh_mode="hang", PREFLIGHT_TIMEOUT_S="2")
    )
    elapsed = time.monotonic() - started
    assert rc != 0, "悬挂的远端 preflight 必须被看门狗终止 → 非零退出"
    assert elapsed < 30, f"看门狗必须有界(实际 {elapsed:.1f}s)"
    assert "未通过或有界超时" in err
    assert sandbox.leftovers(sandbox.runner, "prod_deploy_key") == []


# --------------------------------------------------------------------------- #
# T-SEC-07:凭据/锚缺失 → ssh 零调用
# --------------------------------------------------------------------------- #


def test_tsec07_missing_required_var_fails_closed_before_ssh(sandbox):
    """2026-10-22 通道:锚/证据 secret 退出;SSH 通道必需变量缺失仍须在
    远程执行前 fail-closed(ssh 零调用)。"""
    rc, out, err = sandbox.run_step(sandbox.step_env(DEPLOY_TAG=""))
    assert rc != 0
    assert "DEPLOY_TAG" in err
    assert not sandbox.ssh_argv.exists(), "必需变量缺失 → 绝不发起 SSH(零远端副作用)"
    assert sandbox.leftovers(sandbox.runner, "prod_deploy_key") == []


# --------------------------------------------------------------------------- #
# T-SEC-08:凭据读取/写入权限不足
# --------------------------------------------------------------------------- #


def test_tsec08_unwritable_runner_temp_fails_closed(sandbox):
    sandbox.runner.chmod(0o555)
    try:
        rc, out, err = sandbox.run_step(sandbox.step_env())
    finally:
        sandbox.runner.chmod(0o755)
    assert rc != 0, "RUNNER_TEMP 不可写 → fail-closed(install 密钥文件失败)"
    assert not sandbox.ssh_argv.exists(), "绝不带着未就绪的 SSH 材料连生产"


# --------------------------------------------------------------------------- #
# T-SEC-09:全进程 argv / stdout / stderr 扫描无测试密钥材料
# --------------------------------------------------------------------------- #


def test_tsec09_no_secret_in_any_argv_stdout_stderr(sandbox):
    rc, out, err = sandbox.run_step(sandbox.step_env())
    assert rc == 0
    scanned: list[tuple[str, str]] = [
        ("step stdout", out), ("step stderr", err),
        ("ssh argv", sandbox.ssh_argv.read_text(encoding="utf-8") if sandbox.ssh_argv.exists() else ""),
        ("docker argv", sandbox.docker_argv.read_text(encoding="utf-8") if sandbox.docker_argv.exists() else ""),
        ("eval argv", sandbox.eval_argv.read_text(encoding="utf-8") if sandbox.eval_argv.exists() else ""),
        (
            "remote script",
            (sandbox.base / "remote_script_captured.sh").read_text(encoding="utf-8"),
        ),
    ]
    for label, text in scanned:
        assert "R3SEC-FAKEKEY" not in text, f"{label} 泄露 SSH 私钥材料"
        assert "BEGIN OPENSSH" not in text, f"{label} 泄露私钥头"
    # ssh argv 只含密钥**路径**(-i $RUNNER_TEMP/prod_deploy_key),绝不含内容
    assert "prod_deploy_key" in scanned[2][1]
    # 锚内容(base64)属非秘密钉扎标识,允许经 ssh 命令串传输 —— 但 SSH 私钥
    # 与任何 DSN 口令形态字符串绝不可出现(不把生产 IP/真实凭据字面量引入仓库)
    for label, text in scanned:
        for marker in ("changeme", "ghp_", "PGPASSWORD="):
            assert marker not in text, f"{label} 出现敏感标记 {marker}"


# --------------------------------------------------------------------------- #
# T-SEC-10:结束后临时目录无含密文件
# --------------------------------------------------------------------------- #


def test_tsec10_temp_dirs_clean_after_run(sandbox):
    rc, out, err = sandbox.run_step(sandbox.step_env())
    assert rc == 0
    # runner 侧:SSH 私钥/known_hosts 已清
    assert sandbox.leftovers(sandbox.runner, "*") == [], "RUNNER_TEMP 应无残留"
    # 远端与容器侧:无任何 askai-* 工件,更无含密文件
    assert sandbox.leftovers(sandbox.remote_tmp, "askai-*") == []
    assert sandbox.leftovers(sandbox.container / "tmp", "askai-*") == []
    # 全沙箱逐文件扫描:无私钥材料、无 R2 含密文件名、无 DSN 口令形态
    assert sandbox.scan_sandbox("R3SEC-FAKEKEY") == []
    for p in sandbox.base.rglob("*"):
        if p.is_file() and "iso_dsn" in p.name:
            pytest.fail(f"发现 R2 时代含密文件名残留: {p}")
