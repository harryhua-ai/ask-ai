"""#68:country truth 迁移幂等性 + legacy 启发式值隔离测试。

迁移语义(scripts/migrate_add_country_truth.py):
- 补加性加列 ``conversations.country_source`` + 索引 ``idx_conversations_country``;
- legacy(Accept-Language 启发式时代)值的处置 = 转换为 Unknown:
  ``country_source IS NULL 且 country IS NOT NULL`` 的行是启发式产物,
  一律置 ``country = NULL``(契约禁止 silent grandfathering 为地理事实);
- 幂等:列/索引按 information_schema/pg_indexes 判定;转换语句天然收敛
  (第二轮起无 NULL-source 非空 country 行)。
"""

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from scripts.migrate_add_country_truth import migrate

pytestmark = pytest.mark.asyncio(loop_scope="session")

# DSN 纪律:本模块不 import backend.main(其模块级 load_dotenv 才会注入
# .env 的 TEST_DATABASE_URL),必须自行 load_dotenv,否则 DSN 会落到 dev 库
# ask_ai 而非共享测试库 ask_ai_test(两面异库 = 静默测错对象)。
from dotenv import load_dotenv

load_dotenv()
from backend.config import load_settings as _load_settings

_load_settings()
DSN = os.environ.get("TEST_DATABASE_URL", _load_settings().postgres_dsn)
from backend.db.session import get_engine


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(DSN)
    try:
        from backend.db.session import init_db

        await init_db(engine)
        yield engine
    finally:
        await engine.dispose()


_Q = "country-truth-migration-"
_MARKER = f"{_Q}{uuid.uuid4().hex[:8]}%"


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(db_engine):
    """按 (country, country_source) 组合播种,结束后按 question 前缀精准清理。"""
    rows = [
        # (question, country, country_source)
        (f"{_MARKER}-legacy-us", "US", None),  # 启发式产物 → 必须被转 Unknown
        (f"{_MARKER}-trusted-de", "DE", "ingress"),  # 权威值 → 必须原样保留
        (f"{_MARKER}-null-none", None, None),  # 从未有过值
    ]
    async with db_engine.begin() as conn:
        for question, country, source in rows:
            await conn.execute(
                text(
                    "INSERT INTO conversations (id, question, channel, sources, custom_tags, is_answered, country, country_source) "
                    "VALUES (:id, :q, 'widget', '[]'::jsonb, '[]'::jsonb, false, :c, :s)"
                ),
                {"id": uuid.uuid4(), "q": question, "c": country, "s": source},
            )
    yield rows
    async with db_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM conversations WHERE question LIKE :p"), {"p": _MARKER}
        )


async def _country_of(db_engine, question):
    async with db_engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT country, country_source FROM conversations WHERE question = :q"),
                {"q": question},
            )
        ).one()


async def test_migration_nulls_legacy_heuristic_country(db_engine, seeded):
    applied = await migrate(db_engine)
    # 共享库 schema 已是最新 → 加列/索引分支可能为 no-op;legacy 转换是行为断言
    country, source = await _country_of(db_engine, seeded[0][0])
    assert (country, source) == (None, None)


async def test_migration_preserves_trusted_country(db_engine, seeded):
    await migrate(db_engine)
    country, source = await _country_of(db_engine, seeded[1][0])
    assert (country, source) == ("DE", "ingress")


async def test_migration_idempotent_second_run(db_engine, seeded):
    await migrate(db_engine)
    applied_second = await migrate(db_engine)
    assert applied_second == []
    country, source = await _country_of(db_engine, seeded[0][0])
    assert (country, source) == (None, None)


async def test_migration_recreates_missing_column_and_index(db_engine, seeded):
    """加列/索引分支:物理移除后迁移必须重建(全新库/旧库升级路径)。"""
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_conversations_country"))
        await conn.execute(text("ALTER TABLE conversations DROP COLUMN IF EXISTS country_source"))
    applied = await migrate(db_engine)
    assert any("country_source" in step for step in applied)
    assert any("idx_conversations_country" in step for step in applied)
    async with db_engine.begin() as conn:
        col = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='conversations' AND column_name='country_source'"
                )
            )
        ).scalar()
        idx = (
            await conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = 'idx_conversations_country'"
                )
            )
        ).scalar()
    assert col == 1 and idx == 1
    # 重建列后 legacy 行(source NULL, country 非空)再次被转换
    country, _ = await _country_of(db_engine, seeded[0][0])
    assert country is None
