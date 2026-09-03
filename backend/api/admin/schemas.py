"""Admin API Pydantic 模型。"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

from pydantic import BaseModel, EmailStr, Field


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
    last_sync_status: str | None = None
    last_sync_error: str | None = None


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
    items_unchanged: int = 0
    error_detail: str | None
    triggered_by: str


# --------------------------------------------------------------------------- #
# ⑫ Sync Truth 读侧 schema(W2;Frozen Discovery §19 contract)
# --------------------------------------------------------------------------- #


class SyncStatusItem(BaseModel):
    """单数据源当前运行态(bulk;由 request + latest run 读时派生)。"""

    source_id: str
    state: str
    request_id: int | None = None
    attempt: int | None = None
    recovering: bool = False
    stage: str | None = None
    stage_current: int | None = None
    stage_total: int | None = None
    counters: dict = Field(default_factory=dict)
    execution_device: str | None = None
    started_at: str | None = None
    updated_at: str | None = None


class SyncStatusResponse(BaseModel):
    """GET /sync-status 响应:全部相关源的运行态快照。"""

    items: list[SyncStatusItem]


class SyncRunLogSummary(BaseModel):
    """运行历史关联的业务结局(sync_log;真实语义命名)。"""

    id: str
    status: str
    items_new: int
    chunks_written: int  # = sync_log.items_updated:写入 chunk 总数,非"更新文档数"
    items_deleted: int
    items_unchanged: int
    error_detail: str | None = None


class SyncRunHistoryItem(BaseModel):
    """单条运行历史(ONE SOURCE × ONE ATTEMPT + 关联业务结局)。"""

    id: int
    source_id: str
    triggered_by: str
    request_id: int | None = None
    attempt: int
    recovery: bool
    status: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    stage: str | None = None
    counters: dict = Field(default_factory=dict)
    consistency: dict | None = None
    execution_device: str | None = None
    fallback_reason: str | None = None
    fallback_detail: str | None = None
    error_summary: str | None = None
    ingestion_skipped: bool = False
    sync_log: SyncRunLogSummary | None = None


class SyncRunsResponse(BaseModel):
    """GET /sync-runs 响应:分页运行历史。"""

    items: list[SyncRunHistoryItem]
    total: int
    page: int
    size: int


class HealthDimension(BaseModel):
    """单健康维度:{state, evidence, as_of};无证据 → UNKNOWN/INSUFFICIENT_DATA。"""

    state: str
    evidence: str | None = None
    as_of: str | None = None


class SourceHealthItem(BaseModel):
    """单数据源五维健康(读时派生,无 SourceHealthSnapshot)。"""

    source_id: str
    source_type: str
    enabled: bool
    expected_state: str
    overall: str
    recovering: bool = False
    document_count: int | None = None
    connectivity: HealthDimension
    sync: HealthDimension
    coverage: HealthDimension
    freshness: HealthDimension
    consistency: HealthDimension


class SourceHealthResponse(BaseModel):
    """GET /sync-health 响应:全部数据源五维健康快照。"""

    items: list[SourceHealthItem]


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


# 内置预授权 LLM 主机(既有产品语义:三家直连默认可用,无需 DB 授权行)
_DEFAULT_LLM_HOSTS = {"api.deepseek.com", "api.openai.com", "api.anthropic.com"}


def _env_allowed_llm_hosts() -> set[str]:
    """部署级预授权扩展(env LLM_ALLOWED_HOSTS),与 DB 显式授权叠加生效。"""
    extra = os.environ.get("LLM_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in extra.split(",") if h.strip()}


def _is_non_global_ip(host: str) -> bool:
    """主机是否为非全局 IP 字面量(内网族)。

    覆盖 RFC1918 / loopback / link-local / reserved,以及 is_global=False 的
    共享地址段(含 CGNAT 100.64/10,如 Tailscale 网关)。
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_link_local or ip.is_private or ip.is_loopback or ip.is_reserved or not ip.is_global


def validate_llm_api_base(
    url: str,
    *,
    authorized_public: frozenset[str] = frozenset(),
    authorized_private: frozenset[str] = frozenset(),
) -> str:
    """校验 LLM api_base,防 SSRF 与凭证外泄。

    信任模型(显式授权、可审查、默认拒绝):
      - 内置三家主机 + env ``LLM_ALLOWED_HOSTS``:部署级预授权(公网语义);
      - ``authorized_public`` / ``authorized_private``:DB 显式授权
        (管理员通过「模型配置 → 端点授权」维护),private 级才可放行
        私有/内网地址与内网 http;
      - 任何授权都不放宽协议(仅 http/https)与畸形输入检查。
    prod 额外要求 https 并拒绝解析到内网族的公网主机(private 级显式授权除外,
    即管理员明确信任该内网通道)。错误文案只描述产品级操作,不暴露实现层指令。
    """
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("api_base 只允许 http/https 协议")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("api_base 缺少主机名")

    private_tier = host in authorized_private
    if _is_non_global_ip(host):
        if not private_tier:
            raise ValueError(
                f"内网/私有地址 {host} 默认拒绝:"
                "请由管理员在「模型配置 → 端点授权」中显式授权后使用"
            )
    else:
        allowed = (
            _DEFAULT_LLM_HOSTS | _env_allowed_llm_hosts() | authorized_public | authorized_private
        )
        if host not in allowed:
            raise ValueError(
                f"API 地址主机 {host} 尚未授权:" "请由管理员在「模型配置 → 端点授权」中添加后重试"
            )

    if os.environ.get("APP_MODE", "dev") != "prod":
        return url

    if parsed.scheme != "https" and not private_tier:
        raise ValueError("prod 模式 api_base 必须使用 https(内网端点需显式授权内网级别)")
    if private_tier:
        return url

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"api_base 主机 {host} 无法解析") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_non_global_ip(str(ip)):
            raise ValueError(f"prod 模式禁止 api_base 指向内网地址 {ip}")
    return url


class ProviderConfig(BaseModel):
    """LLM 供应商配置（结构化校验，防 cost 放大）。

    api_base 不在此处校验:端点授权需查 DB(llm_allowed_hosts),
    校验由 API 端点层结合授权集合执行(validate_llm_api_base)。
    max_tokens/temperature 限界防止管理员误设导致成本放大。
    """

    model_config = {"extra": "forbid"}

    api_base: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    available_models: list[str] = Field(default_factory=list)


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


class FetchModelsRequest(BaseModel):
    """fetch-models 可选请求体(T27)。

    携带编辑表单中尚未保存的 api_base/api_key:非空值优先生效,空值回退 DB 已存凭证。
    生效 api_base 仍走 validate_llm_api_base(SSRF 边界与保存路径一致,不放宽)。
    """

    api_base: str | None = None
    api_key: str | None = None


class LLMAllowedHostOut(BaseModel):
    """LLM 端点授权记录输出 schema。"""

    host: str
    allow_private: bool
    note: str | None
    created_by: str | None
    created_at: str


class LLMAllowedHostCreate(BaseModel):
    """LLM 端点授权创建 schema。

    host 接受裸主机名/IP,也容忍携带 scheme/port/path 的粘贴输入
    (服务端归一化后存储;通配符与非法输入在端点层 422)。
    """

    host: str = Field(..., min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=500)


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
    miss_type: str | None = None


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
    miss_type_summary: dict[str, int] = {}


class SourceAnalyticsList(BaseModel):
    """来源分析响应。"""

    items: list[SourceAnalyticsOut]
    days: int
