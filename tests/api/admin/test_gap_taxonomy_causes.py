"""Track D U-14 扩展原因词表测试(v1.6.3 Wave 1,IF-2)。

覆盖 TI-09 参考要求扩展的 6 个新原因类,每类 ≥1 行确定性真实证据
(fixture 构造经真实 DB→API 分类回放,禁 keyword/label-only):
- 生成异常   = generation failure 真相(Trace.type=generation_error,PC-06 持久化)
- 内容缺失   = 知识缺失变体(未回答 + 零来源 + 检索零候选 hybrid_count=0)
- 引用异常   = 引用一致性违例(答案引用编号越界,标记形状契约同 backend.pipeline.citation)
- 内容冲突   = 多源冲突真相(同会话同时引用 superseded 文档与其接替者)
- 内容过期   = 内容时间真相(所引文档内容最后更新早于会话超过冻结阈值)
- 检索异常   = 检索异常证据(已回答有来源但检索未达最低有效召回)

旧 4 类(reject/low/召回空/召回不足)语义回归:无新类证据时分类逐字不变。

分类权威 = backend/api/admin/analytics.py:classify_gap_miss_types
(单会话规则函数 = backend/services/gap_taxonomy.py:classify_conversation_miss_type,
IF-2 冻结挂载点)。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Document, QuestionCluster, Trace, User
from backend.main import app
from backend.services.gap_taxonomy import (
    GAP_MISS_CITATION_ANOMALY,
    GAP_MISS_CONTENT_CONFLICT,
    GAP_MISS_CONTENT_MISSING,
    GAP_MISS_GENERATION_FAILURE,
    GAP_MISS_RETRIEVAL_ANOMALY,
    GAP_MISS_STALE_CONTENT,
    GAP_STALE_CONTENT_DAYS,
    CitedDocEvidence,
    classify_conversation_miss_type,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# 纯规则函数单元测试(证据→分类,确定性;不触 DB)
# --------------------------------------------------------------------------- #


class TestConversationClassifierPure:
    """单会话证据规则(gap_taxonomy.classify_conversation_miss_type)。"""

    @staticmethod
    def _trace(type_: str = "rag", stages: dict | None = None, confidence: float | None = 0.9):
        return {"type": type_, "stages": stages or {}, "confidence": confidence}

    def test_generation_failure_truth(self):
        """生成异常 = Trace.type=generation_error(generation failure 真相,PC-06)。"""
        miss = classify_conversation_miss_type(
            is_answered=False,
            sources=[],
            answer=None,
            trace_type="generation_error",
            trace_stages={"error": {"kind": "provider_error"}},
            trace_confidence=None,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_GENERATION_FAILURE

    def test_content_missing_knowledge_missing_variant(self):
        """内容缺失 = 未回答 + 零来源 + 检索零候选(知识缺失变体)。"""
        miss = classify_conversation_miss_type(
            is_answered=False,
            sources=[],
            answer=None,
            trace_type="rag",
            trace_stages={"retrieve": {"hybrid_count": 0, "effective_min": 5}},
            trace_confidence=None,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_CONTENT_MISSING

    def test_citation_anomaly_dangling_marker(self):
        """引用异常 = 答案引用编号越界(2 个来源却引用 [3])。"""
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"url": "a"}, {"url": "b"}],
            answer="结论见 [3]。",
            trace_type="rag",
            trace_stages={},
            trace_confidence=0.9,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_CITATION_ANOMALY

    def test_citation_marker_in_range_is_not_anomaly(self):
        """引用编号在范围内 → 非引用异常(回落旧类:召回不足)。"""
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"url": "a"}, {"url": "b"}],
            answer="结论见 [2]。",
            trace_type="rag",
            trace_stages={},
            trace_confidence=0.9,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == "召回不足"

    def test_content_conflict_superseded_co_citation(self):
        """内容冲突 = 同会话同时引用 superseded 文档与其接替者(多源冲突真相)。"""
        cited = {
            "src/A": CitedDocEvidence(updated_at=NOW - timedelta(days=1), superseded_by="src/B"),
            "src/B": CitedDocEvidence(updated_at=NOW - timedelta(days=1)),
        }
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"source_id": "src/A"}, {"source_id": "src/B"}],
            answer="a",
            trace_type="rag",
            trace_stages={},
            trace_confidence=0.9,
            cited_docs=cited,
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_CONTENT_CONFLICT

    def test_stale_content_time_truth(self):
        """内容过期 = 所引文档内容更新早于会话超过冻结阈值(内容时间真相)。"""
        cited = {
            "src/old": CitedDocEvidence(
                updated_at=NOW - timedelta(days=GAP_STALE_CONTENT_DAYS + 1)
            ),
        }
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"source_id": "src/old"}],
            answer="a",
            trace_type="rag",
            trace_stages={},
            trace_confidence=0.9,
            cited_docs=cited,
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_STALE_CONTENT

    def test_retrieval_anomaly_below_effective_min(self):
        """检索异常 = 已回答有来源但检索未达最低有效召回(min_results_met=False)。"""
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"url": "u"}],
            answer="a",
            trace_type="rag",
            trace_stages={
                "retrieve": {"hybrid_count": 1, "effective_min": 5, "min_results_met": False}
            },
            trace_confidence=0.9,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_RETRIEVAL_ANOMALY

    def test_priority_generation_beats_content_missing(self):
        """优先级:生成失败真相 > 内容缺失(同一会话双证据时取更具体失败真相)。"""
        miss = classify_conversation_miss_type(
            is_answered=False,
            sources=[],
            answer=None,
            trace_type="generation_error",
            trace_stages={"retrieve": {"hybrid_count": 0, "effective_min": 5}},
            trace_confidence=None,
            cited_docs={},
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_GENERATION_FAILURE

    def test_priority_conflict_beats_stale(self):
        """优先级:内容冲突 > 内容过期(冲突是更具体的多源真相)。"""
        cited = {
            "src/A": CitedDocEvidence(
                updated_at=NOW - timedelta(days=GAP_STALE_CONTENT_DAYS + 30),
                superseded_by="src/B",
            ),
            "src/B": CitedDocEvidence(updated_at=NOW),
        }
        miss = classify_conversation_miss_type(
            is_answered=True,
            sources=[{"source_id": "src/A"}, {"source_id": "src/B"}],
            answer="a",
            trace_type="rag",
            trace_stages={},
            trace_confidence=0.9,
            cited_docs=cited,
            conversation_at=NOW,
        )
        assert miss == GAP_MISS_CONTENT_CONFLICT

    def test_old_four_classes_preserved_without_new_evidence(self):
        """旧 4 类回归:无新类证据时 reject/low/召回空/召回不足 逐字不变。"""
        base = {"trace_type": None, "trace_stages": {}, "cited_docs": {}, "conversation_at": NOW}
        # reject:未回答,无 trace 证据
        assert (
            classify_conversation_miss_type(
                is_answered=False,
                sources=[{"url": "x"}],
                answer=None,
                trace_confidence=None,
                **base,
            )
            == "reject"
        )
        # low:answered + sources 非空 + conf<0.6,无检索阶段证据
        assert (
            classify_conversation_miss_type(
                is_answered=True,
                sources=[{"url": "x"}],
                answer="a",
                trace_confidence=0.3,
                trace_type="rag",
                **{k: v for k, v in base.items() if k != "trace_type"},
            )
            == "low"
        )
        # 召回空:answered + sources 空
        assert (
            classify_conversation_miss_type(
                is_answered=True, sources=[], answer="a", trace_confidence=None, **base
            )
            == "召回空"
        )
        # 召回不足:answered + sources 非空 + conf>=0.6
        assert (
            classify_conversation_miss_type(
                is_answered=True,
                sources=[{"url": "x"}],
                answer="a",
                trace_confidence=0.8,
                trace_type="rag",
                **{k: v for k, v in base.items() if k != "trace_type"},
            )
            == "召回不足"
        )


# --------------------------------------------------------------------------- #
# 真实 DB→API 分类回放(每新类 ≥1 行确定性真实证据)
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    """创建 admin 用户并返回认证头;测试后按 id 精准清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-gaptaxonomy@test.com",
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


def _gap_cluster(title: str) -> QuestionCluster:
    return QuestionCluster(
        id=uuid.uuid4(),
        cluster_type="gap",
        representative_question=title,
        question_count=1,
        status="open",
    )


async def _seed_cause_fixture(factory, evidence: str) -> str:
    """按证据类型 seed 一个 gap cluster + 单会话真实证据,返回 cluster_id。"""
    cluster = _gap_cluster(f"WD-U14-{evidence}")
    cid = str(cluster.id)
    async with factory() as session:
        session.add(cluster)
        if evidence == "generation":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 生成异常问句",
                answer=None,
                sources=[],
                is_answered=False,
                cluster_id=cid,
                created_at=NOW - timedelta(hours=1),
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="generation_error",
                    stages={"error": {"kind": "provider_error"}},
                    config_snapshot={"failure_kind": "provider_error"},
                    confidence=None,
                )
            )
        elif evidence == "content_missing":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 内容缺失问句",
                answer=None,
                sources=[],
                is_answered=False,
                cluster_id=cid,
                created_at=NOW - timedelta(hours=2),
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={"retrieve": {"hybrid_count": 0, "effective_min": 5}},
                    config_snapshot={},
                    confidence=None,
                )
            )
        elif evidence == "citation":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 引用异常问句",
                answer="电池寿命约为 2 年 [3]。",
                sources=[
                    {"url": "u1", "title": "t1", "type": "website", "product": "NE101"},
                    {"url": "u2", "title": "t2", "type": "website", "product": "NE101"},
                ],
                is_answered=True,
                cluster_id=cid,
                created_at=NOW - timedelta(hours=3),
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={},
                    config_snapshot={},
                    confidence=0.9,
                )
            )
        elif evidence == "conflict":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 内容冲突问句",
                answer="a",
                sources=[
                    {
                        "url": "",
                        "title": "A",
                        "type": "filesystem",
                        "product": "NE101",
                        "source_id": "WD-U14/doc-A/old.md",
                    },
                    {
                        "url": "",
                        "title": "B",
                        "type": "filesystem",
                        "product": "NE101",
                        "source_id": "WD-U14/doc-B/new.md",
                    },
                ],
                is_answered=True,
                cluster_id=cid,
                created_at=NOW - timedelta(hours=4),
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={},
                    config_snapshot={},
                    confidence=0.9,
                )
            )
            session.add(
                Document(
                    source_id="WD-U14/doc-A/old.md",
                    content_hash="hA",
                    source_type="filesystem",
                    product="NE101",
                    title="旧版电池文档",
                    url="/old.md",
                    lifecycle="superseded",
                    superseded_by="WD-U14/doc-B/new.md",
                    updated_at=NOW - timedelta(days=5),
                )
            )
            session.add(
                Document(
                    source_id="WD-U14/doc-B/new.md",
                    content_hash="hB",
                    source_type="filesystem",
                    product="NE101",
                    title="新版电池文档",
                    url="/new.md",
                    lifecycle="active",
                    updated_at=NOW - timedelta(days=1),
                )
            )
        elif evidence == "stale":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 内容过期问句",
                answer="a",
                sources=[
                    {
                        "url": "",
                        "title": "S",
                        "type": "filesystem",
                        "product": "NE101",
                        "source_id": "WD-U14/doc-stale.md",
                    }
                ],
                is_answered=True,
                cluster_id=cid,
                created_at=NOW,
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={},
                    config_snapshot={},
                    confidence=0.9,
                )
            )
            session.add(
                Document(
                    source_id="WD-U14/doc-stale.md",
                    content_hash="hS",
                    source_type="filesystem",
                    product="NE101",
                    title="过期规格文档",
                    url="/stale.md",
                    updated_at=NOW - timedelta(days=GAP_STALE_CONTENT_DAYS + 30),
                )
            )
        elif evidence == "retrieval":
            conv = Conversation(
                id=uuid.uuid4(),
                question="WD-U14 检索异常问句",
                answer="a",
                sources=[{"url": "u9", "title": "t9", "type": "website", "product": "NE101"}],
                is_answered=True,
                cluster_id=cid,
                created_at=NOW - timedelta(hours=5),
            )
            session.add(conv)
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={
                        "retrieve": {
                            "hybrid_count": 1,
                            "effective_min": 5,
                            "min_results_met": False,
                        }
                    },
                    config_snapshot={},
                    confidence=0.9,
                )
            )
        else:  # pragma: no cover
            raise ValueError(evidence)
        await session.commit()
    return cid


async def _cleanup_cluster(factory, cluster_id: str) -> None:
    async with factory() as session:
        convs = (
            (
                await session.execute(
                    Conversation.__table__.select().where(Conversation.cluster_id == cluster_id)
                )
            )
            .mappings()
            .all()
        )
        for c in convs:
            await session.execute(Trace.__table__.delete().where(Trace.conversation_id == c["id"]))
        await session.execute(
            Conversation.__table__.delete().where(Conversation.cluster_id == cluster_id)
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like("WD-U14/%"))
        )
        await session.execute(
            QuestionCluster.__table__.delete().where(QuestionCluster.id == uuid.UUID(cluster_id))
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.parametrize(
    "evidence,expected_miss_type",
    [
        ("generation", GAP_MISS_GENERATION_FAILURE),
        ("content_missing", GAP_MISS_CONTENT_MISSING),
        ("citation", GAP_MISS_CITATION_ANOMALY),
        ("conflict", GAP_MISS_CONTENT_CONFLICT),
        ("stale", GAP_MISS_STALE_CONTENT),
        ("retrieval", GAP_MISS_RETRIEVAL_ANOMALY),
    ],
)
async def test_new_cause_classes_via_tech_answer_gaps(admin_headers, evidence, expected_miss_type):
    """每个新原因类:真实 DB 证据 → /tech/answer-gaps 权威分类回放。"""
    factory = app.state.session_factory
    cluster_id = await _seed_cause_fixture(factory, evidence)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/tech/answer-gaps",
                params={"q": f"WD-U14-{evidence}"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        items = [it for it in resp.json()["items"] if it["id"] == cluster_id]
        assert len(items) == 1, f"证据 {evidence} 的 cluster 未命中"
        assert items[0]["miss_type"] == expected_miss_type, (
            f"证据 {evidence} 预期 {expected_miss_type},实际 {items[0]['miss_type']}"
        )
        assert items[0]["miss_type_breakdown"].get(expected_miss_type, 0) >= 1
    finally:
        await _cleanup_cluster(factory, cluster_id)


@pytest.mark.integration
async def test_new_cause_classes_via_coverage_gaps_and_summary(admin_headers):
    """六新类经 /analytics/coverage-gaps 同源权威分类;summary 含新类计数。"""
    factory = app.state.session_factory
    seeded: dict[str, str] = {}
    try:
        for evidence in (
            "generation",
            "content_missing",
            "citation",
            "conflict",
            "stale",
            "retrieval",
        ):
            seeded[evidence] = await _seed_cause_fixture(factory, evidence)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/analytics/coverage-gaps",
                params={"size": 100},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        j = resp.json()
        by_id = {it["id"]: it for it in j["items"]}
        expected = {
            "generation": GAP_MISS_GENERATION_FAILURE,
            "content_missing": GAP_MISS_CONTENT_MISSING,
            "citation": GAP_MISS_CITATION_ANOMALY,
            "conflict": GAP_MISS_CONTENT_CONFLICT,
            "stale": GAP_MISS_STALE_CONTENT,
            "retrieval": GAP_MISS_RETRIEVAL_ANOMALY,
        }
        for evidence, miss in expected.items():
            item = by_id.get(seeded[evidence])
            assert item is not None, f"{evidence} cluster 缺失"
            assert item["miss_type"] == miss, f"{evidence} 预期 {miss},实际 {item['miss_type']}"
        summary = j["miss_type_summary"]
        for miss in expected.values():
            assert summary.get(miss, 0) >= 1, f"miss_type_summary 缺新类 {miss}"
    finally:
        for cluster_id in seeded.values():
            await _cleanup_cluster(factory, cluster_id)


@pytest.mark.integration
async def test_cause_filter_new_class_authoritative_rowset(admin_headers):
    """功能 E2E:按新原因过滤 → 行集 = 该分类权威行集(其余类被排除)。"""
    factory = app.state.session_factory
    gen_id = await _seed_cause_fixture(factory, "generation")
    stale_id = await _seed_cause_fixture(factory, "stale")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/tech/answer-gaps",
                params={"cause": GAP_MISS_GENERATION_FAILURE},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        j = resp.json()
        ids = {it["id"] for it in j["items"]}
        assert gen_id in ids, "生成异常 cluster 应在 cause=生成异常 行集内"
        assert stale_id not in ids, "内容过期 cluster 不应混入生成异常行集"
        assert all(it["miss_type"] == GAP_MISS_GENERATION_FAILURE for it in j["items"]), (
            "行集内存在非权威分类行"
        )
        assert j["total"] == len(ids)
    finally:
        await _cleanup_cluster(factory, gen_id)
        await _cleanup_cluster(factory, stale_id)


@pytest.mark.integration
@pytest.mark.parametrize(
    "evidence,residual_miss",
    [
        # 未回答 + 有来源无 trace 证据 → reject 语义不变(非生成异常/内容缺失)
        ("reject_plain", "reject"),
        # answered + sources 空 → 召回空 语义不变(内容缺失不侵入)
        ("recall_empty_plain", "召回空"),
        # answered + sources 非空 + conf<0.6 无检索阶段 → low 不被检索异常侵入
        ("low_plain", "low"),
        # answered + sources 非空 + conf>=0.9 无任何新类证据 → 召回不足 不变
        ("insufficient_plain", "召回不足"),
    ],
)
async def test_old_four_classes_unchanged_under_extension(admin_headers, evidence, residual_miss):
    """旧 4 类回归:无新类证据的既有证据形态分类逐字保持。"""
    factory = app.state.session_factory
    cluster = _gap_cluster(f"WD-U14-{evidence}")
    cid = str(cluster.id)
    async with factory() as session:
        session.add(cluster)
        conv = Conversation(
            id=uuid.uuid4(),
            question=f"WD-U14 {evidence} 问句",
            answer=None if evidence == "reject_plain" else "a",
            sources=[] if evidence in ("reject_plain", "recall_empty_plain") else [{"url": "x"}],
            is_answered=evidence != "reject_plain",
            cluster_id=cid,
            created_at=NOW - timedelta(hours=1),
        )
        session.add(conv)
        if evidence in ("low_plain", "insufficient_plain"):
            session.add(
                Trace(
                    conversation_id=conv.id,
                    turn_index=0,
                    type="rag",
                    stages={"intent": {"ms": 5}},  # 无 retrieve 阶段证据
                    config_snapshot={},
                    confidence=0.3 if evidence == "low_plain" else 0.9,
                )
            )
        await session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/tech/answer-gaps",
                params={"q": f"WD-U14-{evidence}"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        items = [it for it in resp.json()["items"] if it["id"] == cid]
        assert len(items) == 1
        assert items[0]["miss_type"] == residual_miss, (
            f"旧类 {evidence} 语义被扩展侵入:预期 {residual_miss},实际 {items[0]['miss_type']}"
        )
    finally:
        await _cleanup_cluster(factory, cid)


@pytest.mark.integration
async def test_stale_content_fresh_document_not_stale(admin_headers):
    """内容过期边界:所引文档内容新鲜(阈值内)→ 不判内容过期(回落召回不足)。"""
    factory = app.state.session_factory
    cluster = _gap_cluster("WD-U14-fresh-doc")
    cid = str(cluster.id)
    async with factory() as session:
        session.add(cluster)
        conv = Conversation(
            id=uuid.uuid4(),
            question="WD-U14 新鲜文档问句",
            answer="a",
            sources=[
                {
                    "url": "",
                    "title": "F",
                    "type": "filesystem",
                    "product": "NE101",
                    "source_id": "WD-U14/doc-fresh.md",
                }
            ],
            is_answered=True,
            cluster_id=cid,
            created_at=NOW,
        )
        session.add(conv)
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=0,
                type="rag",
                stages={},
                config_snapshot={},
                confidence=0.9,
            )
        )
        session.add(
            Document(
                source_id="WD-U14/doc-fresh.md",
                content_hash="hF",
                source_type="filesystem",
                product="NE101",
                title="新鲜文档",
                url="/fresh.md",
                updated_at=NOW - timedelta(days=10),
            )
        )
        await session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/tech/answer-gaps",
                params={"q": "WD-U14-fresh-doc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        items = [it for it in resp.json()["items"] if it["id"] == cid]
        assert len(items) == 1
        assert items[0]["miss_type"] == "召回不足"
    finally:
        await _cleanup_cluster(factory, cid)
