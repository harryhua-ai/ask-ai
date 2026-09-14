"""V1.6.3 Wave 2 Integration 阶段 1 — INT 义务回归(INT-C-01..04 / INT-SYS-01)。

Independent Review 收口义务的硬性回归(义务来源:Wave-1 Independent Review
转述;语义权威:track-c/track-e 冻结合同 + U-15 状态机不变量):

- INT-C-01(BLOCKING):document_repair 回写 = 现行版本**在服代命名空间**
  (generation uuid + generation_id/generation_ordinal props);复验口径同步
  在服代;legacy/非在服 chunk 不计成功修复;幂等。回归口径:**before 修复 →
  在服代过滤检索 miss 目标;after → 同一过滤检索命中**;collection 替身带
  generation 语义(uuid 寻址 + generation_ordinal props),禁无 generation
  语义的 fake。
- INT-C-02:channel_visibility 以持久 chunk props 为底恢复(去硬编码与
  overlay 跳过);受限渠道源修复不得扩权。
- INT-C-03:freshness_hours 写入收敛冻结词表(6/12/24/72/168),非法值 422
  fail-loud;CURRENT/HISTORICAL 语义零变化。
- INT-C-04:policy_impact_counts/ledger_fingerprint LIKE 通配符转义;
  含 %/_ 的 source_id 不扩查询。
- INT-SYS-01(BLOCKING):遗留 PATCH /analytics/gaps/{id}/resolve 收敛为
  U-15 状态机 thin-wrapper —— 直接强转 RESOLVED 不可能(open/observing/
  resolved 三态全覆盖)、无悬挂 active observation、转移留痕可审计。
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    GapObservation,
    GapObservationEvent,
    IndexGeneration,
    QuestionCluster,
    User,
)
from backend.main import app
from backend.pipeline.ingest import (
    _deterministic_uuid,
    generation_uuid,
)
from backend.services.document_repair import (
    STATUS_SUCCEEDED,
    create_repair_task,
    execute_repair_task,
)
from backend.services.knowledge_policy import (
    DEFAULT_FRESHNESS_HOURS,
    FRESHNESS_CHOICES_HOURS,
    effective_freshness_hours,
    ledger_fingerprint,
    policy_impact_counts,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = f"intwave2-{uuid.uuid4().hex[:10]}"
NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# 基础设施:generation-语义 collection 替身(uuid 寻址 + generation props)
# --------------------------------------------------------------------------- #


class GenerationAwareCollection:
    """weaviate v4 collection 替身(**带 generation 语义**):

    - 对象按 uuid 寻址存储(insert 服从 uuid5 命名空间语义);
    - properties 保留完整 dict(含 generation_ordinal/generation_ordinal);
    - iterator 支持在服代过滤所需的 return_properties;
    - 语义与真实 Weaviate 同构:检索/投影按对象属性过滤。
    """

    def __init__(self) -> None:
        # uuid → {properties, vector}
        self.objects: dict[str, dict] = {}

    def iterator(self, return_properties=None, **kw):
        def _gen():
            for u, obj in self.objects.items():
                props = dict(obj["properties"])
                if return_properties:
                    props = {k: props.get(k) for k in return_properties}
                yield SimpleNamespace(properties=props, uuid=u)

        return _gen()

    @property
    def data(self):
        coll = self

        class _Data:
            def insert(self, *, properties, vector, uuid):
                coll.objects[uuid] = {"properties": dict(properties), "vector": vector}
                return uuid

        return _Data()


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


def _filtered_serving(collection, doc_source_id, total, gen_ordinal):
    """在服代过滤检索(INT-C-01 回归口径):与生产 _generation_ordinal_filter
    同一判定谓词(generation_ordinal INT 精确匹配)下的在服 chunk_index 集。"""
    present: set[int] = set()
    for item in collection.iterator(
        return_properties=["source_id", "chunk_index", "generation_ordinal"]
    ):
        props = item.properties
        if str(props.get("source_id")) != doc_source_id:
            continue
        if props.get("generation_ordinal") != gen_ordinal:
            continue  # 非在服代 → 检索不可见
        present.add(int(props["chunk_index"]))
    return present & set(range(total))


async def _seed_doc_version(session, *, doc_id, gen, ordinal, chunk_count=12, channel="widget"):
    """播种:1 文档 + active 版本(代归属)+ 持久 chunk 副本(props 含
    channel_visibility 持久真值)。返回 (doc, version)。"""
    version = DocumentVersion(
        source_id=doc_id,
        version_seq=1,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=gen.id,
        generation_ordinal=ordinal,
        status="active",
        title=doc_id.rsplit("/", 1)[-1],
        url=f"https://s.example.com/{doc_id.rsplit('/', 1)[-1]}",
        chunk_count=chunk_count,
    )
    session.add(version)
    await session.flush()
    for i in range(chunk_count):
        session.add(
            DocumentVersionChunk(
                version_id=version.id,
                chunk_index=i,
                text=f"{doc_id}#chunk-{i}",
                props={
                    "source_id": doc_id,
                    "source_type": "github",
                    "chunk_index": i,
                    "channel_visibility": [channel],
                },
            )
        )
    doc = Document(
        source_id=doc_id,
        content_hash="c" * 64,
        source_type="github",
        product="int",
        title=doc_id.rsplit("/", 1)[-1],
        url=f"https://s.example.com/{doc_id.rsplit('/', 1)[-1]}",
        branch="",
        chunk_count=chunk_count,
        lifecycle="active",
        current_version_id=version.id,
    )
    session.add(doc)
    await session.flush()
    return doc, version


@pytest_asyncio.fixture(loop_scope="session")
async def int_seed():
    """播种:数据源 + 在服代(ordinal=N>0)+ 一文档(12 chunk 持久副本)。

    Weaviate 替身内只放**legacy 命名空间的 10 个残片**(无 generation props,
    旧代迁移残留语义)→ 在服代过滤检索 miss 全部 12 个目标(修复前真值)。"""
    factory = app.state.session_factory
    collection = GenerationAwareCollection()
    client = SimpleNamespace(collections=SimpleNamespace(get=lambda _n: collection))
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    app.state.weaviate_client = client
    app.state.embedder = _FakeEmbedder()
    app.state.weaviate_class_name = "Document"

    ordinal = 100_000_000 + (uuid.uuid4().int % 900_000)
    async with factory() as session:
        ds = DataSource(
            id=SRC,
            type="github",
            product="int",
            config={"repo": "x/y"},
            sync_interval="24h",
            enabled=True,
        )
        session.add(ds)
        gen = IndexGeneration(ordinal=ordinal, source_id=SRC, status="ready")
        session.add(gen)
        await session.flush()
        doc_id = f"{SRC}/main/guide.md"
        doc, version = await _seed_doc_version(
            session, doc_id=doc_id, gen=gen, ordinal=ordinal, channel="api"
        )
        # legacy 命名空间残片:10 个(0..9),无 generation props(检索不可见)
        for i in range(10):
            collection.objects[_deterministic_uuid(doc_id, i)] = {
                "properties": {"source_id": doc_id, "chunk_index": i},
                "vector": [0.0],
            }
        await session.commit()
        yield {
            "collection": collection,
            "doc_id": doc_id,
            "doc": doc,
            "version": version,
            "ordinal": ordinal,
            "gen_id": str(gen.id),
        }
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)
    from backend.db.models import DocumentRepairTask

    async with factory() as session:
        await session.execute(
            DocumentRepairTask.__table__.delete().where(
                DocumentRepairTask.source_id == SRC
            )
        )
        await session.execute(
            DocumentVersionChunk.__table__.delete().where(
                DocumentVersionChunk.version_id.in_(
                    select(DocumentVersion.id).where(
                        DocumentVersion.source_id.like(f"{SRC}/%")
                    )
                )
            )
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%"))
        )
        await session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.like(f"{SRC}/%")
            )
        )
        await session.execute(
            IndexGeneration.__table__.delete().where(IndexGeneration.source_id == SRC)
        )
        await session.execute(DataSource.__table__.delete().where(DataSource.id == SRC))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    factory = app.state.session_factory
    async with factory() as session:
        user = User(
            email=f"int-{uuid.uuid4().hex[:8]}@test.local",
            name="int",
            role="admin",
            password_hash=hash_password("test-password"),
            is_active=True,
        )
        session.add(user)
        await session.commit()
    token = create_access_token(str(user.id), user.role, app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# INT-C-01:generation-correct repair(hard regression)
# --------------------------------------------------------------------------- #


async def test_int_c01_repair_targets_serving_generation(int_seed):
    """修复前:在服代过滤检索 miss 全部 12 个目标(legacy 残片不可见);
    修复后:同一过滤检索命中 0..11;回写对象落在在服代 uuid 命名空间且携带
    generation props;任务 consistency=passed 只由在服代集合判定。"""
    factory = app.state.session_factory
    doc_id = int_seed["doc_id"]
    ordinal = int_seed["ordinal"]
    gen_id = int_seed["gen_id"]
    collection = int_seed["collection"]

    async with factory() as session:
        # ---- before:在服代过滤检索 miss 全部目标 ----
        assert _filtered_serving(collection, doc_id, 12, ordinal) == set()

        task, created = await create_repair_task(
            session, SRC, doc_id, requested_by="int@test", idempotency_key=f"key-{uuid.uuid4().hex}"
        )
        assert created is True
        done = await execute_repair_task(
            factory,
            weaviate_client=app.state.weaviate_client,
            embedder=app.state.embedder,
            class_name="Document",
            task_id=task.id,
        )
        assert done.status == STATUS_SUCCEEDED
        assert done.result["consistency"] == "passed"
        assert sorted(done.result["repaired_indices"]) == list(range(12))

        # ---- after:同一过滤检索命中全部修复目标 ----
        assert _filtered_serving(collection, doc_id, 12, ordinal) == set(range(12))

        # 回写对象:在服代命名空间 uuid + generation props
        for i in range(12):
            obj = collection.objects.get(generation_uuid(doc_id, gen_id, i))
            assert obj is not None, f"chunk {i} 未落在在服代命名空间 uuid"
            assert obj["properties"]["generation_ordinal"] == ordinal
            assert obj["properties"]["generation_id"] == gen_id
        # legacy 命名空间未被修复写触碰(残片原样,但也不计成功)
        assert _deterministic_uuid(doc_id, 11) not in collection.objects

        # 复验口径 = 在服代(chunk_serving_for_doc 带 generation 过滤)
        from backend.services.chunk_serving import chunk_serving_for_doc

        verify = chunk_serving_for_doc(
            app.state.weaviate_client, "Document", doc_id, 12, generation_ordinals=(ordinal,)
        )
        assert verify.consistent is True


async def test_int_c01_legacy_objects_not_counted_as_success(int_seed):
    """禁把 legacy/非在服 chunk 计为成功修复:即便 legacy 命名空间已有
    10 个残片,在服代投影仍 miss;修复不会以 legacy 残片凑满一致性。"""
    doc_id = int_seed["doc_id"]
    ordinal = int_seed["ordinal"]

    from backend.services.chunk_serving import chunk_serving_for_doc

    # legacy 残片存在但非在服代 → 投影不认(修复前 serving=0,非 10)
    proj = chunk_serving_for_doc(
        app.state.weaviate_client, "Document", doc_id, 12, generation_ordinals=(ordinal,)
    )
    assert proj.serving_chunks == 0
    assert proj.missing_indices == tuple(range(12))


async def test_int_c01_repair_idempotent_rerun(int_seed):
    """幂等:重复修复 = 复验 no-op(0 重灌,复验通过),零重复写。"""
    factory = app.state.session_factory
    doc_id = int_seed["doc_id"]
    collection = int_seed["collection"]

    async with factory() as session:
        task, _ = await create_repair_task(
            session, SRC, doc_id, requested_by="int@test", idempotency_key=f"key2-{uuid.uuid4().hex}"
        )
        first = await execute_repair_task(
            factory,
            weaviate_client=app.state.weaviate_client,
            embedder=app.state.embedder,
            class_name="Document",
            task_id=task.id,
        )
        assert first.status == STATUS_SUCCEEDED
        before = dict(collection.objects)
        again = await execute_repair_task(
            factory,
            weaviate_client=app.state.weaviate_client,
            embedder=app.state.embedder,
            class_name="Document",
            task_id=task.id,
        )
        assert again.status == STATUS_SUCCEEDED
        assert again.result["repaired_indices"] == []  # no-op
        assert again.result["consistency"] == "passed"
        assert collection.objects == before  # 零写


# --------------------------------------------------------------------------- #
# INT-C-02:channel_visibility 持久 props 恢复(修复不得扩权)
# --------------------------------------------------------------------------- #


async def test_int_c02_channel_visibility_from_persisted_props_not_expanded(int_seed):
    """受限渠道源(github/api-only 持久真值)修复回写后 channel_visibility =
    持久 props 真值(不出现未授权的 widget 渠道扩权;不硬编码)。"""
    factory = app.state.session_factory
    doc_id = int_seed["doc_id"]
    gen_id = int_seed["gen_id"]
    collection = int_seed["collection"]

    async with factory() as session:
        task, _ = await create_repair_task(
            session, SRC, doc_id, requested_by="int@test", idempotency_key=f"key3-{uuid.uuid4().hex}"
        )
        done = await execute_repair_task(
            factory,
            weaviate_client=app.state.weaviate_client,
            embedder=app.state.embedder,
            class_name="Document",
            task_id=task.id,
        )
        assert done.status == STATUS_SUCCEEDED
    for i in range(12):
        props = collection.objects[generation_uuid(doc_id, gen_id, i)]["properties"]
        assert props["channel_visibility"] == ["api"]  # 播种持久真值(_seed 默认 widget?否:见下)
    # 上面断言失败即说明硬编码默认可见渠道回潮(扩权缺陷回归)。


# --------------------------------------------------------------------------- #
# INT-C-03:freshness_hours 冻结词表(fail-loud)
# --------------------------------------------------------------------------- #


async def test_int_c03_freshness_vocabulary_rejects_illegal_values():
    """非法值 → pydantic ValidationError(422);合法词表 + NULL 通过。"""
    from pydantic import ValidationError

    from backend.api.admin.schemas import KnowledgePreviewRequest, KnowledgeSettingsUpdate

    for v in FRESHNESS_CHOICES_HOURS:
        assert KnowledgeSettingsUpdate(role="current", freshness_hours=v).freshness_hours == v
        assert KnowledgePreviewRequest(role="current", freshness_hours=v).freshness_hours == v
    assert KnowledgeSettingsUpdate(role="current").freshness_hours is None
    assert KnowledgePreviewRequest(role="current", freshness_hours=None).freshness_hours is None
    for bad in (1, 5, 7, 25, 48, 100, 169, 10000):
        with pytest.raises(ValidationError):
            KnowledgeSettingsUpdate(role="current", freshness_hours=bad)
        with pytest.raises(ValidationError):
            KnowledgePreviewRequest(role="current", freshness_hours=bad)


async def test_int_c03_effective_freshness_fail_loud_on_corrupt_row():
    """读取侧:NULL → 默认 24h(既有语义零变化);非空非法值 fail-loud
    (禁静默回落 24)。"""
    ds = SimpleNamespace(freshness_hours=None)
    assert effective_freshness_hours(ds) == DEFAULT_FRESHNESS_HOURS
    for v in FRESHNESS_CHOICES_HOURS:
        assert effective_freshness_hours(SimpleNamespace(freshness_hours=v)) == v
    with pytest.raises(ValueError):
        effective_freshness_hours(SimpleNamespace(freshness_hours=25))


# --------------------------------------------------------------------------- #
# INT-C-04:LIKE 通配符转义(%/_ 不扩查询)
# --------------------------------------------------------------------------- #


async def test_int_c04_wildcard_source_id_does_not_expand_scope(int_seed):
    """含 %/_ 的 source_id:影响计数/账本指纹精确圈定本源,不扩查询。

    播种:`intwave2-a_b` 源下 1 文档(本源);`intwave2-x y` 源下 1 文档
    (LIKE 语义下 `intwave2-a_b/%` 未转义会命中 `intwave2-aXb/...`)。"""
    factory = app.state.session_factory
    tricky = f"{SRC}-a_b"
    other = f"{SRC}-aXb"
    async with factory() as session:
        for sid in (tricky, other):
            session.add(
                DataSource(
                    id=sid,
                    type="github",
                    product="int",
                    config={},
                    sync_interval="24h",
                    enabled=True,
                )
            )
        session.add(
            Document(
                source_id=f"{tricky}/doc-1.md",
                content_hash="c" * 64,
                source_type="github",
                product="int",
                title="d1",
                url="https://s/d1",
                branch="",
                chunk_count=1,
                lifecycle="active",
            )
        )
        session.add(
            Document(
                source_id=f"{other}/doc-2.md",
                content_hash="c" * 64,
                source_type="github",
                product="int",
                title="d2",
                url="https://s/d2",
                branch="",
                chunk_count=1,
                lifecycle="active",
            )
        )
        await session.commit()
    try:
        async with factory() as session:
            counts = await policy_impact_counts(session, tricky)
            # 未转义时 `tricky/%` LIKE 会匹配 `{other}/doc-2.md`(_ 通配)→ 2
            assert counts["affected_documents"] == 1
            fp1 = await ledger_fingerprint(session, tricky)
            fp2 = await ledger_fingerprint(session, other)
            assert fp1 != fp2  # 各源指纹独立(未转义会同域漂移)
            counts_other = await policy_impact_counts(session, other)
            assert counts_other["affected_documents"] == 1
    finally:
        async with factory() as session:
            await session.execute(
                Document.__table__.delete().where(
                    Document.source_id.in_([f"{tricky}/doc-1.md", f"{other}/doc-2.md"])
                )
            )
            await session.execute(
                DataSource.__table__.delete().where(DataSource.id.in_([tricky, other]))
            )
            await session.commit()


# --------------------------------------------------------------------------- #
# INT-SYS-01:遗留 resolve 端点收敛(U-15 状态机 thin-wrapper)
# --------------------------------------------------------------------------- #


async def _mk_gap_cluster(session, *, status, cluster_type="gap"):
    cid = uuid.uuid4()
    session.add(
        QuestionCluster(
            id=cid,
            cluster_type=cluster_type,
            representative_question=f"int-sys-01 gap {status}",
            question_count=2,
            status=status,
        )
    )
    await session.commit()
    return cid


@pytest_asyncio.fixture(loop_scope="session")
async def sys01_env():
    factory = app.state.session_factory
    saved = {
        k: getattr(app.state, k, None) for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    yield {"factory": factory}
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)


async def _patch_resolve(cluster_id, headers, status):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.patch(
            f"/api/admin/analytics/gaps/{cluster_id}/resolve",
            json={"status": status},
            headers=headers,
        )


async def _cleanup_cluster(factory, cluster_id):
    async with factory() as session:
        await session.execute(
            GapObservationEvent.__table__.delete().where(
                GapObservationEvent.cluster_id == cluster_id
            )
        )
        await session.execute(
            GapObservation.__table__.delete().where(GapObservation.cluster_id == cluster_id)
        )
        await session.execute(
            QuestionCluster.__table__.delete().where(QuestionCluster.id == cluster_id)
        )
        await session.commit()


async def test_int_sys01_open_force_resolve_rejected_no_transition(admin_headers, sys01_env):
    """open 态直接强转 RESOLVED → 409;状态零变化;无 observation/事件残留。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="open")
    try:
        resp = await _patch_resolve(cid, admin_headers, "resolved")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "resolve_not_allowed"
        async with factory() as session:
            row = (
                await session.execute(select(QuestionCluster).where(QuestionCluster.id == cid))
            ).scalar_one()
            assert row.status == "open"  # 强转不可能
            assert (
                await session.execute(
                    select(GapObservation).where(GapObservation.cluster_id == cid)
                )
            ).scalars().all() == []
            assert (
                await session.execute(
                    select(GapObservationEvent).where(GapObservationEvent.cluster_id == cid)
                )
            ).scalars().all() == []
    finally:
        await _cleanup_cluster(factory, cid)


async def test_int_sys01_observing_force_resolve_window_not_elapsed_rejected(
    admin_headers, sys01_env
):
    """observing 强转 RESOLVED(窗未满)→ 触发权威评估但不转移 → 409;
    active observation 保持(未满窗),无悬挂。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="observing")
        session.add(
            GapObservation(
                cluster_id=cid,
                started_at=NOW - timedelta(days=1),
                window_days=7,
                window_ends_at=NOW + timedelta(days=6),  # 窗未满
                is_active=True,
            )
        )
        await session.commit()
    try:
        resp = await _patch_resolve(cid, admin_headers, "resolved")
        assert resp.status_code == 409
        async with factory() as session:
            row = (
                await session.execute(select(QuestionCluster).where(QuestionCluster.id == cid))
            ).scalar_one()
            assert row.status == "observing"  # 未满窗不强转
            obs = (
                (
                    await session.execute(
                        select(GapObservation).where(GapObservation.cluster_id == cid)
                    )
                )
                .scalars()
                .one()
            )
            assert obs.is_active is True  # 无悬挂(评估未产生转移,观察仍在窗内)
    finally:
        await _cleanup_cluster(factory, cid)


async def test_int_sys01_observing_resolve_after_window_elapsed_delegates_to_machine(
    admin_headers, sys01_env
):
    """observing 满窗后 resolve → 委托状态机评估真实 RESOLVED(唯一合法
    进入路径)+ observation 关闭(window_elapsed)+ resolve 事件留痕。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="observing")
        session.add(
            GapObservation(
                cluster_id=cid,
                started_at=NOW - timedelta(days=8),
                window_days=7,
                window_ends_at=NOW - timedelta(days=1),  # 已满窗
                is_active=True,
            )
        )
        await session.commit()
    try:
        resp = await _patch_resolve(cid, admin_headers, "resolved")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
        async with factory() as session:
            obs = (
                (
                    await session.execute(
                        select(GapObservation).where(GapObservation.cluster_id == cid)
                    )
                )
                .scalars()
                .one()
            )
            assert obs.is_active is False
            assert obs.ended_reason == "window_elapsed"
            events = (
                (
                    await session.execute(
                        select(GapObservationEvent).where(
                            GapObservationEvent.cluster_id == str(cid)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [e.event_type for e in events] == ["resolve"]  # 审计行存在
    finally:
        await _cleanup_cluster(factory, cid)


async def test_int_sys01_resolved_direct_write_rejected(admin_headers, sys01_env):
    """resolved 态:direct open(resolved→open 手动路径不存在)→ 409;
    direct resolved 幂等语义下亦不允许改写 → 走 resolved 分支 409 不可达?
    —— 收敛语义:resolved 态任何直接写都被拒绝(resolved 为终态,重开需
    证据复现走状态机)。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="resolved")
    try:
        resp = await _patch_resolve(cid, admin_headers, "resolved")
        assert resp.status_code == 409  # 非 observing → resolve 分支拒绝
        resp2 = await _patch_resolve(cid, admin_headers, "open")
        assert resp2.status_code == 409
        assert resp2.json()["detail"]["code"] == "reopen_not_allowed"
        async with factory() as session:
            row = (
                await session.execute(select(QuestionCluster).where(QuestionCluster.id == cid))
            ).scalar_one()
            assert row.status == "resolved"  # 零变化
    finally:
        await _cleanup_cluster(factory, cid)


async def test_int_sys01_observing_status_open_delegates_to_abort_no_dangling(
    admin_headers, sys01_env
):
    """observing 态 status=open → 委托 abort(观察行关闭 aborted + abort
    事件留痕),不留悬挂 active observation。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="observing")
        session.add(
            GapObservation(
                cluster_id=cid,
                started_at=NOW - timedelta(days=1),
                window_days=7,
                window_ends_at=NOW + timedelta(days=6),
                is_active=True,
            )
        )
        await session.commit()
    try:
        resp = await _patch_resolve(cid, admin_headers, "open")
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"
        async with factory() as session:
            obs = (
                (
                    await session.execute(
                        select(GapObservation).where(GapObservation.cluster_id == cid)
                    )
                )
                .scalars()
                .one()
            )
            assert obs.is_active is False
            assert obs.ended_reason == "aborted"
            events = (
                (
                    await session.execute(
                        select(GapObservationEvent).where(
                            GapObservationEvent.cluster_id == str(cid)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [e.event_type for e in events] == ["abort"]  # 留痕
    finally:
        await _cleanup_cluster(factory, cid)


async def test_int_sys01_open_status_open_idempotent_noop(admin_headers, sys01_env):
    """open 态 status=open → 幂等 no-op 200(既有调用方读语义零回归)。"""
    factory = sys01_env["factory"]
    async with factory() as session:
        cid = await _mk_gap_cluster(session, status="open")
    try:
        resp = await _patch_resolve(cid, admin_headers, "open")
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"
        async with factory() as session:
            events = (
                (
                    await session.execute(
                        select(GapObservationEvent).where(
                            GapObservationEvent.cluster_id == str(cid)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert events == []  # 无转移 → 无事件(no-op 不伪造审计)
    finally:
        await _cleanup_cluster(factory, cid)
