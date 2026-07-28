"""API 请求体 Pydantic 模型。

所有入口校验(字段必填、长度、枚举)在系统边界完成,服务层不再重复校验。
"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """``POST /api/ask`` 请求体。

    Attributes:
        message: 用户问题文本(1~2000 字符)。
        language: 可选语言提示(如 ``zh-cn`` / ``en``);为空时由管道自动检测。
        channel: 渠道标识,默认 ``widget``。预留供路由 / 限流使用。
        conversation_history: OpenAI 风格历史消息(最多 10 条),供多轮对话使用。
    """

    message: str = Field(..., min_length=1, max_length=2000)
    language: str | None = None
    channel: str = "widget"
    conversation_history: list[dict] = Field(default_factory=list, max_length=10)


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
