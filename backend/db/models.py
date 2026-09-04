"""SQLAlchemy ORM 模型定义。

包含 11 张表(对齐设计文档 §11 SQL DDL + 灌入管道需要的 documents 表):
- documents: 已灌入文档元数据(source_id 路径身份为主键,content_hash 为内容指纹索引;灌入管道维护)
- conversations: 对话记录(含 Phase 2/3 预留字段)
- source_clicks: 来源点击日志
- sync_log: 同步任务日志
- data_sources: 数据源配置
- customizations: 定制化配置
- customization_bindings: 定制化绑定
- answer_overrides: 答案覆盖
- users: 用户
- llm_providers: LLM 供应商配置
- llm_routing: LLM 路由配置
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    """已灌入向量库的文档元数据(灌入管道维护)。

    Issue #13(D1/D2 冻结):主键 = ``source_id``(复合路径串
    ``<source_id>/<branch>/<rel_path>``),即**源文档(路径)身份** ——
    每个真实文档一行;不同 source/path 即使 ``content_hash`` 相同也必须
    各自成行。``content_hash`` 降级为内容指纹/索引(检索去重辅助查询),
    不再承担唯一性身份。chunk 级数据落在 Weaviate(uuid5(source_id#i),
    与本表同为路径寻址),本表承担"哪些文档已灌入 / 何时被灌入 / 灌了
    多少 chunk"的对账权威,供同步 reconciliation 与管理界面使用。
    """

    __tablename__ = "documents"

    source_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    branch: Mapped[str] = mapped_column(String(100), default="", nullable=False, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="widget")
    language: Mapped[str | None] = mapped_column(String(10))
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    is_answered: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str | None] = mapped_column(String(10))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Phase 2 预留
    intent_tag: Mapped[str | None] = mapped_column(String(100))
    custom_tags: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    customization_id: Mapped[str | None] = mapped_column(String(50))
    country: Mapped[str | None] = mapped_column(String(10))
    # Sales Lead(V1):widget 匿名会话 ID,会话线程聚合(sales_leads.thread 依赖)
    session_id: Mapped[str | None] = mapped_column(String(64))

    # Phase 3 预留
    cluster_id: Mapped[str | None] = mapped_column(String(100))
    gap_status: Mapped[str | None] = mapped_column(String(20))
    override_answer: Mapped[str | None] = mapped_column(Text)

    # 多站点 Widget(MSW):站点体验标识;channel 保持传输语义(widget),站点仅作
    # 分析维度。nullable —— legacy 嵌入与无站点上下文的对话为 NULL。
    site_id: Mapped[str | None] = mapped_column(String(100))

    clicks: Mapped[list["SourceClick"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", lazy="raise"
    )
    traces: Mapped[list["Trace"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Trace.conversation_id",
    )


class Trace(Base):
    """单轮 RAG/澄清/拒答的执行 trace,1 conversation : N trace。"""

    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prev_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="SET NULL"),
        nullable=True,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="rag")
    stages: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    total_ms: Mapped[int | None] = mapped_column(Integer)
    intent: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="traces")
    prev_trace: Mapped["Trace | None"] = relationship(
        remote_side="Trace.id", foreign_keys=[prev_trace_id]
    )


class BusinessSignal(Base):
    """业务信号聚类(场景应用/产品需求),LLM 后处理批跑产出。"""

    __tablename__ = "business_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pct: Mapped[float] = mapped_column(Float, default=0.0)
    sample_conversation_ids: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceClick(Base):
    __tablename__ = "source_clicks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product: Mapped[str | None] = mapped_column(String(50))
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="clicks")


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_deleted: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(20), default="cron")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sync_interval: Mapped[str] = mapped_column(String(20), default="24h")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ---- S0 源生命周期契约(#18 前置;词汇表/判定原语见
    # backend/services/source_lifecycle.py,删除编排不在本列语义内)----
    # lifecycle_state:NULL = ACTIVE(既有行默认态,零回填);持久化值仅
    # delete_requested / deleting / delete_failed。删除成功 = 整行删除,
    # 无 DELETED tombstone。
    lifecycle_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lifecycle_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifecycle_error: Mapped[str | None] = mapped_column(Text)


class SyncRequest(Base):
    """同步执行交接请求(阶段⑨ AC6 容器级隔离)。

    ONLINE PLANE(backend 容器)触发同步时只写一行 ``pending`` 请求;
    独立 ``sync-executor`` 容器(部署级独立于 backend 生命周期)轮询领用
    并以子进程运行 ``scripts/sync.py``。backend 容器重启/重建/换镜像
    不影响交接队列与进行中的同步。

    语义边界:
    - ``status``(done/failed)是**交接/进程级**结果(runner 进程退出码),
      业务成败以 ``sync_log`` 为准(JOB SUCCESS ≠ KNOWLEDGE HEALTH);
    - ``source_id IS NULL`` 表示同步全部启用源(sync-all);
    - 本表**不是** SyncRun 模型:无 stage 计数 / 心跳 / 进度统计,
      中断恢复也属阶段⑩(执行面重启时遗留 ``running`` 行诚实标记 failed)。
    """

    __tablename__ = "sync_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runner_exit_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # ---- 阶段⑩ 恢复字段(持久状态仍四态;INTERRUPTED/RETRYING 为派生呈现态) ----
    # attempt_count:实际启动过的 runner 次数(首次启动=1);MAX_TOTAL_ATTEMPTS=4。
    # failure_kind:机器可判断的失败种类(interrupted/spawn_failed/runner_failed;
    #   terminal 终态以 status=failed + attempt 用尽表达,不入本列)。
    # next_retry_at:恢复重试到期时间;非空且未到 → claim_next 不可领取。
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_kind: Mapped[str | None] = mapped_column(String(20))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 被中断 attempt 的执行开始时间(恢复证据锚):reconcile 安排恢复时保留,
    # 供重试启动前的孤儿完成复检锚定——retry claim 会覆盖 picked_at,不能用它
    # 当证据边界(Planner FINAL REVIEW CORRECTION B)。
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    """同步运行可观测性(⑪+⑫ Wave-0 共享核心)。

    一行 = **ONE SOURCE × ONE ATTEMPT** 的运行真相,由 sync.py 业务进程
    单写者维护(executor 只在对账时把孤儿 running 行盖章为 interrupted/
    completed——服从而非复刻阶段⑩恢复裁决):

    - ``sync_requests`` 仍是执行交接/恢复权威(阶段⑨/⑩谓词零改动);
    - ``sync_log`` 仍是业务历史结局(SyncRun 不参与任何恢复判定);
    - ``sync_runs`` 只承担运行期遥测:attempt start / stage / progress /
      terminal outcome,供读时派生 Health 与 Progress(Wave-0 不做派生 UI)。

    进度语义:``stage_total IS NULL`` 表示分母未知(如增量抓取未 materialize),
    此时**禁止**计算百分比,只允许呈现真实计数(stage_current)。
    """

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recovery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(20), default="cron", nullable=False)
    # running / completed / failed / interrupted(QUEUED/WAITING/RECOVERING/IDLE
    # 是由 sync_requests + 本表派生的呈现态,不持久化虚假行)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    stage: Mapped[str | None] = mapped_column(String(20))
    stage_current: Mapped[int | None] = mapped_column(Integer)
    stage_total: Mapped[int | None] = mapped_column(Integer)
    counters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    consistency: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_summary: Mapped[str | None] = mapped_column(Text)
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # W2 运行时事实(全部可空,NULL=未知,读侧禁止推断):
    #   execution_device ∈ {gpu, cpu, gpu_to_cpu}(词表见 sync_runs 服务;
    #   gpu_to_cpu = 本次运行发生过自动降级且最终以 CPU 完成);
    #   fallback_reason = 机器可读原因码(cuda_init_failure / cuda_oom …,
    #   由 W1 写入);fallback_detail = 人类可读补充,绝不作为状态判断依据。
    execution_device: Mapped[str | None] = mapped_column(String(16))
    fallback_reason: Mapped[str | None] = mapped_column(String(32))
    fallback_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # FINAL REVIEW CORRECTION C:(request_id, source_id, attempt) 对请求托管
    # 运行在 DB 层强制唯一(部分唯一索引,仅 request 非空生效);NULL 直跑
    # (cron/CLI)不受约束,同源同 attempt 多次独立运行合法。
    __table_args__ = (
        Index(
            "uq_sync_runs_request_source_attempt",
            "request_id",
            "source_id",
            "attempt",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL"),
        ),
    )


class Customization(Base):
    __tablename__ = "customizations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style_tone: Mapped[str | None] = mapped_column(Text)
    guardrails: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="auto")
    assistant_name: Mapped[str] = mapped_column(String(50), default="CamThink 助手")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomizationBinding(Base):
    __tablename__ = "customization_bindings"

    channel: Mapped[str] = mapped_column(String(20), primary_key=True)
    customization_id: Mapped[str] = mapped_column(
        ForeignKey("customizations.id", ondelete="CASCADE")
    )


class AnswerOverride(Base):
    __tablename__ = "answer_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(String(20), default="semantic")
    override_answer: Mapped[str] = mapped_column(Text, nullable=False)
    override_sources: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    created_by: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    password_hash: Mapped[str | None] = mapped_column(String(255))  # bcrypt 哈希
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LLMProviderModel(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMRouting(Base):
    __tablename__ = "llm_routing"

    task: Mapped[str] = mapped_column(String(50), primary_key=True)
    chain: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMAllowedHost(Base):
    """LLM 自定义端点显式授权(管理员通过产品工作流维护,持久化可审查)。

    host: 小写主机名或 IP 字面量(不含 scheme/port),精确匹配,无通配符。
    allow_private: True = 私有/内网端点授权(允许私有 IP 字面量与内网 http),
                   由授权时的主机形态自动判定,不可手工改。
    """

    __tablename__ = "llm_allowed_hosts"

    host: Mapped[str] = mapped_column(String(255), primary_key=True)
    allow_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteExperience(Base):
    """站点体验身份(MSW:ONE Widget + 多站点体验)。

    site_id 是**标识符**而非凭证:授权 = 站点存在且 enabled + 请求 Origin 归一化
    后精确命中 ``allowed_origins``(服务端校验,CORS 仅为浏览器执行层)。
    与 CustomizationBinding(channel 传输定制)语义分离,互相不重载。
    """

    __tablename__ = "site_experiences"

    site_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed_origins: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    starters: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    welcome: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(10))
    # ML 闭环(G-L5):按语言键的体验文案变体(如 {"zh": ...});站点身份与
    # 默认字段语义不变,变体缺失时回落默认(站点身份独立于语言)
    welcome_i18n: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    starters_i18n: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Issue #24:launcher 外观(per-site;NULL = 未配置 → 兼容默认 current|auto)。
    # 种子(seed_default_sites)不写这两列:Admin 独立持久值跨 YAML 重启存续。
    launcher_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    launcher_theme: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Issue #24 REV1:统一外观模型 icon × shape × theme 持久列(加列、零回填)。
    # launcher_style 冻结为 REV0 遗留(回滚保真:旧应用只读它,不受 REV1 写入影响);
    # 有效图标 = launcher_icon 优先,遗留 launcher_style 值退役回落 current。
    launcher_icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    launcher_shape: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuestionCluster(Base):
    """问题聚类结果(Phase 3B Coverage Gaps + Top Questions)。"""

    __tablename__ = "question_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'gap' | 'top'
    representative_question: Mapped[str] = mapped_column(Text, nullable=False)
    sample_questions: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # 'open' | 'resolved' (仅 gap)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Attachment(Base):
    """聊天附件(日志/截图),作为会话补充上下文。

    Phase 1a 仅处理日志(kind="log");图片(kind="image")字段预留,1b 接入 vision。
    """

    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)  # widget_anon | admin
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # log | image
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation | None"] = relationship(back_populates="attachments")


class SalesLead(Base):
    """销售线索(Sales Lead)——独立于 Conversation 的一等业务对象。

    产品契约(CAMTHINK V1 Sales Lead Capture & Handoff):
    - Conversation 回答「AI 聊得怎么样」,SalesLead 回答「哪些客户值得跟进」;
      线索必须能关联原会话(source_conversation_id / last_conversation_id / session_id)。
    - 生命周期:potential → qualified → contact_captured → handed_off(管理员手动
      移交为终态;自动流程只升不降,见 backend/pipeline/lead_qualify.compute_status)。

    隐私边界(HARD):contact_value 等联系方式 PII 只落本表(PostgreSQL,
    仅授权 Admin 经 /api/admin/leads 访问);绝不进入 Knowledge Corpus /
    Weaviate / RAG。对外展示一律用 contact_masked。

    不设到 conversations 的外键:线索生命周期独立于对话保留策略,
    会话行被清理不应级联删除商业线索。
    """

    __tablename__ = "sales_leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 线索线程键:widget 匿名会话 ID(一轮问不出联系方式、后续轮补充的场景靠它聚合)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="potential", index=True)

    # 联系方式(PII,仅此表持有原文;contact_value 最长 RFC 邮箱 320)
    contact_type: Mapped[str | None] = mapped_column(
        String(20)
    )  # email|phone|whatsapp|wechat|other
    contact_value: Mapped[str | None] = mapped_column(String(320))
    contact_masked: Mapped[str | None] = mapped_column(String(80))
    contact_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 商业画像(用户自愿提供,允许全空)
    name: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(200))
    product_interest: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[str | None] = mapped_column(String(100))
    use_case: Mapped[str | None] = mapped_column(Text)
    purchase_intent: Mapped[str | None] = mapped_column(String(50))
    timeline: Mapped[str | None] = mapped_column(String(100))
    ai_summary: Mapped[str | None] = mapped_column(Text)

    # One-Proactive-Ask 记账:AI 已主动邀请次数与最近邀请时间(契约 §7)
    prompt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 会话关联(无外键,见类注释)
    source_conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    last_conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    channel: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str | None] = mapped_column(String(10))

    # 手动移交销售(admin/editor 触发)
    handoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_by: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# 索引(对齐设计文档 §11 SQL DDL)
Index("idx_sales_leads_status_created", SalesLead.status, SalesLead.created_at.desc())
Index("idx_conversations_created_at", Conversation.created_at)
Index("idx_conversations_is_answered", Conversation.is_answered)
Index("idx_conversations_channel", Conversation.channel)
Index("idx_conversations_site", Conversation.site_id)
Index("idx_conversations_session_id", Conversation.session_id)
Index(
    "idx_conversations_cluster_id",
    Conversation.cluster_id,
    postgresql_where=text("cluster_id IS NOT NULL"),
)
Index(
    "idx_conversations_gap_status",
    Conversation.gap_status,
    postgresql_where=text("gap_status IS NOT NULL"),
)
Index("idx_source_clicks_conversation", SourceClick.conversation_id)
Index("idx_source_clicks_source_url", SourceClick.source_url)
Index("idx_sync_log_source", SyncLog.source_id, SyncLog.started_at.desc())
Index("idx_sync_log_status", SyncLog.status, SyncLog.started_at.desc())
Index("idx_question_clusters_type_status", QuestionCluster.cluster_type, QuestionCluster.status)
Index(
    "idx_question_clusters_type_count",
    QuestionCluster.cluster_type,
    QuestionCluster.question_count.desc(),
)
