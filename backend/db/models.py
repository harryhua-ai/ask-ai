"""SQLAlchemy ORM 模型定义。

包含 11 张表(对齐设计文档 §11 SQL DDL + 灌入管道需要的 documents 表):
- documents: 已灌入文档元数据(content_hash 去重,灌入管道维护)
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

    用 ``(content_hash, branch)`` 复合主键实现 doc 级去重:同内容跨分支各留一行,同分支重复灌入仅更新
    chunk_count 与 updated_at,避免 Postgres 行膨胀。chunk 级数据落在
    Weaviate,本表只承担"哪些文档已灌入 / 何时被灌入 / 灌了多少 chunk"
    的索引职责,供同步脚本与未来管理界面使用。
    """

    __tablename__ = "documents"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    branch: Mapped[str] = mapped_column(String(100), default="", nullable=False, primary_key=True, index=True)
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

    # Phase 3 预留
    cluster_id: Mapped[str | None] = mapped_column(String(100))
    gap_status: Mapped[str | None] = mapped_column(String(20))
    override_answer: Mapped[str | None] = mapped_column(Text)

    clicks: Mapped[list["SourceClick"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", lazy="raise"
    )


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


# 索引(对齐设计文档 §11 SQL DDL)
Index("idx_conversations_created_at", Conversation.created_at)
Index("idx_conversations_is_answered", Conversation.is_answered)
Index("idx_conversations_channel", Conversation.channel)
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
Index(
    "idx_question_clusters_type_status", QuestionCluster.cluster_type, QuestionCluster.status
)
Index(
    "idx_question_clusters_type_count",
    QuestionCluster.cluster_type,
    QuestionCluster.question_count.desc(),
)
