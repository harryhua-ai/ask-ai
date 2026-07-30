"""LLM 供应商 CRUD + 路由 + 连通性测试端点。

viewer+ 可读取 LLM 供应商与路由;admin / editor 可写入。
所有端点从 ``request.app.state.session_factory`` 获取异步会话,
不依赖全局 DB 单例,便于测试隔离。

api_key 安全:
    - ``_mask_config`` 将响应中的 api_key / secret / token / password 替换为 ``********``
    - ``_encrypt_sensitive`` 在写入 DB 前对敏感字段 Fernet 加密
    - 连通性测试端点在调用 LLMRegistry 前解密 api_key
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    ConnectivityTestResult,
    LLMProviderCreate,
    LLMProviderOut,
    LLMProviderUpdate,
    LLMRoutingOut,
    LLMRoutingUpdate,
)
from backend.auth.crypto import decrypt_api_key, encrypt_api_key
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import LLMProviderModel, LLMRouting
from backend.llm.registry import LLMRegistry

router = APIRouter(tags=["LLM 供应商管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

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
    encrypted_config = _encrypt_sensitive(req.config, settings.encryption_key)
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
        id=req.id, type=req.type, enabled=req.enabled, config=_mask_config(req.config)
    )


@router.patch("/llm-providers/{provider_id}", response_model=LLMProviderOut)
async def update_provider(
    provider_id: str, req: LLMProviderUpdate, _: EditorDep, request: Request
) -> LLMProviderOut:
    """更新 LLM 供应商字段(admin / editor),仅写入非 None 字段。

    若传入 config,会与已有 config 浅合并后整体加密回写。
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
            merged = {**provider.config, **req.config}
            provider.config = _encrypt_sensitive(merged, settings.encryption_key)
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
        if route:
            route.chain = req.chain
        else:
            session.add(LLMRouting(task=task, chain=req.chain))
        await session.commit()
    return {"status": "ok"}


@router.post("/llm-providers/{provider_id}/test", response_model=ConnectivityTestResult)
async def test_provider(provider_id: str, _: EditorDep, request: Request) -> ConnectivityTestResult:
    """对指定 LLM 供应商执行连通性测试(admin / editor)。

    在调用 LLMRegistry 前先解密 DB 中的 api_key;
    测试结果返回 success / latency_ms / error,不泄露 api_key。
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
            pass  # 可能是明文(旧数据),保持原样继续尝试

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
    except Exception as exc:  # noqa: BLE001 - 连通性测试需兜底所有异常并返回结构化结果
        return ConnectivityTestResult(
            provider_id=provider_id, success=False, latency_ms=None, error=str(exc)
        )
