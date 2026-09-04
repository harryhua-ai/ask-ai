"""内部嵌入端点(sync 执行面消费 backend 单一驻留嵌入运行时)。

- 路径:POST /api/internal/embeddings(HMAC 内部令牌,见 runtime.internal_auth);
- 语义:workload=sync_embedding → 复用 backend 的单一驻留嵌入实例(§6 单一
  驻留不变量);GPU→CPU 单向回退在服务端完成,响应如实携带
  execution_device / fallback 事实(供 W2 SyncRun 运行事实记录);
- 有界性:批次 ≤ EMBEDDER_BATCH_SIZE、单文本 ≤ EMBEDDER_MAX_LENGTH 字符,
  越界 422/413 显式拒绝;GPU 并发由 Manager 信号量有界(在线查询优先);
- 授权:仅内部令牌;不授予任何其他能力,site/来源授权语义零触碰。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.runtime.internal_auth import verify_internal_token
from backend.runtime.manager import WORKLOAD_SYNC_EMBEDDING

router = APIRouter(prefix="/internal", tags=["内部嵌入服务"])


class InternalEmbeddingsRequest(BaseModel):
    """内部嵌入请求(批有界)。"""

    texts: list[str] = Field(min_length=1)


@router.post("/embeddings")
async def internal_embeddings(
    req: InternalEmbeddingsRequest,
    request: Request,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    settings = getattr(request.app.state, "settings", None)
    jwt_secret = getattr(settings, "jwt_secret", None)
    if not jwt_secret or not verify_internal_token(jwt_secret, x_internal_token):
        raise HTTPException(status_code=401, detail="invalid internal token")
    manager = getattr(request.app.state, "model_runtime", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="model runtime not ready")

    batch_limit = int(getattr(settings, "embedder_batch_size", 16))
    max_length = int(getattr(settings, "embedder_max_length", 8192))
    if len(req.texts) > batch_limit:
        raise HTTPException(
            status_code=422,
            detail=f"batch too large: {len(req.texts)} > {batch_limit}",
        )
    if any(len(t) > max_length for t in req.texts):
        raise HTTPException(
            status_code=413,
            detail=f"text exceeds max_length={max_length}",
        )

    try:
        vectors = await run_in_threadpool(manager.embed, WORKLOAD_SYNC_EMBEDDING, list(req.texts))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"embedding unavailable: {type(exc).__name__}: {exc}"[:500],
        ) from exc

    state = manager.states[WORKLOAD_SYNC_EMBEDDING]
    return {
        "vectors": [v.tolist() for v in vectors],
        "dimension": int(vectors[0].shape[0]) if vectors else None,
        "execution_device": "cpu" if state.effective.kind == "cpu" else "gpu",
        "fallback_reason": state.fallback_reason,
        "fallback_detail": state.fallback_detail,
    }
