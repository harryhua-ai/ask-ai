"""Admin API Pydantic 模型。"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.services.knowledge_policy import FRESHNESS_CHOICES_HOURS


def _validate_freshness_hours(v: int | None) -> int | None:
    """INT-C03:新鲜度阈值写入侧收敛冻结词表(6/12/24/72/168)。

    非法值 → pydantic ValidationError(422 fail-loud);禁静默接受后在
    读取侧回落默认 24(掩盖真值)。CURRENT/HISTORICAL 语义零变化。"""
    if v is not None and v not in FRESHNESS_CHOICES_HOURS:
        raise ValueError(
            f"freshness_hours 必须为冻结词表之一 {list(FRESHNESS_CHOICES_HOURS)}(小时)"
        )
    return v


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
    # #18 删除生命周期(NULL = ACTIVE):状态持久化在行上,刷新即恢复
    lifecycle_state: str | None = None
    lifecycle_since: str | None = None
    lifecycle_error: str | None = None
    # ---- v1.6.3 Track C(U-11/U-12;加性真值)----
    # next_run_at = 调度器权威持久真值;NULL = 调度现实不构成倒计时
    # (禁用/同步进行中/从未同步),前端禁止从 sync_interval 纯派生。
    next_run_at: str | None = None
    schedule_state: str | None = None  # scheduled/syncing/paused/waiting_first/deleting
    knowledge_role: str | None = None  # U-12 生效角色(current/historical)
    freshness_hours: int | None = None  # U-12 生效新鲜度阈值(小时)
    freshness_overdue: bool | None = None  # U-12 后端权威超期态(Admin 可见)
    # ---- #71 权威成员货币真值(持久列直读;渲染端禁止实时枚举)----
    membership_status: str | None = None  # current/stale/failed/unsupported;NULL=未对账
    membership_checked_at: str | None = None
    membership_stale_detected: int | None = None
    membership_stale_retired: int | None = None


class SourceScheduleTruthOut(BaseModel):
    """GET /data-sources/{source_id}/schedule 响应(U-11 调度真值)。"""

    source_id: str
    next_run_at: str | None = None
    state: str  # scheduled/syncing/paused/waiting_first/deleting
    sync_interval: str
    enabled: bool


class ConversationIdPolicyOut(BaseModel):
    """Conversation ID 新建策略(已有 ID 不受影响)。"""

    strategy: str
    label: str
    description: str
    example: str
    affects_new_conversations_only: bool = True
    updated_at: str | None = None


class ConversationIdPolicyUpdate(BaseModel):
    """Conversation ID 策略写入词表。"""

    strategy: str = Field(..., pattern="^(uuid4|uuid7)$")


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
    delta_counts: dict | None = None  # #65 document-level contract; NULL = legacy unit unknown
    error_detail: str | None
    triggered_by: str


# --------------------------------------------------------------------------- #
# #50 B1 Data Source Workspace V2 读模型(只读;权威账本投影)
# --------------------------------------------------------------------------- #


class DataSourceDocumentItem(BaseModel):
    """逐源文档清单行(复合路径身份;禁止虚构 content-role/discovered 等字段)。"""

    source_id: str  # 复合身份 <source_id>/<branch>/<rel_path>(canonical path)
    title: str
    url: str
    branch: str
    source_type: str
    product: str
    lifecycle: str  # L 轴词表(DocLifecycle.ALL)
    serving: bool  # 在服 = lifecycle ∈ SERVING ∧ 现行版本可解析(权威关系)
    chunk_count: int
    created_at: str | None = None  # 权威时间戳(仅 created_at/updated_at)
    updated_at: str | None = None
    current_version_seq: int | None = None  # None = 后端无此记录
    generation_ordinal: int | None = None  # None = 后端无此记录
    content_type: str | None = None  # U-7(NULL = 存量行不可用)


class DataSourceDocumentsResponse(BaseModel):
    """GET /data-sources/{source_id}/documents 响应。

    total = 过滤后分页总数;lifecycle_counts / ledger_total / serving_count /
    current_count 为全源账本聚合(不受过滤影响)。
    content_type_counts = U-7 逐文档内容类型账本聚合(不含 NULL;类型过滤
    词表的真实来源,前端禁推断)。
    """

    source_id: str
    total: int
    ledger_total: int
    page: int
    size: int
    lifecycle_counts: dict[str, int] = Field(default_factory=dict)
    serving_count: int = 0
    current_count: int = 0
    content_type_counts: dict[str, int] = Field(default_factory=dict)
    items: list[DataSourceDocumentItem]


class DocumentCurrentVersionTruth(BaseModel):
    """单文档现行版本真相(版本链 + 生成归属;chunk 账本计数)。"""

    id: str
    version_seq: int
    status: str
    title: str
    url: str
    chunk_count: int
    chunks_total: int  # document_version_chunks 持久账本计数
    source_version: dict | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by_version_id: str | None = None
    generation_id: str
    generation_ordinal: int


class DocumentGenerationTruth(BaseModel):
    """索引生成行真相(P 轴;失败证据 failure JSONB 原样)。"""

    id: str
    ordinal: int
    status: str
    doc_count: int
    chunk_count: int
    failure: dict | None = None
    created_at: str | None = None


class DocumentVersionHistoryEntry(BaseModel):
    """Issue #55(版本历史):DocumentVersion 权威行的 Inspector 投影。

    与现行版本同一权威关系(document_versions 行),仅按 version_seq
    降序展开;不新增真值、不推断状态。
    """

    version_seq: int
    status: str
    chunk_count: int
    source_version: dict | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by_version_id: str | None = None
    generation_ordinal: int | None = None


class DocumentCitationTruth(BaseModel):
    """Issue #55(引用与链接有效性):#48 既有权威派生的 Inspector 投影。

    - ``url``:账本存储 canonical 目标(identity 保全,绝不改写);
    - ``citation_url``:权威引用目标(wiki slug 权威映射后的可导航路由;
      与存储 URL 相同 = 无映射发生);空白 URL → None(知识案例语义);
    - ``link_state``:#48 冻结词表 external/none/private/stale,由
      ``rag._derive_link_state`` 派生(单一权威,零第二真值);
    - ``visitor_reachability``:连接器 clone 时探测真值原样;
      None = 元数据未记录(显式缺席,绝不推断)。
    """

    url: str
    citation_url: str | None = None
    link_state: str
    visitor_reachability: str | None = None
    ready_at: str | None = None
    activated_at: str | None = None
    withdrawn_at: str | None = None
    retired_at: str | None = None
    gc_eligible_at: str | None = None
    purged_at: str | None = None


class ChunkServingTruth(BaseModel):
    """U-9 chunk 级 serving 投影真值(UI 比例必须等于 serving_chunks/total_chunks)。"""

    serving_chunks: int
    total_chunks: int
    missing_indices: list[int] = Field(default_factory=list)
    stale_indices: list[int] = Field(default_factory=list)
    consistent: bool


class DocumentRepairTaskOut(BaseModel):
    """U-8 修复任务(进度/结果/审计;验证卡数据源 = result 真值)。"""

    id: str
    source_id: str
    doc_source_id: str
    status: str  # pending/running/succeeded/failed/rebuild_requested
    stage: str | None = None
    requested_by: str | None = None
    idempotency_key: str | None = None
    result: dict | None = None
    error: str | None = None
    events: list[dict] = Field(default_factory=list)
    created_at: str | None = None
    finished_at: str | None = None


class BulkDocumentRepairItem(BaseModel):
    """单个批量修复项的权威结果(不把未执行伪装成成功)。

    INC-WEB-EMBED-413 REMEDIATION:status 增 "rebuild_requested"(系统自选
    权威源重建交接);``sync_request_id`` 携带交接行 id 供审计追溯。
    """

    doc_source_id: str
    status: str
    task_id: str | None = None
    error: str | None = None
    sync_request_id: int | None = None


class BulkDocumentRepairOut(BaseModel):
    """数据源级批量修复聚合结果。"""

    source_id: str
    eligible: int
    succeeded: int
    failed: int
    # REMEDIATION:系统自选源重建交接的项数(succeeded/failed 均不含)。
    rebuild_requested: int = 0
    items: list[BulkDocumentRepairItem] = Field(default_factory=list)


class DataSourceDocumentTruth(BaseModel):
    """GET /data-sources/{source_id}/documents/detail 响应:单文档真相。

    current_version / generation 为 None = 后端无此记录(显式缺席,
    前端呈现「后端无此记录」,不得编造)。
    """

    source_id: str  # 数据源配置 id(路径前缀)
    doc_source_id: str  # 复合文档身份(canonical path)
    title: str
    url: str
    branch: str
    source_type: str
    product: str
    lifecycle: str
    serving: bool
    chunk_count: int
    created_at: str | None = None
    updated_at: str | None = None
    superseded_by: str | None = None
    superseded_at: str | None = None
    deleted_at: str | None = None
    # ---- v1.6.3 Track C(加性真相;None = 后端无此记录/不可用)----
    content_type: str | None = None  # U-7(NULL = 存量行不可用,前端诚实呈现)
    chunk_serving: ChunkServingTruth | None = None  # U-9(None = 向量库不可用)
    recovery_attempts_failed: int = 0  # U-10(自动恢复尝试未成功权威计数)
    recovery_attempts_succeeded: int = 0  # U-10
    latest_repair_task: DocumentRepairTaskOut | None = None  # U-8
    current_version: DocumentCurrentVersionTruth | None = None
    generation: DocumentGenerationTruth | None = None
    # ---- Issue #55(Inspector 真值面;矩阵 gap 闭环,加性)----
    versions: list[DocumentVersionHistoryEntry] = Field(default_factory=list)
    versions_truncated: bool = False  # True = 超出上限,仅最近 N 条(诚实标注)
    citation: DocumentCitationTruth | None = None  # None = 不可用(绝不伪造)


class DocumentRepairRequest(BaseModel):
    """POST /data-sources/{source_id}/documents/repair 请求(U-8)。"""

    doc_source_id: str  # 复合文档身份 <source_id>/<branch>/<rel_path>
    idempotency_key: str | None = Field(default=None, max_length=100)


class KnowledgeSettingsOut(BaseModel):
    """GET /data-sources/{source_id}/knowledge-settings 响应(U-12)。

    effective_* = 后端权威生效值(显式配置优先,默认兜底);freshness =
    新鲜度真值(超期态 Admin 可见)。
    """

    source_id: str
    role: str  # current/historical(生效值)
    explicit_role: str | None = None  # 行上显式配置(NULL=默认)
    freshness_hours: int
    explicit_freshness_hours: int | None = None
    freshness: dict = Field(default_factory=dict)
    updated_at: str | None = None


class KnowledgeSettingsUpdate(BaseModel):
    """PUT /data-sources/{source_id}/knowledge-settings 请求(U-12/U-13)。

    高风险变更(时态角色变化)必须携带 preview_token(服务端一致性校验),
    且 pending 策略与预览完全一致,否则 409。
    """

    role: str = Field(..., pattern="^(current|historical)$")
    freshness_hours: int | None = Field(default=None, ge=1, le=10000)
    preview_token: str | None = None

    @field_validator("freshness_hours")
    @classmethod
    def _freshness_in_frozen_vocabulary(cls, v: int | None) -> int | None:
        return _validate_freshness_hours(v)


class KnowledgePreviewRequest(BaseModel):
    """POST /data-sources/{source_id}/knowledge-settings/preview 请求(U-13)。"""

    role: str = Field(..., pattern="^(current|historical)$")
    freshness_hours: int | None = Field(default=None, ge=1, le=10000)

    @field_validator("freshness_hours")
    @classmethod
    def _freshness_in_frozen_vocabulary(cls, v: int | None) -> int | None:
        return _validate_freshness_hours(v)


class KnowledgePreviewResponse(BaseModel):
    """预览响应(影响计数 = 服务端权威;token = 确认一致性锚)。"""

    preview_token: str
    source_id: str
    current_policy: dict
    pending_policy: dict
    impact: dict
    expires_at: str | None = None


class SourceAttentionSummaryItem(BaseModel):
    """v1.6.3 B1:逐源运营桶聚合投影(只读;与 documents 端点聚合同一定义)。

    current = active ∧ 现行版本可解析;retired = superseded + deleted;
    attention = ledger_total − current − retired(冻结公式,DocLifecycle 词表)。
    """

    source_id: str
    ledger_total: int
    current_count: int
    serving_count: int
    retired_count: int
    attention_count: int
    lifecycle_counts: dict[str, int] = Field(default_factory=dict)


class SourceAttentionSummaryResponse(BaseModel):
    """GET /data-sources/attention-summary 响应(全源一次取全,零文档源为零值行)。"""

    items: list[SourceAttentionSummaryItem]


class DataSourceGenerationsResponse(BaseModel):
    """GET /data-sources/{source_id}/generations 响应(ordinal 倒序)。"""

    source_id: str
    total: int
    serving_ordinals: list[int] = Field(default_factory=list)
    items: list[DocumentGenerationTruth]


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
    chunks_written: int  # legacy = sync_log.items_updated;非"更新文档数"
    items_deleted: int
    items_unchanged: int
    delta_counts: dict | None = None  # #65 explicit document units; NULL = historical unknown
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
    """单数据源健康(读时派生,无 SourceHealthSnapshot)。"""

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
    # #71 权威成员货币(持久真值直读;与 PG↔Weaviate consistency 严格分维)
    currency: HealthDimension


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
