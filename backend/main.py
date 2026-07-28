"""Ask AI FastAPI 应用入口。

在 lifespan 中完成全栈接线:
    Postgres → Weaviate → BGEEmbedder/BGEReranker → LLMRegistry/LLMRouter
    → HybridSearcher → RerankPipeline → RAGOrchestrator → app.state

路由注册:
    - ``GET  /health`` —— 健康检查
    - ``POST /api/ask`` —— SSE 流式问答
    - ``POST /api/feedback`` —— 对话反馈
    - ``POST /api/click`` —— 来源点击
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import uvicorn
import weaviate
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# 导入 connector 实现以触发 @ConnectorRegistry.register
import backend.connectors.filesystem
import backend.connectors.github  # noqa: F401
from backend.api.routes import router as api_router
from backend.config import load_settings, load_yaml_config
from backend.db.session import get_engine, get_session_factory, init_db
from backend.embedder.bge import BGEEmbedder, BGEReranker
from backend.llm.registry import LLMRegistry, LLMRouter
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import HybridSearcher

logger = logging.getLogger(__name__)
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


def _build_llm_router(config_dir) -> LLMRouter:
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

    # Postgres
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    app.state.session_factory = get_session_factory(engine)

    # Weaviate
    weaviate_host, weaviate_port = _parse_weaviate_url(settings.weaviate_url)
    weaviate_client = weaviate.connect_to_local(host=weaviate_host, port=weaviate_port)

    # Embedder + Reranker
    embedder = BGEEmbedder(device=settings.embedder_device)
    reranker = BGEReranker(device=settings.embedder_device)

    # LLM
    router_llm = _build_llm_router(settings.config_dir)

    # System prompt
    prompt_config = load_yaml_config(settings.config_dir / "system_prompt.yaml")

    # RAG
    searcher = HybridSearcher(weaviate_client, embedder, settings.weaviate_class_name)
    rerank_pipeline = RerankPipeline(reranker)
    app.state.rag = RAGOrchestrator(
        searcher=searcher,
        reranker=rerank_pipeline,
        llm=router_llm,
        system_prompt=prompt_config["system_prompt"],
    )
    app.state.weaviate_client = weaviate_client
    app.state.engine = engine

    logger.info("Ask AI 后端就绪")
    yield

    weaviate_client.close()
    await engine.dispose()
    logger.info("Ask AI 后端关闭")


app = FastAPI(title="Ask AI", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查端点,供编排系统探活。"""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
