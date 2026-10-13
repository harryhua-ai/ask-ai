"""#124 错误联系方式可审计作废:sales_leads 作废审计列加性迁移测试。

legacy 形态(无作废审计列)→ 迁移补列 → 幂等重跑 no-op;存量行零回填
(contact_voided=false)。真实 Postgres(一次性数据库);不可达时整文件 skip。
"""

import asyncio
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.models import Base
from scripts.migrate_add_sales_lead_contact_void import migrate

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
ADMIN_DSN = TEST_DSN.replace("+asyncpg", "+psycopg2").rsplit("/", 1)[0] + "/postgres"
VOID_DB = "ask_ai_lead_void_test"
VOID_DSN_SYNC = ADMIN_DSN.rsplit("/", 1)[0] + "/" + VOID_DB
VOID_DSN_ASYNC = TEST_DSN.rsplit("/", 1)[0] + "/" + VOID_DB

_VOID_COLUMNS = (
    "contact_voided",
    "contact_voided_at",
    "contact_voided_by",
    "contact_voided_reason",
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def void_db():
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{VOID_DB}"'))
        c.execute(text(f'CREATE DATABASE "{VOID_DB}"'))
    admin.dispose()
    engine = create_engine(VOID_DSN_SYNC)
    # legacy 形态:建表后拆掉作废审计列(模拟存量部署)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for col in _VOID_COLUMNS:
            c.execute(text(f"ALTER TABLE sales_leads DROP COLUMN IF EXISTS {col}"))
    yield engine
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{VOID_DB}"'))


def _columns(engine) -> set[str]:
    with engine.connect() as c:
        return {
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='sales_leads'"
                )
            )
        }


def test_contact_void_columns_additive_idempotent(void_db):
    assert not set(_VOID_COLUMNS) <= _columns(void_db)

    async_engine = create_async_engine(VOID_DSN_ASYNC)

    async def _twice():
        await migrate(async_engine)
        assert set(_VOID_COLUMNS) <= _columns(void_db)
        await migrate(async_engine)  # 幂等:重跑 no-op
        assert set(_VOID_COLUMNS) <= _columns(void_db)

    try:
        asyncio.run(_twice())
    finally:
        asyncio.run(async_engine.dispose())
