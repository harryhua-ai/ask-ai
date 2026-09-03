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
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas import AskRequest, ClickRequest, FeedbackRequest
from backend.db.models import Attachment, Conversation, SourceClick, Trace
from backend.pipeline.lead_qualify import LeadTurnContext
from backend.pipeline.rag import EmptyGenerationError, RAGOrchestrator
from backend.services.attachments import (
    MAX_ATTACHMENTS_PER_MESSAGE,
    compute_storage_path,
    extract_log_text,
    sanitize_filename,
    validate_upload_file,
)
from backend.services.lead_service import apply_lead_turn, load_lead_context
from backend.services.site_experiences import (
    SiteDenied,
    extract_request_origin,
    resolve_site,
)
from backend.utils.budget import BudgetLimiter, estimate_tokens
from backend.utils.language import (
    conversation_language,
    normalize_language,
    resolve_answer_language,
)
from backend.utils.pii import mask_pii
from backend.utils.user_messages import (
    BUDGET_DECLINED_KEY,
    SERVICE_UNAVAILABLE_KEY,
    localized_message,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
limiter = Limiter(key_func=get_remote_address)

# 生成失败兜底文案(PC-02):冻结产品文案,经 user_messages 本地化表取值。
# 此常量保留 zh 形态供兼容引用;实际下发走 localized_message(key, language)。
SERVICE_UNAVAILABLE_MSG = localized_message(SERVICE_UNAVAILABLE_KEY, "zh")

# MSW:站点授权失败的对外统一文案(不区分未知站/禁用站/来源不匹配,防枚举)
SITE_DENIED_MSG = "站点未授权或来源不受信任"


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
        1. 保留原始消息(lead 联系方式检测用),PII 脱敏用户消息后进入管线。
        2. 构建 lead 上下文(会话既有线索 + 确定性联系方式检测,只读,fail-open)。
        3. S2 预算熔断:估算 prompt token + max_tokens(4096)预扣;
           超限时返回 ``declined`` 事件,不再调用 LLM。
        4. ``rag.stream_answer`` 产出 JSON 事件,逐条转为 SSE:
           - ``sources`` 事件 → 转发 ``sources`` SSE 事件。
           - ``token`` 事件 → 转发 ``token`` SSE 事件。
           - ``complete`` 事件 → 提取最终元数据(含可选 lead payload),不直接转发。
        5. 空结果(拒答)时 ``stream_answer`` 仅产一条 ``complete`` 事件;
           此处将拒答文本作为 ``token`` SSE 事件补发,保证客户端可见。
        5. 生成可靠性(PC-01/02/03):零可用内容完成、首 token 前异常、
           部分 token 后中断均视为异常完成 —— 补发失败文案 token(若无内容)
           并在 ``done`` 之前发 ``error`` SSE 事件(``kind`` 标注失败类别),
           持久化 ``is_answered=False`` + ``Trace(type=generation_error)``。
        6. 写入 Postgres conversations 表;lead 判定结果落 sales_leads(fail-open)。
        7. 发送 ``done`` SSE 事件,携带 ``conversation_id``。
    """
    raw_message = req.message
    masked_message = mask_pii(raw_message)

    # Sales Lead:单轮上下文(只读;任何异常 fail-open,不影响问答)
    lead_ctx: LeadTurnContext | None = None
    try:
        lead_ctx = await load_lead_context(
            session_factory,
            session_id=req.session_id,
            raw_question=raw_message,
            conversation_history=req.conversation_history,
        )
    except Exception:
        logger.exception("lead 上下文构建失败,本轮跳过 lead 处理")

    # MSW:站点门禁 —— 显式 site_id 必须通过「站点存在且 enabled + 请求 Origin
    # 精确命中」授权(CORS 仅为浏览器执行层,此处为服务端权威校验),否则
    # fail-safe 403,rag 不被调用、对话不落库。legacy(无 site_id)不校验。
    site = None
    if req.site_id:
        try:
            site = await resolve_site(session_factory, req.site_id, extract_request_origin(request))
        except SiteDenied:
            raise HTTPException(403, SITE_DENIED_MSG)

    # 地域:从 Accept-Language 提取地区码作为地域代理(无需 GeoIP 数据库)
    country: str | None = None
    accept_lang = request.headers.get("accept-language", "")
    for part in accept_lang.split(","):
        sub = part.strip().split(";")[0].split("-")
        if len(sub) == 2:
            country = sub[1].upper()
            break

    # 阶段⑯(语言前置):任何 user-visible fallback / Conversation 持久化
    # 之前,先用与 rag 相同的 authoritative resolver、相同输入确定性重算
    # 答案语言(resolve_answer_language 纯函数无 I/O,与 rag 内部值逐位
    # 相等,单一 authority 不破)——complete 前失败不再错落 language。
    language_hint = req.language or (site.language if site else None)
    answer_language = resolve_answer_language(masked_message, language_hint)
    conv_language = conversation_language(answer_language)

    # S2: 预算熔断 — 估算 prompt token + max_tokens 预扣
    est_input = estimate_tokens(masked_message) + sum(
        estimate_tokens(str(h.get("content", ""))) for h in req.conversation_history
    )
    if not budget.check_and_reserve(est_input + 4096):
        # 阶段⑯(Budget Declined HARD CONTRACT):declined 是真实 outcome
        # (DECLINED,非 generation error),必须持久化真实 Conversation,
        # 禁止幽灵 conversation_id;文案按解析语言本地化;
        # trace type=budget_declined,不污染 generation_error taxonomy。
        conversation_id = str(uuid.uuid4())
        busy_msg = localized_message(BUDGET_DECLINED_KEY, answer_language)
        # FINAL REVIEW Blocker A:仅当 Conversation 真实持久化成功,才允许把该 id
        # 作为 declined Conversation 身份下发;持久化失败 → 不下发任何身份
        # (诚实优于幽灵),DECLINED 用户语义与文案保持不变,绝不弱化持久化。
        declined_persisted = False
        try:
            async with session_factory() as session:
                session.add(
                    Conversation(
                        id=uuid.UUID(conversation_id),
                        question=masked_message,
                        answer=busy_msg,
                        channel=req.channel,
                        language=conv_language,
                        sources=[],
                        is_answered=False,
                        response_time_ms=0,
                        country=country,
                        site_id=req.site_id if site else None,
                        session_id=req.session_id,
                    )
                )
                session.add(
                    Trace(
                        conversation_id=uuid.UUID(conversation_id),
                        turn_index=0,
                        type="budget_declined",
                        stages={},
                        config_snapshot={"outcome": "declined"},
                    )
                )
                await session.commit()
                declined_persisted = True
        except Exception:
            logger.exception("budget declined 持久化失败, conversation_id=%s", conversation_id)

        declined_payload: dict[str, Any] = {
            "reason": busy_msg,
            "message_key": BUDGET_DECLINED_KEY,
        }
        done_payload: dict[str, Any] = {}
        if declined_persisted:
            declined_payload["conversation_id"] = conversation_id
            done_payload["conversation_id"] = conversation_id

        async def declined() -> Any:
            yield {"event": "declined", "data": json.dumps(declined_payload)}
            yield {"event": "done", "data": json.dumps(done_payload)}

        return EventSourceResponse(declined())

    # Phase 1a:附件加载 + 归属校验(同步返回 422/403,不进 SSE)
    attachment_objs: list[Attachment] = []
    if req.attachments:
        expected_owner = req.session_id or ""
        if req.channel == "widget" and not expected_owner:
            raise HTTPException(422, "session_id required for widget attachments")
        async with session_factory() as s:
            for att_id_str in req.attachments:
                try:
                    att_id = uuid.UUID(att_id_str)
                except ValueError:
                    raise HTTPException(422, f"Invalid attachment id: {att_id_str}")
                att = await s.get(Attachment, att_id)
                if not att:
                    raise HTTPException(422, f"Unknown attachment: {att_id_str}")
                # 归属校验:widget 用 session_id(admin 走 /api/admin/upload,owner_id=user.id,
                # 经 admin 鉴权端点单独处理;此处 widget 路径强制匹配 session_id)
                if att.owner_id != expected_owner:
                    raise HTTPException(403, "Attachment access denied")
                attachment_objs.append(att)

    async def event_generator() -> Any:
        conversation_id = str(uuid.uuid4())
        full_answer = ""
        sources: list = []
        is_answered = False
        # 阶段⑯:初始值即 authoritative 解析结果(此前恒 "en",complete 前
        # 失败会错落 language);complete 事件仍覆盖,值由同一 resolver 决定恒等。
        language = answer_language
        elapsed = 0
        token_emitted = False
        intent: str | None = None
        trace_payload: dict | None = None
        # 生成失败分类(PC-06,持久化与 error 事件共用):
        # - empty_generation: 流正常结束但零可用内容(含仅空白);
        # - provider_error: 首 token 前异常;
        # - stream_interrupted: 已产出部分 token 后异常。
        failure_kind: str | None = None
        lead_payload: dict | None = None

        try:
            async for chunk in rag.stream_answer(
                query=masked_message,
                channel=req.channel,
                conversation_history=req.conversation_history,
                attachments=attachment_objs or None,
                page_context=(
                    req.page_context.model_dump(exclude_none=True) if req.page_context else None
                ),
                site_name=site.display_name if site else None,
                lead_ctx=lead_ctx,
                # ML 闭环:请求 language 提示被消费为默认答案语境(G-L1);
                # 显式 site_id 未带提示时回落站点默认语言(宿主默认语境)
                language_hint=req.language or (site.language if site else None),
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
                    # FINAL REVIEW Blocker B:complete 缺 language 时回退到
                    # 前置权威解析值(绝不硬编码 "en" 覆写);有值时恒等
                    # (同一 resolver 同输入),语言算法仍单一。
                    language = data.get("language") or language
                    elapsed = data.get("response_time_ms", 0)
                    intent = data.get("intent")
                    trace_payload = data.get("trace_payload")
                    lead_payload = data.get("lead")
        except Exception as exc:
            # S5: LLM 流式生成中途异常(超时/网络错误)时,降级返回友好提示。
            # 200 响应头已发送,无法改写状态码,但通过 SSE token/error 事件通知客户端。
            logger.exception("SSE 流式生成异常, conversation_id=%s", conversation_id)
            if isinstance(exc, EmptyGenerationError):
                failure_kind = "empty_generation"
            else:
                failure_kind = "stream_interrupted" if token_emitted else "provider_error"

        # 用户可见内容发射(恰好一次,三选一互斥):
        # 1) 既有空结果契约:拒答文本(complete 且 is_answered=False)补发为 token;
        # 2) PC-01 零内容守护:流结束仍无可用内容 → 补发失败文案 token + error 事件;
        # 3) 正常回答/部分中断:token 已按原样转发,不重复发射(NA-04)。
        if not token_emitted and failure_kind is None and full_answer:
            yield {"event": "token", "data": json.dumps({"content": full_answer})}
        elif not full_answer.strip():
            # 阶段⑯:失败兜底文案按解析语言本地化(zh→中文,其余→英文冻结文案)
            failure_kind = failure_kind or "empty_generation"
            full_answer = localized_message(SERVICE_UNAVAILABLE_KEY, language)
            yield {"event": "token", "data": json.dumps({"content": full_answer})}

        # PC-02/PC-03:结构化失败信号,在 done 之前发出 —— 用户可见地
        # 区分「回答完成」与「生成失败/中断」;旧客户端忽略未知事件类型,
        # 行为退化为仅显示兜底 token 文本,仍满足可见失败要求。
        if failure_kind is not None:
            is_answered = False  # 失败绝不持久化为成功(NA-05)
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "kind": failure_kind,
                        # message 恒保留(旧客户端兼容);message_key 为
                        # 阶段⑯新增的可选结构化身份,新客户端可据此映射
                        "message": localized_message(SERVICE_UNAVAILABLE_KEY, language),
                        "message_key": SERVICE_UNAVAILABLE_KEY,
                    }
                ),
            }
            # 持久化可观测性(PC-06):复用 Trace 行区分 生成失败 与 拒答/成功,
            # 不扩表结构 —— type=generation_error,failure_kind 记入 config_snapshot。
            base = trace_payload or {}
            trace_payload = {
                **base,
                "type": "generation_error",
                "stages": {**base.get("stages", {}), "error": {"kind": failure_kind}},
                "total_ms": base.get("total_ms", elapsed),
                "config_snapshot": {
                    **base.get("config_snapshot", {}),
                    "failure_kind": failure_kind,
                },
            }

        # 持久化到 Postgres
        try:
            async with session_factory() as session:
                conv = Conversation(
                    id=uuid.UUID(conversation_id),
                    question=masked_message,
                    answer=full_answer,
                    channel=req.channel,
                    # 阶段⑯:新写入归一为 zh / en(冻结规则:中文→zh,其余→en)
                    language=conversation_language(language),
                    sources=sources,
                    is_answered=is_answered,
                    response_time_ms=elapsed,
                    intent_tag=intent,
                    country=country,
                    # MSW:仅记录已通过授权校验的站点标识(channel 语义不变)
                    site_id=req.site_id if site else None,
                    # 会话线程聚合(Lead 契约):跨轮 lead 状态读取的键
                    session_id=req.session_id,
                )
                session.add(conv)
                if trace_payload:
                    session.add(
                        Trace(
                            conversation_id=uuid.UUID(conversation_id),
                            turn_index=0,
                            type=trace_payload.get("type", "rag"),
                            stages=trace_payload.get("stages", {}),
                            total_ms=trace_payload.get("total_ms"),
                            intent=trace_payload.get("intent"),
                            confidence=trace_payload.get("confidence"),
                            config_snapshot=trace_payload.get("config_snapshot", {}),
                        )
                    )
                await session.commit()
        except Exception:
            logger.exception("写入 conversations 表失败, conversation_id=%s", conversation_id)

        # Sales Lead:判定结果落 sales_leads(fail-open;联系方式原文只入该表)
        if lead_payload is not None:
            try:
                await apply_lead_turn(
                    session_factory,
                    lead_ctx,
                    lead_payload,
                    conversation_id=uuid.UUID(conversation_id),
                    session_id=req.session_id,
                    channel=req.channel,
                    language=language,
                    country=country,
                )
            except Exception:
                logger.exception("sales_leads 写入失败, conversation_id=%s", conversation_id)

        yield {"event": "done", "data": json.dumps({"conversation_id": conversation_id})}

    return EventSourceResponse(event_generator())


@router.get("/widget/site-config")
async def widget_site_config(
    request: Request,
    session_factory: SessionFactoryDep,
    site_id: str = Query(min_length=1, max_length=100),
    language: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    """公开站点体验配置(MSW;Widget 启动时按 data-site-id 拉取)。

    与 /ask 同一套服务端 Origin 授权:站点存在且 enabled + 请求 Origin
    精确命中 allowed_origins;否则 403 统一文案。响应仅含体验字段,
    **不回** allowed_origins 等内部配置。

    ML 闭环(G-L5):可选 ``language`` 查询参数(归一化)选择 welcome /
    starters 的本地化变体;无该语言的变体时回落站点默认——站点身份
    (site_id / display_name)与语言无关,响应形状不变。
    """
    try:
        site = await resolve_site(session_factory, site_id, extract_request_origin(request))
    except SiteDenied:
        raise HTTPException(403, SITE_DENIED_MSG)
    normalized_language = normalize_language(language)
    return {
        "site_id": site.site_id,
        "display_name": site.display_name,
        "welcome": site.localized_welcome(normalized_language),
        "language": site.language,
        "starters": list(site.localized_starters(normalized_language)),
    }


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


# --------------------------------------------------------------------------- #
# POST /api/upload —— 聊天附件上传(Phase 1a:仅日志)
# --------------------------------------------------------------------------- #


def _attachments_base_dir() -> Path:
    """存储根目录(ATTACHMENTS_DIR 覆盖,默认 data/attachments)。"""
    import os

    return Path(os.environ.get("ATTACHMENTS_DIR", "data/attachments"))


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_attachments_widget(
    request: Request,
    background_tasks: BackgroundTasks,
    session_factory: SessionFactoryDep,
    session_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """widget 匿名上传:固定 owner_type=widget_anon,owner_id=session_id。"""
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(422, f"Too many files (max {MAX_ATTACHMENTS_PER_MESSAGE})")
    return await _do_upload(files, "widget_anon", session_id, background_tasks, session_factory)


async def _do_upload(
    files: list[UploadFile],
    owner_type: str,
    owner_id: str,
    background_tasks: BackgroundTasks,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """共享上传逻辑:校验 + 落盘 + DB + 异步提取。

    fail-open:单文件失败记录 ok=False,不阻塞其他文件;全部失败返回 422。
    """
    results: list[dict[str, Any]] = []
    base_dir = _attachments_base_dir()

    for f in files:
        first_bytes = await f.read(512)
        await f.seek(0)
        content = await f.read()
        ok, kind, mime, err = validate_upload_file(f.filename or "", first_bytes, len(content))
        if not ok:
            results.append({"ok": False, "filename": f.filename, "error": err})
            continue

        clean_name = sanitize_filename(f.filename or "upload")
        att = Attachment(
            id=uuid.uuid4(),
            owner_type=owner_type,
            owner_id=owner_id,
            filename=clean_name,
            mime_type=mime,
            kind=kind,
            size_bytes=len(content),
        )
        ext = Path(clean_name).suffix.lower()
        storage_path = compute_storage_path(att.id, ext, base_dir=str(base_dir))
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        att.storage_path = str(storage_path)

        if kind == "log":
            background_tasks.add_task(
                _extract_and_persist, att.id, str(storage_path), session_factory
            )
            status = "processing"
        else:
            status = "ready"  # 图片 1b 才启用(1a 校验已拒)

        async with session_factory() as s:
            s.add(att)
            await s.commit()

        results.append(
            {
                "ok": True,
                "id": str(att.id),
                "filename": att.filename,
                "kind": kind,
                "mime_type": mime,
                "size_bytes": att.size_bytes,
                "status": status,
            }
        )

    if all(not r["ok"] for r in results):
        raise HTTPException(422, "All files rejected")
    return {"attachments": results}


async def _extract_and_persist(
    att_id: uuid.UUID,
    storage_path: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """BackgroundTask:提取日志文本 + mask_pii + 写 extracted_text。

    两层 fail-open:提取异常 / 持久化异常都仅记录日志,extracted_text 留 None,
    ask 时该附件贡献空 log_text,不阻塞整次问答。
    """
    try:
        text, warning = extract_log_text(Path(storage_path))
        masked = mask_pii(text)
    except Exception as e:  # noqa: BLE001 — BackgroundTask 兜底
        logger.warning("log extract failed att=%s: %s", att_id, e)
        masked, warning = "", f"extract failed: {e}"
    try:
        async with session_factory() as s:
            att = await s.get(Attachment, att_id)
            if att:
                att.extracted_text = masked
                att.parse_warning = warning
                await s.commit()
    except Exception as e:  # noqa: BLE001 — BackgroundTask 兜底
        logger.warning("persist extracted_text failed att=%s: %s", att_id, e)
