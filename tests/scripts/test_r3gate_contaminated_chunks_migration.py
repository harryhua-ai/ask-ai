"""r3 发布安全门:contaminated chunk 迁移半态核查(第四节;只验证+钉住行为)。

12 项测试映射(胶囊):
- T10:迁移部分完成后重跑 → 幂等/续跑安全;DELETE 范围精确(generation_ordinal>0
  AND chunk_index >= chunk_count);ordinal=0 legacy 行不在范围(冻结契约);
- T11:迁移异常 → 异常向上抛、无假成功标记("OK:" 缺席)、数据原样保留。

五点核查结论的钉住(①DELETE 精确 WHERE 范围 ②幂等 ③中断后状态 ④r2 兼容
⑤异常不误报成功):本文件以行为测试固定 ①②③⑤;④ 由代码证据固定
(generation_builder 重放范围 = 版本权威 chunk 集 chunk_index < chunk_count,
删除的恰是范围外行 → r2 读少些行不崩,不读 chunk 原文)。

R2-2 迁移测试 DB 身份保护(fail-closed,先于任何连接/DELETE):
``migrate(engine)`` 内含**不受前缀限制**的 ``DELETE FROM
document_version_chunks``——若 ``TEST_DATABASE_URL`` 被错误指向非测试库,
现行(R1)代码只强制"env 有值",会照常执行 DELETE(#R2-2 RED 实证:本地
scratch 库 ``ask_ai_r2red_scratch`` 上 migrate 无拒绝直接执行)。修复后:
- URL 级校验先于**任何连接**:scheme 必须 postgresql(-driver);host ∈
  {localhost, 127.0.0.1, ::1};database 名必须恰为隔离测试库
  ``ask_ai_test``;缺 env / 任一不过 → 拒绝,engine 永不创建;
- 连接后身份复核先于任何 DELETE:``SELECT current_database()`` 必须与 URL
  声明一致;不可读/不一致 → 拒绝(fixture 在 yield 前抛出,测试体与
  ``migrate`` 永不执行 → 所有拒绝路径 DELETE 均未执行);
- 负例(缺失 env / 非测试库名 / 远程 host / 身份不一致 / 身份不可读)与
  正例(合法隔离库)均钉住;负例 URL 一律由真实 env DSN **派生**(只改
  host/dbname),真实凭据绝不落入本文件任何字面量。
"""

from __future__ import annotations

import os
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

import scripts.migrate_remove_contaminated_version_chunks as mc
from backend.db.models import DocumentVersion, DocumentVersionChunk
from scripts.migrate_remove_contaminated_version_chunks import migrate

# --------------------------------------------------------------------------- #
# R2-2:测试库身份 fail-closed 守卫(校验先于任何连接/DELETE)
# --------------------------------------------------------------------------- #

_ALLOWED_TEST_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}
# 隔离测试库的强约束:database 名必须恰为该名(共享测试库纪律)
_TEST_DB_NAME = "ask_ai_test"


class _TestDbIdentityRefused(RuntimeError):
    """TEST_DATABASE_URL 未通过隔离测试库身份校验 → 拒绝任何连接/迁移。"""


def _env_dsn() -> str:
    raw = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if not raw:
        raise _TestDbIdentityRefused(
            "R2-2 fail-closed:TEST_DATABASE_URL 缺失 —— 拒绝任何连接/迁移"
            "(无回退默认值;绝不静默指向未知库)"
        )
    return raw


def _declared_identity(dsn: str) -> tuple[str, str]:
    """URL 级校验(先于任何连接)→ (host 归一化后保留原 dsn, declared_dbname)。"""
    parsed = urlsplit(dsn)
    scheme_root = parsed.scheme.split("+", 1)[0]
    if scheme_root not in ("postgresql", "postgres"):
        raise _TestDbIdentityRefused(
            f"R2-2 fail-closed:DSN scheme 必须为 postgresql(实际 {scheme_root!r})"
        )
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_TEST_DB_HOSTS:
        raise _TestDbIdentityRefused(
            f"R2-2 fail-closed:DB host 必须 ∈ {sorted(_ALLOWED_TEST_DB_HOSTS)},"
            f"实际 {host!r}(远程/未知 host 拒绝)"
        )
    dbname = parsed.path.lstrip("/")
    if dbname != _TEST_DB_NAME:
        raise _TestDbIdentityRefused(
            f"R2-2 fail-closed:database 必须恰为隔离测试库 {_TEST_DB_NAME!r},"
            f"实际 {dbname!r}(迁移含不受前缀限制的 DELETE,错指非测试库即拒绝)"
        )
    return dsn, dbname


async def _assert_server_identity(engine, declared_dbname: str) -> None:
    """连接后身份复核(**先于任何 DELETE**):current_database() == URL 声明。"""
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT current_database()"))).first()
    actual = row[0] if row else None
    if actual is None:
        raise _TestDbIdentityRefused(
            "R2-2 fail-closed:无法读取 current_database()(身份不可证)→ 拒绝"
        )
    if actual != declared_dbname:
        raise _TestDbIdentityRefused(
            f"R2-2 fail-closed:current_database()={actual!r} ≠ URL 声明 "
            f"{declared_dbname!r} → 拒绝(连接目标与声明不一致)"
        )


def _derived_dsn(*, dbname: str | None = None, host: str | None = None) -> str:
    """从真实 env DSN 派生负例 URL(只改 host/dbname;凭据绝不入字面量)。"""
    p = urlsplit(_env_dsn())
    path = f"/{dbname}" if dbname is not None else p.path
    netloc = p.netloc
    if host is not None:
        creds, sep, hostport = p.netloc.rpartition("@")
        port = f":{hostport.rpartition(':')[2]}" if ":" in hostport else ""
        netloc = f"{creds}{sep}{host}{port}"
    return urlunsplit((p.scheme, netloc, path, p.query, p.fragment))


@pytest.fixture
async def engine():
    """fail-closed 引擎:身份校验全部通过才创建/连接;任何拒绝路径下
    DELETE 与 migrate 均未执行(fixture 在 yield 前抛出)。"""
    dsn, declared = _declared_identity(_env_dsn())
    eng = create_async_engine(dsn)
    try:
        await _assert_server_identity(eng, declared)  # 校验先于测试体/迁移
        yield eng
    finally:
        await eng.dispose()


def _mk_version(source_id: str, *, ordinal: int, chunk_count: int) -> DocumentVersion:
    return DocumentVersion(
        id=uuid.uuid4(),
        source_id=source_id,
        version_seq=1,
        content_hash=uuid.uuid4().hex,
        metadata_hash=uuid.uuid4().hex,
        generation_id=uuid.uuid4(),
        generation_ordinal=ordinal,
        status="active",
        chunk_count=chunk_count,
    )


async def _seed(engine, marker: str) -> dict[str, DocumentVersion]:
    """三版本:误挂行(ordinal>0 超限)、legacy 冻结行(ordinal=0 超限)、干净行。"""
    v_bad = _mk_version(f"t10-{marker}/bad", ordinal=3, chunk_count=2)
    v_legacy = _mk_version(f"t10-{marker}/legacy", ordinal=0, chunk_count=1)
    v_clean = _mk_version(f"t10-{marker}/clean", ordinal=7, chunk_count=2)
    chunks = [
        (v_bad, 0), (v_bad, 1),  # 在范围内,保留
        (v_bad, 2), (v_bad, 3),  # 超限误挂 → 迁移目标
        (v_legacy, 0), (v_legacy, 1),  # ordinal=0 超限 → 冻结契约,保留
        (v_clean, 0), (v_clean, 1),  # 干净
    ]
    async with engine.begin() as conn:
        for v in (v_bad, v_legacy, v_clean):
            await conn.execute(
                insert(DocumentVersion).values(
                    id=v.id,
                    source_id=v.source_id,
                    version_seq=v.version_seq,
                    content_hash=v.content_hash,
                    metadata_hash=v.metadata_hash,
                    generation_id=v.generation_id,
                    generation_ordinal=v.generation_ordinal,
                    status=v.status,
                    chunk_count=v.chunk_count,
                )
            )
        for v, idx in chunks:
            await conn.execute(
                insert(DocumentVersionChunk).values(
                    version_id=v.id, chunk_index=idx, text=f"t-{idx}", props={}
                )
            )
    return {"bad": v_bad, "legacy": v_legacy, "clean": v_clean}


async def _chunk_indices(engine, version_id) -> list[int]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(DocumentVersionChunk.chunk_index)
                .where(DocumentVersionChunk.version_id == version_id)
                .order_by(DocumentVersionChunk.chunk_index)
            )
        ).all()
    return [int(r[0]) for r in rows]


async def _cleanup(engine, versions: list[DocumentVersion]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            delete(DocumentVersionChunk).where(
                DocumentVersionChunk.version_id.in_([v.id for v in versions])
            )
        )
        await conn.execute(
            delete(DocumentVersion).where(
                DocumentVersion.id.in_([v.id for v in versions])
            )
        )


async def test_t10_exact_scope_idempotent_and_resume_safe(engine):
    """T10:范围精确 + 幂等 + 部分完成后续跑安全。"""
    # 共享测试库先收敛到零基线(迁移幂等,重复执行安全)
    await migrate(engine)
    marker = uuid.uuid4().hex[:8]
    versions = await _seed(engine, marker)
    try:
        # 首轮:只删 ordinal>0 且 idx>=chunk_count 的行(v_bad 的 2,3)
        receipt = await migrate(engine)
        assert receipt == {"planned": 2, "removed": 2}
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1]
        # ordinal=0 legacy 超限行不在 DELETE 范围(冻结契约,原样保留)
        assert await _chunk_indices(engine, versions["legacy"].id) == [0, 1]
        # 干净行零触碰
        assert await _chunk_indices(engine, versions["clean"].id) == [0, 1]

        # 重跑 = no-op(幂等)
        assert await migrate(engine) == {"planned": 0, "removed": 0}

        # 部分完成模拟:外部先删 1 条误挂行 → 续跑只清剩余(无重复/无残留)
        async with engine.begin() as conn:
            await conn.execute(
                delete(DocumentVersionChunk).where(
                    DocumentVersionChunk.version_id == versions["bad"].id,
                    DocumentVersionChunk.chunk_index == 3,
                )
            )
        async with engine.begin() as conn:
            await conn.execute(
                insert(DocumentVersionChunk).values(
                    version_id=versions["bad"].id,
                    chunk_index=4,
                    text="re-contaminated",
                    props={},
                )
            )
        receipt = await migrate(engine)
        assert receipt == {"planned": 1, "removed": 1}
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1]
    finally:
        await _cleanup(engine, list(versions.values()))


async def test_t11_migration_exception_never_reports_success(engine, capsys, monkeypatch):
    """T11:迁移异常 → 异常向上抛、无 "OK:" 假成功标记、数据原样。"""
    await migrate(engine)  # 零基线
    capsys.readouterr()  # 冲掉基线成功运行的输出,仅断言异常路径自身无成功标记
    marker = uuid.uuid4().hex[:8]
    versions = await _seed(engine, marker)
    try:
        monkeypatch.setattr(mc, "_DELETE_SQL", "THIS IS NOT VALID SQL")
        with pytest.raises(DBAPIError):  # 非法 SQL → 语法错误,驱动层结构化上抛
            await migrate(engine)
        out = capsys.readouterr().out
        assert "OK:" not in out, "异常路径不得输出成功标记"
        # 数据原样(单事务原子性:DELETE 失败即回滚,无半态)
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1, 2, 3]
    finally:
        await _cleanup(engine, list(versions.values()))


# --------------------------------------------------------------------------- #
# R2-2:六类身份校验路径(五负例 + 一正例)
#
# RED 实证(R1 现码,2026-10-19):非测试库名的本地 scratch 库
# ``ask_ai_r2red_scratch`` 上,R1 路径(仅强制 env 有值)无任何拒绝,
# migrate() 直接执行不受限 DELETE(receipt 返回,详见交接证据)。
# 下列负例断言的"先于连接拒绝"与"身份复核拒绝"均为 R2 新增行为。
# --------------------------------------------------------------------------- #


class _NeverEngine:
    """哨兵:任何试图创建真实连接的路径都会触发失败(证明拒绝先于连接)。"""

    def __init__(self, *a, **k):
        raise AssertionError("拒绝路径不得创建任何 engine/连接(校验必须先于连接)")


async def test_r22_neg_missing_env_refuses_before_any_connection(monkeypatch):
    """负例 1:缺失 TEST_DATABASE_URL → 拒绝;engine 永不创建(DELETE 未执行)。"""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        sys.modules[__name__], "create_async_engine", _NeverEngine
    )
    with pytest.raises(_TestDbIdentityRefused, match="缺失"):
        _declared_identity(_env_dsn())


async def test_r22_neg_non_test_dbname_refuses_before_any_connection(monkeypatch):
    """负例 2:非测试库名(本地派生 URL)→ URL 级拒绝,先于任何连接。"""
    dsn = _derived_dsn(dbname="ask_ai_r2red_scratch")  # 真实本地实例上的他名库
    assert urlsplit(dsn).path.lstrip("/") != _TEST_DB_NAME
    monkeypatch.setenv("TEST_DATABASE_URL", dsn)
    monkeypatch.setattr(
        sys.modules[__name__], "create_async_engine", _NeverEngine
    )
    with pytest.raises(_TestDbIdentityRefused, match="ask_ai_test"):
        _declared_identity(_env_dsn())


async def test_r22_neg_remote_host_refuses_before_any_connection(monkeypatch):
    """负例 3:远程 host → URL 级拒绝,先于任何连接(绝不外连)。"""
    dsn = _derived_dsn(host="db.internal.example.com")
    monkeypatch.setenv("TEST_DATABASE_URL", dsn)
    monkeypatch.setattr(
        sys.modules[__name__], "create_async_engine", _NeverEngine
    )
    with pytest.raises(_TestDbIdentityRefused, match="host"):
        _declared_identity(_env_dsn())


class _StubResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _StubConn:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _StubResult(self._row)


class _StubEngine:
    """仅回答 current_database() 的桩 engine(身份复核决策逻辑;不触真库)。"""

    def __init__(self, row):
        self._row = row

    def connect(self):
        return _StubConn(self._row)


async def test_r22_neg_identity_mismatch_refuses_before_delete():
    """负例 4:连接后 current_database() ≠ URL 声明 → 拒绝(DELETE 未执行)。"""
    with pytest.raises(_TestDbIdentityRefused, match="≠ URL 声明"):
        await _assert_server_identity(_StubEngine(("ask_ai_other_db",)), _TEST_DB_NAME)


async def test_r22_neg_identity_unreadable_refuses_before_delete():
    """负例 5:身份不可读(current_database() 行缺失/NULL)→ 拒绝。"""
    with pytest.raises(_TestDbIdentityRefused, match="无法读取"):
        await _assert_server_identity(_StubEngine((None,)), _TEST_DB_NAME)
    with pytest.raises(_TestDbIdentityRefused, match="无法读取"):
        await _assert_server_identity(_StubEngine(None), _TEST_DB_NAME)


async def test_r22_pos_legit_isolated_test_db_accepted(engine):
    """正例:合法隔离测试库(localhost/ask_ai_test)→ 校验全通过,连接真实可读。

    本测试体执行到此处即证明:URL 级校验 + 连接后身份复核均通过(fixture
    已完成两重校验),T10/T11 的受控 DELETE 在正确的隔离库上运行。
    """
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT current_database()"))).first()
    assert row is not None and row[0] == _TEST_DB_NAME
