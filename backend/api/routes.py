"""FastAPI API 路由定义。

三个端点:
- ``POST /api/ask`` —— SSE 流式问答,事件序列:``sources → token(s) → done``;
  空结果(拒答)时仍输出拒答文本作为 token 事件,最后发 ``done``。
- ``POST /api/feedback`` —— 记录对话反馈(up / down)。
- ``POST /api/click`` —— 记录来源点击。

所有端点在系统边界对输入做 Pydantic 校验;服务端异常由 FastAPI 统一处理。
"""

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas import AskRequest, ClickRequest, FeedbackRequest
from backend.db.models import Conversation, SourceClick
from backend.pipeline.rag import RAGOrchestrator
from backend.utils.budget import BudgetLimiter, estimate_tokens
from backend.utils.pii import mask_pii

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
limiter = Limiter(key_func=get_remote_address)


def get_rag(request: Request) -> RAGOrchestrator:
    """依赖:从 app.state 获取 RAGOrchestrator 实例。"""
    return request.app.state.rag


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """依赖:从 app.state 获取 Postgres 异步会话工厂。"""
    return request.app.state.session_factory


def get_budget(request: Request) -> BudgetLimiter:
    """依赖:从 app.state 获取预算熔断器(Task 21 S2)。"""
    return request.app.state.budget


# Annotated 依赖类型(Annotated 风格消除 ruff B008)
RAGDep = Annotated[RAGOrchestrator, Depends(get_rag)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
BudgetDep = Annotated[BudgetLimiter, Depends(get_budget)]


@router.post("/ask")
@limiter.limit("20/minute")
async def ask(
    req: AskRequest,
    request: Request,
    rag: RAGDep,
    session_factory: SessionFactoryDep,
    budget: BudgetDep,
) -> EventSourceResponse:
    """SSE 流式问答端点。

    流程:
        1. PII 脱敏用户消息。
        2. S2 预算熔断:估算 prompt token + max_tokens(4096)预扣;
           超限时返回 ``declined`` 事件,不再调用 LLM。
        3. ``rag.stream_answer`` 产出 JSON 事件,逐条转为 SSE:
           - ``sources`` 事件 → 转发 ``sources`` SSE 事件。
           - ``token`` 事件 → 转发 ``token`` SSE 事件。
           - ``complete`` 事件 → 提取最终元数据,不直接转发。
        4. 空结果(拒答)时 ``stream_answer`` 仅产一条 ``complete`` 事件;
           此处将拒答文本作为 ``token`` SSE 事件补发,保证客户端可见。
        5. 写入 Postgres conversations 表。
        6. 发送 ``done`` SSE 事件,携带 ``conversation_id``。
    """
    masked_message = mask_pii(req.message)

    # S2: 预算熔断 — 估算 prompt token + max_tokens 预扣
    est_input = estimate_tokens(masked_message) + sum(
        estimate_tokens(str(h.get("content", ""))) for h in req.conversation_history
    )
    if not budget.check_and_reserve(est_input + 4096):

        async def declined() -> Any:
            yield {"event": "declined", "data": json.dumps({"reason": "服务繁忙,请稍后再试"})}
            yield {"event": "done", "data": json.dumps({"conversation_id": str(uuid.uuid4())})}

        return EventSourceResponse(declined())

    async def event_generator() -> Any:
        conversation_id = str(uuid.uuid4())
        full_answer = ""
        sources: list = []
        is_answered = False
        language = "en"
        elapsed = 0
        token_emitted = False

        try:
            async for chunk in rag.stream_answer(
                query=masked_message,
                channel=req.channel,
                conversation_history=req.conversation_history,
            ):
                data = json.loads(chunk)
                evt_type = data["type"]
                if evt_type == "sources":
                    sources = data["sources"]
                    yield {
                        "event": "sources",
                        "data": json.dumps(
                            {"conversation_id": conversation_id, "sources": sources}
                        ),
                    }
                elif evt_type == "token":
                    token_emitted = True
                    full_answer += data["content"]
                    yield {"event": "token", "data": json.dumps({"content": data["content"]})}
                elif evt_type == "complete":
                    full_answer = data.get("answer", full_answer)
                    is_answered = data["is_answered"]
                    language = data.get("language", "en")
                    elapsed = data.get("response_time_ms", 0)
        except Exception:
            # S5: LLM 流式生成中途异常(超时/网络错误)时,降级返回友好提示。
            # 200 响应头已发送,无法改写状态码,但通过 SSE token 事件通知客户端。
            logger.exception("SSE 流式生成异常, conversation_id=%s", conversation_id)
            if not token_emitted:
                full_answer = "服务暂时不可用,请稍后再试。"
                yield {"event": "token", "data": json.dumps({"content": full_answer})}

        # 空结果契约:stream_answer 仅产 complete(is_answered=False)时,
        # 未发过 token 事件 —— 此处补发拒答文本,保证客户端可见
        if not token_emitted and full_answer:
            yield {"event": "token", "data": json.dumps({"content": full_answer})}

        # 持久化到 Postgres
        try:
            async with session_factory() as session:
                conv = Conversation(
                    id=uuid.UUID(conversation_id),
                    question=masked_message,
                    answer=full_answer,
                    channel=req.channel,
                    language=language,
                    sources=sources,
                    is_answered=is_answered,
                    response_time_ms=elapsed,
                )
                session.add(conv)
                await session.commit()
        except Exception:
            logger.exception("写入 conversations 表失败, conversation_id=%s", conversation_id)

        yield {"event": "done", "data": json.dumps({"conversation_id": conversation_id})}

    return EventSourceResponse(event_generator())


@router.post("/feedback")
async def feedback(
    req: FeedbackRequest,
    session_factory: SessionFactoryDep,
) -> dict[str, str]:
    """记录用户对某次对话的反馈(up / down)。"""
    async with session_factory() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(req.conversation_id))
            .values(feedback=req.feedback)
        )
        await session.commit()
    return {"status": "ok"}


@router.post("/click")
async def click(
    req: ClickRequest,
    session_factory: SessionFactoryDep,
) -> dict[str, str]:
    """记录用户对某条来源 URL 的点击。"""
    async with session_factory() as session:
        click_log = SourceClick(
            conversation_id=uuid.UUID(req.conversation_id),
            source_url=req.source_url,
            source_type=req.source_type,
            product=req.product,
        )
        session.add(click_log)
        await session.commit()
    return {"status": "ok"}
