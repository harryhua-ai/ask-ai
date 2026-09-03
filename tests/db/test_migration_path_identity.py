"""documents 身份迁移测试(Issue #13 Stage A;真实 Postgres DDL 演练)。

正向:旧 PK (content_hash, branch) 形态表 → migrate → PK=source_id +
content_hash 指数索引;同 source_id 历史重复行合并;同 hash 不同路径可共存。
幂等:重复执行 no-op。回滚:无冲突时恢复旧 PK;存在同 (hash,branch) 多行
(新契约合法共存)时拒绝回滚。
"""

import pytest
from sqlalchemy import text

from scripts.migrate_documents_path_identity import migrate

pytestmark = pytest.mark.asyncio

_OLD_DDL = """
CREATE TABLE documents (
    content_hash VARCHAR(64) NOT NULL,
    source_id VARCHAR(200) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    product VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    branch VARCHAR(100) NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (content_hash, branch)
)
"""
_CREATE_IX = "CREATE INDEX IF NOT EXISTS ix_documents_source_id ON documents (source_id)"


async def _seed_old_shape(engine):
    """drop 现表并重建旧 PK 形态,插入三行:两行同 source_id(内容变更遗留)+
    一行独立文档。"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS documents"))
        await conn.execute(text(_OLD_DDL))
        await conn.execute(text(_CREATE_IX))
        await conn.execute(
            text(
                "INSERT INTO documents (content_hash, source_id, source_type, product, "
                "title, url, branch, chunk_count, updated_at) VALUES "
                "('h-old', 'src/main/a.py', 'github', 'p', 'a', 'u', 'main', 2, "
                "now() - interval '2 hour'),"
                "('h-new', 'src/main/a.py', 'github', 'p', 'a', 'u', 'main', 5, now()),"
                "('h-x',   'src/main/b.py', 'github', 'p', 'b', 'u', 'main', 1, now())"
            )
        )


async def test_migration_old_to_path_identity(db_engine):
    await _seed_old_shape(db_engine)

    report = await migrate(db_engine)

    assert any("add PK (source_id)" in a for a in report["actions"])
    async with db_engine.connect() as conn:
        pk = list(
            (
                await conn.execute(
                    text(
                        "SELECT a.attname FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indrelid "
                        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey) "
                        "WHERE i.indisprimary AND c.relname = 'documents'"
                    )
                )
            ).scalars()
        )
        n = (await conn.execute(text("SELECT count(*) FROM documents"))).scalar()
        # 同 hash 不同路径可共存(D2 契约,旧 PK 下不可能)
        await conn.execute(
            text(
                "INSERT INTO documents (content_hash, source_id, source_type, product, "
                "title, url, branch, chunk_count) VALUES "
                "('h-dup', 'src/main/x1.py', 'github', 'p', 'x', 'u', 'main', 1),"
                "('h-dup', 'src/main/x2.py', 'github', 'p', 'x', 'u', 'main', 1)"
            )
        )
    assert pk == ["source_id"]
    assert n == 2  # 同 source_id 两行合并为保留 updated_at 最新一行


async def test_migration_idempotent(db_engine):
    await _seed_old_shape(db_engine)
    await migrate(db_engine)
    report2 = await migrate(db_engine)
    assert report2["actions"] == ["noop: already migrated (PK=source_id)"]


async def test_rollback_restores_old_pk_and_refuses_on_coexistence(db_engine):
    await _seed_old_shape(db_engine)
    await migrate(db_engine)

    # 无共存行:可回滚
    report = await migrate(db_engine, rollback=True)
    assert any("restore PK (content_hash, branch)" in a for a in report["actions"])
    # 回滚后再正向迁移(往返一致性)
    report2 = await migrate(db_engine)
    assert any("add PK (source_id)" in a for a in report2["actions"])

    # 制造新契约下的合法共存行 → 回滚必须拒绝(不静默丢数据)
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO documents (content_hash, source_id, source_type, product, "
                "title, url, branch, chunk_count) VALUES "
                "('h-same', 'src/main/y1.py', 'github', 'p', 'y', 'u', 'main', 1),"
                "('h-same', 'src/main/y2.py', 'github', 'p', 'y', 'u', 'main', 1)"
            )
        )
    with pytest.raises(RuntimeError, match="拒绝"):
        await migrate(db_engine, rollback=True)
