"""LLM 供应商 CRUD + 路由 + 连通性测试端点。

viewer+ 可读取 LLM 供应商与路由;admin / editor 可写入。
所有端点从 ``request.app.state.session_factory`` 获取异步会话,
不依赖全局 DB 单例,便于测试隔离。

api_key 安全:
    - ``_mask_config`` 将响应中的 api_key / secret / token / password 替换为 ``"********"``
    - ``_encrypt_sensitive`` 在写入 DB 前对敏感字段 Fernet 加密
    - 连通性测试端点在调用 LLMRegistry 前解密 api_key
    - PATCH config 时仅加密新传入的敏感字段,保留 DB 中已加密的旧值
      (避免对密文二次加密 / 用 "********" 占位符覆盖真实密文)
    - 连通性测试异常返回脱敏的通用错误消息,完整异常仅 server-side 记录
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    ConnectivityTestResult,
    FetchModelsRequest,
    LLMProviderCreate,
    LLMProviderOut,
    LLMProviderUpdate,
    LLMRoutingOut,
    LLMRoutingUpdate,
    validate_llm_api_base,
)
from backend.auth.crypto import decrypt_api_key, encrypt_api_key
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import LLMProviderModel, LLMRouting
from backend.llm.registry import LLMRegistry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LLM 供应商管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@router.get("/local-models")
async def list_local_models(_: ViewerDep, request: Request) -> list[dict]:
    """返回本地加载的嵌入模型与重排序模型信息(viewer+ 可访问)。"""
    models: list[dict] = []
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is not None:
        models.append(
            {
                "role": "embedding",
                "model_name": getattr(embedder, "_model_name", "BAAI/bge-m3"),
                "device": getattr(embedder, "_device", "unknown"),
                "dimension": getattr(embedder, "_dimension", 1024),
            }
        )
    reranker = getattr(request.app.state, "reranker", None)
    if reranker is not None:
        models.append(
            {
                "role": "reranking",
                "model_name": getattr(reranker, "_model_name", "BAAI/bge-reranker-v2-m3"),
                "device": getattr(reranker, "_device", "unknown"),
            }
        )
    return models


# 所有需要在响应中脱敏、在写入时加密的敏感字段名
SENSITIVE_KEYS = {"api_key", "secret", "token", "password"}


def _mask_config(config: dict) -> dict:
    """脱敏 config 中的 api_key 等敏感字段,返回新 dict。

    非敏感字段原样保留;敏感字段有值时替换为 ``"********"``,空值替换为空串。
    """
    masked: dict = {}
    for k, v in config.items():
        if k in SENSITIVE_KEYS:
            masked[k] = "********" if v else ""
        else:
            masked[k] = v
    return masked


def _encrypt_sensitive(config: dict, encryption_key: str) -> dict:
    """加密 config 中的敏感字段,返回新 dict。

    跳过空值与已脱敏的占位值 ``"********"``,避免把占位符当明文加密回写。
    """
    encrypted: dict = {}
    for k, v in config.items():
        if k in SENSITIVE_KEYS and v and v != "********":
            encrypted[k] = encrypt_api_key(str(v), encryption_key)
        else:
            encrypted[k] = v
    return encrypted


@router.get("/llm-providers", response_model=list[LLMProviderOut])
async def list_providers(_: ViewerDep, request: Request) -> list[LLMProviderOut]:
    """列出全部 LLM 供应商(viewer+ 可访问),按 id 排序,api_key 已脱敏。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(LLMProviderModel).order_by(LLMProviderModel.id))
        providers = result.scalars().all()
    return [
        LLMProviderOut(id=p.id, type=p.type, enabled=p.enabled, config=_mask_config(p.config))
        for p in providers
    ]


@router.post("/llm-providers", response_model=LLMProviderOut, status_code=201)
async def create_provider(req: LLMProviderCreate, _: EditorDep, request: Request) -> LLMProviderOut:
    """创建 LLM 供应商(admin / editor),ID 重复返回 409。

    请求体中的明文 api_key 在写入 DB 前会被 Fernet 加密,
    响应中返回脱敏后的 ``"********"`` 占位符。
    """
    settings = request.app.state.settings
    encrypted_config = _encrypt_sensitive(req.config.model_dump(), settings.encryption_key)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == req.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="供应商 ID 已存在")
        provider = LLMProviderModel(
            id=req.id, type=req.type, enabled=req.enabled, config=encrypted_config
        )
        session.add(provider)
        await session.commit()
    return LLMProviderOut(
        id=req.id, type=req.type, enabled=req.enabled, config=_mask_config(req.config.model_dump())
    )


@router.patch("/llm-providers/{provider_id}", response_model=LLMProviderOut)
async def update_provider(
    provider_id: str, req: LLMProviderUpdate, _: EditorDep, request: Request
) -> LLMProviderOut:
    """更新 LLM 供应商字段(admin / editor),仅写入非 None 字段。

    config 合并语义(防止 api_key 损坏):
      - 仅加密 req.config 中**新传入**的敏感字段(明文 → 密文)
      - 丢弃 req.config 中值为 ``"********"`` 的敏感字段(前端回显占位符 → 保留 DB 旧密文)
      - 再与 provider.config 浅合并,确保未改动的敏感字段保持原密文不变

    不存在返回 404。
    """
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
        )
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if req.type:
            provider.type = req.type
        if req.enabled is not None:
            provider.enabled = req.enabled
        if req.config:
            # 仅加密新传入的敏感字段;"********" 占位符会被 _encrypt_sensitive 原样保留,
            # 随后在此处被剔除,避免用占位符覆盖 DB 中的真实密文。
            # exclude_unset=True：只取客户端显式传入的字段，避免默认值覆盖 DB 原值（部分更新语义）
            new_encrypted = _encrypt_sensitive(
                req.config.model_dump(exclude_unset=True), settings.encryption_key
            )
            new_encrypted = {
                k: v
                for k, v in new_encrypted.items()
                if not (k in SENSITIVE_KEYS and (v == "********" or v == ""))
            }
            provider.config = {**provider.config, **new_encrypted}
        await session.commit()
        await session.refresh(provider)
    return LLMProviderOut(
        id=provider.id,
        type=provider.type,
        enabled=provider.enabled,
        config=_mask_config(provider.config),
    )


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, _: EditorDep, request: Request) -> None:
    """删除 LLM 供应商(admin / editor)。不存在返回 404。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
        )
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        await session.delete(provider)
        await session.commit()


@router.get("/llm-routing", response_model=list[LLMRoutingOut])
async def list_routing(_: ViewerDep, request: Request) -> list[LLMRoutingOut]:
    """列出全部 LLM 路由(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(LLMRouting))
        routes = result.scalars().all()
    return [LLMRoutingOut(task=r.task, chain=list(r.chain)) for r in routes]


@router.put("/llm-routing/{task}")
async def update_routing(
    task: str, req: LLMRoutingUpdate, _: EditorDep, request: Request
) -> dict[str, str]:
    """更新指定任务的 LLM 路由链路(admin / editor)。

    若任务不存在则创建,存在则覆盖。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        route = await session.execute(select(LLMRouting).where(LLMRouting.task == task))
        route = route.scalar_one_or_none()
        # Pydantic 对象转 dict 才能写 JSONB
        chain = [item.model_dump() for item in req.chain]
        if route:
            route.chain = chain
        else:
            session.add(LLMRouting(task=task, chain=chain))
        await session.commit()
    return {"status": "ok"}


@router.post("/llm-providers/{provider_id}/test", response_model=ConnectivityTestResult)
async def test_provider(provider_id: str, _: EditorDep, request: Request) -> ConnectivityTestResult:
    """对指定 LLM 供应商执行连通性测试(admin / editor)。

    在调用 LLMRegistry 前先解密 DB 中的 api_key;
    测试结果返回 success / latency_ms / error,不泄露 api_key 或内部异常细节。
    异常的完整堆栈仅记录到服务端日志,响应中只返回脱敏的通用错误消息。
    """
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
        )
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")

    config = dict(provider.config)
    if config.get("api_key"):
        try:
            config["api_key"] = decrypt_api_key(config["api_key"], settings.encryption_key)
        except ValueError:
            logger.warning("api_key 解密失败，按明文兼容继续: provider_id=%s", provider_id)

    # 与 fetch-models 相同：连通性测试也会携带解密后的 key，请求前必须防 SSRF
    try:
        validate_llm_api_base(config.get("api_base", ""))
    except ValueError:
        logger.warning("test_provider api_base 校验失败: provider_id=%s", provider_id)
        return ConnectivityTestResult(
            provider_id=provider_id,
            success=False,
            latency_ms=None,
            error="api_base 校验失败",
        )

    try:
        start = time.monotonic()
        llm = LLMRegistry.create(
            provider.type,
            provider_id=provider.id,
            api_base=config.get("api_base", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            max_tokens=config.get("max_tokens", 100),
            temperature=config.get("temperature", 0.1),
        )
        ok = await llm.health_check()
        latency = int((time.monotonic() - start) * 1000)
        return ConnectivityTestResult(
            provider_id=provider_id, success=ok, latency_ms=latency, error=None
        )
    except Exception:  # 连通性测试需兜底所有异常并返回结构化结果
        # 完整异常仅记录到服务端日志(可能含 URL / auth header,不可外泄)
        logger.exception("LLM 连通性测试失败: provider_id=%s", provider_id)
        # 返回脱敏的通用错误消息 + 异常类型名,绝不外泄 str(exc)
        return ConnectivityTestResult(
            provider_id=provider_id,
            success=False,
            latency_ms=None,
            error="LLM 连通性测试失败（详见服务端日志）",
        )


@router.post("/llm-providers/reload")
async def reload_providers(_: EditorDep, request: Request) -> dict:
    """从 DB 重读供应商/路由，调 app.state.llm.reconfigure 热重载。

    DB 全空时返回 400（避免清空线上 router）。
    单个 provider 构造失败记 skipped，不影响整体 reload。
    """
    # 函数级 import 避免循环依赖（main.py 已 import 本模块）
    from backend.main import _build_llm_state

    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory

    providers, routing, skipped, _ = await _build_llm_state(settings, factory)
    if not providers:
        raise HTTPException(
            status_code=400,
            detail="无可启用的供应商，reload 已取消（保留现有配置）",
        )

    request.app.state.llm.reconfigure(providers, routing)
    logger.info("LLM 已热重载（%d 个供应商，跳过 %d 个）", len(providers), len(skipped))
    return {
        "status": "ok",
        "providers_count": len(providers),
        "routing": routing,
        "skipped": skipped,
    }


@router.post("/llm-providers/{provider_id}/fetch-models")
async def fetch_models(
    provider_id: str,
    _: EditorDep,
    request: Request,
    req: FetchModelsRequest | None = None,
) -> dict:
    """调供应商 GET /models 拉取可用模型列表。

    body 可选携带表单未保存的 api_base/api_key(T27):非空值优先生效,空值回退
    DB 已存凭证;生效 api_base 复用 validate_llm_api_base(SSRF 边界不放宽)。
    失败返回脱敏错误（不泄露 key/内部异常，同 test 端点策略）。
    """
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
        )
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")

    config = dict(provider.config)

    # 表单值优先(T27):body 非空字段生效,空值回退 DB 凭证
    form_api_base = (req.api_base or "").strip() if req else ""
    form_api_key = (req.api_key or "").strip() if req else ""
    eff_api_base = form_api_base or config.get("api_base", "")
    if form_api_key:
        eff_api_key = form_api_key
    elif config.get("api_key"):
        try:
            eff_api_key = decrypt_api_key(config["api_key"], settings.encryption_key)
        except ValueError:
            logger.warning("api_key 解密失败，按明文兼容继续: provider_id=%s", provider_id)
            eff_api_key = config["api_key"]
    else:
        eff_api_key = ""

    # revalidate api_base：防绕过 schema 直接改库/表单乱填后的 SSRF / 凭证外泄
    try:
        validate_llm_api_base(eff_api_base)
    except ValueError:
        logger.warning("fetch_models api_base 校验失败: provider_id=%s", provider_id)
        return {"provider_id": provider_id, "models": [], "error": "api_base 校验失败"}

    try:
        llm = LLMRegistry.create(
            provider.type,
            provider_id=provider.id,
            api_base=eff_api_base,
            api_key=eff_api_key,
            model=config.get("model", ""),
        )
        models = await llm.list_models()
        return {"provider_id": provider_id, "models": models, "error": None}
    except Exception:
        logger.exception("拉取模型失败: provider_id=%s", provider_id)
        return {
            "provider_id": provider_id,
            "models": [],
            "error": "拉取模型失败（详见服务端日志）",
        }
