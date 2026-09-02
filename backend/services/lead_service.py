"""销售线索服务:单轮上下文构建(读)与线索落库(写)。

数据流(routes.py 编排):
    raw_message ──► load_lead_context(DB 现状 + 确定性联系方式检测,只读)
                          │
                          ▼
              rag.stream_answer(lead_ctx=…)  ← 资格判定/邀请决策在管线内
                          │
                          ▼
              apply_lead_turn(lead_payload, 写 sales_leads,只升不降)

隐私边界(HARD):联系方式原文来自「mask_pii 之前的原始消息」的确定性正则,
只写入 PostgreSQL sales_leads;进入 LLM/对话表/trace 的一律是 mask 后文本,
trace 中只允许 contact_masked。
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import SalesLead
from backend.pipeline.lead_qualify import (
    ContactHit,
    LeadQualification,
    LeadTurnContext,
    compute_status,
    detect_contact,
    explicit_sales_hint,
)
from backend.utils.pii import mask_pii

logger = logging.getLogger(__name__)

# 供 qualifier 使用的历史上限(消息条数 / 单条字符数),约束 prompt 体积
_HISTORY_MESSAGES = 8
_HISTORY_CONTENT_CAP = 2000


async def load_lead_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str | None,
    raw_question: str,
    conversation_history: list[dict] | None = None,
) -> LeadTurnContext:
    """构建单轮 LeadTurnContext(只读,任何异常由调用方 fail-open)。

    - 会话已有线索 → 携带其状态/记账/已记录字段(供 stronger_signal 对比);
    - 原始消息确定性检测联系方式与「要求销售联系」短语;
    - 历史轮次逐条 mask 后截断(qualifier prompt 用)。
    """
    ctx = LeadTurnContext(session_id=session_id)
    ctx.contact = detect_contact(raw_question or "")
    ctx.explicit_sales_hint = explicit_sales_hint(raw_question or "")

    if conversation_history:
        ctx.history = [
            {
                "role": h.get("role", "user"),
                "content": mask_pii(str(h.get("content", "")))[:_HISTORY_CONTENT_CAP],
            }
            for h in conversation_history[-_HISTORY_MESSAGES:]
        ]

    if session_id:
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(SalesLead)
                    .where(SalesLead.session_id == session_id)
                    .order_by(SalesLead.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row:
                ctx.has_lead = True
                ctx.lead_id = row.id
                ctx.status = row.status
                ctx.prompt_count = row.prompt_count
                ctx.contact_present = bool(row.contact_value)
                ctx.recorded_fields = {
                    "name": row.name or "",
                    "company": row.company or "",
                    "region": row.region or "",
                    "product_interest": row.product_interest or "",
                    "quantity": row.quantity or "",
                    "use_case": (row.use_case or "")[:500],
                    "purchase_intent": row.purchase_intent or "",
                    "timeline": row.timeline or "",
                }
    return ctx


def _qualification_from_payload(payload: dict[str, Any]) -> LeadQualification:
    """把管线产出的 lead_payload 还原为 LeadQualification(status 计算只需 level)。"""
    return LeadQualification(level=payload.get("level") or "none", ran=bool(payload.get("ran")))


def _merge_fields(
    existing: SalesLead | None, payload_fields: dict[str, Any]
) -> dict[str, str | None]:
    """字段合并:新值非空则覆盖,否则保留旧值。"""
    current = {
        "name": existing.name if existing else None,
        "company": existing.company if existing else None,
        "region": existing.region if existing else None,
        "product_interest": existing.product_interest if existing else None,
        "quantity": existing.quantity if existing else None,
        "use_case": existing.use_case if existing else None,
        "purchase_intent": existing.purchase_intent if existing else None,
        "timeline": existing.timeline if existing else None,
    }
    for key in current:
        new_value = (payload_fields.get(key) or "").strip()
        if new_value:
            current[key] = new_value[:500] if key == "use_case" else new_value
    return current


async def apply_lead_turn(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: LeadTurnContext | None,
    lead_payload: dict[str, Any] | None,
    *,
    conversation_id: uuid.UUID,
    session_id: str | None,
    channel: str | None = None,
    language: str | None = None,
    country: str | None = None,
) -> uuid.UUID | None:
    """把单轮判定结果落库(只升不降),返回线索 id;无信号时返回 None。

    写入规则:
    - qualifier 未运行且本轮未检出联系方式 → 不产生/不修改线索;
    - level=none 且既无旧线索也无联系方式 → 同上(避免普通咨询灌爆线索表);
    - invited(管线已按 One-Proactive-Ask 决策并内嵌邀请指令)→ 记账 prompt_count;
    - 联系方式:原文只入本表;已联系过的线索不覆盖既有联系方式。
    """
    if ctx is None or not lead_payload:
        return None
    contact_now: ContactHit | None = ctx.contact
    ran = bool(lead_payload.get("ran"))
    if not ran and contact_now is None:
        return None

    qual = _qualification_from_payload(lead_payload)
    fields_payload = (
        lead_payload.get("fields") if isinstance(lead_payload.get("fields"), dict) else {}
    )

    async with session_factory() as session:
        existing: SalesLead | None = None
        if ctx.lead_id is not None:
            existing = await session.get(SalesLead, ctx.lead_id)

        contact_present_before = bool(existing and existing.contact_value)
        # LEAD-G001:普通咨询(none 级、无既有线索、无联系方式)不产生线索行,
        # 避免线索列表被普通产品/价格咨询灌爆
        if existing is None and contact_now is None and qual.level == "none":
            return None
        status = compute_status(
            existing.status if existing else None,
            qual,
            contact_now=contact_now is not None or contact_present_before,
        )

        now = datetime.now(UTC)
        merged = _merge_fields(existing, fields_payload)
        summary = (lead_payload.get("summary") or "").strip()
        if not summary and existing is not None:
            summary = existing.ai_summary or ""
        if not summary and contact_now is not None:
            summary = f"用户在会话中提供了{contact_now.type}联系方式,暂无更多商业信息。"

        invited = bool(lead_payload.get("invited"))
        if existing is None:
            lead = SalesLead(
                session_id=session_id,
                status=status,
                source_conversation_id=conversation_id,
                last_conversation_id=conversation_id,
                channel=channel,
                language=language,
                country=country,
                prompt_count=1 if invited else 0,
                last_prompted_at=now if invited else None,
                ai_summary=summary or None,
                **{k: v for k, v in merged.items()},
            )
            if contact_now is not None:
                lead.contact_type = contact_now.type
                lead.contact_value = contact_now.value
                lead.contact_masked = contact_now.masked
                lead.contact_captured_at = now
            session.add(lead)
            await session.flush()
            await session.commit()
            return lead.id

        # 已有线索:更新(不降级;已有联系方式不覆盖)
        existing.status = status
        for key, value in merged.items():
            setattr(existing, key, value)
        if summary:
            existing.ai_summary = summary
        existing.last_conversation_id = conversation_id
        if channel:
            existing.channel = channel
        if language:
            existing.language = language
        if country:
            existing.country = country
        if invited:
            existing.prompt_count = (existing.prompt_count or 0) + 1
            existing.last_prompted_at = now
        if contact_now is not None and not contact_present_before:
            existing.contact_type = contact_now.type
            existing.contact_value = contact_now.value
            existing.contact_masked = contact_now.masked
            existing.contact_captured_at = now
        await session.commit()
        return existing.id
