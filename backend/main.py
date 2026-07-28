import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from backend.config import load_settings

logger = logging.getLogger(__name__)
settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Ask AI 后端启动中...")
    yield
    logger.info("Ask AI 后端关闭")


app = FastAPI(title="Ask AI", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
