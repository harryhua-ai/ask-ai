"""LeadService 数据层测试(真实 Postgres,隔离库 ask_ai_lead_test)。

覆盖:load_lead_context 的现状读取/联系方式检测、apply_lead_turn 的
建行/更新/记账/联系方式捕获/不降级,以及「无信号不建行」。
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import SalesLead
from backend.db.session import get_session_factory
from backend.pipeline.lead_qualify import (
    LEAD_STATUS_CONTACT_CAPTURED,
    LEAD_STATUS_HANDED_OFF,
    LEAD_STATUS_POTENTIAL,
    LEAD_STATUS_QUALIFIED,
    LeadTurnContext,
)
from backend.services.lead_service import apply_lead_turn, load_lead_context


@pytest.fixture
def factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return get_session_factory(db_engine)


def _payload(ran=True, level="qualified", invited=False, fields=None, summary="s") -> dict:
    return {
        "ran": ran,
        "level": level,
        "invited": invited,
        "ack": False,
        "explicit_sales_request": False,
        "fields": fields or {},
        "summary": summary,
        "ms": 100,
    }


async def test_load_context_no_lead(factory) -> None:
    ctx = await load_lead_context(factory, session_id="sess-none", raw_question="NE503 有什么接口?")
    assert ctx.has_lead is False
    assert ctx.contact is None
    assert ctx.explicit_sales_hint is False
    assert ctx.capture_mode is False


async def test_load_context_detects_contact_and_history_mask(factory) -> None:
    ctx = await load_lead_context(
        factory,
        session_id=None,
        raw_question="邮箱 john@example.com,请让销售联系我",
        conversation_history=[
            {"role": "user", "content": "我邮箱是 alice@secret.com"},
            {"role": "assistant", "content": "好的"},
        ],
    )
    assert ctx.contact is not None and ctx.contact.value == "john@example.com"
    assert ctx.explicit_sales_hint is True
    # 历史 mask:上一轮邮箱不得以明文进入 qualifier prompt
    assert "alice@secret.com" not in str(ctx.history)
    assert "[邮箱已脱敏]" in ctx.history[0]["content"]


async def test_load_context_reads_existing_lead(factory) -> None:
    sid = "sess-read"
    async with factory() as s:
        s.add(
            SalesLead(
                session_id=sid,
                status=LEAD_STATUS_QUALIFIED,
                source_conversation_id=uuid.uuid4(),
                last_conversation_id=uuid.uuid4(),
                company="Acme",
                prompt_count=1,
            )
        )
        await s.commit()

    ctx = await load_lead_context(factory, session_id=sid, raw_question="还要更多")
    assert ctx.has_lead is True
    assert ctx.status == LEAD_STATUS_QUALIFIED
    assert ctx.prompt_count == 1
    assert ctx.recorded_fields["company"] == "Acme"


async def test_apply_creates_lead_on_qualified(factory) -> None:
    sid = "sess-create"
    conv_id = uuid.uuid4()
    ctx = await load_lead_context(factory, session_id=sid, raw_question="请报 500 台的价格")
    lead_id = await apply_lead_turn(
        factory,
        ctx,
        _payload(level="qualified", fields={"company": "Acme", "quantity": "500 台"}),
        conversation_id=conv_id,
        session_id=sid,
        channel="widget",
    )
    assert lead_id is not None
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.status == LEAD_STATUS_QUALIFIED
    assert row.company == "Acme"
    assert row.quantity == "500 台"
    assert row.source_conversation_id == conv_id
    assert row.session_id == sid


async def test_apply_no_signal_creates_nothing(factory) -> None:
    sid = "sess-nosignal"
    ctx = await load_lead_context(factory, session_id=sid, raw_question="NE503 多少钱?")
    out = await apply_lead_turn(
        factory,
        ctx,
        _payload(ran=True, level="none"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    assert out is None
    async with factory() as s:
        rows = (await s.execute(select(SalesLead).where(SalesLead.session_id == sid))).all()
    assert rows == []


async def test_apply_not_ran_and_no_contact_creates_nothing(factory) -> None:
    ctx = LeadTurnContext(session_id="sess-x")
    out = await apply_lead_turn(
        factory,
        ctx,
        _payload(ran=False, level="none"),
        conversation_id=uuid.uuid4(),
        session_id="sess-x",
    )
    assert out is None


async def test_second_turn_same_session_updates_and_prompt_bookkeeping(factory) -> None:
    sid = "sess-thread"
    ctx1 = await load_lead_context(factory, session_id=sid, raw_question="项目要批量采购")
    lead_id = await apply_lead_turn(
        factory,
        ctx1,
        _payload(level="qualified", invited=True, summary="采购意向"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    ctx2 = await load_lead_context(factory, session_id=sid, raw_question="对,还要正式报价")
    assert ctx2.has_lead is True and ctx2.prompt_count == 1
    lead_id2 = await apply_lead_turn(
        factory,
        ctx2,
        _payload(level="qualified", invited=False, fields={"timeline": "Q4"}),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    assert lead_id2 == lead_id
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.prompt_count == 1  # 第二轮未再邀请
    assert row.last_prompted_at is not None
    assert row.timeline == "Q4"  # 字段跨轮合并


async def test_contact_capture_upgrades_status(factory) -> None:
    """LEAD-G004:用户只给一个邮箱也 capture。"""
    sid = "sess-contact"
    ctx1 = await load_lead_context(factory, session_id=sid, raw_question="批量采购需要报价")
    await apply_lead_turn(
        factory,
        ctx1,
        _payload(level="qualified", invited=True),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    ctx2 = await load_lead_context(factory, session_id=sid, raw_question="邮箱 john@example.com")
    lead_id = await apply_lead_turn(
        factory,
        ctx2,
        _payload(ran=True, level="potential"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.status == LEAD_STATUS_CONTACT_CAPTURED
    assert row.contact_value == "john@example.com"
    assert row.contact_type == "email"
    assert row.contact_masked.endswith("@example.com")
    assert row.contact_captured_at is not None


async def test_contact_only_turn_without_prior_lead(factory) -> None:
    """无既有线索、qualifier 未运行、仅检出联系方式 → 也要能形成线索。"""
    sid = "sess-bare"
    ctx = LeadTurnContext(session_id=sid)
    ctx.contact = await _detect(factory, "john@example.com")
    lead_id = await apply_lead_turn(
        factory,
        ctx,
        _payload(ran=False, level="none"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    assert lead_id is not None
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.status == LEAD_STATUS_CONTACT_CAPTURED
    assert row.contact_value == "john@example.com"


async def _detect(factory, text: str):
    from backend.pipeline.lead_qualify import detect_contact

    return detect_contact(text)


async def test_existing_contact_not_overwritten(factory) -> None:
    sid = "sess-keep"
    ctx1 = LeadTurnContext(session_id=sid)
    ctx1.contact = _detect_sync("old@example.com")
    lead_id = await apply_lead_turn(
        factory,
        ctx1,
        _payload(ran=False, level="none"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    ctx2 = LeadTurnContext(session_id=sid)
    ctx2.contact = _detect_sync("new@example.com")
    await apply_lead_turn(
        factory,
        ctx2,
        _payload(ran=False, level="none"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.contact_value == "old@example.com"


def _detect_sync(text: str):
    from backend.pipeline.lead_qualify import detect_contact

    return detect_contact(text)


async def test_handed_off_not_downgraded(factory) -> None:
    sid = "sess-handoff"
    async with factory() as s:
        lead = SalesLead(
            session_id=sid,
            status=LEAD_STATUS_HANDED_OFF,
            source_conversation_id=uuid.uuid4(),
            last_conversation_id=uuid.uuid4(),
        )
        s.add(lead)
        await s.flush()
        lead_id = lead.id
        await s.commit()
    ctx = await load_lead_context(factory, session_id=sid, raw_question="再聊点别的")
    await apply_lead_turn(
        factory,
        ctx,
        _payload(level="potential"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.status == LEAD_STATUS_HANDED_OFF


async def test_potential_lead_created_on_potential_level(factory) -> None:
    """potential(初步商业意向)也建行——线索列表需要「潜在线索」口径(契约 §13)。"""
    sid = "sess-pot"
    ctx = await load_lead_context(factory, session_id=sid, raw_question="我们在选型,比较了三家")
    lead_id = await apply_lead_turn(
        factory,
        ctx,
        _payload(level="potential", summary="选型评估中"),
        conversation_id=uuid.uuid4(),
        session_id=sid,
    )
    assert lead_id is not None
    async with factory() as s:
        row = await s.get(SalesLead, lead_id)
    assert row.status == LEAD_STATUS_POTENTIAL
