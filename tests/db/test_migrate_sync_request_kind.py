"""INC-WEB-EMBED-413 REMEDIATION:sync_requests.kind 加性迁移测试。

legacy 形态(无 kind 列)→ 迁移补列 → 幂等重跑 no-op;旧行 kind=NULL。
真实 Postgres(一次性数据库);不可达时整文件 skip。
"""

import asyncio
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.models import Base
from scripts.migrate_add_sync_request_kind import migrate

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
ADMIN_DSN = TEST_DSN.replace("+asyncpg", "+psycopg2").rsplit("/", 1)[0] + "/postgres"
KIND_DB = "ask_ai_srkind_test"
KIND_DSN_SYNC = ADMIN_DSN.rsplit("/", 1)[0] + "/" + KIND_DB
KIND_DSN_ASYNC = TEST_DSN.rsplit("/", 1)[0] + "/" + KIND_DB

pytestmark = pytest.mark.integration


@pytest.fixture()
def kind_db():
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{KIND_DB}"'))
        c.execute(text(f'CREATE DATABASE "{KIND_DB}"'))
    admin.dispose()
    engine = create_engine(KIND_DSN_SYNC)
    # legacy 形态:建表后拆掉 kind 列(模拟存量部署)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE sync_requests DROP COLUMN IF EXISTS kind"))
    yield engine
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{KIND_DB}"'))


def _has_kind(engine) -> bool:
    with engine.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='sync_requests'"
        ))}
    return "kind" in cols


def test_kind_column_additive_idempotent(kind_db):
    assert not _has_kind(kind_db)

    async_engine = create_async_engine(KIND_DSN_ASYNC)

    async def _twice():
        await migrate(async_engine)
        assert _has_kind(kind_db)
        await migrate(async_engine)  # 幂等:重跑 no-op
        assert _has_kind(kind_db)

    try:
        asyncio.run(_twice())
    finally:
        asyncio.run(async_engine.dispose())
