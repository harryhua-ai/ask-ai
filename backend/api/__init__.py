"""FastAPI HTTP API 层。

将 RAGOrchestrator、Postgres 会话通过 SSE 端点对外暴露:
- ``POST /api/ask`` —— 流式问答(SSE)
- ``POST /api/feedback`` —— 对话反馈(up/down)
- ``POST /api/click`` —— 来源点击日志
"""

from backend.api.routes import router

__all__ = ["router"]
