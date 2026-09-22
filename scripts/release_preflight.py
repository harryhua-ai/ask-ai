"""#46 Release Compatibility Preflight(fail-closed、有界、零 mutation)。

消费**发布树自带**的 ``deploy/prod/compatibility.yml``(release-owned
manifest,随 tag 冻结),在任何生产 mutation(DB migration / application
rollout)之前给出确定性升级兼容性判定:

- 判定来源只有显式 ``--manifest`` 路径 —— 调用方(update.sh / deploy
  workflow)必须从**冻结镜像**中提取 manifest 与本脚本,mutable main 永远
  无法重解释一个历史冻结发布(AC2);
- 契约期缺 manifest ⇒ fail-closed;``--pre-contract-release`` 仅用于历史
  (前契约)镜像:有界兼容路径 = 显式逐类 deferred 记录,绝不静默(AC2/AC4);
- config 检查只输出 name/期望形状/实际形状类,**任何配置值绝不进入输出**
  (含失败路径;AC3);
- host capability 与 dependency probe 是有界只读操作(subprocess 超时 /
  socket connect 超时;probe 词表封闭,manifest 无任何可执行字段 —— 不存在
  shell-in-manifest 面);评估器不可证的检查(如同拓扑 same-tag 一致性)
  显式 defer 到部署原语既有门(AC3);
- rollback 显式:``previous_compatible: false`` 的发布必须持有所声明的
  ``remediation_gate`` 才能通过(AC4)。

退出码:0 = pass / pass_with_deferred;2 = fail-closed。
本脚本全程零写副作用(只读文件/socket/有界子进程)。

用法:
    python3 scripts/release_preflight.py --manifest /path/compatibility.yml \
        [--env-file /path/.env] [--env K=V ...] [--probe-timeout 7] \
        [--remediation-ack GATE] [--pre-contract-release]
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

# 有界性上限(AC3):任何探针不得超过该墙钟;manifest 声明的超时同样受限。
MAX_PROBE_TIMEOUT_S = 30
DEFAULT_PROBE_TIMEOUT_S = 10
_SUBPROCESS_TIMEOUT_S = 10

CONFIG_SHAPES = ("non_empty_string", "integer", "boolean")
HOST_CAPABILITIES = ("docker_compose_v2", "nvidia_gpu")
DEPENDENCY_PROBES = ("tcp_connect",)
TOPOLOGY_REQUIREMENTS = ("same_tag_all_services",)
_MANIFEST_SECTIONS = ("config", "host", "topology", "dependencies", "rollback")
_DEFERRED_CLASSES = ("config", "host", "topology", "dependencies", "rollback")

_BOOL_VALUES = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}


# --------------------------------------------------------------------------- #
# 判定记录构造(reason 只含 name/class/gate 名,绝不含配置值)
# --------------------------------------------------------------------------- #


def _check(section: str, name: str, class_: str, status: str, reason: str = "") -> dict:
    return {
        "section": section,
        "name": name,
        "class": class_,
        "status": status,
        "reason": reason,
    }


def _fail_verdict(manifest: str, checks: list[dict], era: str = "contract") -> dict:
    return {
        "manifest": manifest,
        "era": era,
        "status": "fail",
        "checks": checks,
        "deferred": [],
    }


def _shape_of(value: str, shape: str) -> bool:
    """形状判定只看值类,评估结果不回显值本身。"""
    if shape == "non_empty_string":
        return bool(value.strip())
    if shape == "integer":
        try:
            int(value.strip())
            return True
        except ValueError:
            return False
    if shape == "boolean":
        return value.strip().lower() in _BOOL_VALUES
    return False  # 未知 shape 在 schema 校验即拒绝,此处不可达


def _shape_actual_class(value: str, shape: str) -> str:
    if value.strip() == "":
        return "empty"
    if shape == "integer":
        return "not_an_integer"
    if shape == "boolean":
        return "not_a_boolean"
    return "shape_mismatch"


# --------------------------------------------------------------------------- #
# Manifest 严格 schema(fail-closed;无任何可执行字段 → 无 shell-in-manifest 面)
# --------------------------------------------------------------------------- #


def _invalid(checks: list[dict], reason: str) -> tuple[dict, int]:
    checks.append(
        _check("manifest", "compatibility.yml", "manifest_invalid", "fail", reason)
    )
    return _fail_verdict("compatibility.yml", checks), 2


def _validate_manifest(raw: Any, checks: list[dict]) -> tuple[dict | None, int | None]:
    if not isinstance(raw, dict):
        return _invalid(checks, "manifest 根必须是映射")
    if raw.get("version") != 1:
        return _invalid(checks, f"version 必须为 1(实际 {raw.get('version')!r})")
    unknown = sorted(set(raw) - set(_MANIFEST_SECTIONS) - {"version"})
    if unknown:
        return _invalid(checks, f"未知 section(词表封闭): {unknown}")
    for sec in ("config", "host", "topology", "dependencies"):
        entries = raw.get(sec, [])
        if not isinstance(entries, list):
            return _invalid(checks, f"{sec} 必须是列表(显式空列表 = 无要求)")
    for entry in raw.get("config", []):
        if not isinstance(entry, dict) or sorted(entry) != sorted(
            ("name", "required", "shape", "secret")
        ):
            return _invalid(
                checks,
                "config 条目字段必须恰为 name/required/shape/secret",
            )
        if entry["shape"] not in CONFIG_SHAPES:
            return _invalid(checks, f"未知 config shape: {entry['shape']!r}")
        if not isinstance(entry["required"], bool) or not isinstance(entry["secret"], bool):
            return _invalid(checks, "config required/secret 必须是布尔")
        if not str(entry["name"]).strip():
            return _invalid(checks, "config name 不得为空")
    for entry in raw.get("host", []):
        if not isinstance(entry, dict) or sorted(entry) != ["capability"]:
            return _invalid(checks, "host 条目字段必须恰为 capability")
        if entry["capability"] not in HOST_CAPABILITIES:
            return _invalid(checks, f"未知 host capability: {entry['capability']!r}")
    for entry in raw.get("topology", []):
        if not isinstance(entry, dict) or sorted(entry) != ["requirement"]:
            return _invalid(checks, "topology 条目字段必须恰为 requirement")
        if entry["requirement"] not in TOPOLOGY_REQUIREMENTS:
            return _invalid(checks, f"未知 topology requirement: {entry['requirement']!r}")
    for entry in raw.get("dependencies", []):
        if not isinstance(entry, dict) or sorted(entry) != sorted(
            ("name", "probe", "host", "port", "timeout_s")
        ):
            return _invalid(
                checks,
                "dependencies 条目字段必须恰为 name/probe/host/port/timeout_s",
            )
        if entry["probe"] not in DEPENDENCY_PROBES:
            return _invalid(checks, f"未知 dependency probe: {entry['probe']!r}")
        if not (isinstance(entry["port"], int) and 0 < entry["port"] < 65536):
            return _invalid(checks, "dependency port 必须是合法端口整数")
        if not (isinstance(entry["timeout_s"], int) and 0 < entry["timeout_s"] <= MAX_PROBE_TIMEOUT_S):
            return _invalid(
                checks,
                f"dependency timeout_s 必须在 1..{MAX_PROBE_TIMEOUT_S}(探针必须有界)",
            )
    rollback = raw.get("rollback")
    if not isinstance(rollback, dict) or sorted(rollback) not in (
        ["previous_compatible"],
        ["previous_compatible", "remediation_gate"],
    ):
        return _invalid(
            checks,
            "rollback 必须是映射:previous_compatible(可含 remediation_gate)",
        )
    if not isinstance(rollback["previous_compatible"], bool):
        return _invalid(checks, "rollback.previous_compatible 必须是布尔")
    if not rollback["previous_compatible"] and not str(
        rollback.get("remediation_gate") or ""
    ).strip():
        return _invalid(
            checks,
            "previous_compatible=false 时必须声明 remediation_gate",
        )
    return raw, None


# --------------------------------------------------------------------------- #
# 有界只读探针
# --------------------------------------------------------------------------- #


def _run_probe(cmd: list[str], timeout_s: int) -> tuple[int, str]:
    """有界子进程探针(只读);超时/缺失按失败处理,绝不重试、绝不 mutation。"""
    try:
        proc = subprocess.run(  # noqa: S603 - cmd 来自封闭词表构造,非用户输入
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""
    return proc.returncode, (proc.stdout or "").strip()


def _capability_probe(capability: str) -> tuple[list[str], Any]:
    """capability → (命令, 判定函数)。命令由封闭词表构造,manifest 无注入面。"""
    if capability == "docker_compose_v2":
        cmd = ["docker", "compose", "version", "--short"]

        def ok(rc: int, out: str) -> bool:
            try:
                return rc == 0 and int(out.lstrip("vV").split(".")[0]) >= 2
            except (ValueError, IndexError):
                return False

        return cmd, ok
    if capability == "nvidia_gpu":
        cmd = ["nvidia-smi", "-L"]
        return cmd, (lambda rc, out: rc == 0 and bool(out))
    raise AssertionError("不可达:capability 词表已在 schema 校验封闭")


# --------------------------------------------------------------------------- #
# 主评估(全程只读)
# --------------------------------------------------------------------------- #


def evaluate(
    manifest_path: str,
    *,
    env: dict[str, str] | None = None,
    probe_timeout_s: int = DEFAULT_PROBE_TIMEOUT_S,
    remediation_ack: str | None = None,
    pre_contract: bool = False,
) -> tuple[dict, int]:
    env = dict(env or {})
    checks: list[dict] = []
    path = Path(manifest_path)
    if not path.is_file():
        if pre_contract:
            deferred = [
                {"class": cls, "reason": "前契约发布无 compatibility manifest,兼容性未证明"}
                for cls in _DEFERRED_CLASSES
            ]
            return (
                {
                    "manifest": manifest_path,
                    "era": "pre_contract",
                    "status": "pass_with_deferred",
                    "checks": [],
                    "deferred": deferred,
                },
                0,
            )
        checks.append(
            _check(
                "manifest",
                path.name,
                "manifest_missing",
                "fail",
                "契约期发布必须自带 compatibility manifest(AC2 fail-closed);"
                "历史镜像请显式使用 --pre-contract-release 有界路径",
            )
        )
        return _fail_verdict(manifest_path, checks), 2
    try:
        # stdlib json:宿主侧引导零第三方依赖(AC3/#46 REVIEW_1 blocker 4 ——
        # 不得要求生产主机预装 PyYAML 等未声明包)
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checks.append(
            _check("manifest", path.name, "manifest_invalid", "fail", f"JSON 解析失败: {exc.msg}")
        )
        return _fail_verdict(manifest_path, checks), 2
    manifest, err = _validate_manifest(raw, checks)
    if err is not None:
        # _validate_manifest 的错误路径已构造完整 fail verdict(err=2)
        verdict = checks and _fail_verdict(manifest_path, checks) or {}
        return verdict, 2
    assert manifest is not None

    # ---- config(存在性/形状;值绝不外泄)----
    for entry in manifest["config"]:
        name = str(entry["name"])
        value = env.get(name)
        # non_empty_string 的空值在语义上 = 缺失(提供不了值)
        if value is None or (entry["shape"] == "non_empty_string" and not value.strip()):
            if entry["required"]:
                checks.append(
                    _check(
                        "config", name, "config_missing", "fail",
                        f"必需配置缺失: {name}(期望形状 {entry['shape']};值不外泄)",
                    )
                )
            else:
                checks.append(_check("config", name, "config_optional_absent", "pass"))
            continue
        if not _shape_of(value, entry["shape"]):
            checks.append(
                _check(
                    "config", name, "config_invalid_shape", "fail",
                    f"{name} 形状不匹配: 期望 {entry['shape']},实际 "
                    f"{_shape_actual_class(value, entry['shape'])}(值不外泄)",
                )
            )
        else:
            checks.append(_check("config", name, "config_ok", "pass"))

    # ---- host capability(有界只读子进程;--probe-timeout 为全局执行上限)----
    subprocess_cap = min(_SUBPROCESS_TIMEOUT_S, max(1, probe_timeout_s))
    for entry in manifest["host"]:
        cap = entry["capability"]
        cmd, ok_fn = _capability_probe(cap)
        rc, out = _run_probe(cmd, subprocess_cap)
        if ok_fn(rc, out):
            checks.append(_check("host", cap, "host_capability_ok", "pass"))
        else:
            checks.append(
                _check(
                    "host", cap, "host_capability_missing", "fail",
                    f"主机能力不可证明: {cap}(探针 {' '.join(cmd)};有界 "
                    f"{subprocess_cap}s)",
                )
            )

    # ---- topology(声明式;评估器不可证 ⇒ 显式 defer 到部署原语既有门)----
    for entry in manifest["topology"]:
        req = entry["requirement"]
        checks.append(_check("topology", req, "topology_declared", "pass"))

    # ---- dependency probe(有界 socket connect;非 mutation)----
    for entry in manifest["dependencies"]:
        name = str(entry["name"])
        effective = min(int(entry["timeout_s"]), max(1, probe_timeout_s))
        try:
            with socket.create_connection(
                (str(entry["host"]), int(entry["port"])), timeout=effective
            ):
                checks.append(_check("dependencies", name, "dependency_ok", "pass"))
        except OSError as exc:
            checks.append(
                _check(
                    "dependencies", name, "dependency_unreachable", "fail",
                    f"{name} 不可达: {entry['host']}:{entry['port']}"
                    f"(有界 {effective}s;{type(exc).__name__})",
                )
            )

    # ---- rollback 兼容性门(AC4)----
    rollback = manifest["rollback"]
    if rollback["previous_compatible"]:
        checks.append(
            _check("rollback", "previous_compatible", "rollback_ok", "pass",
                   "普通 previous-tag 回滚兼容")
        )
    else:
        gate = str(rollback["remediation_gate"]).strip()
        if (remediation_ack or "").strip() == gate:
            checks.append(
                _check(
                    "rollback", "previous_compatible", "rollback_ok", "pass",
                    f"已确认 remediation gate: {gate}",
                )
            )
        else:
            checks.append(
                _check(
                    "rollback", "previous_compatible", "rollback_remediation_gate_required",
                    "fail",
                    "该发布声明与先前版本不兼容:普通 previous-tag 回滚不适用,"
                    f"必须确认声明的 remediation gate: {gate}",
                )
            )

    deferred: list[dict] = []
    for entry in manifest["topology"]:
        if entry["requirement"] == "same_tag_all_services":
            deferred.append(
                {
                    "class": "topology",
                    "reason": "same-tag 全服务一致性由部署原语既有 [6/6] 同 tag 断言强制;"
                    "评估器显式 defer,不重复实现",
                }
            )

    status = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    return (
        {
            "manifest": manifest_path,
            "era": "contract",
            "status": status,
            "checks": checks,
            "deferred": deferred,
        },
        0 if status != "fail" else 2,
    )


# --------------------------------------------------------------------------- #
# CLI(--env-file 逐行解析,值只进入内存,绝不输出)
# --------------------------------------------------------------------------- #


def _parse_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_preflight",
        description="#46 发布兼容性 preflight(fail-closed;先于任何生产 mutation)",
    )
    parser.add_argument("--manifest", required=True, help="发布树内 compatibility.yml 路径")
    parser.add_argument("--env-file", default=None, help="生产 env 文件(值绝不输出)")
    parser.add_argument(
        "--env", action="append", default=[], metavar="K=V",
        help="附加 env 键值(可重复;测试/注入用;值绝不输出)",
    )
    parser.add_argument(
        "--probe-timeout", type=int, default=DEFAULT_PROBE_TIMEOUT_S,
        help=f"依赖探针执行上限秒(≤{MAX_PROBE_TIMEOUT_S})",
    )
    parser.add_argument(
        "--remediation-ack", default=None,
        help="rollback remediation gate 确认(必须与 manifest 声明精确一致)",
    )
    parser.add_argument(
        "--pre-contract-release", action="store_true",
        help="历史(前契约)镜像的有界兼容路径:缺 manifest ⇒ 显式 deferred 而非 fail",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_out",
        help="stdout 输出机器可读 JSON verdict(默认行为;旗标为显式自描述)",
    )
    args = parser.parse_args(argv)

    env: dict[str, str] = {}
    if args.env_file:
        env.update(_parse_env_file(args.env_file))
    for pair in args.env:
        key, _, value = pair.partition("=")
        env[key.strip()] = value

    verdict, code = evaluate(
        args.manifest,
        env=env,
        probe_timeout_s=min(max(args.probe_timeout, 1), MAX_PROBE_TIMEOUT_S),
        remediation_ack=args.remediation_ack,
        pre_contract=args.pre_contract_release,
    )
    json.dump(verdict, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    if code == 2:
        print(
            "❌ 兼容性 preflight 未通过 —— 在 DB migration / application rollout "
            "之前 fail-closed(零 mutation)。逐项见上方 JSON verdict。",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
