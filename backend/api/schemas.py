"""API 请求体 Pydantic 模型。

所有入口校验(字段必填、长度、枚举)在系统边界完成,服务层不再重复校验。
"""

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.utils.language import normalize_language

# S3: conversation_history 后端强制边界
MAX_HISTORY_ITEMS = 10
MAX_HISTORY_CONTENT_CHARS = 8000
MAX_HISTORY_TOTAL_CHARS = 40000


def _clean_hint_text(value: str | None, limit: int) -> str | None:
    """非信任文本消毒:控制字符(Cc/Cf)转空格、折叠空白;空 → None。

    用于 page_context(宿主页面自动收集的元数据)。注意:语义内容**保留**
    (含疑似注入文案)—— 信任边界由提示词分层兜住(G008),边界只负责
    结构与体积可控;超长由 Field max_length 在校验期 422 拒绝(与 message/
    history 边界语义一致)。
    """
    if value is None:
        return None
    cleaned = "".join(ch if unicodedata.category(ch) not in ("Cc", "Cf") else " " for ch in value)
    cleaned = " ".join(cleaned.split())[:limit]
    return cleaned or None


class PageContext(BaseModel):
    """宿主页面上下文(MSW;冻结契约 §9/§10)。

    **非信任语义提示**:仅帮助解释指代 / 软检索加分 / 选择站点体验,
    不授权、不进 system 消息、不构成事实依据。未知字段一律丢弃;
    url 仅接受 http/https(数据只作提示,不渲染为链接,仍收敛 scheme)。
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    language: str | None = Field(default=None, max_length=20)
    page_type: str | None = Field(default=None, max_length=50)
    product: str | None = Field(default=None, max_length=100)
    product_id: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    section: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _clean_url(cls, v: str | None) -> str | None:
        cleaned = _clean_hint_text(v, 2048)
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            return None
        return cleaned

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str | None) -> str | None:
        return _clean_hint_text(v, 300)

    @field_validator("language", "page_type")
    @classmethod
    def _clean_short(cls, v: str | None) -> str | None:
        return _clean_hint_text(v, 50)

    @field_validator("product", "product_id", "sku")
    @classmethod
    def _clean_productish(cls, v: str | None) -> str | None:
        return _clean_hint_text(v, 100)

    @field_validator("section")
    @classmethod
    def _clean_section(cls, v: str | None) -> str | None:
        return _clean_hint_text(v, 200)


class AskRequest(BaseModel):
    """``POST /api/ask`` 请求体。

    Attributes:
        message: 用户问题文本(1~8000 字符)。
        language: 可选语言提示(如 ``zh-cn`` / ``en``);归一化为规范形(zh/en/其他
            主子标签)后作为**默认答案语境**(ML 闭环);为空时由管道自动检测。
        channel: 渠道标识(仅允许 ``widget|discord|whatsapp|mcp|admin``),默认 ``widget``。
            ``admin`` 为管理后台内嵌聊天专用渠道,用于数据边界隔离:
            管理员测试对话不与真实访客(widget)对话混入同一统计池。
        conversation_history: OpenAI 风格历史消息(最多 ``MAX_HISTORY_ITEMS`` 条),
            单条 content 上限 ``MAX_HISTORY_CONTENT_CHARS`` 字符,总计上限
            ``MAX_HISTORY_TOTAL_CHARS`` 字符。仅保留 ``role`` / ``content`` 键。
    """

    message: str = Field(..., min_length=1, max_length=8000)
    # ML 闭环(G-L1):语言提示归一化(zh-CN→zh / en-US→en);无效值 fail-open 为
    # None 交回文本检测,不因宿主误传改变基线行为
    language: str | None = None

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, v: str | None) -> str | None:
        return normalize_language(v)

    channel: str = Field(default="widget", pattern="^(widget|discord|whatsapp|mcp|admin)$")
    conversation_history: list[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    # Phase 1a:widget 匿名会话标识(localStorage UUID),用于附件归属校验
    session_id: str | None = Field(default=None, max_length=200)
    # Phase 1a:附件 id 列表(UUID 字符串),归属校验在 /ask 端点做
    attachments: list[str] = Field(default_factory=list, max_length=5)
    # MSW:站点体验标识(标识符非凭证;空 = legacy 公共 widget,不做站点校验)
    site_id: str | None = Field(default=None, max_length=100)
    # MSW:宿主页面上下文(非信任语义提示;消毒规则见 PageContext)
    page_context: PageContext | None = None

    @field_validator("site_id")
    @classmethod
    def _normalize_site_id(cls, v: str | None) -> str | None:
        """site_id 规范化:trim + 小写;空白 → None(legacy);形状非法拒绝。"""
        if v is None:
            return None
        normalized = v.strip().lower()
        if not normalized:
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,98}[a-z0-9]|[a-z0-9]", normalized):
            raise ValueError("site_id 形状非法")
        return normalized

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
