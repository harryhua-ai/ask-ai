"""Issue #92:canonical 文档身份列扩容 varchar(200) → varchar(500)(幂等迁移)。

生产事实(2026-09-16/17,`wiki-documents-local` 每轮失败):Docusaurus i18n
英文路径的复合身份 `<source>/<branch>/<rel_path>` 超过 200 字符,INSERT 触发
``StringDataRightTruncation``,合法权威文档无法入账。

身份盘点(#92 依赖审计):携带**复合文档身份**的列共 5 个,全部同批扩容 ——
    documents.source_id(PK)/ documents.superseded_by /
    document_versions.source_id(uq_document_versions_source_seq +
    idx_document_versions_source_status)/ document_repair_tasks.doc_source_id /
    document_recovery_events.doc_source_id。
源配置级 id(source_id 不含路径复合,≤100)不在本迁移范围。

语义:纯容量扩容,零数据改写 —— 存量 ≤200 身份逐字节不变;不引入第二身份
体系;不截断、不哈希。PostgreSQL 加宽 varchar 为元数据级变更(无表重写,
索引原位有效)。幂等:按 information_schema 当前容量判定,≥500 即 no-op。
生产执行窗口:任意(瞬时 ACCESS EXCLUSIVE 锁,仅元数据)。
"""

import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TARGET_LENGTH = 500

# (table, column) 复合文档身份列全集(#92 依赖审计产出)
IDENTITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("documents", "source_id"),
    ("documents", "superseded_by"),
    ("document_versions", "source_id"),
    ("document_repair_tasks", "doc_source_id"),
    ("document_recovery_events", "doc_source_id"),
)

# superseded_by 可空列:加宽不影响 NULL 语义
_STATEMENT = 'ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR({length})'


def _current_length(sync_conn, table: str, column: str) -> int | None:
    row = sync_conn.execute(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar_one_or_none()
    return int(row) if row is not None else None


def migrate_sync(sync_conn) -> list[str]:
    """幂等扩容(同步连接面;测试与部署桥共用)。返回实际执行的 ALTER 列表。"""
    applied: list[str] = []
    for table, column in IDENTITY_COLUMNS:
        length = _current_length(sync_conn, table, column)
        if length is None:
            # 列不存在(全新库由 create_all 建出目标 schema)→ no-op
            continue
        if length >= TARGET_LENGTH:
            continue
        stmt = _STATEMENT.format(table=table, column=column, length=TARGET_LENGTH)
        sync_conn.execute(text(stmt))
        applied.append(f"{table}.{column}")
    return applied


async def migrate(engine) -> list[str]:
    """asyncpg 面入口(deploy/prod/migrations.json 清单执行形态)。"""
    applied: list[str] = []
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: applied.extend(migrate_sync(sync_conn)))
    return applied


async def _main() -> None:
    from backend.config import load_settings
    from backend.db.session import get_engine

    engine = get_engine(load_settings().postgres_dsn)
    try:
        applied = await migrate(engine)
        if applied:
            print(f"OK: 扩容至 VARCHAR({TARGET_LENGTH}): {', '.join(applied)}")
        else:
            print(f"OK: 全部身份列已 ≥ VARCHAR({TARGET_LENGTH})(幂等 no-op)")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
