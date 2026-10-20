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
  缺省读 ``ISOLATION_PG_DSN``)、安全文件(``--isolation-pg-dsn-file``)或
  进程自身 env 组件装配(``--isolation-pg-dsn-parts``,生产 backend 容器内
  路径:凭据经容器自身 env 继承)进入;argparse 只见变量名/路径/旗标,
  绝不见秘密本身。缺失/格式非法/连接失败一律 fail-closed 非零退出;DSN
  绝不进入日志/异常/JSON 输出;psql 口令仍仅经 PGPASSWORD env 传递。
- 可信生产身份绑定(R3-1,独立信任锚):R2 的 current_database()==DSN
  dbname 与 /v1/meta hostname==URL host:port 属**同源配置自洽检查**,不能
  独立证明连的是权威生产实例(误配同名测试库/代理环境可制造假 PASS)。
  R3 起隔离断言必须持带外钉扎的信任锚(``--isolation-trust-anchor-file``,
  A 采集):PG 用 ``pg_control_system().system_identifier``(每集群 initdb
  唯一;文件级复制恢复会保留生产 id —— 恢复副本=生产衍生数据,识别为
  生产衍生是正确语义)。锚文件缺失/缺字段/不可读/词表外 → fail-closed,
  **绝不进入隔离断言**;实测值与钉扎值不一致 → fail-closed(同名库/同名
  集合/别名代理一律拒)。锚值不视为机密,但被测配置绝不同时充当期望
  身份。
- Weaviate 身份锚双模式(R4-1,真实 1.28.0 实测修正):R3 假定
  /v1/schema class 对象携带 ``collectionId``/``uuid`` 强稳定标识 —— 生产
  固定镜像 ``cr.weaviate.io/semitechnologies/weaviate:1.28.0`` 的官方
  OpenAPI ``definitions.Class`` 与**真实实例实测**均无这些字段(2026-10-20
  本地同版实例三个只读端点实测;R3 绿色测试里的 collectionId 是 fake
  构造数据)。R4 起锚分两版,A 按目标版本钉扎其一:
  * v1(新版本 Weaviate,响应含 collectionId):数据面直接与钉扎
    collectionId 精确比对(R3 语义原样保留;meta hostname↔URL 绑定保持
    严格);
  * v2(1.28.0):API 层无强唯一标识 → **控制面+数据面组合锚**。
    控制面(deploy workflow SSH 步骤,已被主机密钥钉扎)只读核验运行中
    weaviate 容器:镜像 config digest、数据卷挂载、CLUSTER_HOSTNAME env、
    数据卷目录**元数据清单哈希**(文件名/大小/mtime 排序后 sha256,不读
    客户内容),与锚钉扎值任一不匹配 → 在容器 preflight 之前中止;
    数据面(本脚本,容器内)把 URL 可达实例与控制面钉扎值绑定:
    GET /v1/nodes 单节点 ``name`` 必须等于钉扎 ``weaviate_cluster_hostname``
    (1.28.0 实测 = CLUSTER_HOSTNAME env 自报;meta.hostname 实测为绑定
    地址自述 ``http://[::]:8080``,与客户端 URL 分属命名空间,不作 v2
    身份判据,仅保留形状 sanity)。集合存在 + 总对象 > 0 + filesystem
    对象 = 0 断言保持不变。两层任一不匹配 → fail-closed。
    **诚实边界**:数据卷内容在钉扎后被整体原样替换且元数据清单恰好一致
    的场景不可排除(v2 组合锚 PARTIAL 残余风险,如实保留)。
- psql 缺失容器内的 DB 只读通道(R3-2):冻结镜像 runtime 无
  postgresql-client → psql 通道缺失时回退冻结镜像自带 psycopg2 的单会话
  只读探针(与 psql 通道完全相同的三条 SELECT 与身份复核;连接/查询失败
  详情一律不回显,只报异常类型)。两通道均不可用 → 子项 BLOCKED(不谎报
  PASS)。

退出码:0 = pass / pass_with_deferred;2 = fail-closed。
本脚本全程零写副作用(只读文件/socket/有界子进程)。

用法:
    python3 scripts/release_preflight.py --manifest /path/compatibility.json \
        [--env-file /path/.env] [--env K=V ...] [--probe-timeout 7] \
        [--remediation-ack GATE] [--pre-contract-release] \
        [--verify-upload-isolation \
         [--isolation-pg-dsn-env VAR_NAME | --isolation-pg-dsn-file PATH | \
          --isolation-pg-dsn-parts] \
         [--isolation-weaviate-url URL | --isolation-weaviate-url-env VAR_NAME] \
         [--isolation-weaviate-class NAME | --isolation-weaviate-class-env VAR_NAME] \
         --isolation-trust-anchor-file PATH]]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

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


class IsolationIdentityUnprovable(IsolationChannelUnavailable):
    """强身份标识不可得(R3-1:如 Weaviate 响应无 collectionId/uuid 字段)
    → 该子项如实 BLOCKED:无法与信任锚比对,绝不降低验证强度换 PASS。"""


class IsolationIdentityMismatch(RuntimeError):
    """连接后身份复核失败(current_database()/meta hostname/信任锚钉扎值
    与实测不一致,或身份不可读)→ fail-closed。错误文本只含库名/host/port
    类非秘密标识,绝不含 DSN 口令,可安全进入结构化 reason。"""


# 封闭词表只读 SQL(SELECT count(*);无任何外部输入拼接面)
_UPLOAD_MODE_COUNT_SQL = (
    "SELECT count(*) FROM data_sources WHERE config->>'upload_mode' = 'true'"
)
# R2-4①:连接后身份复核 —— current_database() 必须与 DSN 声明的 dbname 一致
_CURRENT_DATABASE_SQL = "SELECT current_database()"
# R3-1:独立信任锚实测值 —— 每集群 initdb 唯一的 system_identifier
# (pg_control_system();文件级复制恢复保留生产 id = 恢复副本属生产衍生的正确语义)
_PG_SYSTEM_ID_SQL = "SELECT system_identifier FROM pg_control_system()"
# Weaviate class 名词表(同集合命名规则):杜绝 GraphQL 注入面
_WEAVIATE_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _http_connection_factory(scheme: str, host: str, port: int, timeout_s: int):
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout_s)
    return http.client.HTTPConnection(host, port, timeout=timeout_s)


def _pg_target_fields(dsn: str) -> dict:
    """libpq DSN → {host, port, user, password, dbname}(口令只回传给 env/驱动)。"""
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
    return {
        "host": parsed.hostname or "",
        "port": parsed.port,  # None = 未声明(psql 走 libpq 缺省)
        "user": unquote(parsed.username) if parsed.username else "",
        "password": unquote(parsed.password) if parsed.password else "",
        "dbname": dbname,
    }


def _parse_pg_target(dsn: str) -> tuple[list[str], str, str | None]:
    """libpq DSN → (psql 基础 argv, dbname, password)。口令只回传给 env 构造。"""
    f = _pg_target_fields(dsn)
    argv = ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    if f["host"]:
        argv += ["-h", f["host"]]
    if f["port"]:
        argv += ["-p", str(f["port"])]
    if f["user"]:
        argv += ["-U", f["user"]]
    argv += ["-d", f["dbname"]]
    return argv, f["dbname"], (f["password"] or None)


def _psql_argv_env(dsn: str) -> tuple[list[str], dict[str, str]]:
    """libpq DSN → (psql argv, env 增量)。口令只进 PGPASSWORD env,绝不进 argv。"""
    argv, _dbname, password = _parse_pg_target(dsn)
    return argv, {"PGPASSWORD": password} if password else {}


def _import_psycopg2():
    """psycopg2 导入统一入口(冻结镜像自带;宿主 stdlib-only 路径不触发)。
    不可用 → IsolationChannelUnavailable(两通道均缺失 → 子项 BLOCKED)。"""
    try:
        import psycopg2  # noqa: PLC0415 - 容器内冻结镜像自带,按需导入
    except ImportError as exc:
        raise IsolationChannelUnavailable(
            "psql 与 psycopg2 只读查询通道均不可用"
        ) from exc
    return psycopg2


def _pg_probe_psql(dsn: str, timeout_s: int) -> tuple[str, str, int]:
    """psql 只读探针:单会话顺序执行 current_database / system_identifier /
    upload_mode 计数 → (dbname, system_id, count)。"""
    base_argv, _declared_db, password = _parse_pg_target(dsn)
    argv = base_argv + [
        "-c", _CURRENT_DATABASE_SQL, "-c", _PG_SYSTEM_ID_SQL, "-c", _UPLOAD_MODE_COUNT_SQL,
    ]
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
    if len(lines) < 3:
        raise IsolationIdentityMismatch(
            "psql 探针输出缺身份行/system_identifier 行/计数行(身份不可证)—— fail-closed"
        )
    return lines[0], lines[1], _count_or_fail(lines[2])


def _strict_probe_count(value: Any) -> int:
    """R4-2:驱动通道 COUNT 结果严格采用 —— 仅当取得合法非负整数才可作计数。

    None(空行)/NULL/布尔/浮点/字符串/bytes 等任何其它类型、负数、非整数值
    一律 RuntimeError(fail-closed:BLOCKED/FAIL),**绝不默认零、绝不吞噬**。
    psycopg2 对 ``SELECT count(*)`` 返回 int;``numeric`` 以 Decimal 返回
    (仅接受可无损整转的值)。
    """
    from decimal import Decimal  # noqa: PLC0415 - 局部导入,失败面最小

    if value is None:
        raise RuntimeError(
            "psycopg2 只读探针计数不可证明(NULL/空行)—— 绝不解释为 0,fail-closed"
        )
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise RuntimeError(
            f"psycopg2 只读探针计数类型非法({type(value).__name__})—— fail-closed"
        )
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise RuntimeError(
                "psycopg2 只读探针计数非整数值 —— fail-closed"
            )
        number = int(value)
    else:
        number = int(value)
    if number < 0:
        raise RuntimeError("psycopg2 只读探针计数为负数 —— fail-closed")
    return number


def _pg_probe_driver(dsn: str, timeout_s: int) -> tuple[str, str, int]:
    """psql 缺失容器内的只读通道(R3-2):冻结镜像自带 psycopg2,单会话
    执行与 psql 通道**完全相同**的三条只读 SELECT。凭据只从受控通道的 DSN
    进入本进程内存;连接/查询失败的详情(可能含 conninfo)绝不回显,只报
    异常类型。会话显式 rollback 收尾(零 mutation 语义)。

    R4-2:COUNT 结果经 ``_strict_probe_count`` 严格采用 —— fetchone() 返回
    None 行/NULL/非法类型/负数/转换失败/查询异常/断连一律 fail-closed,
    绝不再把不可证明的计数解释为 0(旧 fail-open 已消除)。
    """
    psycopg2 = _import_psycopg2()
    f = _pg_target_fields(dsn)
    try:
        conn = psycopg2.connect(
            host=f["host"] or None,
            port=f["port"] or 5432,
            user=f["user"] or None,
            password=f["password"] or None,
            dbname=f["dbname"],
            connect_timeout=max(1, timeout_s),
        )
    except Exception as exc:  # noqa: BLE001 - 异常文本可能含 conninfo,绝不回显
        raise RuntimeError(
            f"psycopg2 只读探针连接失败({type(exc).__name__};详情不回显)"
        ) from exc
    try:
        with conn.cursor() as cur:
            cur.execute(_CURRENT_DATABASE_SQL)
            row = cur.fetchone()
            db = str(row[0]) if row and row[0] is not None else ""
            cur.execute(_PG_SYSTEM_ID_SQL)
            row = cur.fetchone()
            sid = str(row[0]) if row and row[0] is not None else ""
            cur.execute(_UPLOAD_MODE_COUNT_SQL)
            row = cur.fetchone()
            count = _strict_probe_count(row[0] if row is not None else None)
        conn.rollback()  # 只读会话显式回滚收尾(零 mutation 语义)
    except Exception as exc:  # noqa: BLE001 - 异常文本可能含 conninfo,绝不回显
        raise RuntimeError(
            f"psycopg2 只读探针失败({type(exc).__name__};详情不回显)"
        ) from exc
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - 收尾路径,不掩盖原异常
            pass
    return db, sid, count


def _count_or_fail(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError("psql 探针输出不可读为计数") from exc


def probe_upload_mode_rows(pg_cfg: dict, timeout_s: int) -> int:
    """目标 DB 中 ``upload_mode=true`` 注册行数(有界只读探针)。

    R2-4①:同一会话先 ``SELECT current_database()`` 再计数,与 DSN 声明不一致
    → fail-closed。R3-1:进一步查询 ``pg_control_system().system_identifier``
    并与**带外钉扎的信任锚**精确比对 —— 锚值独立于被测 DSN/URL/自报
    metadata,同名库/误配测试集群即使 dbname 自洽也一律拒;缺失期望锚值
    → fail-closed(绝不执行计数断言)。psql 通道缺失 → 冻结镜像自带
    psycopg2 只读通道(两通道均缺失 → BLOCKED)。

    Raises:
        IsolationChannelUnavailable: psql 与 psycopg2 通道均不可用(→ BLOCKED)。
        IsolationIdentityMismatch: 缺期望锚值/身份不可读/身份不一致(→ fail-closed)。
        RuntimeError: DSN 非法/超时/非零退出/输出不可读(→ fail-closed)。
    """
    dsn = str(pg_cfg.get("dsn") or "").strip()
    if not dsn:
        raise IsolationChannelUnavailable(
            "缺隔离 DB DSN(须经 --isolation-pg-dsn-env <VAR_NAME>、"
            " --isolation-pg-dsn-file <PATH> 或 --isolation-pg-dsn-parts 提供;"
            "DSN 含口令,绝不进 argv)"
        )
    expected_sid = str(pg_cfg.get("expected_pg_system_id") or "").strip()
    if not expected_sid:
        raise IsolationIdentityMismatch(
            "缺信任锚期望 pg system_identifier(--isolation-trust-anchor-file 缺失/"
            "未接线):目标身份无法独立于被测 DSN 证明 —— 绝不执行计数断言,fail-closed"
        )
    try:
        actual_db, actual_sid, rows = _pg_probe_psql(dsn, timeout_s)
    except IsolationChannelUnavailable:
        actual_db, actual_sid, rows = _pg_probe_driver(dsn, timeout_s)
    if actual_db != _pg_target_fields(dsn)["dbname"]:
        raise IsolationIdentityMismatch(
            f"目标 DB 身份不一致:current_database()={actual_db!r} ≠ DSN 声明 "
            f"{_pg_target_fields(dsn)['dbname']!r} —— 连接目标与显式声明不符,fail-closed"
        )
    if not re.fullmatch(r"[0-9]+", actual_sid or ""):
        raise IsolationIdentityMismatch(
            "pg_control_system() system_identifier 不可读(身份不可证)—— fail-closed"
        )
    if actual_sid != expected_sid:
        raise IsolationIdentityMismatch(
            f"目标 DB 身份不一致:pg_control_system() system_identifier={actual_sid}"
            " ≠ 信任锚钉扎值 —— 所连非锚定生产实例(同名库/误配测试集群亦拒;"
            "文件级恢复副本保留生产 id 属正确语义),fail-closed"
        )
    return rows


def _schema_collection_identity(schema: Any, class_name: str) -> tuple[dict | None, str, list[str]]:
    """/v1/schema 响应 → (目标 collection 对象, 强稳定标识, 可用字段名词表)。

    封闭解析两种响应形状(无执行面):旧式 class 对象数组 / 对象化
    ``{"collections": [...]}``(collection 携带 collectionId/uuid 稳定标识)。
    只回传字段**名**词表,绝不回显字段值。
    """
    items: list = []
    if isinstance(schema, list):
        items = [i for i in schema if isinstance(i, dict)]
    elif isinstance(schema, dict):
        for key in ("collections", "objects", "classes"):
            value = schema.get(key)
            if isinstance(value, list):
                items = [i for i in value if isinstance(i, dict)]
                break
    for item in items:
        name = item.get("class") or item.get("name")
        if isinstance(name, str) and name == class_name:
            cid = item.get("collectionId") or item.get("uuid") or ""
            return item, (str(cid).strip() if cid else ""), sorted(str(k) for k in item)
    return None, "", []


def probe_filesystem_objects(wv_cfg: dict, timeout_s: int) -> int:
    """filesystem 类 Weaviate 对象数(只读探针;R4-1 双身份模式)。

    R2-4②/③:先 GET ``/v1/meta``(形状 sanity);GraphQL 单请求双聚合取
    「集合总对象数」与「filesystem 类对象数」,两 alias 的 ``meta.count``
    只接受非负真正 JSON 整数(R2 复审阻塞:bool/float/字符串/null 一律
    fail-closed,绝不隐式转换成计数),总对象 = 0 →
    ``IsolationTargetUnproven``(BLOCKED)。

    R3-1(v1 锚模式,新版本 Weaviate):GET /v1/schema,目标 collection 的
    ``collectionId``/``uuid`` 与**带外钉扎的信任锚**精确比对;meta hostname
    与显式期望(URL host:port)严格绑定;无强标识字段 → 该子项如实
    BLOCKED(不降低验证强度换 PASS)。

    R4-1(v2 锚模式,Weaviate 1.28.0):真实 1.28.0 的 /v1/schema class
    对象无 collectionId/uuid(官方 spec definitions.Class 与同版实例实测
    一致),/v1/meta.hostname 为绑定地址自述(http://[::]:8080),均非身份
    判据。身份改由**组合锚**承担:数据面把 URL 可达实例绑定到控制面钉扎
    值 —— GET /v1/nodes 必须恰为单节点且其 ``name`` 精确等于钉扎的
    ``weaviate_cluster_hostname``(1.28.0 实测 = CLUSTER_HOSTNAME 自报;
    钉扎值与镜像 digest/数据卷核验由 deploy workflow 控制面在 preflight
    之前强制执行,两层任一不匹配 → fail-closed)。meta.hostname 若与 URL
    自洽亦接受;绑定地址形态(::、0.0.0.0、*、空)放行给 nodes 绑定;
    **其它任何实际 DNS 名与 URL 不一致 → IsolationIdentityMismatch**
    (别名代理自报名在此拒)。集合存在 + 总对象 > 0 断言不变。

    Raises:
        IsolationChannelUnavailable: URL/class 参数缺失(→ BLOCKED)。
        IsolationIdentityUnprovable: v1 锚下 collection 无强标识字段 /
            v2 下 nodes 响应不可证(→ BLOCKED)。
        IsolationTargetUnproven: 集合不存在/总对象 = 0(BLOCKED,不构成隔离证据)。
        IsolationIdentityMismatch: 缺期望锚值/锚不一致/身份不可读(→ fail-closed)。
        RuntimeError: class 名词表外/meta/nodes/schema 不可达/HTTP 错误/
            响应不可读(→ fail-closed)。
    """
    url = str(wv_cfg.get("url") or "").strip()
    class_name = str(wv_cfg.get("class") or "").strip()
    if not url or not class_name:
        raise IsolationChannelUnavailable(
            "缺 --isolation-weaviate-url/--isolation-weaviate-class"
        )
    if not _WEAVIATE_CLASS_RE.match(class_name):
        raise RuntimeError("isolation weaviate class 名在词表外(拒绝)")
    expected_cid = str(wv_cfg.get("expected_collection_id") or "").strip()
    expected_host = str(wv_cfg.get("expected_cluster_hostname") or "").strip()
    if bool(expected_cid) == bool(expected_host):
        raise IsolationIdentityMismatch(
            "缺信任锚期望身份(锚未接线/模式含混:collectionId 与 "
            "cluster_hostname 必须二选一)—— 目标身份无法独立于被测 URL/"
            "自报 metadata 证明,绝不执行计数断言,fail-closed"
        )
    v2_mode = bool(expected_host)
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("isolation weaviate url 非法(http/https + host 必需)")
    default_port = 443 if parsed.scheme == "https" else 80
    conn = _http_connection_factory(
        parsed.scheme, parsed.hostname, parsed.port or default_port, max(1, timeout_s)
    )
    try:
        # ---- R2-4② meta 形状 sanity(+v1 模式身份绑定)----
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
        if v2_mode:
            # R4-1 v2:meta.hostname 是绑定地址自述,不作身份判据(模块头)。
            # 自洽 → 同样接受;绑定地址形态 → 放行给 /v1/nodes 绑定;
            # 其它实际 DNS 名 ≠ URL → 拒(别名代理自报名)。
            if (meta_host, meta_port) != (parsed.hostname.lower(), our_port) and (
                meta_host not in _BIND_SHAPE_META_HOSTS
            ):
                raise IsolationIdentityMismatch(
                    "weaviate 身份不一致:/v1/meta hostname 自报实际 DNS 名与显式"
                    f"期望(URL host:{our_port})不匹配 —— 拒绝把证据记在未证实"
                    "的目标上,fail-closed"
                )
        elif (meta_host, meta_port) != (parsed.hostname.lower(), our_port):
            raise IsolationIdentityMismatch(
                "weaviate 身份不一致:/v1/meta hostname 与显式期望(URL host:"
                f"{our_port})不匹配 —— 拒绝把证据记在未证实的目标上,fail-closed"
            )

        if v2_mode:
            # ---- R4-1 v2 数据面身份绑定:GET /v1/nodes ↔ 钉扎 CLUSTER_HOSTNAME ----
            conn.request(
                "GET", "/v1/nodes", body=None, headers={"Accept": "application/json"}
            )
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"weaviate /v1/nodes 探针 HTTP {resp.status}")
            try:
                nodes_doc = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError("weaviate /v1/nodes 响应非 JSON") from exc
            nodes = (
                nodes_doc.get("nodes")
                if isinstance(nodes_doc, dict)
                else None
            )
            if not isinstance(nodes, list) or not nodes or not all(
                isinstance(n, dict) for n in nodes
            ):
                raise IsolationIdentityUnprovable(
                    "weaviate /v1/nodes 响应不可证(缺 nodes 列表)—— 控制面"
                    "钉扎 CLUSTER_HOSTNAME 无法与数据面绑定,该子项 BLOCKED"
                )
            if len(nodes) != 1:
                raise IsolationIdentityUnprovable(
                    f"weaviate /v1/nodes 返回 {len(nodes)} 节点:多节点拓扑的"
                    "单值身份未定义 —— 该子项 BLOCKED(不降低验证强度换 PASS)"
                )
            node_name = str(nodes[0].get("name") or "").strip()
            if not node_name:
                raise IsolationIdentityUnprovable(
                    "weaviate /v1/nodes 节点缺 name —— 控制面钉扎 "
                    "CLUSTER_HOSTNAME 无法与数据面绑定,BLOCKED"
                )
            if node_name != expected_host:
                raise IsolationIdentityMismatch(
                    "weaviate 身份不一致:/v1/nodes name ≠ 信任锚钉扎 "
                    "CLUSTER_HOSTNAME —— 所连非控制面核验的实例(别名代理/"
                    "重装实例亦拒),fail-closed"
                )

        # ---- R3-1(v1)/ R4-1(v2 存在性)GET /v1/schema ----
        conn.request("GET", "/v1/schema", body=None, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"weaviate /v1/schema 探针 HTTP {resp.status}")
        try:
            schema = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("weaviate /v1/schema 响应非 JSON") from exc
        item, actual_cid, available_fields = _schema_collection_identity(schema, class_name)
        if item is None:
            raise IsolationTargetUnproven(
                f"目标 collection(class={class_name})在 /v1/schema 不存在:所连实例"
                "无此集合 —— 空集合/错实例上的 0 计数不构成隔离证据,BLOCKED"
                "(不谎报 PASS)"
            )
        if not v2_mode:
            # v1:collectionId 强标识与锚精确比对(R3 语义原样)
            if not actual_cid:
                raise IsolationIdentityUnprovable(
                    f"weaviate collection(class={class_name})无强稳定标识(响应字段词表:"
                    f" {available_fields})—— collectionId 缺失,无法与信任锚比对,该子项"
                    "BLOCKED(不降低验证强度换 PASS)"
                )
            if actual_cid.lower() != expected_cid.lower():
                raise IsolationIdentityMismatch(
                    "weaviate 身份不一致:/v1/schema collectionId ≠ 信任锚钉扎值 —— "
                    "所连为错误实例/同名集合(别名代理环境亦拒),fail-closed"
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
            # R2 复审阻塞(AC2):count 只接受**非负真正 JSON 整数**。
            # int() 的隐式转换会把非法证据变成 clean 0 → 假 PASS
            # (false→0、0.5→截断 0、"0"→0);type(x) is int 显式排除 bool
            # (isinstance(True, int) 为 True)。未知/非法计数 → probe
            # 失败 fail-closed,绝不产生 PASS;空 Aggregate([])= 合法
            # 零命中语义不变;总对象 = 0 → BLOCKED 语义不变。
            groups = aggregate.get(alias)
            if groups == []:
                return 0  # Aggregate 空组 = 零命中
            try:
                raw = groups[0]["meta"]["count"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError("weaviate 探针响应形状不可读") from exc
            if type(raw) is not int:
                raise RuntimeError(
                    "weaviate 探针 count 非法(bool/float/字符串/null 等非 "
                    "JSON 整数)—— 未知/非法计数绝不解释为 0,fail-closed"
                )
            if raw < 0:
                raise RuntimeError("weaviate 探针 count 非法(负数)")
            return raw

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
    """构造 isolation 检查项;BLOCKED 与 fail 均使整体非零退出(fail-closed)。

    R3-1 信任锚门禁:锚不可用(缺失/不可读/非法)→ 只产出一条 fail 检查,
    **绝不执行任何隔离探针**(身份失败时隔离结果绝不 PASS;T-ID-09/10)。
    """
    out: list[dict] = []

    anchor = isolation.get("trust_anchor")
    anchor_err = str(isolation.get("trust_anchor_error") or "").strip()
    if anchor_err or not isinstance(anchor, dict):
        out.append(
            _check(
                "isolation", "trust_anchor", "isolation_trust_anchor_invalid",
                "fail",
                f"信任锚不可用({anchor_err or '缺失'})——目标身份无法独立于被测 "
                "DSN/URL/自报 metadata 证明:绝不进入隔离断言(身份失败时隔离"
                "结果绝不 PASS),fail-closed",
            )
        )
        return out

    dsn = str(isolation.get("pg_dsn") or "").strip()
    if not dsn:
        out.append(
            _check(
                "isolation", "upload_mode_rows", "isolation_upload_mode_unprovable",
                "blocked",
                "只读 DB 查询通道不可用(缺隔离 DB DSN:env 变量未设/文件不可读/"
                "容器 env 组件缺失,DSN 含口令绝不进 argv):upload_mode 注册行"
                "断言无法证明,BLOCKED(不谎报 PASS)",
            )
        )
    else:
        try:
            rows = probe_upload_mode_rows(
                {"dsn": dsn, "expected_pg_system_id": anchor["pg_system_id"]},
                timeout_s,
            )
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
            # R4-1:按锚版本传期望身份 —— v1=collectionId(数据面单层),
            # v2=cluster_hostname(控制面+数据面组合锚的数据面绑定值)。
            wv_expect = (
                {"expected_cluster_hostname": anchor["weaviate_cluster_hostname"]}
                if "weaviate_cluster_hostname" in anchor
                else {"expected_collection_id": anchor["weaviate_collection_id"]}
            )
            objects = probe_filesystem_objects(
                {"url": wv_url, "class": wv_class, **wv_expect},
                timeout_s,
            )
        except IsolationIdentityUnprovable as exc:
            out.append(
                _check(
                    "isolation", "filesystem_objects",
                    "isolation_weaviate_identity_unprovable", "blocked",
                    f"{exc}",
                )
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
    remediation_evidence: dict | None = None,
    remediation_evidence_error: str | None = None,
    remediation_artifact_digest: str | None = None,
    remediation_artifact_error: str | None = None,
    approval_public_key: dict | None = None,
    approval_public_key_error: str | None = None,
    release_tag: str | None = None,
    release_sha: str | None = None,
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
        evidence = remediation_evidence if isinstance(remediation_evidence, dict) else None
        # 放行 = 全链验证(逐环给出结构化 actionable 拒绝;任一环失败即
        # fail-closed,绝不部分放行):
        #   记录形状 → 工件真实性(SHA256 对实际文件) → 验证公钥可用 →
        #   RSA-2048 签名审批真伪 → gate/target_tag/release_sha 三重绑定 →
        #   有效期。签名验证 = 纯 stdlib RSASSA-PKCS1-v1_5(SHA-256):
        #   公钥只能验签、无法签发 ⇒ 应用容器 env 权限不构成签发能力
        #   (A R6v2 审查阻塞 1:对称 HMAC 密钥经 compose env_file 扩散 =
        #   自授权面,已整体移除)。
        bind_ok = False
        reason = ""
        if (remediation_evidence_error or "").strip():
            reason = f"整改证据不可用({remediation_evidence_error})—— fail-closed"
        elif evidence is None:
            if (remediation_ack or "").strip() == gate:
                reason = (
                    "字符串 --remediation-ack 与声明 gate 匹配,但字符串 ACK 不构成"
                    "整改证明(A #138 P3:不能凭命令行传入相同字符串获得合法放行)"
                    "—— 必须提供【真实不可变证据工件 + 受信审批】"
                    "(--remediation-evidence-file + --remediation-evidence-artifact"
                    " + --release-tag + --release-sha)"
                )
            else:
                reason = (
                    "该发布声明与先前版本不兼容:普通 previous-tag 回滚不适用,"
                    "必须提供【真实不可变证据工件 + 受信审批】的整改证据记录"
                    "(--remediation-evidence-file + --remediation-evidence-artifact"
                    f" + --release-tag + --release-sha,声明的 remediation gate: {gate})"
                )
        elif (remediation_artifact_error or "").strip():
            reason = (
                f"整改证据工件不可信({remediation_artifact_error})"
                "—— 记录声明不等于工件本身,fail-closed"
            )
        elif (approval_public_key_error or "").strip():
            reason = f"整改审批不可验证({approval_public_key_error})—— fail-closed"
        else:
            if not _approval_signature_valid(
                approval_public_key,
                str(evidence["approval"]["signature"]),
                _approval_signature_payload(evidence),
            ):
                reason = (
                    "整改审批无效(RSA-2048 签名校验失败:记录未经审批私钥签发或"
                    "任一绑定字段被篡改)—— 自填 recorded_by/伪造审批不构成"
                    "整改证明;验证公钥无法签发 ⇒ 容器 env 权限不构成签发能力,"
                    "fail-closed"
                )
            elif evidence.get("gate") != gate:
                reason = (
                    "整改证据绑定失败: 证据 gate="
                    f"{evidence.get('gate')!r} ≠ manifest 声明 {gate!r}(fail-closed)"
                )
            elif evidence.get("target_tag") != (release_tag or "").strip():
                reason = (
                    "整改证据绑定失败: 证据 target_tag="
                    f"{evidence.get('target_tag')!r} ≠ 本次部署 release-tag="
                    f"{(release_tag or '')!r}(跨发行证据不可移作他用,fail-closed)"
                )
            elif evidence.get("release_sha") != (release_sha or "").strip().lower():
                reason = (
                    "整改证据绑定失败: 证据 release_sha="
                    f"{evidence.get('release_sha')!r} ≠ 本次部署 release-sha="
                    f"{(release_sha or '')!r}(跨 SHA/镜像身份证据不可挪用,"
                    "fail-closed)"
                )
            else:
                na, na_err = _parse_iso_datetime(evidence["not_after"], "not_after")
                if na_err or na is None:
                    reason = f"整改证据不可用({na_err})—— fail-closed"
                elif datetime.now(timezone.utc) > na:
                    reason = (
                        f"整改审批已过期(not_after={evidence['not_after']})"
                        "—— 过期证据不放行,fail-closed"
                    )
                else:
                    bind_ok = True
                    reason = (
                        f"整改证据全链验证通过: gate={gate} "
                        f"target_tag={evidence.get('target_tag')} "
                        f"release_sha={evidence.get('release_sha')}"
                        "(诚实边界: release_sha 绑定的是镜像内 RELEASE.json "
                        "git_sha 断言,非 OCI image 内容摘要) "
                        f"evidence_digest={evidence.get('evidence_digest')}(工件"
                        "SHA256 实测一致) "
                        f"evidence_ref={evidence.get('evidence_ref')}(自述引用:"
                        "仅证明工件与批准记录一致,不证明演练真实发生/审核方"
                        "实际批准 —— 后者属 A 受信审计) "
                        f"approved_by={evidence['approval']['approved_by']} "
                        f"approved_at={evidence['approval']['approved_at']} "
                        f"not_after={evidence.get('not_after')}"
                        "(A #138 P3:真实工件 + 非对称签名审批 + 发行/SHA/镜像"
                        "身份三重绑定;不因字符串 ACK 或自述记录放行)"
                    )
        if bind_ok:
            checks.append(
                _check(
                    "rollback", "previous_compatible", "rollback_ok", "pass", reason,
                )
            )
        else:
            if not reason:
                reason = (
                    "该发布声明与先前版本不兼容:普通 previous-tag 回滚不适用,"
                    f"必须提供真实证据工件与受信审批(gate: {gate})"
                )
            checks.append(
                _check(
                    "rollback", "previous_compatible", "rollback_remediation_gate_required",
                    "fail", reason,
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

# R3-1:带外钉扎信任锚 schema(封闭词表;锚值 = 非秘密的集群/集合唯一标识,
# 由 A 带外采集;**绝不**以被测 DSN/URL/自报 metadata 兼任期望身份)
# R4-1:锚分两版 —— v1 = collectionId 数据面单层(新版本 Weaviate);
#       v2 = 1.28.0 控制面+数据面组合锚(API 无强唯一标识,见模块头)。
_TRUST_ANCHOR_VERSIONS = (1, 2)
_TRUST_ANCHOR_V1_FIELDS = ("pg_system_id", "weaviate_collection_id")
_TRUST_ANCHOR_V2_FIELDS = (
    "pg_system_id",
    "weaviate_cluster_hostname",
    "weaviate_image_digest",
    "weaviate_volume_name",
    "weaviate_volume_manifest_sha256",
)
# v2 数据面允许的 /v1/meta.hostname 绑定地址形态(1.28.0 实测自述值;
# 其它任何与 URL 不一致的实际 DNS 名一律身份不匹配)
_BIND_SHAPE_META_HOSTS = {"::", "0.0.0.0", "*", ""}

# ---- G3 整改证据消费(R6v3;A #138 P3 + R6v2 审查阻塞 1 修复)----
# 唯一合法放行面 = 【真实不可变证据工件 + 非对称签名审批】双因子,缺一
# fail-closed:
#   1) 工件真实性:对 --remediation-evidence-artifact 指向的实际文件计算
#      SHA256,与记录声明 evidence_digest 精确一致(引用不存在/摘要伪造 ⇒
#      拒绝;记录本身不是证据);
#   2) 审批可信:approval.signature = RSASSA-PKCS1-v1_5(SHA-256) 签名,
#      **纯 stdlib 验证**(pow(s,e,n) + 精确 EM 比较)。R6v2 的对称 HMAC
#      密钥同时是验证与签发秘密,经 compose env_file 注入 backend/sync/
#      sync-executor/sync-cron 全部 workload ⇒ 任何能读容器 env 的执行面
#      可自授权(A R6v2 审查阻塞 1)—— 该通道已整体删除,绝不再引入。
#      改为:审批私钥仅存 A 离线受控路径(scripts/sign_remediation_
#      approval.py 签发);评估器只持验证公钥,经可信钉扎通道(与信任锚
#      同款:workflow secret → SSH stdin → 远端 0600 临时件 → 容器文件,
#      **绝不**走 compose env_file/容器 env)进入。公钥无法签发 ⇒ 应用
#      容器 env 权限不构成签发能力;
#   3) 身份绑定:gate == manifest 声明 ∧ target_tag == --release-tag ∧
#      release_sha == --release-sha(工作流身份步/镜像内 RELEASE.json
#      git_sha;诚实边界:git_sha 断言,非 OCI image 内容摘要)——同一
#      证据不可挪用于其他发行/SHA/镜像;
#   4) 有效期:not_after 过期 ⇒ fail-closed;
#   5) 真实 G3 恢复演练未完成 ⇒ 无记录/无工件/无审批 ⇒ BLOCKED(现状不变)。
# 测试使用明确定义的测试信任根(测试自造 RSA 密钥对,注明 test-only),
# 绝不宣称生产已整改。
_REMEDIATION_EVIDENCE_VERSIONS = (3,)
_REMEDIATION_EVIDENCE_V3_FIELDS = (
    "gate",
    "target_tag",
    "release_sha",
    "evidence_digest",
    "evidence_ref",
    "recorded_at",
    "recorded_by",
    "not_after",
    "approval",
)
_REMEDIATION_APPROVAL_FIELDS = ("approved_by", "approved_at", "signature")
_RELEASE_TAG_PATTERN = r"v[0-9]+\.[0-9]+\.[0-9]+(-r[0-9]+)?"
_REMEDIATION_GATE_TOKEN_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_EVIDENCE_DIGEST_PATTERN = r"[0-9a-f]{64}"
_RELEASE_SHA_PATTERN = r"[0-9a-f]{40}"
# 签名规范化载荷上下文(域分离,防跨用途/跨版本重用;v3 起为非对称签名)
_APPROVAL_SIGNATURE_CONTEXT = "askai-remediation-approval-v3"
# RSA-2048 钉扎(模数恰 2048 位;拒绝其它强度)
_APPROVAL_RSA_MODULUS_BITS = 2048
_APPROVAL_RSA_N_HEX_LEN = _APPROVAL_RSA_MODULUS_BITS // 4
_APPROVAL_SIGNATURE_HEX_LEN = _APPROVAL_RSA_MODULUS_BITS // 4
_APPROVAL_RSA_MAX_E_BITS = 17  # 覆盖 65537 等常用小奇指数
# RSASSA-PKCS1-v1_5 + SHA-256 的 DigestInfo 前缀(DER;固定 19 字节):
#   SEQUENCE(AlgorithmIdentifier(sha256 OID + NULL), OCTET STRING)
_RSA_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)
# 证据工件传输上界(base64 通道;超过即拒绝,不无限读入)
_MAX_EVIDENCE_ARTIFACT_BYTES = 65536


def _load_trust_anchor(path: str | None) -> tuple[dict | None, str | None]:
    """加载带外钉扎的目标身份信任锚(R4-1 双版本,v1/v2 词表封闭)。

    Returns:
        (anchor, None) 或 (None, 结构化错误)。缺文件/不可读/非 JSON/缺字段/
        词表外/版本不符/形状非法一律拒绝(fail-closed);错误信息只含字段名
        类结构信息,绝不回显文件内容;锚值本身为非秘密标识(pg 数字 id /
        UUID / CLUSTER_HOSTNAME / 镜像 digest / 卷名 / 清单哈希)。
    """
    if not path or not path.strip():
        return None, "缺 --isolation-trust-anchor-file(身份锚必填)"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None, "锚文件不可读"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None, "锚文件非合法 JSON"
    if not isinstance(raw, dict):
        return None, "锚文件根必须是映射"
    if raw.get("version") not in _TRUST_ANCHOR_VERSIONS:
        return None, (
            f"锚 version 必须为 {'/'.join(map(str, _TRUST_ANCHOR_VERSIONS))}"
            f"(实际 {raw.get('version')!r})"
        )
    version = int(raw["version"])
    fields = _TRUST_ANCHOR_V1_FIELDS if version == 1 else _TRUST_ANCHOR_V2_FIELDS
    unknown = sorted(set(map(str, raw)) - {"version"} - set(fields))
    if unknown:
        return None, f"锚字段词表外: {unknown}"
    pg = str(raw.get("pg_system_id") or "").strip()
    if not pg:
        return None, "锚缺字段: pg_system_id(fail-closed)"
    if not re.fullmatch(r"[0-9]{1,20}", pg):
        return None, "锚 pg_system_id 必须是十进制整数(pg_control_system().system_identifier)"
    if version == 1:
        wv = str(raw.get("weaviate_collection_id") or "").strip()
        if not wv:
            return None, "锚缺字段: weaviate_collection_id(fail-closed)"
        return {"pg_system_id": pg, "weaviate_collection_id": wv.lower()}, None
    # ---- v2:控制面+数据面组合锚(1.28.0;各字段形状封闭校验)----
    host = str(raw.get("weaviate_cluster_hostname") or "").strip()
    if not host:
        return None, "锚缺字段: weaviate_cluster_hostname(fail-closed)"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,253}", host):
        return None, "锚 weaviate_cluster_hostname 形状非法"
    digest = str(raw.get("weaviate_image_digest") or "").strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return None, "锚 weaviate_image_digest 必须是 sha256:<64hex>(docker .Image)"
    vol = str(raw.get("weaviate_volume_name") or "").strip()
    if not vol:
        return None, "锚缺字段: weaviate_volume_name(fail-closed)"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,253}", vol):
        return None, "锚 weaviate_volume_name 形状非法"
    manifest = str(raw.get("weaviate_volume_manifest_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", manifest):
        return None, "锚 weaviate_volume_manifest_sha256 必须是 64 位小写 hex"
    return {
        "pg_system_id": pg,
        "weaviate_cluster_hostname": host,
        "weaviate_image_digest": digest,
        "weaviate_volume_name": vol,
        "weaviate_volume_manifest_sha256": manifest,
    }, None


def _parse_iso_datetime(value: str, field: str) -> tuple[datetime | None, str | None]:
    """解析必须带时区的 ISO-8601 时间( naive 时间拒绝,防跨时区歧义)。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, f"证据字段形状非法: {field}(须为带时区 ISO-8601)"
    if parsed.tzinfo is None:
        return None, f"证据字段形状非法: {field}(必须带时区偏移)"
    return parsed, None


def _load_remediation_evidence(
    path: str | None, release_tag: str | None, release_sha: str | None
) -> tuple[dict | None, str | None]:
    """加载整改证据记录(R6v3;形状校验 —— 真实性与审批由 rollback 门验证)。

    Returns:
        (record, None) 或 (None, 结构化错误)。缺文件/不可读/非 JSON/根非映射/
        版本不符/词表外字段/缺字段/形状非法/缺 --release-tag 或 --release-sha
        绑定键/换行类控制字符(防签名载荷歧义)一律拒绝(fail-closed);
        错误信息只含字段名类结构信息,绝不回显文件内容;记录本身非秘密。
    """
    if not path or not path.strip():
        return None, "缺 --remediation-evidence-file(整改证据记录必填)"
    if not release_tag or not release_tag.strip():
        return (
            None,
            "缺 --release-tag(整改证据必须绑定本次部署目标发行,fail-closed)",
        )
    release_tag = release_tag.strip()
    if not re.fullmatch(_RELEASE_TAG_PATTERN, release_tag):
        return None, "--release-tag 形状非法(须为 vX.Y.Z(-rN) 不可变 tag)"
    if not release_sha or not release_sha.strip():
        return None, "缺 --release-sha(整改证据必须绑定本次部署不可变 SHA)"
    release_sha = release_sha.strip().lower()
    if not re.fullmatch(_RELEASE_SHA_PATTERN, release_sha):
        return None, "--release-sha 形状非法(须为 40 位小写 hex)"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None, "整改证据文件不可读"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None, "整改证据文件非合法 JSON"
    if not isinstance(raw, dict):
        return None, "整改证据文件根必须是映射"
    if raw.get("version") not in _REMEDIATION_EVIDENCE_VERSIONS:
        return None, (
            f"证据 version 必须为 {'/'.join(map(str, _REMEDIATION_EVIDENCE_VERSIONS))}"
            f"(实际 {raw.get('version')!r})"
        )
    unknown = sorted(
        set(map(str, raw)) - {"version"} - set(_REMEDIATION_EVIDENCE_V3_FIELDS)
    )
    if unknown:
        return None, f"证据字段词表外: {unknown}"
    approval = raw.get("approval")
    if not isinstance(approval, dict):
        return None, "证据缺字段: approval(未经审批的记录不构成整改证明)"
    unknown_ap = sorted(set(map(str, approval)) - set(_REMEDIATION_APPROVAL_FIELDS))
    if unknown_ap:
        return None, f"证据 approval 字段词表外: {unknown_ap}"

    def _token(field: str, pattern: str | None = None, *, max_len: int = 0) -> str:
        v = str(raw.get(field) or "").strip()
        if not v:
            raise ValueError(f"证据缺字段/形状非法: {field}")
        if ("\n" in v) or ("\r" in v):
            raise ValueError(f"证据字段形状非法: {field}(含换行类控制字符)")
        if pattern and not re.fullmatch(pattern, v):
            raise ValueError(f"证据字段形状非法: {field}")
        if max_len and len(v) > max_len:
            raise ValueError(f"证据字段形状非法: {field}(≤{max_len} 字符)")
        return v

    try:
        gate = _token("gate", _REMEDIATION_GATE_TOKEN_PATTERN)
        target_tag = _token("target_tag", _RELEASE_TAG_PATTERN)
        release_sha_r = _token("release_sha", _RELEASE_SHA_PATTERN)
        digest = _token("evidence_digest", _EVIDENCE_DIGEST_PATTERN).lower()
        ref = _token("evidence_ref", max_len=512)
        recorded_at = _token("recorded_at", max_len=64)
        recorded_by = _token("recorded_by", max_len=256)
        not_after = _token("not_after", max_len=64)
        approved_by = str(approval.get("approved_by") or "").strip()
        if not approved_by or len(approved_by) > 256 or ("\n" in approved_by):
            raise ValueError("证据字段形状非法: approval.approved_by")
        approved_at = str(approval.get("approved_at") or "").strip()
        if not approved_at or len(approved_at) > 64 or ("\n" in approved_at):
            raise ValueError("证据字段形状非法: approval.approved_at")
        signature_hex = str(approval.get("signature") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{%d}" % _APPROVAL_SIGNATURE_HEX_LEN, signature_hex):
            raise ValueError(
                "证据字段形状非法: approval.signature(%d 位小写 hex,对应 "
                "RSA-2048 签名;未经审批私钥签发的记录不构成整改证明)"
                % _APPROVAL_SIGNATURE_HEX_LEN
            )
    except ValueError as exc:
        return None, str(exc)

    for field, value in (
        ("recorded_at", recorded_at),
        ("approval.approved_at", approved_at),
        ("not_after", not_after),
    ):
        _, err = _parse_iso_datetime(value, field)
        if err:
            return None, err

    return {
        "version": 3,
        "gate": gate,
        "target_tag": target_tag,
        "release_sha": release_sha_r,
        "evidence_digest": digest,
        "evidence_ref": ref,
        "recorded_at": recorded_at,
        "recorded_by": recorded_by,
        "not_after": not_after,
        "approval": {
            "approved_by": approved_by,
            "approved_at": approved_at,
            "signature": signature_hex,
        },
    }, None


def _approval_signature_payload(record: dict) -> bytes:
    """审批签名规范化载荷:全部绑定字段的定长次序拼接(域分离上下文打头;
    各字段已经加载器拒绝换行类控制字符 ⇒ 拼接无歧义)。v3 起该载荷由
    审批私钥(RSA-2048,仅 A 离线受控路径持有)签发,验证侧只需公钥。"""
    core = "\n".join(
        [
            _APPROVAL_SIGNATURE_CONTEXT,
            record["gate"],
            record["target_tag"],
            record["release_sha"],
            record["evidence_digest"],
            record["evidence_ref"],
            record["recorded_at"],
            record["recorded_by"],
            record["not_after"],
            record["approval"]["approved_by"],
            record["approval"]["approved_at"],
        ]
    )
    return core.encode("utf-8")


def _load_approval_public_key(path: str | None) -> tuple[dict | None, str | None]:
    """加载受信验证公钥(钉扎通道:workflow secret → SSH stdin → 0600 文件;
    **绝不**经 compose env_file/容器 env —— 公钥为非秘密材料,但通道纪律与
    信任锚一致,杜绝任何审批材料混入应用 env 扩散面)。

    文件形状(JSON,词表封闭):{"kty":"rsa","n_hex":"<512 hex>","e_hex":"010001"}
    模数钉扎恰 2048 位、指数必须为奇数且 ≥3(拒绝空/偶/超界)。任何形状
    违规 ⇒ (None, 结构化错误) ⇒ rollback 门 fail-closed(无受信公钥 ⇒
    审批无法验证 ⇒ 绝不放行)。
    """
    if not path or not path.strip():
        return (
            None,
            "缺 --remediation-approval-public-key-file(整改审批无法验证,"
            "fail-closed)",
        )
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None, "审批公钥文件不可读"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None, "审批公钥文件非合法 JSON"
    if not isinstance(raw, dict):
        return None, "审批公钥根必须是映射"
    if sorted(map(str, raw)) != ["e_hex", "kty", "n_hex"]:
        return None, f"审批公钥字段词表外/缺失: {sorted(map(str, raw))}"
    if raw.get("kty") != "rsa":
        return None, "审批公钥 kty 必须为 \"rsa\""
    n_hex = str(raw.get("n_hex") or "").strip().lower()
    e_hex = str(raw.get("e_hex") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{%d}" % _APPROVAL_RSA_N_HEX_LEN, n_hex):
        return None, (
            "审批公钥 n_hex 形状非法(须为 %d 位小写 hex = RSA-%d 模数)"
            % (_APPROVAL_RSA_N_HEX_LEN, _APPROVAL_RSA_MODULUS_BITS)
        )
    if not re.fullmatch(r"[0-9a-f]{1,%d}" % _APPROVAL_RSA_MAX_E_BITS, e_hex):
        return None, "审批公钥 e_hex 形状非法(小写 hex,过界)"
    n = int(n_hex, 16)
    e = int(e_hex, 16)
    if n.bit_length() != _APPROVAL_RSA_MODULUS_BITS:
        return None, (
            f"审批公钥模数必须是恰 {_APPROVAL_RSA_MODULUS_BITS} 位(RSA-2048 钉扎;"
            f"实际 {n.bit_length()} 位)"
        )
    if e < 3 or e % 2 == 0:
        return None, "审批公钥指数非法(须为奇数且 ≥3)"
    return {"n": n, "e": e}, None


def _approval_signature_valid(
    public_key: dict | None, signature_hex: str, payload: bytes
) -> bool:
    """纯 stdlib RSASSA-PKCS1-v1_5(SHA-256)验证:
    pow(s,e,n) 还原编码 EM,与精确构造的
    ``0x00 0x01 || FF..FF || 0x00 || DigestInfo(SHA-256) || H(payload)``
    常量时间比较(DigestInfo 前缀 3031300d060960864801650304020105000420)。
    签名形状已在记录加载器钉扎为 %d 位小写 hex;任何形状/数值/编码偏差
    ⇒ False(fail-closed,绝不异常逃逸)。""" % _APPROVAL_SIGNATURE_HEX_LEN
    if not isinstance(public_key, dict):
        return False
    k = _APPROVAL_RSA_MODULUS_BITS // 8
    if len(signature_hex) != _APPROVAL_SIGNATURE_HEX_LEN:
        return False
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    n = int(public_key["n"])
    e = int(public_key["e"])
    if not (0 <= s < n):
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest_info = _RSA_SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(payload).digest()
    t_len = len(digest_info)
    ps_len = k - 3 - t_len
    if ps_len < 8:
        return False
    expected_em = b"\x00\x01" + b"\xff" * ps_len + b"\x00" + digest_info
    return hmac.compare_digest(em, expected_em)


def _hash_evidence_artifact(path: str) -> tuple[str | None, str | None]:
    """对实际证据工件计算 SHA256(有界读取;超限/缺失/不可读 ⇒ 拒绝)。"""
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError:
        return None, "整改证据工件不可访问(引用的工件不存在或不可读)"
    if size > _MAX_EVIDENCE_ARTIFACT_BYTES:
        return None, f"整改证据工件超过有界上界(>{_MAX_EVIDENCE_ARTIFACT_BYTES} 字节)"
    try:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return None, "整改证据工件不可读"
    return digest, None


def _dsn_from_pg_env_parts(env: dict[str, str]) -> str | None:
    """R3-2:从进程自身 env 的 POSTGRES_* 组件装配 libpq DSN(生产 backend
    容器内执行路径 —— 凭据经容器自身 env 继承,零新增传输)。装配只发生在
    进程内存;任一必需组件缺失/为空 → None(由隔离检查转 BLOCKED,fail-closed,
    绝不回退、绝不编造)。组件经 percent-encode 后拼入 URL,特殊字符安全。
    """
    host = (env.get("POSTGRES_HOST") or "").strip()
    port = (env.get("POSTGRES_PORT") or "5432").strip()
    dbname = (env.get("POSTGRES_DB") or "").strip()
    user = (env.get("POSTGRES_USER") or "").strip()
    password = env.get("POSTGRES_PASSWORD")
    if not host or not dbname or not user or not password:
        return None
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{quote(host, safe='')}:{quote(port, safe='')}/{quote(dbname, safe='')}"
    )


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
        "--release-tag", default=None, metavar="TAG",
        help="本次部署目标不可变 tag(如 v1.6.4-r3);整改证据绑定的目标发行,"
        "提供 --remediation-evidence-file 时必填",
    )
    parser.add_argument(
        "--release-sha", default=None, metavar="SHA",
        help="本次部署不可变 40 位 hex(工作流身份步仓库权威解析 / update.sh "
        "取镜像内 RELEASE.json git_sha);整改证据绑定的镜像身份",
    )
    parser.add_argument(
        "--remediation-evidence-artifact", default=None, metavar="PATH",
        help="整改证据工件(真实不可变文件;对其计算 SHA256 并与记录声明"
        "evidence_digest 精确比对)—— 记录自述摘要不是证据,必须实测工件",
    )
    parser.add_argument(
        "--remediation-approval-public-key-file", default=None, metavar="PATH",
        help="受信审批**验证公钥**文件(JSON {\"kty\":\"rsa\",\"n_hex\":<512hex>,"
        "\"e_hex\":\"010001\"};非秘密,但经与信任锚同款钉扎通道送达:"
        "workflow secret → SSH stdin → 0600 文件,绝不走 compose env_file/"
        "容器 env)。公钥只能验签、无法签发 ⇒ 应用容器 env 权限不构成签发能力;"
        "提供 --remediation-evidence-file 时必填,缺失/形状非法 fail-closed",
    )
    parser.add_argument(
        "--remediation-evidence-file", default=None, metavar="PATH",
        help="整改证据工件 JSON(A #138 P3 唯一合法放行面):"
        "{version:3,gate,target_tag,release_sha,evidence_digest,evidence_ref,"
        "recorded_at,recorded_by,not_after,approval{approved_by,approved_at,"
        "signature}};gate 须与 manifest 声明精确一致、target_tag 须与 "
        "--release-tag 精确一致;词表外/形状非法/绑定不一致一律 fail-closed",
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
        "--isolation-pg-dsn-parts", action="store_true",
        help="从进程自身 env 的 POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/"
        "POSTGRES_USER/POSTGRES_PASSWORD 组件在内存中装配 DSN(生产 backend "
        "容器内执行路径:凭据经容器自身 env 继承,零新增传输;argparse 只见"
        "旗标本身)。显式给出时为唯一 DSN 通道,不回退其他通道",
    )
    parser.add_argument(
        "--isolation-weaviate-url-env", default=None, metavar="VAR_NAME",
        help="持有隔离断言目标 Weaviate URL 的环境变量名(如容器自身 env 的 "
        "WEAVIATE_URL;argparse 只收变量名)",
    )
    parser.add_argument(
        "--isolation-weaviate-class-env", default=None, metavar="VAR_NAME",
        help="持有向量 collection class 名的环境变量名(如 WEAVIATE_CLASS_NAME)",
    )
    parser.add_argument(
        "--isolation-trust-anchor-file", default=None, metavar="PATH",
        help="带外钉扎的目标身份信任锚 JSON(A 采集;独立于被测 DSN/URL)。"
        "v1={version:1,pg_system_id,weaviate_collection_id}(新版 Weaviate);"
        "v2={version:2,pg_system_id,weaviate_cluster_hostname,"
        "weaviate_image_digest,weaviate_volume_name,"
        "weaviate_volume_manifest_sha256}(1.28.0 控制面+数据面组合锚,"
        "控制面核验由 deploy workflow 强制)。--verify-upload-isolation 下必填:"
        "缺失/不可读/缺字段/形状非法/不匹配一律 fail-closed,绝不进入隔离断言",
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

    # R3-1:信任锚(--verify-upload-isolation 下必填;加载失败经
    # trust_anchor_error 传入隔离门禁 → 单条 fail 检查,绝不执行探针)
    anchor: dict | None = None
    anchor_error: str | None = None
    if args.verify_upload_isolation:
        anchor, anchor_error = _load_trust_anchor(args.isolation_trust_anchor_file)

    # G3 整改证据(A #138 P3 唯一合法放行面):加载失败经 remediation_evidence_error
    # 传入 rollback 门 → 单条 fail 检查,绝不放行;未提供时零变化(维持 #46/#159
    # 既有 fail-closed 语义)。
    evidence: dict | None = None
    evidence_error: str | None = None
    artifact_digest: str | None = None
    artifact_error: str | None = None
    approval_public_key: dict | None = None
    approval_public_key_error: str | None = None
    if args.remediation_approval_public_key_file:
        approval_public_key, approval_public_key_error = _load_approval_public_key(
            args.remediation_approval_public_key_file
        )
    elif args.remediation_evidence_file:
        # 提供证据但缺钉扎公钥 ⇒ 结构化拒绝(审批无法验证,fail-closed)
        approval_public_key_error = (
            "缺 --remediation-approval-public-key-file(整改审批无法验证,"
            "fail-closed;公钥经可信钉扎通道送达,绝不走容器 env)"
        )
    if args.remediation_evidence_file:
        evidence, evidence_error = _load_remediation_evidence(
            args.remediation_evidence_file, args.release_tag, args.release_sha
        )
        if evidence is not None:
            # 工件真实性:必须对实际不可变文件实测 SHA256 并与声明一致;
            # 引用不存在/摘要伪造在此拒绝(记录自述不是证据)。
            if args.remediation_evidence_artifact:
                artifact_digest, artifact_error = _hash_evidence_artifact(
                    args.remediation_evidence_artifact
                )
                if (
                    artifact_digest is not None
                    and artifact_digest != evidence["evidence_digest"]
                ):
                    artifact_error = (
                        "实际工件 SHA256 与记录声明 evidence_digest 不一致"
                        "(fail-closed)"
                    )
                    artifact_digest = None
            else:
                artifact_error = (
                    "缺 --remediation-evidence-artifact(必须对实际不可变证据"
                    "工件计算 SHA256;记录自述摘要不是证据)"
                )

    # DSN 通道(显式、无回退):--isolation-pg-dsn-parts = 容器 env 组件装配;
    # 否则 file > env 变量。Weaviate URL/class:显式旗标 > env 变量名通道。
    if args.isolation_pg_dsn_parts:
        pg_dsn = _dsn_from_pg_env_parts(os.environ)
    else:
        pg_dsn = _resolve_isolation_pg_dsn(args)
    wv_url = args.isolation_weaviate_url
    if not wv_url and args.isolation_weaviate_url_env:
        wv_url = os.environ.get(args.isolation_weaviate_url_env) or None
    wv_class = args.isolation_weaviate_class
    if not wv_class and args.isolation_weaviate_class_env:
        wv_class = os.environ.get(args.isolation_weaviate_class_env) or None

    verdict, code = evaluate(
        args.manifest,
        env=env,
        probe_timeout_s=min(max(args.probe_timeout, 1), MAX_PROBE_TIMEOUT_S),
        remediation_ack=args.remediation_ack,
        remediation_evidence=evidence,
        remediation_evidence_error=evidence_error,
        remediation_artifact_digest=artifact_digest,
        remediation_artifact_error=artifact_error,
        approval_public_key=approval_public_key,
        approval_public_key_error=approval_public_key_error,
        release_tag=args.release_tag,
        release_sha=args.release_sha,
        pre_contract=args.pre_contract_release,
        verify_upload_isolation=args.verify_upload_isolation,
        isolation=(
            {
                "pg_dsn": pg_dsn,
                "weaviate_url": wv_url,
                "weaviate_class": wv_class,
                "trust_anchor": anchor,
                "trust_anchor_error": anchor_error,
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
