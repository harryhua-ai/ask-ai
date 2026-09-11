"""TB-P1 生产迁移矫正 RED→GREEN 门测试(NUL 安全真值迁移 + verify-only 状态机)。

矫正冻结口径(Role A):
- FIX-1:Weaviate 文本真值 → PG 拷贝时**仅剥离 NUL(\x00)**;对象/chunk 结构
  1:1 保全(source_id/chunk_index/chunk_count 不变;不跳过、不删对象、不动
  向量、零重嵌);清理统计入迁移输出(objects scanned / chunks inserted /
  含 NUL 的 chunks / 移除 NUL 总数);重跑幂等;
- FIX-2:--verify-only 状态机——CLEAN LEGACY → 显式 ELIGIBLE(退出成功);
  PARTIAL/INVALID → FAIL CLOSED;FULLY MIGRATED → 既有全量验证;
  --verify-only 永不变更 schema/数据。

真实 Postgres + 真实 Weaviate(与 test_migration_p1_lifecycle 同基座;不可达 skip)。
"""

import asyncio
import os
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, DocumentVersion

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")
ADMIN_DSN = TEST_DSN.rsplit("/", 1)[0] + "/postgres"
MIG_DB = "ask_ai_p1fix_test"
MIG_DSN = TEST_DSN.rsplit("/", 1)[0] + "/" + MIG_DB
MIG_DSN_ASYNC = MIG_DSN.replace("+psycopg2", "+asyncpg")
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "P1FixProbe"

pytestmark = pytest.mark.integration


def _weaviate():
    try:
        return weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture()
def mig():
    client = _weaviate()
    if client is None:
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")

    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        c.execute(text(f'CREATE DATABASE "{MIG_DB}"'))
    admin.dispose()

    engine = create_engine(MIG_DSN)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS document_version_chunks CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS document_versions CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS index_generations CASCADE"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS lifecycle"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS current_version_id"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS superseded_by"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS superseded_at"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at"))
    sync_factory = sessionmaker(engine, expire_on_commit=False)

    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    yield SimpleNamespace(engine=engine, sync_factory=sync_factory, client=client)

    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))


async def _ensure_schema():
    import scripts.migrate_p1_lifecycle_foundation as m

    engine = create_async_engine(MIG_DSN_ASYNC)
    try:
        await m.ensure_pg_schema(engine)
    finally:
        await engine.dispose()


def _seed_legacy_rows(sync_factory, rows) -> None:
    with sync_factory() as s:
        for sid, cc in rows:
            s.execute(
                text(
                    "INSERT INTO documents (source_id, content_hash, source_type, product,"
                    " title, url, metadata, branch, chunk_count)"
                    " VALUES (:sid, :h, 'web_crawl', 'probe', :sid, :u, '{}', '', :cc)"
                ),
                {"sid": sid, "h": f"h-{sid}", "u": f"https://x/{sid}", "cc": cc},
            )
        s.commit()


def _run_chain(mig) -> dict:
    import scripts.migrate_p1_lifecycle_foundation as m

    asyncio.run(_ensure_schema())
    m.backfill_versions(mig.sync_factory)
    m.ensure_weaviate_schema(mig.client, CLASS_NAME)
    return m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)


def _seed_objects(mig, objs) -> None:
    """objs: [(source_id, chunk_index, text, extra_props)](legacy 确定性 UUID)。"""
    import weaviate.classes.data as wd
    from weaviate.classes.config import Configure, DataType, Property

    from backend.pipeline.ingest import COLLECTION_PROPERTIES, _deterministic_uuid

    mig.client.collections.create(
        name=CLASS_NAME,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(
                name=n,
                data_type={"text": DataType.TEXT, "int": DataType.INT,
                           "text[]": DataType.TEXT_ARRAY}[d],
            )
            for n, d in COLLECTION_PROPERTIES
            if n not in ("generation_ordinal", "generation_id")
        ],
    )
    col = mig.client.collections.get(CLASS_NAME)
    data = []
    for sid, idx, text_, extra in objs:
        props = {
            "source_id": sid,
            "chunk_index": idx,
            "text": text_,
            "content_hash": f"h-{sid}",
            "source_type": "web_crawl",
            "product": "probe",
            "title": sid,
            "url": f"https://x/{sid}",
            "branch": "",
        }
        props.update(extra)
        data.append(
            wd.DataObject(
                properties=props,
                vector=[0.1] * 4,
                uuid=_deterministic_uuid(sid, idx),
            )
        )
    col.data.insert_many(data)


def _chunk_rows(mig, sid: str) -> dict[int, str]:
    with mig.sync_factory() as s:
        rows = s.execute(
            text(
                "SELECT c.chunk_index, c.text FROM document_version_chunks c"
                " JOIN document_versions v ON v.id = c.version_id"
                " WHERE v.source_id = :sid ORDER BY c.chunk_index"
            ),
            {"sid": sid},
        ).all()
    return {idx: t for idx, t in rows}


# --------------------------------------------------------------------------- #
# FIX-1 RED:仅剥 NUL;结构 1:1;统计精确;幂等
# --------------------------------------------------------------------------- #


def test_nul_in_chunk_text_is_stripped_and_chunk_preserved(mig):
    """RED-1:chunk text 含 NUL → 拷贝剥 NUL;chunk 不跳过;Weaviate 对象不动。"""

    raw = "before\x00after"
    _seed_legacy_rows(mig.sync_factory, [("nul-doc-a", 1)])
    _seed_objects(mig, [("nul-doc-a", 0, raw, {})])

    stats = _run_chain(mig)
    rows = _chunk_rows(mig, "nul-doc-a")
    assert rows == {0: "beforeafter"}  # 仅 NUL 移除,chunk 保全(不跳过)
    assert stats["chunks_inserted"] == 1
    # 结构 1:1:version.chunk_count 与持久行数一致
    with mig.sync_factory() as s:
        ver = s.query(DocumentVersion).filter(
            DocumentVersion.source_id == "nul-doc-a"
        ).one()
    assert ver.chunk_count == len(rows) == 1
    # Weaviate 对象未被删除/改写(text 原样含 NUL;仅补 generation 属性)
    from weaviate.classes.query import Filter

    from backend.pipeline.ingest import _deterministic_uuid

    col = mig.client.collections.get(CLASS_NAME)
    resp = col.query.fetch_objects(
        filters=Filter.by_id().contains_any([_deterministic_uuid("nul-doc-a", 0)]),
        limit=1,
    )
    assert resp.objects[0].properties["text"] == raw  # 向量库内容原样


def test_nul_in_nested_persisted_property_is_stripped(mig):
    """RED-2:嵌套持久字符串(数组属性)含 NUL → props JSONB 内剥 NUL。"""
    _seed_legacy_rows(mig.sync_factory, [("nul-doc-b", 1)])
    _seed_objects(
        mig,
        [("nul-doc-b", 0, "clean text", {"channel_visibility": ["widget\x00", "api"]})],
    )

    _run_chain(mig)
    with mig.sync_factory() as s:
        row = s.execute(
            text(
                "SELECT c.props FROM document_version_chunks c"
                " JOIN document_versions v ON v.id = c.version_id"
                " WHERE v.source_id = 'nul-doc-b'"
            )
        ).scalar_one()
    assert row["channel_visibility"] == ["widget", "api"]  # 嵌套串已剥
    assert row["text"] == "clean text"


def test_multiple_nuls_exact_removal_accounting(mig):
    """RED-3:多处 NUL(文本+属性)→ 统计精确到字符;对象/chunk 计数区分。"""
    _seed_legacy_rows(mig.sync_factory, [("nul-doc-c", 2)])
    _seed_objects(
        mig,
        [
            ("nul-doc-c", 0, "a\x00b\x00\x00c", {"title": "t\x00i"}),
            ("nul-doc-c", 1, "\x00\x00tail", {}),
        ],
    )

    stats = _run_chain(mig)
    # 文本 3+2=5;属性 title 1 → 总移除 6
    assert stats["nul_chars_removed"] == 6
    assert stats["nul_chunks"] == 2  # 两个含 NUL chunk
    assert stats["nul_objects"] == 1  # 一个对象(两 chunk 同对象)
    rows = _chunk_rows(mig, "nul-doc-c")
    assert rows[0] == "abc" and rows[1] == "tail"


def test_normal_text_untouched_and_zero_nul_stats(mig):
    """RED-4:常规文本零改动、零归一化;NUL 统计全零。"""
    _seed_legacy_rows(mig.sync_factory, [("clean-doc", 1)])
    _seed_objects(mig, [("clean-doc", 0, "plain 中文 text ✦ unchanged", {})])

    stats = _run_chain(mig)
    assert _chunk_rows(mig, "clean-doc") == {0: "plain 中文 text ✦ unchanged"}
    assert stats["nul_chunks"] == 0
    assert stats["nul_objects"] == 0
    assert stats["nul_chars_removed"] == 0


def test_rerun_idempotent_with_nul_docs(mig):
    """RED-5:NUL 文档在场时重跑幂等:零新插、零重复行、统计归零。"""
    _seed_legacy_rows(mig.sync_factory, [("nul-doc-d", 1)])
    _seed_objects(mig, [("nul-doc-d", 0, "x\x00y", {})])

    first = _run_chain(mig)
    assert first["chunks_inserted"] == 1
    second = _run_chain(mig)
    assert second["chunks_inserted"] == 0
    assert second["props_backfilled"] == 0
    assert second["nul_chunks"] == 0
    assert _chunk_rows(mig, "nul-doc-d") == {0: "xy"}


def test_structural_count_preserved_across_nul_and_normal(mig):
    """RED-6:混批(NUL+常规)下逐文档 chunk 计数与结构 1:1,无相互挤占。"""
    _seed_legacy_rows(
        mig.sync_factory,
        [("mix-nul", 2), ("mix-clean", 3), ("mix-nul2", 1)],
    )
    _seed_objects(
        mig,
        [
            ("mix-nul", 0, "\x00one", {}),
            ("mix-nul", 1, "two", {}),
            ("mix-clean", 0, "c0", {}),
            ("mix-clean", 1, "c1", {}),
            ("mix-clean", 2, "c2", {}),
            ("mix-nul2", 0, "\x00\x00z\x00", {}),
        ],
    )

    stats = _run_chain(mig)
    assert stats["chunks_inserted"] == 6
    assert stats["scanned"] == 6
    with mig.sync_factory() as s:
        counts = {
            src: cc for src, cc in s.execute(
                text("SELECT source_id, chunk_count FROM document_versions")
            ).all()
        }
    assert counts == {"mix-nul": 2, "mix-clean": 3, "mix-nul2": 1}
    assert len(_chunk_rows(mig, "mix-nul")) == 2
    assert _chunk_rows(mig, "mix-nul2") == {0: "z"}


# --------------------------------------------------------------------------- #
# FIX-2 RED:--verify-only 状态机(legacy / partial / migrated)
# --------------------------------------------------------------------------- #


def test_verify_only_reports_clean_legacy_eligible(mig):
    """RED-7:纯净 legacy(八结构全缺)→ state=legacy;迁移门显式 ELIGIBLE 且放行。"""
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory, [("legacy-doc", 1)])
    state = m.inspect_pg_migration_state(mig.sync_factory)
    assert state["state"] == "legacy"
    assert state["columns_present"] == [] and state["tables_present"] == []
    label, ok = m.migration_gate(state)
    assert ok is True and "ELIGIBLE" in label


def test_verify_only_fails_closed_on_partial_state(mig):
    """RED-8:部分迁移态(缺一列)→ state=partial;门 FAIL CLOSED。"""
    import scripts.migrate_p1_lifecycle_foundation as m

    asyncio.run(_ensure_schema())
    with mig.engine.begin() as c:
        c.execute(text("ALTER TABLE documents DROP COLUMN deleted_at"))
    state = m.inspect_pg_migration_state(mig.sync_factory)
    assert state["state"] == "partial"
    assert state["columns_missing"] == ["deleted_at"]
    _label, ok = m.migration_gate(state)
    assert ok is False
    # verify-only 顶层入口在 partial 态必须 raise(部署门 fail-closed)
    with pytest.raises(RuntimeError, match="partial|fail-closed"):
        m.run_verify_only_gate(mig.sync_factory, None, CLASS_NAME)


def test_verify_only_passes_on_fully_migrated(mig):
    """RED-9:全迁移态 → state=migrated;门走既有全量验证并 PASS。"""
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory, [("mig-doc-a", 1)])
    _seed_objects(mig, [("mig-doc-a", 0, "t", {})])
    _run_chain(mig)
    state = m.inspect_pg_migration_state(mig.sync_factory)
    assert state["state"] == "migrated"
    label, ok = m.migration_gate(state)
    assert ok is True and "MIGRATED" in label
    # 顶层入口:迁移完成态 = 走既有 verify()(PG+Weaviate 全不变量)且不抛
    result = m.run_verify_only_gate(mig.sync_factory, mig.client, CLASS_NAME)
    assert result["pg"]["null_current"] == 0


# --------------------------------------------------------------------------- #
# FIX-3 RED:部署迁移清单必须登记 P1 迁移
# --------------------------------------------------------------------------- #


def test_migration_manifest_registers_p1_migration():
    """RED-10:migrations.json 含 P1 迁移;条目合法且冻结树内真实存在。"""
    import json
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "deploy/prod/migrations.json").read_text())
    entries = manifest["migrations"]
    assert "scripts/migrate_p1_lifecycle_foundation.py" in entries
    entry_re = re.compile(r"^scripts/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$")
    for e in entries:
        assert entry_re.match(e), e
        assert (root / e).exists(), e
