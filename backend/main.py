"""Ask AI FastAPI 应用入口。

在 lifespan 中完成全栈接线:
    Postgres → Weaviate → BGEEmbedder/BGEReranker → LLMRegistry/LLMRouter
    → HybridSearcher → RerankPipeline → RAGOrchestrator → app.state

路由注册:
    - ``GET  /health`` —— 健康检查
    - ``POST /api/ask`` —— SSE 流式问答
    - ``POST /api/feedback`` —— 对话反馈
    - ``POST /api/click`` —— 来源点击

安全加固(Task 21):
    - S2 预算熔断器(BudgetLimiter)接入 app.state
    - S4 GITHUB_TOKEN 最小权限校验
    - S5 全局异常 handler 不回显堆栈 / 安全响应头 / CORS 白名单 / debug 受控
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
import weaviate
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

# 导入 connector 实现以触发 @ConnectorRegistry.register
import backend.connectors.filesystem
import backend.connectors.github

# 导入 LLM provider 以触发 @LLMRegistry.register
import backend.llm.deepseek  # noqa: F401
from backend.api.admin.router import admin_router
from backend.api.routes import router as api_router
from backend.auth.crypto import decrypt_api_key
from backend.config import load_settings, load_yaml_config
from backend.db.session import get_engine, get_session_factory, init_db
from backend.embedder.bge import BGEEmbedder, BGEReranker
from backend.llm.registry import LLMRegistry, LLMRouter
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import HybridSearcher
from backend.services.config_loader import load_llm_config_from_db
from backend.utils.budget import BudgetConfig, BudgetLimiter

logger = logging.getLogger(__name__)
load_dotenv()
settings = load_settings()

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


def _parse_weaviate_url(url: str) -> tuple[str, int]:
    """从 Weaviate URL 解析 host 与 port。

    使用 ``urllib.parse.urlparse`` 做健壮解析,避免脆弱的字符串 split。

    Args:
        url: Weaviate HTTP URL,如 ``http://localhost:8080``。

    Returns:
        ``(host, port)`` 元组。端口缺失时回退到 8080。
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080
    return host, port


def _build_llm_router(config_dir: Path) -> LLMRouter:
    """从 YAML 配置构造 LLMRouter。

    YAML routing 结构为 ``{task: {chain: [provider_id, ...]}}``,
    需展平为 ``{task: [provider_id, ...]}`` 以匹配 LLMRouter 契约。

    Args:
        config_dir: 配置目录路径。

    Returns:
        配置好的 :class:`LLMRouter` 实例。
    """
    llm_config = load_yaml_config(config_dir / "llm_providers.yaml")
    providers = {}
    for prov in llm_config["providers"]:
        if not prov.get("enabled", True):
            continue
        cfg = prov["config"]
        provider = LLMRegistry.create(
            prov["type"],
            provider_id=prov["id"],
            api_base=cfg["api_base"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            max_tokens=cfg.get("max_tokens", 4096),
            temperature=cfg.get("temperature", 0.3),
        )
        providers[prov["id"]] = provider

    # 展平 routing: {task: {"chain": [...]}} → {task: [...]}
    raw_routing = llm_config.get("routing", {})
    routing = {
        task: (cfg.get("chain", []) if isinstance(cfg, dict) else cfg)
        for task, cfg in raw_routing.items()
    }
    return LLMRouter(providers, routing)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期:启动时接线,关闭时释放资源。"""
    logging.basicConfig(level=settings.log_level)
    logger.info("Ask AI 后端启动中...")
    app.state.settings = settings

    try:
        # Postgres
        engine = get_engine(settings.postgres_dsn)
        await init_db(engine)
        app.state.session_factory = get_session_factory(engine)

        # Seed: 确保 default customization + widget 绑定存在
        from backend.auth.crypto import encrypt_api_key
        from backend.auth.jwt import hash_password
        from backend.db.models import (
            Customization, CustomizationBinding, LLMProviderModel, LLMRouting, User,
        )
        from sqlalchemy import select as sa_select

        prompt_cfg = load_yaml_config(settings.config_dir / "system_prompt.yaml")
        async with app.state.session_factory() as session:
            # Admin 用户
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@camthink.ai")
            existing_admin = (await session.execute(
                sa_select(User).where(User.email == admin_email)
            )).scalar_one_or_none()
            if not existing_admin:
                session.add(User(
                    email=admin_email,
                    role="admin",
                    password_hash=hash_password(os.environ.get("ADMIN_PASSWORD", "admin123")),
                ))
                logger.info("已创建 admin 用户: %s", admin_email)

            # Default customization + widget 绑定
            if not await session.get(Customization, "default"):
                session.add(Customization(
                    id="default",
                    name="默认配置",
                    system_prompt=prompt_cfg["system_prompt"],
                    language=prompt_cfg.get("language", "auto"),
                    assistant_name=prompt_cfg.get("assistant_name", "CamThink 助手"),
                ))
                session.add(CustomizationBinding(
                    channel="widget",
                    customization_id="default",
                ))
                logger.info("已创建 default customization + widget 绑定")
            await session.commit()

        # Seed: 将 YAML 中的 LLM 供应商 + 路由迁移到 DB(首次启动时)
        llm_yaml = load_yaml_config(settings.config_dir / "llm_providers.yaml")
        async with app.state.session_factory() as session:
            for prov in llm_yaml.get("providers", []):
                if not prov.get("enabled", True):
                    continue
                if await session.get(LLMProviderModel, prov["id"]):
                    continue
                cfg = dict(prov["config"])
                if cfg.get("api_key"):
                    cfg["api_key"] = encrypt_api_key(cfg["api_key"], settings.encryption_key)
                session.add(LLMProviderModel(
                    id=prov["id"],
                    type=prov["type"],
                    enabled=prov.get("enabled", True),
                    config=cfg,
                ))
            for task, cfg in llm_yaml.get("routing", {}).items():
                chain = cfg.get("chain", []) if isinstance(cfg, dict) else cfg
                if await session.get(LLMRouting, task):
                    continue
                session.add(LLMRouting(task=task, chain=chain))
            await session.commit()
            logger.info("LLM 供应商 + 路由已迁移到 DB")

        # Weaviate
        weaviate_host, weaviate_port = _parse_weaviate_url(settings.weaviate_url)
        weaviate_client = weaviate.connect_to_local(host=weaviate_host, port=weaviate_port)

        # Embedder + Reranker
        embedder = BGEEmbedder(
            device=settings.embedder_device,
            batch_size=settings.embedder_batch_size,
            max_length=settings.embedder_max_length,
        )
        reranker = BGEReranker(device=settings.embedder_device)
        app.state.embedder = embedder
        app.state.reranker = reranker
        app.state.weaviate_class_name = settings.weaviate_class_name

        # LLM:优先从 DB 加载(Task 16),为空时回退 YAML(Phase 1 兼容)
        db_config = await load_llm_config_from_db(app.state.session_factory)
        if db_config:
            providers_list, routing_dict = db_config
            providers: dict[str, object] = {}
            settings_enc = settings.encryption_key
            for prov in providers_list:
                cfg = dict(prov["config"])
                if cfg.get("api_key"):
                    try:
                        cfg["api_key"] = decrypt_api_key(cfg["api_key"], settings_enc)
                    except ValueError:
                        pass  # 旧数据可能是明文,保持原样继续尝试
                try:
                    provider = LLMRegistry.create(
                        prov["type"],
                        provider_id=prov["id"],
                        api_base=cfg.get("api_base", ""),
                        api_key=cfg.get("api_key", ""),
                        model=cfg.get("model", ""),
                        max_tokens=cfg.get("max_tokens", 4096),
                        temperature=cfg.get("temperature", 0.3),
                    )
                except Exception:
                    # 单个供应商构造失败(未注册的 type / 配置非法)不阻塞启动,
                    # 跳过该供应商,其余正常加载。
                    logger.exception(
                        "LLM 供应商构造失败,已跳过: id=%s type=%s",
                        prov["id"],
                        prov["type"],
                    )
                    continue
                providers[prov["id"]] = provider
            router_llm = LLMRouter(providers, routing_dict)
            logger.info("LLM 配置已从 DB 加载(%d 个供应商)", len(providers))
        else:
            router_llm = _build_llm_router(settings.config_dir)
            logger.info("LLM 配置已从 YAML 加载(DB 为空)")
        app.state.llm = router_llm

        # System prompt
        prompt_config = load_yaml_config(settings.config_dir / "system_prompt.yaml")

        # Customization(Phase 2B):从 DB 加载按渠道的 system_prompt,
        # 失败 / 为空时回退到 YAML(Phase 1 兼容)。widget 渠道必须有可用 prompt。
        from backend.services.config_loader import load_customizations_from_db

        channel_custs = await load_customizations_from_db(app.state.session_factory)
        if channel_custs:
            system_prompt = channel_custs.get("widget", {}).get(
                "system_prompt", prompt_config["system_prompt"]
            )
            channel_customizations: dict[str, str] | None = {
                ch: c["system_prompt"] for ch, c in channel_custs.items()
            }
        else:
            system_prompt = prompt_config["system_prompt"]
            channel_customizations = None

        # RAG
        searcher = HybridSearcher(weaviate_client, embedder, settings.weaviate_class_name)
        rerank_pipeline = RerankPipeline(reranker)

        # Pruner(Phase 3A):检查 routing 中是否有 "pruning" task
        pruner = None
        routing_for_pruning = routing_dict.get("pruning", []) if db_config else []
        if routing_for_pruning and any(pid in providers for pid in routing_for_pruning):
            from backend.pipeline.pruner import LLMPruner

            pruner = LLMPruner(router_llm)
            logger.info("Pruner 已启用(task=pruning)")

        # OverrideMatcher(Phase 3A):人工答案覆盖匹配
        from backend.services.override_matcher import OverrideMatcher

        override_matcher = OverrideMatcher(app.state.session_factory, embedder)
        await override_matcher.refresh()
        app.state.override_matcher = override_matcher
        logger.info("OverrideMatcher 已加载(%d 条覆盖)", len(override_matcher._overrides))

        app.state.rag = RAGOrchestrator(
            searcher=searcher,
            reranker=rerank_pipeline,
            llm=router_llm,
            system_prompt=system_prompt,
            channel_customizations=channel_customizations,
            intent_styles=prompt_config.get("intent_styles", {}),
            pruner=pruner,
            override_matcher=override_matcher,
        )
        app.state.weaviate_client = weaviate_client
        app.state.engine = engine

        # ClusteringService(Phase 3B):问题聚类
        # 依赖 session_factory 与 embedder,两者在 RAG 之前已就绪;
        # 放在 engine 赋值之后、S2 预算熔断器之前,保持"RAG → 分析"的逻辑相邻。
        from backend.services.clustering import ClusteringService

        clustering = ClusteringService(app.state.session_factory, embedder)
        app.state.clustering = clustering

        # S2: 预算熔断器(每日 LLM 调用 / token 上限,超阈熔断)
        budget_cfg = BudgetConfig(
            daily_request_limit=int(os.environ.get("BUDGET_DAILY_REQUESTS", "500")),
            daily_token_limit=int(os.environ.get("BUDGET_DAILY_TOKENS", "2000000")),
        )
        app.state.budget = BudgetLimiter(budget_cfg)

        # S4: GITHUB_TOKEN 最小权限校验(prod 严格,dev 仅 warn)
        from backend.connectors.github import validate_github_token

        validate_github_token(
            os.environ.get("GITHUB_TOKEN", ""),
            strict=os.environ.get("APP_MODE", "dev") == "prod",
        )

        logger.info("Ask AI 后端就绪")
        yield
    finally:
        # 资源释放:每步独立 guard,确保单个关闭失败不阻塞后续清理。
        # 覆盖两种场景:(1) 启动中途抛异常 → 已建立的连接仍能释放;
        #             (2) 正常关闭时 weaviate/engine 抛异常互不影响。
        try:
            weaviate_client.close()
        except Exception:
            logger.exception("Weaviate 连接关闭失败")
        try:
            await engine.dispose()
        except Exception:
            logger.exception("Postgres engine dispose 失败")
        logger.info("Ask AI 后端关闭")


# S5: 生产配置加固 —— debug / docs 受 FASTAPI_DEBUG 控制(默认 false)
_debug = os.environ.get("FASTAPI_DEBUG", "false").lower() == "true"
app = FastAPI(
    title="Ask AI",
    lifespan=lifespan,
    debug=_debug,
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# S5: 安全响应头 + 全局异常兜底(异常不回显堆栈,仅记录日志)。
# 注:Starlette 的 ServerErrorMiddleware 即使处理了异常也会 re-raise 给上层,
# 导致 ASGI 客户端看到的是 exception 而非 500 响应。在此层 catch 后直接返回
# JSONResponse,确保客户端拿到安全的降级响应。
@app.middleware("http")
async def _security_and_error_handler(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception on %s", request.url.path)
        response = JSONResponse(status_code=500, content={"detail": "内部服务错误"})
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# S5: CORS 白名单(env 控制,默认仅本地开发站点;不再用 "*")
_cors = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:1313,http://localhost:5173"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(api_router)
app.include_router(admin_router)

# Task 21: 生产部署 — 在 /admin 路径下托管 admin SPA 构建产物。
# _admin_dist 存在时挂载 StaticFiles;对未匹配的子路径(如 /admin/users)
# 回退到 index.html,使 SPA 深链刷新不会 404。
_admin_dist = Path(__file__).resolve().parent.parent / "admin" / "dist"


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for unknown paths.

    ``StaticFiles(html=True)`` 仅在挂载根路径返回 index.html,
    对 ``/admin/users`` 等 SPA 前端路由刷新时会抛 404。
    本子类捕获异常并回退到 index.html,由前端路由接管。
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException):
            return await super().get_response("index.html", scope)


if _admin_dist.exists():
    app.mount(
        "/admin",
        SPAStaticFiles(directory=str(_admin_dist), html=True),
        name="admin",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查端点,供编排系统探活。"""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
