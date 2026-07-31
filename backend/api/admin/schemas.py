"""Admin API Pydantic 模型。"""

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


class DataSourceCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(github|filesystem|web_crawl|sdk)$")
    product: str = Field(..., min_length=1, max_length=50)
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    sync_interval: str = Field(default="24h", pattern=r"^\d+[hm]$")


class DataSourceUpdate(BaseModel):
    type: str | None = Field(default=None, pattern="^(github|filesystem|web_crawl|sdk)$")
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


class LLMProviderOut(BaseModel):
    """LLM 供应商输出 schema(api_key 已脱敏)。"""

    id: str
    type: str
    enabled: bool
    config: dict


class LLMProviderCreate(BaseModel):
    """LLM 供应商创建 schema(config 中包含明文 api_key)。"""

    id: str = Field(..., min_length=1, max_length=50)
    type: str = Field(..., pattern="^(openai_compatible|anthropic|openai)$")
    enabled: bool = True
    config: dict


class LLMProviderUpdate(BaseModel):
    """LLM 供应商更新 schema(仅非 None 字段会被写入)。"""

    type: str | None = None
    enabled: bool | None = None
    config: dict | None = None


class LLMRoutingOut(BaseModel):
    """LLM 路由输出 schema。"""

    task: str
    chain: list[str]


class LLMRoutingUpdate(BaseModel):
    """LLM 路由更新 schema。"""

    chain: list[str]


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
