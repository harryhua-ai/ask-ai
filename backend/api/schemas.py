"""API 请求体 Pydantic 模型。

所有入口校验(字段必填、长度、枚举)在系统边界完成,服务层不再重复校验。
"""

from pydantic import BaseModel, Field, field_validator

# S3: conversation_history 后端强制边界
MAX_HISTORY_ITEMS = 10
MAX_HISTORY_CONTENT_CHARS = 8000
MAX_HISTORY_TOTAL_CHARS = 40000


class AskRequest(BaseModel):
    """``POST /api/ask`` 请求体。

    Attributes:
        message: 用户问题文本(1~2000 字符)。
        language: 可选语言提示(如 ``zh-cn`` / ``en``);为空时由管道自动检测。
        channel: 渠道标识(仅允许 ``widget|discord|whatsapp|mcp|admin``),默认 ``widget``。
            ``admin`` 为管理后台内嵌聊天专用渠道,用于数据边界隔离:
            管理员测试对话不与真实访客(widget)对话混入同一统计池。
        conversation_history: OpenAI 风格历史消息(最多 ``MAX_HISTORY_ITEMS`` 条),
            单条 content 上限 ``MAX_HISTORY_CONTENT_CHARS`` 字符,总计上限
            ``MAX_HISTORY_TOTAL_CHARS`` 字符。仅保留 ``role`` / ``content`` 键。
    """

    message: str = Field(..., min_length=1, max_length=8000)
    language: str | None = None
    channel: str = Field(default="widget", pattern="^(widget|discord|whatsapp|mcp|admin)$")
    conversation_history: list[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    # Phase 1a:widget 匿名会话标识(localStorage UUID),用于附件归属校验
    session_id: str | None = Field(default=None, max_length=200)
    # Phase 1a:附件 id 列表(UUID 字符串),归属校验在 /ask 端点做
    attachments: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("conversation_history")
    @classmethod
    def _validate_history(cls, v: list[dict]) -> list[dict]:
        """校验每条 content 长度、总字符数,并仅保留 role/content 键。

        role 仅允许 ``user`` / ``assistant``;其他值(如 ``system``)降级为
        ``user``,防止 system-role 注入攻击。
        """
        total = 0
        for item in v:
            content = str(item.get("content", ""))
            if len(content) > MAX_HISTORY_CONTENT_CHARS:
                raise ValueError(f"history 单条 content 超过 {MAX_HISTORY_CONTENT_CHARS} 字符")
            total += len(content)
        if total > MAX_HISTORY_TOTAL_CHARS:
            raise ValueError(f"history 总字符超过 {MAX_HISTORY_TOTAL_CHARS}")
        # 仅保留 role/content,丢弃其他键;role 仅允许 user/assistant(防止 system 注入)
        result: list[dict] = []
        for item in v:
            role = item.get("role", "user")
            if role not in ("user", "assistant"):
                role = "user"
            result.append({"role": role, "content": str(item.get("content", ""))})
        return result


class FeedbackRequest(BaseModel):
    """``POST /api/feedback`` 请求体。

    Attributes:
        conversation_id: 对话 UUID 字符串。
        feedback: 反馈类型,仅允许 ``up`` 或 ``down``。
    """

    conversation_id: str
    feedback: str = Field(..., pattern="^(up|down)$")


class ClickRequest(BaseModel):
    """``POST /api/click`` 请求体。

    Attributes:
        conversation_id: 对话 UUID 字符串。
        source_url: 被点击来源的 URL。
        source_type: 来源类型(``github`` / ``wiki`` 等)。
        product: 可选产品标识。
    """

    conversation_id: str
    source_url: str
    source_type: str
    product: str | None = None
