"""Admin API Pydantic 模型。"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    is_active: bool


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class UserCreate(BaseModel):
    email: EmailStr
    name: str | None = None
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|editor|viewer)$")
    is_active: bool | None = None


class DataSourceOut(BaseModel):
    id: str
    type: str
    product: str
    enabled: bool
    config: dict
    sync_interval: str
    created_at: str
    updated_at: str
    last_sync: str | None = None


class DataSourceCreate(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    type: str = Field(..., pattern="^(github|filesystem|local_git|web_crawl|sdk|woocommerce)$")
    product: str = Field(..., min_length=1, max_length=50)
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    sync_interval: str = Field(default="24h", pattern=r"^\d+[hm]$")


class DataSourceUpdate(BaseModel):
    type: str | None = Field(
        default=None, pattern="^(github|filesystem|local_git|web_crawl|sdk|woocommerce)$"
    )
    product: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    sync_interval: str | None = Field(default=None, pattern=r"^\d+[hm]$")


class SyncLogOut(BaseModel):
    """同步日志输出 schema。"""

    id: str
    source_id: str
    source_type: str
    status: str
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    items_new: int
    items_updated: int
    items_deleted: int
    error_detail: str | None
    triggered_by: str


class PaginatedResponse(BaseModel):
    """通用分页响应 schema。"""

    items: list
    total: int
    page: int
    size: int


class CustomizationOut(BaseModel):
    """Customization 输出 schema。"""

    id: str
    name: str
    system_prompt: str
    style_tone: str | None
    guardrails: str | None
    language: str
    assistant_name: str
    is_active: bool
    version: str


class CustomizationCreate(BaseModel):
    """Customization 创建 schema。"""

    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    system_prompt: str = Field(..., min_length=1)
    style_tone: str | None = None
    guardrails: str | None = None
    language: str = "auto"
    assistant_name: str = "CamThink 助手"


class CustomizationUpdate(BaseModel):
    """Customization 更新 schema(仅非 None 字段会被写入)。"""

    name: str | None = None
    system_prompt: str | None = None
    style_tone: str | None = None
    guardrails: str | None = None
    language: str | None = None
    assistant_name: str | None = None
    is_active: bool | None = None


class BindingOut(BaseModel):
    """渠道绑定输出 schema。"""

    channel: str
    customization_id: str


class BindingUpdate(BaseModel):
    """渠道绑定更新 schema。"""

    customization_id: str


# prod 模式 LLM api_base 白名单（防 SSRF + 凭证外泄）
_DEFAULT_LLM_HOSTS = {"api.deepseek.com", "api.openai.com", "api.anthropic.com"}


def _allowed_llm_hosts() -> set[str]:
    """返回允许的 LLM 主机白名单（默认 + env LLM_ALLOWED_HOSTS 扩展）。"""
    hosts = set(_DEFAULT_LLM_HOSTS)
    extra = os.environ.get("LLM_ALLOWED_HOSTS", "")
    return hosts | {h.strip().lower() for h in extra.split(",") if h.strip()}


def validate_llm_api_base(url: str) -> str:
    """校验 LLM api_base，防 SSRF 与凭证外泄。

    所有环境都只允许默认供应商主机或通过 ``LLM_ALLOWED_HOSTS`` 显式配置的主机。
    这不是 UI 校验，而是携带解密凭证发起出站请求前的安全边界。
    prod 额外拒绝 DNS 解析到内网、loopback、保留和 link-local 地址。
    本地 LLM 若确实需要使用，必须显式加入 allowlist；不允许依赖 APP_MODE
    的默认值放行任意目标。
    """
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("api_base 只允许 http/https 协议")
    if os.environ.get("APP_MODE", "dev") == "prod" and parsed.scheme != "https":
        raise ValueError("prod 模式 api_base 必须使用 https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("api_base 缺少主机名")

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and (
        literal_ip.is_link_local
        or literal_ip.is_private
        or literal_ip.is_loopback
        or literal_ip.is_reserved
    ):
        raise ValueError(f"禁止 api_base 指向内网地址 {literal_ip}")

    if host not in _allowed_llm_hosts():
        raise ValueError(f"api_base 主机 {host} 不在 allowlist（通过 LLM_ALLOWED_HOSTS 配置）")

    if os.environ.get("APP_MODE", "dev") != "prod":
        return url

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"api_base 主机 {host} 无法解析") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_private or ip.is_loopback or ip.is_reserved:
            raise ValueError(f"prod 模式禁止 api_base 指向内网地址 {ip}")
    return url


class ProviderConfig(BaseModel):
    """LLM 供应商配置（结构化校验，防 SSRF / cost 放大）。

    api_base 经 validate_llm_api_base 校验；max_tokens/temperature 限界
    防止管理员误设导致成本放大。
    """

    model_config = {"extra": "forbid"}

    api_base: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    available_models: list[str] = Field(default_factory=list)

    @field_validator("api_base")
    @classmethod
    def _check_api_base(cls, v: str) -> str:
        return validate_llm_api_base(v)


class LLMProviderOut(BaseModel):
    """LLM 供应商输出 schema(api_key 已脱敏)。"""

    id: str
    type: str
    enabled: bool
    config: dict


class LLMProviderCreate(BaseModel):
    """LLM 供应商创建 schema(config 中包含明文 api_key)。"""

    id: str = Field(..., min_length=1, max_length=50)
    type: str = Field(..., pattern="^openai_compatible$")
    enabled: bool = True
    config: ProviderConfig


class LLMProviderUpdate(BaseModel):
    """LLM 供应商更新 schema(仅非 None 字段会被写入)。"""

    type: str | None = Field(default=None, pattern="^openai_compatible$")
    enabled: bool | None = None
    config: ProviderConfig | None = None


class LLMChainItem(BaseModel):
    """LLM 路由链元素:{provider, model}。

    provider: 供应商 id;model: 该任务用的 model,None = 用 provider 默认。
    """

    provider: str
    model: str | None = None


class LLMRoutingOut(BaseModel):
    """LLM 路由输出 schema。"""

    task: str
    chain: list[LLMChainItem | str] = []  # 兼容旧字符串格式(过渡期)


class LLMRoutingUpdate(BaseModel):
    """LLM 路由更新 schema。"""

    chain: list[LLMChainItem] = []  # 写入侧只接受对象格式（读侧 config_loader 仍兼容旧字符串）


class ConnectivityTestResult(BaseModel):
    """连通性测试结果 schema。"""

    provider_id: str
    success: bool
    latency_ms: int | None
    error: str | None


class ConversationOut(BaseModel):
    """对话记录输出 schema。"""

    id: str
    question: str
    answer: str | None
    channel: str
    language: str | None
    sources: list
    is_answered: bool
    feedback: str | None
    response_time_ms: int | None
    created_at: str
    intent_tag: str | None


class AnswerOverrideOut(BaseModel):
    """答案覆盖输出 schema。"""

    id: str
    match_pattern: str
    match_type: str
    override_answer: str
    override_sources: list = Field(default_factory=list)
    created_by: str | None
    is_active: bool
    created_at: str
    updated_at: str


class AnswerOverrideCreate(BaseModel):
    """答案覆盖创建 schema。"""

    match_pattern: str = Field(..., min_length=1)
    match_type: str = Field(default="semantic", pattern="^(semantic|keyword|regex)$")
    override_answer: str = Field(..., min_length=1)
    override_sources: list = Field(default_factory=list)


class AnswerOverrideUpdate(BaseModel):
    """答案覆盖更新 schema(仅非 None 字段会被写入)。"""

    match_pattern: str | None = None
    match_type: str | None = Field(default=None, pattern="^(semantic|keyword|regex)$")
    override_answer: str | None = None
    override_sources: list | None = None
    is_active: bool | None = None


class QuestionClusterOut(BaseModel):
    """聚类结果输出 schema。"""

    id: str
    cluster_type: str
    representative_question: str
    sample_questions: list[str]
    question_count: int
    status: str
    period_start: str | None
    period_end: str | None
    created_at: str


class SourceAnalyticsOut(BaseModel):
    """来源分析输出 schema。"""

    url: str
    source_type: str
    product: str | None
    clicks: int
    references: int


class AnalyticsRefreshResult(BaseModel):
    """聚类刷新结果。"""

    cluster_count: int
    total_questions: int


class QuestionClusterList(BaseModel):
    """聚类列表分页响应。"""

    items: list[QuestionClusterOut]
    total: int
    page: int
    size: int


class SourceAnalyticsList(BaseModel):
    """来源分析响应。"""

    items: list[SourceAnalyticsOut]
    days: int
