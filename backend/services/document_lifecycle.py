"""文档生命周期服务(P1 Lifecycle Foundation 地基)。

Trace B TB-P1(契约 docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md;
Freeze 97cac3f + 915b5f7)。本模块 = **词表 + 纯判定 + 会话级转换原语**:

- L 轴(document lifecycle)与 P 轴(generation processing)词表;
- 变更类别判定(FC-6:UNCHANGED / METADATA_CHANGED / CONTENT_CHANGED;
  NEW_VERSION / SUPERSEDED 为激活事务中的接替动词);
- 激活 / 墓碑 / 恢复 / 接替(alias)/ 缺席候选等转换原语(带前置条件,
  供 P2 消费,P2 无需发明新存储语义);
- active generation 集合计算(服务选择唯一权威:documents.current_version_id
  关系 → document_versions.generation_ordinal);
- 生成行管理(ordinal 分配 / ready / 失败证据 / 撤出退休与 7 天 GC 资格)。

红线(实现不得违反):
- P 轴无 ACTIVE 处理态;激活 = current_version 关系翻转,不新增状态(FC-3);
- 接替时序:替代权威确立瞬间旧知识失去现势;服务撤出 ≤1 天(本模型为
  激活事务提交即时撤出);retired 保留 7 天后可自动物理 GC(Freeze §8a);
- 墓碑 = 逻辑删除;物理清除仅经 GC 接口;墓碑专项窗不设隐式默认(30 天
  默认已废除,禁止回用;运营化归 P5);
- 禁止从向量索引反推任何生命周期事实(权威 = Postgres,I-1)。
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Document, DocumentVersion, IndexGeneration

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 词表(冻结;与 Freeze I-2/S2 §2 四轴模型对齐)
# --------------------------------------------------------------------------- #


class DocLifecycle:
    """L 轴文档生命周期词表。"""

    DISCOVERED = "discovered"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    MISSING_CANDIDATE = "missing_candidate"
    DELETED = "deleted"

    ALL = (DISCOVERED, ACTIVE, SUPERSEDED, MISSING_CANDIDATE, DELETED)
    # 可从墓碑/缺席恢复回 active 的状态(P2 消失确认将消费)
    RECOVERABLE = (MISSING_CANDIDATE, DELETED)
    # 不再计为现役知识的持久状态(服务集/计数排除;对象待 GC)
    WITHDRAWN = (SUPERSEDED, DELETED)
    # 仍在服务集的生命周期(active generation 集合计算口径):
    # MISSING_CANDIDATE 处于缺席宽限,保上一代继续服务(冻结语义;
    # 检索资格派生式 L=ACTIVE ∧ … 的 ACTIVE 泛指"未被撤出"的服务生命期)。
    SERVING = (ACTIVE, MISSING_CANDIDATE)


class GenerationStatus:
    """P 轴索引生成处理状态词表(无 ACTIVE;激活=关系不是状态,FC-3)。"""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    RETIRED = "retired"

    ALL = (PENDING, PROCESSING, READY, FAILED, RETIRED)
    # 建构中(未到 READY 的状态)
    BUILDING = (PENDING, PROCESSING)


class ChangeClass:
    """变更类别(FC-6)。NEW_VERSION / SUPERSEDED 是激活事务的接替动词,
    由 activate_document_version 施加;classify 只产出前三类。"""

    UNCHANGED = "unchanged"
    METADATA_CHANGED = "metadata_changed"
    CONTENT_CHANGED = "content_changed"
    NEW_VERSION = "new_version"
    SUPERSEDED = "superseded"


# Freeze §8a 冻结时序:RETIRED 保留 7 天后可自动物理 GC。
# 原 D-3「默认 30 天」已被取代,禁止以任何形式回用为现役默认。
RETIRED_RETENTION_DAYS = 7

# 服务撤出 deadline(接替时序 §8a):本模型为激活事务提交即时撤出
# (active 集不再含前任代),恒 ≤ 该上限;常量用于审计与测试断言。
SERVING_WITHDRAWAL_MAX_DAYS = 1

# 迁移初始代(legacy 对象寻址不变;ordinal=0):
# 确定性 UUID,迁移幂等的锚 —— 重复迁移不会产生第二个初始代。
LEGACY_GENERATION_ORDINAL = 0
LEGACY_GENERATION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "ask-ai:p1:legacy-initial-generation")


def utcnow() -> datetime:
    """统一 UTC now(测试可 monkeypatch 时间敏感路径)。"""
    return datetime.now(UTC)


def compute_metadata_hash(
    *,
    title: str,
    url: str,
    branch: str,
    source_type: str,
    product: str,
    metadata: dict[str, Any] | None,
    channel_visibility: tuple[str, ...] | list[str],
) -> str:
    """文档级元数据指纹(FC-5:metadata-only 变更不分叉身份/不重嵌)。

    覆盖灌入 Weaviate 对象 props 的全部文档级字段(chunk 级字段除外);
    JSONB 按排序键序列化,保证等价元数据 → 同一哈希。
    """
    payload = json.dumps(
        {
            "title": title,
            "url": url,
            "branch": branch,
            "source_type": source_type,
            "product": product,
            "metadata": metadata or {},
            "channel_visibility": list(channel_visibility),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def metadata_hash_of_version_row(doc: Document, version: DocumentVersion | None) -> str:
    """账本行(现值)的元数据指纹(与 compute_metadata_hash 同口径)。"""
    meta = doc.metadata_ if isinstance(doc.metadata_, dict) else {}
    cv = meta.get("channel_visibility") or []
    return compute_metadata_hash(
        title=doc.title,
        url=doc.url,
        branch=doc.branch or "",
        source_type=doc.source_type,
        product=doc.product,
        metadata={k: v for k, v in meta.items() if k != "channel_visibility"},
        channel_visibility=cv,
    )


def extract_source_version(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """从 RawDocument.metadata 渐进提取源原生版本元数据(不重设计连接器)。

    已知键(git/web/woo/fs);缺失 → None(诚实未知)。纯读取,零连接器改动。
    """
    if not isinstance(metadata, dict):
        return None
    keys = ("commit_sha", "lastmod", "date_modified", "mtime", "etag", "size", "sha")
    found = {k: metadata[k] for k in keys if metadata.get(k) is not None}
    return found or None


# --------------------------------------------------------------------------- #
# 生成代管理(P 轴)
# --------------------------------------------------------------------------- #


def ensure_legacy_generation(session: Session, *, now: datetime | None = None) -> IndexGeneration:
    """确保迁移初始代存在(幂等;迁移与 repair 原语共用)。"""
    row = session.execute(
        select(IndexGeneration).where(IndexGeneration.id == LEGACY_GENERATION_ID)
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = IndexGeneration(
        id=LEGACY_GENERATION_ID,
        ordinal=LEGACY_GENERATION_ORDINAL,
        source_id="*legacy*",
        status=GenerationStatus.READY,
        ready_at=now or utcnow(),
        activated_at=now or utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def create_generation(session: Session, source_id: str, *, now: datetime | None = None) -> IndexGeneration:
    """新建构建代(ordinal = 当前最大 + 1;行锁防并发分配冲突)。"""
    legacy = ensure_legacy_generation(session, now=now)
    # FOR UPDATE 不可作用于聚合(PG FeatureNotSupported):锁最大 ordinal 行
    # 串行化分配;空表回退锁 legacy 行(ensure 已建,恒存在)。
    top = session.execute(
        select(IndexGeneration)
        .order_by(IndexGeneration.ordinal.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    base = int(top.ordinal) if top is not None else -1
    row = IndexGeneration(
        ordinal=max(base, LEGACY_GENERATION_ORDINAL) + 1,
        source_id=source_id,
        status=GenerationStatus.PROCESSING,
    )
    session.add(row)
    session.flush()
    _ = legacy  # ensure 已存在(幂等锚)
    return row


def mark_generation_ready(
    session: Session, gen: IndexGeneration, *, doc_count: int, chunk_count: int, now: datetime | None = None
) -> None:
    """构建+验证通过 → ready(验证在激活前,Freeze I-5)。"""
    gen.status = GenerationStatus.READY
    gen.ready_at = now or utcnow()
    gen.doc_count = doc_count
    gen.chunk_count = chunk_count
    session.flush()


def mark_generation_failed(
    session: Session, gen: IndexGeneration, failure: dict[str, Any], *, now: datetime | None = None
) -> None:
    """构建/验证失败 → failed(失败证据持久化;在服代不受影响)。"""
    gen.status = GenerationStatus.FAILED
    gen.failure = failure
    session.flush()
    _ = now


def retire_generation_if_withdrawn(session: Session, gen_id: uuid.UUID, *, now: datetime | None = None) -> bool:
    """服务撤出完成判定:生成代已无任何 active 版本引用 → retired。

    "撤出"语义:激活事务提交后,active 服务集(见 active_generation_ordinals)
    即不再包含前任代(即时撤出,≤1 天 deadline 恒满足);本原语在撤出后
    将代转 retired 并记 GC 资格时刻(retired + 7 天,§8a)。
    """
    ts = now or utcnow()
    gen = session.execute(select(IndexGeneration).where(IndexGeneration.id == gen_id)).scalar_one_or_none()
    if gen is None or gen.status != GenerationStatus.READY:
        return False
    live = session.execute(
        select(func.count())
        .select_from(DocumentVersion)
        .where(
            DocumentVersion.generation_id == gen_id,
            DocumentVersion.status == "active",
        )
    ).scalar()
    if int(live or 0) > 0:
        return False
    gen.status = GenerationStatus.RETIRED
    gen.withdrawn_at = ts
    gen.retired_at = ts
    gen.gc_eligible_at = ts + timedelta(days=RETIRED_RETENTION_DAYS)
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# active generation 集合(服务选择唯一权威)
# --------------------------------------------------------------------------- #


def active_generation_ordinals_sync(session: Session) -> list[int]:
    """同步会话版:当前在服代序集合(服务过滤用)。

    权威关系:documents(current_version_id, lifecycle ∈ SERVING) →
    document_versions.generation_ordinal。墓碑/被接替文档即时退出本集合
    (激活/墓碑事务提交生效,满足 ≤1 天撤出上限);缺席候选宽限期内
    保上一代服务(不退出)。
    """
    rows = session.execute(
        select(DocumentVersion.generation_ordinal)
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(Document.lifecycle.in_(DocLifecycle.SERVING))
        .distinct()
    ).scalars().all()
    return sorted(int(o) for o in rows)


async def active_generation_ordinals(session_factory: Any) -> list[int]:
    """异步会话工厂版(检索路径 wiring 用;同一权威查询)。"""
    from backend.db.session import get_session_factory  # 避免环导:调用方多传工厂

    _ = get_session_factory
    async with session_factory() as session:
        return await active_generation_ordinals_async_session(session)


async def active_generation_ordinals_async_session(session: Any) -> list[int]:
    result = await session.execute(
        select(DocumentVersion.generation_ordinal)
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(Document.lifecycle.in_(DocLifecycle.SERVING))
        .distinct()
    )
    return sorted(int(o) for o in result.scalars().all())


# --------------------------------------------------------------------------- #
# 转换原语(带前置条件;P2 将直接消费,不得要求新存储语义)
# --------------------------------------------------------------------------- #


def load_document_and_current_version(
    session: Session, source_id: str
) -> tuple[Document | None, DocumentVersion | None]:
    doc = session.execute(select(Document).where(Document.source_id == source_id)).scalar_one_or_none()
    if doc is None or doc.current_version_id is None:
        return doc, None
    version = session.execute(
        select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
    ).scalar_one_or_none()
    return doc, version


def classify_change(doc: Document | None, version: DocumentVersion | None, incoming_hash: str, incoming_meta_hash: str) -> str:
    """变更类别判定(FC-6;权威 = Postgres 现行版本,不读向量索引)。"""
    if doc is None or version is None:
        return ChangeClass.NEW_VERSION
    if version.content_hash != incoming_hash:
        return ChangeClass.CONTENT_CHANGED
    if version.metadata_hash != incoming_meta_hash:
        return ChangeClass.METADATA_CHANGED
    return ChangeClass.UNCHANGED


def next_version_seq(session: Session, source_id: str) -> int:
    current_max = session.execute(
        select(func.max(DocumentVersion.version_seq)).where(DocumentVersion.source_id == source_id)
    ).scalar()
    return int(current_max or 0) + 1


def activate_document_version(
    session: Session,
    doc: Document,
    new_version: DocumentVersion,
    *,
    now: datetime | None = None,
) -> DocumentVersion | None:
    """原子激活(单事务内由调用方提交):new_version 成为唯一现役版本。

    施加 FC-6 接替动词:
    - 前任 current 版本:status active→superseded,valid_to/superseded_by 留痕
      (ChangeClass.SUPERSEDED);
    - new_version:status='active',valid_from=now;
    - documents.current_version_id → new_version(服务选择随之翻转);
      content_hash/chunk_count/title/url 同步为现役值;
    - lifecycle 恢复:deleted/missing_candidate/discovered → active(墓碑撤销
      /重新出现原语语义,激活路径内置);
    返回被接替的前任版本(无则 None,首灌)。
    原子性:本函数只在内存对象上变更,由调用方在同一事务 commit —— 服务
    视角要么旧版要么新版,绝无混合(契约 Gate P1-D)。
    """
    ts = now or utcnow()
    previous: DocumentVersion | None = None
    if doc.current_version_id is not None:
        previous = session.execute(
            select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
        ).scalar_one_or_none()
    if previous is not None and previous.id != new_version.id:
        previous.status = ChangeClass.SUPERSEDED if previous.status == "active" else previous.status
        previous.valid_to = ts
        previous.superseded_by_version_id = new_version.id
    new_version.status = "active"
    if new_version.valid_from is None:
        new_version.valid_from = ts
    doc.current_version_id = new_version.id
    doc.content_hash = new_version.content_hash
    doc.chunk_count = new_version.chunk_count
    doc.title = new_version.title
    doc.url = new_version.url
    if doc.lifecycle != DocLifecycle.ACTIVE:
        doc.lifecycle = DocLifecycle.ACTIVE
        doc.deleted_at = None
        doc.superseded_at = None
        doc.superseded_by = None
    session.flush()
    return previous


def tombstone_document(
    session: Session, source_id: str, *, reason: str = "", now: datetime | None = None
) -> bool:
    """墓碑原语(逻辑删除,非物理):lifecycle→deleted,退出服务集。

    前置条件:存在文档行且尚未墓碑(幂等:已 deleted → False)。
    物理清除仅经 GC 接口(窗值不设隐式默认,运营化归 P5)。
    """
    ts = now or utcnow()
    doc = session.execute(select(Document).where(Document.source_id == source_id)).scalar_one_or_none()
    if doc is None or doc.lifecycle == DocLifecycle.DELETED:
        return False
    doc.lifecycle = DocLifecycle.DELETED
    doc.deleted_at = ts
    doc.superseded_at = None
    doc.superseded_by = None
    session.flush()
    logger.info("墓碑生效 %s(逻辑删除,reason=%s);物理清除仅经 GC", source_id, reason)
    return True


def restore_document(session: Session, source_id: str, *, now: datetime | None = None) -> bool:
    """恢复原语:deleted/missing_candidate → active(墓碑撤销/重新出现)。

    前置条件:存在文档行且处于可恢复态;current 版本保持不变(其对象若已
    被 GC,由重建/repair 路径负责再物化——本原语只管生命周期)。
    """
    _ = now
    doc = session.execute(select(Document).where(Document.source_id == source_id)).scalar_one_or_none()
    if doc is None or doc.lifecycle not in DocLifecycle.RECOVERABLE:
        return False
    doc.lifecycle = DocLifecycle.ACTIVE
    doc.deleted_at = None
    session.flush()
    return True


def mark_missing_candidate(session: Session, source_id: str, *, now: datetime | None = None) -> bool:
    """缺席候选原语(P1 只落地状态与转换;缺席**确认**策略归 P2)。"""
    _ = now
    doc = session.execute(select(Document).where(Document.source_id == source_id)).scalar_one_or_none()
    if doc is None or doc.lifecycle in (DocLifecycle.DELETED, DocLifecycle.SUPERSEDED):
        return False
    doc.lifecycle = DocLifecycle.MISSING_CANDIDATE
    session.flush()
    return True


def set_successor(session: Session, old_source_id: str, new_source_id: str, *, now: datetime | None = None) -> bool:
    """接替/别名地基原语(D-5):旧身份 → superseded,记 successor。

    前置条件:双方存在;旧身份未墓碑;不自接(new != old);幂等:已是
    同一 successor → False。被接替文档即时退出服务集(同撤出时序)。
    """
    ts = now or utcnow()
    if old_source_id == new_source_id:
        return False
    old_doc = session.execute(select(Document).where(Document.source_id == old_source_id)).scalar_one_or_none()
    new_doc = session.execute(select(Document).where(Document.source_id == new_source_id)).scalar_one_or_none()
    if old_doc is None or new_doc is None or old_doc.lifecycle == DocLifecycle.DELETED:
        return False
    if old_doc.superseded_by == new_source_id and old_doc.lifecycle == DocLifecycle.SUPERSEDED:
        return False
    old_doc.lifecycle = DocLifecycle.SUPERSEDED
    old_doc.superseded_by = new_source_id
    old_doc.superseded_at = ts
    session.flush()
    return True


def ensure_initial_version(
    session: Session,
    doc: Document,
    *,
    generation_id: uuid.UUID | None = None,
    generation_ordinal: int | None = None,
    now: datetime | None = None,
) -> DocumentVersion:
    """为无版本的账本行补建初始版本(迁移 / 账本修复原语共用;幂等)。

    迁移路径传 legacy 代(ordinal=0,对象寻址不变);修复路径(repair/reconcile
    重建账本行)同样落 legacy 代,保持"每文档恒有 current 版本"不变量。
    """
    if doc.current_version_id is not None:
        existing = session.execute(
            select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    if generation_id is None:
        ensure_legacy_generation(session, now=now)
        generation_id = LEGACY_GENERATION_ID
        generation_ordinal = LEGACY_GENERATION_ORDINAL
    meta = doc.metadata_ if isinstance(doc.metadata_, dict) else {}
    cv = meta.get("channel_visibility") or []
    version = DocumentVersion(
        source_id=doc.source_id,
        version_seq=next_version_seq(session, doc.source_id),
        content_hash=doc.content_hash,
        metadata_hash=compute_metadata_hash(
            title=doc.title,
            url=doc.url,
            branch=doc.branch or "",
            source_type=doc.source_type,
            product=doc.product,
            metadata={k: v for k, v in meta.items() if k != "channel_visibility"},
            channel_visibility=cv,
        ),
        generation_id=generation_id,
        generation_ordinal=int(generation_ordinal or LEGACY_GENERATION_ORDINAL),
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=int(doc.chunk_count or 0),
        valid_from=doc.created_at or (now or utcnow()),
    )
    session.add(version)
    session.flush()
    doc.current_version_id = version.id
    session.flush()
    return version
