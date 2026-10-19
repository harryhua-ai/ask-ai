"""#46 Release Compatibility Preflight(fail-closed、有界、零 mutation)。

消费**发布树自带**的 ``deploy/prod/compatibility.json``(release-owned
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
- G2 只读隔离断言(显式启用 ``--verify-upload-isolation``;未启用零变化):
  部署前对目标 DB / Weaviate 做只读断言 —— ``upload_mode=true`` 注册行必须
  为 0(按当前门语义取严:0 注册才 PASS)、filesystem 类 Weaviate 对象必须
  为 0;只读查询通道不可用 → 该子项 BLOCKED(不谎报 PASS);任一断言失败
  → 非零退出 + 结构化原因。本检查不创建 remediation ACK、不改门值。
- 目标身份绑定(R2-4,防错连空库/错库假 PASS):DB 侧同会话先
  ``SELECT current_database()`` 并与 DSN 声明精确比对;Weaviate 侧先
  ``GET /v1/meta`` 并将 hostname 与显式期望(URL host:port)绑定;目标
  collection 总对象 = 0 → BLOCKED(空集合上的 0 计数不构成隔离证据)。
  身份不一致/连接失败一律 fail-closed 非零退出;JSON verdict 绝不含 DSN/
  口令。注意:隔离子项 PASS ≠ G2 门 PASS —— G2 的正式满足以生产部署
  workflow 强制接线为准。
- 凭据边界(R2-1):隔离断言的 DB DSN 含口令,**绝不接受命令行参数**
  (``--isolation-pg-dsn`` 已移除并显式拒绝 —— 进程 argv 对同机所有用户/
  ps 可见)。DSN 只经受控环境变量(``--isolation-pg-dsn-env <VAR_NAME>``,
  缺省读 ``ISOLATION_PG_DSN``)或安全文件(``--isolation-pg-dsn-file``)
  进入;argparse 只见变量名/路径,绝不见秘密本身。缺失/格式非法/连接失败
  一律 fail-closed 非零退出;DSN 绝不进入日志/异常/JSON 输出;psql 口令仍
  仅经 PGPASSWORD env 传递。

退出码:0 = pass / pass_with_deferred;2 = fail-closed。
本脚本全程零写副作用(只读文件/socket/有界子进程)。

用法:
    python3 scripts/release_preflight.py --manifest /path/compatibility.json \
        [--env-file /path/.env] [--env K=V ...] [--probe-timeout 7] \
        [--remediation-ack GATE] [--pre-contract-release] \
        [--verify-upload-isolation \
         [--isolation-pg-dsn-env VAR_NAME | --isolation-pg-dsn-file PATH] \
         [--isolation-weaviate-url URL --isolation-weaviate-class NAME]]
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

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
        _check("manifest", "compatibility.json", "manifest_invalid", "fail", reason)
    )
    return _fail_verdict("compatibility.json", checks), 2


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
# G2 只读隔离断言探针(显式启用;全程零 mutation)
# --------------------------------------------------------------------------- #


class IsolationChannelUnavailable(RuntimeError):
    """只读查询通道不可用(工具缺失/参数缺失)→ 子项 BLOCKED,不谎报 PASS。"""


class IsolationTargetUnproven(IsolationChannelUnavailable):
    """目标身份不可证(如 collection 总对象 = 0)→ BLOCKED:空集合上的
    0 计数不构成隔离证据(不能证明测的是对的库/集合)。"""


class IsolationIdentityMismatch(RuntimeError):
    """连接后身份复核失败(current_database()/meta hostname 与显式声明不一致,
    或身份不可读)→ fail-closed。错误文本只含库名/host/port 类非秘密标识,
    绝不含 DSN 口令,可安全进入结构化 reason。"""


# 封闭词表只读 SQL(SELECT count(*);无任何外部输入拼接面)
_UPLOAD_MODE_COUNT_SQL = (
    "SELECT count(*) FROM data_sources WHERE config->>'upload_mode' = 'true'"
)
# R2-4①:连接后身份复核 —— current_database() 必须与 DSN 声明的 dbname 一致
_CURRENT_DATABASE_SQL = "SELECT current_database()"
# Weaviate class 名词表(同集合命名规则):杜绝 GraphQL 注入面
_WEAVIATE_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _http_connection_factory(scheme: str, host: str, port: int, timeout_s: int):
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout_s)
    return http.client.HTTPConnection(host, port, timeout=timeout_s)


def _parse_pg_target(dsn: str) -> tuple[list[str], str, str | None]:
    """libpq DSN → (psql 基础 argv, dbname, password)。口令只回传给 env 构造。"""
    raw = dsn.strip()
    if "://" in raw:
        scheme_part, _, tail = raw.partition("://")
        raw = f"{scheme_part.split('+', 1)[0]}://{tail}"  # 剥离 +asyncpg 等 driver 段
    parsed = urlsplit(raw)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError("isolation pg dsn 必须是 postgresql:// 形式")
    dbname = unquote(parsed.path).lstrip("/")
    if not dbname:
        raise RuntimeError("isolation pg dsn 缺 dbname")
    argv = ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    if parsed.hostname:
        argv += ["-h", parsed.hostname]
    if parsed.port:
        argv += ["-p", str(parsed.port)]
    if parsed.username:
        argv += ["-U", parsed.username]
    argv += ["-d", dbname]
    return argv, dbname, (unquote(parsed.password) if parsed.password else None)


def _psql_argv_env(dsn: str) -> tuple[list[str], dict[str, str]]:
    """libpq DSN → (psql argv, env 增量)。口令只进 PGPASSWORD env,绝不进 argv。"""
    argv, _dbname, password = _parse_pg_target(dsn)
    return argv, {"PGPASSWORD": password} if password else {}


def probe_upload_mode_rows(pg_cfg: dict, timeout_s: int) -> int:
    """目标 DB 中 ``upload_mode=true`` 注册行数(有界只读 psql 探针)。

    R2-4①:同一 psql 会话先 ``SELECT current_database()`` 再计数,身份与
    DSN 声明不一致 → fail-closed(防错连空库/错库后的假 PASS)。

    Raises:
        IsolationChannelUnavailable: psql 不可用(通道缺失 → BLOCKED)。
        RuntimeError: DSN 非法/超时/非零退出/身份不一致/输出不可读(→ fail-closed)。
    """
    dsn = str(pg_cfg.get("dsn") or "").strip()
    if not dsn:
        raise IsolationChannelUnavailable(
            "缺隔离 DB DSN(须经 --isolation-pg-dsn-env <VAR_NAME> 或"
            " --isolation-pg-dsn-file <PATH> 提供;DSN 含口令,绝不进 argv)"
        )
    base_argv, declared_db, password = _parse_pg_target(dsn)
    argv = base_argv + ["-c", _CURRENT_DATABASE_SQL, "-c", _UPLOAD_MODE_COUNT_SQL]
    env = {**os.environ, "PGPASSWORD": password} if password else None
    try:
        proc = subprocess.run(  # noqa: S603 - argv 由封闭词表构造,非用户拼接
            argv,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_s),
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise IsolationChannelUnavailable("psql 不可用(只读 DB 查询通道缺失)") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"psql 探针超时(有界 {timeout_s}s)") from exc
    if proc.returncode != 0:
        # stderr 可能含主机/用户名,一律不回显,只报结构化原因
        raise RuntimeError(f"psql 探针失败(returncode={proc.returncode};输出不回显)")
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        raise IsolationIdentityMismatch(
            "psql 探针输出缺身份行/计数行(身份不可证)—— fail-closed"
        )
    actual_db = lines[0]
    if actual_db != declared_db:
        raise IsolationIdentityMismatch(
            f"目标 DB 身份不一致:current_database()={actual_db!r} ≠ DSN 声明 "
            f"{declared_db!r} —— 连接目标与显式声明不符,fail-closed"
        )
    try:
        return int(lines[-1])
    except ValueError as exc:
        raise RuntimeError("psql 探针输出不可读为计数") from exc


def probe_filesystem_objects(wv_cfg: dict, timeout_s: int) -> int:
    """filesystem 类 Weaviate 对象数(只读探针:/v1/meta 身份绑定 + Aggregate 计数)。

    R2-4②/③:先 GET ``/v1/meta`` 并将其 hostname 与显式期望(URL 的
    host:port)精确绑定 —— 不一致即 fail-closed;GraphQL 单请求双聚合取
    「集合总对象数」与「filesystem 类对象数」,总对象 = 0 →
    ``IsolationTargetUnproven``(BLOCKED):空集合上的 0 计数不能证明测的
    是对的库/集合,绝不假 PASS。

    Raises:
        IsolationChannelUnavailable: URL/class 参数缺失(→ BLOCKED)。
        IsolationTargetUnproven: 集合总对象 = 0(BLOCKED,不构成隔离证据)。
        RuntimeError: class 名词表外/meta 不可达/身份不一致/HTTP 错误/响应
            不可读(→ fail-closed)。
    """
    url = str(wv_cfg.get("url") or "").strip()
    class_name = str(wv_cfg.get("class") or "").strip()
    if not url or not class_name:
        raise IsolationChannelUnavailable(
            "缺 --isolation-weaviate-url/--isolation-weaviate-class"
        )
    if not _WEAVIATE_CLASS_RE.match(class_name):
        raise RuntimeError("isolation weaviate class 名在词表外(拒绝)")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("isolation weaviate url 非法(http/https + host 必需)")
    default_port = 443 if parsed.scheme == "https" else 80
    conn = _http_connection_factory(
        parsed.scheme, parsed.hostname, parsed.port or default_port, max(1, timeout_s)
    )
    try:
        # ---- R2-4② 身份绑定:GET /v1/meta ↔ 显式期望(URL host:port) ----
        conn.request("GET", "/v1/meta", body=None, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"weaviate /v1/meta 探针 HTTP {resp.status}")
        try:
            meta = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("weaviate /v1/meta 响应非 JSON") from exc
        if not isinstance(meta, dict) or not str(meta.get("hostname") or "").strip():
            raise IsolationIdentityMismatch(
                "weaviate /v1/meta 响应缺 hostname(身份不可证)—— fail-closed"
            )
        meta_raw = str(meta["hostname"]).strip()
        meta_parsed = urlsplit(meta_raw if "://" in meta_raw else f"http://{meta_raw}")
        meta_host = (meta_parsed.hostname or "").lower()
        meta_port = meta_parsed.port or (
            443 if meta_parsed.scheme == "https" else 80
        )
        our_port = parsed.port or default_port
        if (meta_host, meta_port) != (parsed.hostname.lower(), our_port):
            raise IsolationIdentityMismatch(
                "weaviate 身份不一致:/v1/meta hostname 与显式期望(URL host:"
                f"{our_port})不匹配 —— 拒绝把证据记在未证实的目标上,fail-closed"
            )

        # ---- R2-4③ 防空集合假 PASS:同一 GraphQL 请求双聚合(total + filesystem) ----
        alias_total = f"{class_name}_TOTAL"
        alias_fs = f"{class_name}_FILESYSTEM"
        query = {
            "query": (
                f"{{Aggregate{{{alias_total}:{class_name}{{meta{{count}}}},"
                f"{alias_fs}:{class_name}(where:{{operator:Equal,"
                f'path:["source_type"],valueString:"filesystem"}}){{meta{{count}}}}}}}}'
            )
        }
        conn.request(
            "POST",
            "/v1/graphql",
            body=json.dumps(query),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"weaviate 探针 HTTP {resp.status}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("weaviate 探针响应非 JSON") from exc
        if not isinstance(data, dict) or data.get("errors"):
            raise RuntimeError("weaviate 探针 GraphQL errors 或响应形状非法")
        aggregate = data.get("data", {}).get("Aggregate", {}) if isinstance(data, dict) else {}

        def _count_of(alias: str) -> int:
            groups = aggregate.get(alias)
            if groups == []:
                return 0  # Aggregate 空组 = 零命中
            try:
                count = int(groups[0]["meta"]["count"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("weaviate 探针响应形状不可读") from exc
            if count < 0:
                raise RuntimeError("weaviate 探针 count 非法(负数)")
            return count

        total = _count_of(alias_total)
        filesystem = _count_of(alias_fs)
        if total == 0:
            raise IsolationTargetUnproven(
                f"目标 collection(class={class_name})总对象 = 0:无法证明所连即"
                "目标库/集合 —— 空集合上的 0 计数不构成隔离证据,BLOCKED"
                "(不谎报 PASS)"
            )
        return filesystem
    finally:
        conn.close()


def _upload_isolation_checks(isolation: dict, timeout_s: int) -> list[dict]:
    """构造 isolation 检查项;BLOCKED 与 fail 均使整体非零退出(fail-closed)。"""
    out: list[dict] = []

    dsn = str(isolation.get("pg_dsn") or "").strip()
    if not dsn:
        out.append(
            _check(
                "isolation", "upload_mode_rows", "isolation_upload_mode_unprovable",
                "blocked",
                "只读 DB 查询通道不可用(缺隔离 DB DSN:env 变量未设/文件不可读,"
                "DSN 含口令绝不进 argv):upload_mode 注册行"
                "断言无法证明,BLOCKED(不谎报 PASS)",
            )
        )
    else:
        try:
            rows = probe_upload_mode_rows({"dsn": dsn}, timeout_s)
        except IsolationChannelUnavailable as exc:
            out.append(
                _check(
                    "isolation", "upload_mode_rows", "isolation_upload_mode_unprovable",
                    "blocked", f"只读 DB 查询通道不可用: {exc}(BLOCKED,不谎报 PASS)",
                )
            )
        except IsolationIdentityMismatch as exc:
            # 身份不一致文本只含库名类非秘密标识(见异常类契约),可入 reason
            out.append(
                _check(
                    "isolation", "upload_mode_rows", "isolation_upload_mode_identity_mismatch",
                    "fail", f"{exc}(fail-closed:不把证据记在未声明的目标上)",
                )
            )
        except Exception as exc:  # noqa: BLE001 - 探针失败 = 证据不成立,fail-closed
            out.append(
                _check(
                    "isolation", "upload_mode_rows", "isolation_upload_mode_probe_failed",
                    "fail",
                    f"upload_mode 注册行断言探针失败({type(exc).__name__}),隔离证据"
                    "不成立,fail-closed",
                )
            )
        else:
            if rows:
                out.append(
                    _check(
                        "isolation", "upload_mode_rows",
                        "isolation_upload_mode_rows_present", "fail",
                        f"目标 DB 存在 {rows} 行 upload_mode=true 注册;按当前门语义"
                        "取严:必须 0 注册才 PASS(r3 摄取空集元数据 fail-closed 依据)",
                    )
                )
            else:
                out.append(
                    _check(
                        "isolation", "upload_mode_rows", "isolation_upload_mode_clean",
                        "pass", "upload_mode=true 注册行 = 0",
                    )
                )

    wv_url = str(isolation.get("weaviate_url") or "").strip()
    wv_class = str(isolation.get("weaviate_class") or "").strip()
    if not wv_url or not wv_class:
        out.append(
            _check(
                "isolation", "filesystem_objects", "isolation_filesystem_unprovable",
                "blocked",
                "只读向量查询通道不可用(缺 --isolation-weaviate-url/"
                "--isolation-weaviate-class):filesystem 类对象断言无法证明,"
                "BLOCKED(不谎报 PASS)",
            )
        )
    else:
        try:
            objects = probe_filesystem_objects(
                {"url": wv_url, "class": wv_class}, timeout_s
            )
        except IsolationChannelUnavailable as exc:
            out.append(
                _check(
                    "isolation", "filesystem_objects", "isolation_filesystem_unprovable",
                    "blocked", f"只读向量查询通道不可用: {exc}(BLOCKED,不谎报 PASS)",
                )
            )
        except IsolationIdentityMismatch as exc:
            out.append(
                _check(
                    "isolation", "filesystem_objects", "isolation_filesystem_identity_mismatch",
                    "fail", f"{exc}(fail-closed:不把证据记在未声明的目标上)",
                )
            )
        except Exception as exc:  # noqa: BLE001 - 探针失败 = 证据不成立,fail-closed
            out.append(
                _check(
                    "isolation", "filesystem_objects", "isolation_filesystem_probe_failed",
                    "fail",
                    f"filesystem 类对象断言探针失败({type(exc).__name__}),隔离证据"
                    "不成立,fail-closed",
                )
            )
        else:
            if objects:
                out.append(
                    _check(
                        "isolation", "filesystem_objects",
                        "isolation_filesystem_objects_present", "fail",
                        f"目标 Weaviate 存在 {objects} 个 filesystem 类对象;必须为 0"
                        "(查询侧幽灵 DENY 版本无关,残留即跨版本重暴露面)",
                    )
                )
            else:
                out.append(
                    _check(
                        "isolation", "filesystem_objects",
                        "isolation_filesystem_clean", "pass",
                        "filesystem 类 Weaviate 对象 = 0",
                    )
                )
    return out


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
    verify_upload_isolation: bool = False,
    isolation: dict | None = None,
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

    # ---- G2 只读隔离断言(显式启用;未启用零变化)----
    if verify_upload_isolation:
        checks.extend(_upload_isolation_checks(isolation or {}, subprocess_cap))

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

    # fail 与 blocked 一律非零退出:BLOCKED = 隔离证据不可证,绝不谎报 PASS
    status = (
        "fail"
        if any(c["status"] in ("fail", "blocked") for c in checks)
        else "pass"
    )
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


# 缺省受控环境变量名(--isolation-pg-dsn-env 未显式给出时)
DEFAULT_ISOLATION_DSN_ENV_VAR = "ISOLATION_PG_DSN"


def _resolve_isolation_pg_dsn(args: argparse.Namespace) -> str | None:
    """解析隔离断言 DB DSN;秘密只经 env 变量或安全文件进入,绝不来自 argv。

    Returns:
        DSN 字符串;来源缺失/不可读 → None(由 isolation 检查转为 BLOCKED,
        整体非零退出 —— fail-closed)。任何失败路径绝不回显 DSN 内容。
    """
    if args.isolation_pg_dsn_file:
        try:
            lines = Path(args.isolation_pg_dsn_file).read_text(
                encoding="utf-8"
            ).splitlines()
        except OSError:
            return None
        # 首行即 DSN;strip 掉空白;绝不打印文件内容
        return (lines[0].strip() if lines else "") or None
    var_name = (args.isolation_pg_dsn_env or DEFAULT_ISOLATION_DSN_ENV_VAR).strip()
    if not var_name:
        return None
    return os.environ.get(var_name) or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_preflight",
        description="#46 发布兼容性 preflight(fail-closed;先于任何生产 mutation)",
        allow_abbrev=False,  # 杜绝 --isolation-pg-dsn 之类前缀歧义静默匹配
    )
    parser.add_argument("--manifest", required=True, help="发布树内 compatibility.json 路径(stdlib JSON;宿主零第三方依赖)")
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
        "--verify-upload-isolation", action="store_true",
        help="G2 只读隔离断言(显式启用;未启用零变化):目标 DB upload_mode=true "
        "注册行必须为 0 且 filesystem 类 Weaviate 对象必须为 0;只读查询通道"
        "不可用 → BLOCKED(fail-closed,不谎报 PASS)",
    )

    class _RejectDsnInArgv(argparse.Action):
        """R2-1:含口令的 DSN 绝不接受为命令行值(argv 对 ps/同机用户可见)。"""

        def __call__(self, parser, namespace, values, option_string=None):
            parser.error(
                f"{option_string} 已移除:DSN 含口令,禁止进入进程 argv;"
                "请改用 --isolation-pg-dsn-env <VAR_NAME>(推荐,缺省读"
                " ISOLATION_PG_DSN)或 --isolation-pg-dsn-file <PATH>(0600)"
            )

    parser.add_argument(
        "--isolation-pg-dsn", action=_RejectDsnInArgv,
        help=argparse.SUPPRESS,  # 显式注册仅为给出明确拒绝信息(fail-closed)
    )
    parser.add_argument(
        "--isolation-pg-dsn-env", default=None, metavar="VAR_NAME",
        help="持有隔离断言目标 DB DSN 的环境变量名(推荐;缺省读 "
        "ISOLATION_PG_DSN)。argparse 只收变量名,秘密本身绝不进 argv",
    )
    parser.add_argument(
        "--isolation-pg-dsn-file", default=None, metavar="PATH",
        help="持有隔离断言目标 DB DSN 的安全文件路径(建议 0600;首行即 DSN)",
    )
    parser.add_argument(
        "--isolation-weaviate-url", default=None,
        help="隔离断言目标 Weaviate http(s) URL(只读 GraphQL Aggregate 探针)",
    )
    parser.add_argument(
        "--isolation-weaviate-class", default=None,
        help="向量 collection class 名(词表 [A-Za-z][A-Za-z0-9_]*)",
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
        verify_upload_isolation=args.verify_upload_isolation,
        isolation=(
            {
                "pg_dsn": _resolve_isolation_pg_dsn(args),
                "weaviate_url": args.isolation_weaviate_url,
                "weaviate_class": args.isolation_weaviate_class,
            }
            if args.verify_upload_isolation
            else None
        ),
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
