"""Postgres 模型集成测试。

依赖 fixtures: ``db_engine`` 与 ``db_session``(定义在 tests/conftest.py)。
需要 Postgres 运行;使用 ``-m integration`` 标记运行。
"""

import pytest
from sqlalchemy import select, text

from backend.db.models import Conversation


@pytest.mark.integration
async def test_all_tables_created(db_engine):
    async with db_engine.begin() as conn:
        tables = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        names = {r[0] for r in tables}
        expected = {
            "conversations",
            "source_clicks",
            "sync_log",
            "data_sources",
            "customizations",
            "customization_bindings",
            "answer_overrides",
            "users",
            "llm_providers",
            "llm_routing",
        }
        assert expected.issubset(names), f"Missing tables: {expected - names}"


@pytest.mark.integration
async def test_conversation_reserved_fields_nullable(db_session):
    conv = Conversation(
        question="NE503 功耗是多少?",
        channel="widget",
        language="zh",
        is_answered=True,
    )
    db_session.add(conv)
    await db_session.commit()

    result = await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    saved = result.scalar_one()
    assert saved.intent_tag is None
    assert saved.cluster_id is None
    assert saved.gap_status is None
