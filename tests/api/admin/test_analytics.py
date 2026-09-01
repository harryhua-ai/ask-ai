"""Analytics API 集成测试(Coverage Gaps + Top Questions + Source Analytics)。

遵循 codebase 现有模式:每个测试内创建 client + headers,
通过 pytestmark 与 admin conftest 的 session 级 _setup_app_state fixture 对齐。
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    Conversation,
    DataSource,
    Document,
    QuestionCluster,
    SyncLog,
    Trace,
    User,
)
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户并返回认证头;测试结束后按 user_id 精准清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-analytics@test.com",
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 精准清理:仅删除本测试创建的 admin 用户
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def viewer_headers():
    """创建 viewer 用户并返回认证头;测试结束后按 user_id 精准清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="viewer-analytics@test.com",
                role="viewer",
                password_hash=hash_password("pass"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 精准清理:仅删除本测试创建的 viewer 用户
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.integration
class TestAnalyticsAPI:
    """Analytics API 集成测试套件。"""

    async def test_coverage_gaps_empty(self, auth_headers):
        """无 gap 数据时返回空列表。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/coverage-gaps", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_refresh_coverage_gaps(self, auth_headers):
        """刷新 Coverage Gaps 聚类(admin/editor)。"""
        # mock app.state.clustering — conftest 不初始化此属性,避免 AttributeError
        original = getattr(app.state, "clustering", None)
        app.state.clustering = AsyncMock()
        app.state.clustering.cluster = AsyncMock(return_value=[])
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/analytics/coverage-gaps/refresh", headers=auth_headers
                )
            assert resp.status_code == 200
            assert "cluster_count" in resp.json()
        finally:
            # 清理 mock 状态,避免影响后续测试
            if original is None:
                if hasattr(app.state, "clustering"):
                    del app.state.clustering
            else:
                app.state.clustering = original

    async def test_top_questions_empty(self, auth_headers):
        """无 top 数据时返回空列表。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/top-questions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_source_analytics(self, auth_headers):
        """来源分析返回聚合数据。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/sources", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    async def test_viewer_can_read(self, viewer_headers):
        """viewer 可以读取 analytics(viewer+ 可访问)。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/coverage-gaps", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_viewer_cannot_refresh(self, viewer_headers):
        """viewer 不能触发聚类刷新(应返回 403)。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/analytics/coverage-gaps/refresh", headers=viewer_headers
            )
        assert resp.status_code == 403

    async def test_resolve_gap_normal(self, auth_headers):
        """PATCH /gaps/{id}/resolve 正常流程:open -> resolved。"""
        # 先在 DB 创建一个 gap 聚类
        factory = app.state.session_factory
        cluster_id = uuid.uuid4()
        async with factory() as session:
            session.add(
                QuestionCluster(
                    id=cluster_id,
                    cluster_type="gap",
                    representative_question="test gap question for resolve",
                    question_count=3,
                    status="open",
                )
            )
            await session.commit()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/admin/analytics/gaps/{cluster_id}/resolve",
                    json={"status": "resolved"},
                    headers=auth_headers,
                )
            assert resp.status_code == 200
            assert resp.json()["status"] == "resolved"
            assert resp.json()["id"] == str(cluster_id)
        finally:
            # 精准清理:仅删除本测试创建的聚类
            async with factory() as session:
                await session.execute(
                    QuestionCluster.__table__.delete().where(QuestionCluster.id == cluster_id)
                )
                await session.commit()

    async def test_resolve_gap_invalid_status(self, auth_headers):
        """PATCH /gaps/{id}/resolve 非法 status 返回 422。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                "/api/admin/analytics/gaps/00000000-0000-0000-0000-000000000000/resolve",
                json={"status": "invalid"},
                headers=auth_headers,
            )
        assert resp.status_code == 422

    async def test_resolve_gap_not_found(self, auth_headers):
        """不存在的 cluster_id 返回 404。"""
        import uuid as _uuid

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/admin/analytics/gaps/{_uuid.uuid4()}/resolve",
                json={"status": "resolved"},
                headers=auth_headers,
            )
        assert resp.status_code == 404

    async def test_refresh_top_questions(self, auth_headers):
        """POST /top-questions/refresh 正常流程(admin/editor)。"""
        # mock app.state.clustering — conftest 不初始化此属性
        original = getattr(app.state, "clustering", None)
        app.state.clustering = AsyncMock()
        app.state.clustering.cluster = AsyncMock(return_value=[])
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/admin/analytics/top-questions/refresh", headers=auth_headers
                )
            assert resp.status_code == 200
            assert "cluster_count" in resp.json()
        finally:
            # 清理 mock 状态,避免影响后续测试
            if original is None:
                if hasattr(app.state, "clustering"):
                    del app.state.clustering
            else:
                app.state.clustering = original


@pytest.mark.integration
async def test_coverage_gaps_miss_type_four_types(auth_headers):
    """miss_type 四态:reject/low/召回空/召回不足。

    reject:is_answered=False
    low:answered, sources 非空, 最新 trace confidence<0.6
    召回空:answered, sources 空
    召回不足:answered, sources 非空, confidence>=0.6(或无 trace)
    """
    factory = app.state.session_factory
    now = datetime.now(UTC)
    cluster_ids: list[uuid.UUID] = []
    conv_ids: list[uuid.UUID] = []
    try:
        async with factory() as session:
            # 4 个独立 cluster,每个 cluster 的对话构成单一 miss_type,
            # 使该 type 成为 dominant,summary 中 4 种 type 各出现 1 次。
            # reject:is_answered=False
            cid_reject = uuid.uuid4()
            session.add(
                QuestionCluster(
                    id=cid_reject,
                    cluster_type="gap",
                    representative_question="miss_reject",
                    question_count=1,
                    status="open",
                )
            )
            c1 = Conversation(
                id=uuid.uuid4(),
                question="biz_miss_reject",
                answer=None,
                is_answered=False,
                cluster_id=str(cid_reject),
                created_at=now - timedelta(days=1),
            )
            session.add(c1)
            # low:answered + sources 非空 + confidence<0.6
            cid_low = uuid.uuid4()
            session.add(
                QuestionCluster(
                    id=cid_low,
                    cluster_type="gap",
                    representative_question="miss_low",
                    question_count=1,
                    status="open",
                )
            )
            c2 = Conversation(
                id=uuid.uuid4(),
                question="biz_miss_low",
                answer="a",
                is_answered=True,
                sources=[{"url": "x"}],
                cluster_id=str(cid_low),
                created_at=now - timedelta(days=1),
            )
            session.add(c2)
            session.add(
                Trace(
                    conversation_id=c2.id,
                    turn_index=0,
                    type="rag",
                    stages={"intent": {"ms": 5}},
                    total_ms=5,
                    confidence=0.3,
                    config_snapshot={},
                )
            )
            # 召回空:answered + sources 空
            cid_empty = uuid.uuid4()
            session.add(
                QuestionCluster(
                    id=cid_empty,
                    cluster_type="gap",
                    representative_question="miss_empty",
                    question_count=1,
                    status="open",
                )
            )
            c3 = Conversation(
                id=uuid.uuid4(),
                question="biz_miss_empty",
                answer="a",
                is_answered=True,
                sources=[],
                cluster_id=str(cid_empty),
                created_at=now - timedelta(days=1),
            )
            session.add(c3)
            # 召回不足:answered + sources 非空 + confidence>=0.6
            cid_insuf = uuid.uuid4()
            session.add(
                QuestionCluster(
                    id=cid_insuf,
                    cluster_type="gap",
                    representative_question="miss_insufficient",
                    question_count=1,
                    status="open",
                )
            )
            c4 = Conversation(
                id=uuid.uuid4(),
                question="biz_miss_insufficient",
                answer="a",
                is_answered=True,
                sources=[{"url": "y"}],
                cluster_id=str(cid_insuf),
                created_at=now - timedelta(days=1),
            )
            session.add(c4)
            session.add(
                Trace(
                    conversation_id=c4.id,
                    turn_index=0,
                    type="rag",
                    stages={"intent": {"ms": 5}},
                    total_ms=5,
                    confidence=0.8,
                    config_snapshot={},
                )
            )
            cluster_ids = [cid_reject, cid_low, cid_empty, cid_insuf]
            conv_ids = [c1.id, c2.id, c3.id, c4.id]
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/coverage-gaps", headers=auth_headers)
        assert resp.status_code == 200
        j = resp.json()
        # 每个 cluster 的 dominant miss_type 应与预期一致
        target_map = {
            str(cid_reject): "reject",
            str(cid_low): "low",
            str(cid_empty): "召回空",
            str(cid_insuf): "召回不足",
        }
        for item in j["items"]:
            if item["id"] in target_map:
                assert item["miss_type"] == target_map[item["id"]], (
                    f"cluster {item['id']} miss_type={item['miss_type']}, "
                    f"预期 {target_map[item['id']]}"
                )
        # 四态汇总均出现
        summary = j["miss_type_summary"]
        for t in ("reject", "low", "召回空", "召回不足"):
            assert summary.get(t, 0) >= 1, f"miss_type {t} 未出现"
    finally:
        async with factory() as session:
            await session.execute(
                Trace.__table__.delete().where(
                    Trace.conversation_id.in_([str(c) for c in conv_ids])
                )
            )
            await session.execute(
                Conversation.__table__.delete().where(
                    Conversation.id.in_([str(c) for c in conv_ids])
                )
            )
            await session.execute(
                QuestionCluster.__table__.delete().where(
                    QuestionCluster.id.in_([str(c) for c in cluster_ids])
                )
            )
            await session.commit()


@pytest.mark.integration
class TestSourceHealth:
    """T28:/source-health doc_count/chunk_count 按数据源 id 前缀聚合。

    documents.source_id 为复合键 "{数据源id}/{路径}"(五 connector 一致);
    旧实现按完整键分组后用 sync_log 纯 id 精确查找 → 永不命中恒 0。
    夹具一律使用真实复合键形态,防止再用纯 id 掩盖缺陷。
    """

    async def _seed(
        self,
        prefix: str,
        docs: list[tuple[str, int]],
        syncs: list[str],
        source_type: str = "web_crawl",
        product: str = "t28-product",
    ) -> list[str]:
        """按数据源 prefix 播种 DataSource + SyncLog + Document(复合键),返回待清理 source_ids。"""
        factory = app.state.session_factory
        async with factory() as session:
            session.add(
                DataSource(
                    id=prefix,
                    type=source_type,
                    product=product,
                    enabled=True,
                    config={"base_url": f"https://{prefix}.example.com"},
                )
            )
            for status in syncs:
                session.add(SyncLog(source_id=prefix, source_type=source_type, status=status))
            for i, (path, chunk_count) in enumerate(docs):
                # 真实复合键形态:"{数据源id}/{路径}"
                session.add(
                    Document(
                        content_hash=uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}/{path}").hex,
                        source_id=f"{prefix}/{path}",
                        source_type=source_type,
                        product=product,
                        title=f"t28 doc {prefix}/{path}",
                        url=f"https://{prefix}.example.com/{path}",
                        chunk_count=chunk_count,
                    )
                )
            await session.commit()
        return [prefix]

    async def _cleanup(self, prefix: str, doc_count: int) -> None:
        factory = app.state.session_factory
        async with factory() as session:
            await session.execute(
                Document.__table__.delete().where(Document.source_id.like(f"{prefix}/%"))
            )
            await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == prefix))
            await session.execute(DataSource.__table__.delete().where(DataSource.id == prefix))
            await session.commit()

    async def _get_items(self, auth_headers) -> dict[str, dict]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/source-health", headers=auth_headers)
        assert resp.status_code == 200
        return {item["source_id"]: item for item in resp.json()["items"]}

    async def test_composite_key_multi_source_counts(self, auth_headers):
        """多源复合键:各源 doc_count/chunk_count 按前缀聚合,不串源。"""
        prefix_a = f"t28-src-a-{uuid.uuid4().hex[:8]}"
        prefix_b = f"t28-src-b-{uuid.uuid4().hex[:8]}"
        await self._seed(prefix_a, [("feed", 3), ("blog/x", 4)], ["success", "success"])
        await self._seed(prefix_b, [("main/readme.md", 2)], ["failed"])
        try:
            items = await self._get_items(auth_headers)
            a, b = items[prefix_a], items[prefix_b]
            assert a["doc_count"] == 2
            assert a["chunk_count"] == 7
            assert a["total_syncs"] == 2
            assert a["failed_syncs"] == 0
            assert b["doc_count"] == 1
            assert b["chunk_count"] == 2
            assert b["failed_syncs"] == 1
        finally:
            await self._cleanup(prefix_a, 2)
            await self._cleanup(prefix_b, 1)

    async def test_source_without_documents_is_zero(self, auth_headers):
        """sync_log 有而 documents 无的源:doc_count/chunk_count 为 0,不报错。"""
        prefix = f"t28-src-empty-{uuid.uuid4().hex[:8]}"
        await self._seed(prefix, [], ["success"])
        try:
            items = await self._get_items(auth_headers)
            assert items[prefix]["doc_count"] == 0
            assert items[prefix]["chunk_count"] == 0
        finally:
            await self._cleanup(prefix, 0)

    async def test_chunk_count_summed_across_docs(self, auth_headers):
        """chunk_count = 同前缀下全部文档 chunk 求和(含 0 chunk 文档)。"""
        prefix = f"t28-src-sum-{uuid.uuid4().hex[:8]}"
        await self._seed(prefix, [("a", 5), ("b", 0), ("c/d", 2)], ["success"])
        try:
            items = await self._get_items(auth_headers)
            assert items[prefix]["doc_count"] == 3
            assert items[prefix]["chunk_count"] == 7
        finally:
            await self._cleanup(prefix, 3)

    async def test_no_slash_source_id_is_own_prefix(self, auth_headers):
        """无斜杠 source_id(历史形态):整串即 id,照常命中计数。"""
        prefix = f"t28-src-flat-{uuid.uuid4().hex[:8]}"
        factory = app.state.session_factory
        async with factory() as session:
            session.add(
                DataSource(
                    id=prefix,
                    type="filesystem",
                    product="t28-flat",
                    enabled=True,
                    config={},
                )
            )
            session.add(SyncLog(source_id=prefix, source_type="filesystem", status="success"))
            session.add(
                Document(
                    content_hash=uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}/legacy").hex,
                    source_id=prefix,  # 无斜杠:整串即数据源 id
                    source_type="filesystem",
                    product="t28-flat",
                    title="legacy flat source_id",
                    url="file:///legacy",
                    chunk_count=4,
                )
            )
            await session.commit()
        try:
            items = await self._get_items(auth_headers)
            assert items[prefix]["doc_count"] == 1
            assert items[prefix]["chunk_count"] == 4
        finally:
            await self._cleanup(prefix, 1)

    async def test_response_field_set_unchanged(self, auth_headers):
        """响应字段集合冻结:DSH-01 起为 T28 字段集 + 新增语义字段的超集契约。"""
        prefix = f"t28-src-schema-{uuid.uuid4().hex[:8]}"
        await self._seed(prefix, [("p", 1)], ["success"])
        try:
            items = await self._get_items(auth_headers)
            expected = {
                # T28 既有字段
                "source_id",
                "source_type",
                "product",
                "enabled",
                "doc_count",
                "chunk_count",
                "sync_success_rate",
                "total_syncs",
                "failed_syncs",
                "health",
                "last_sync",
                # DSH-01 新增语义字段(当前态/窗口/分子分母显式化)
                "window_days",
                "success_syncs",
                "partial_syncs",
                "last_sync_status",
                "last_sync_error",
            }
            assert set(items[prefix].keys()) == expected
        finally:
            await self._cleanup(prefix, 1)


# ----------------------------------------------------------------------- #
# DSH-01:数据源健康语义(当前态 vs 历史可靠性 可区分、可解释)
# ----------------------------------------------------------------------- #


@pytest.mark.integration
class TestSourceHealthSemantics:
    """DSH-01:/source-health 健康语义显式化。

    产品契约(Frozen Product Contract):
    - 窗口与分母必须可测:window_days + success/partial/failed_syncs 显式返回;
    - partial(一致性自愈)计入分母但不计入成功数——数学口径不变,但必须可见;
    - 禁用 ≠ 不健康:enabled=False → health="disabled"(G005);
    - 无历史/历史不足不得伪造成 0% 或 degraded:total_syncs < MIN_SYNC_RUNS →
      health="insufficient_data"(G004);
    - 最近一次同步的 status/error 必须透出(G003 当前态)。
    """

    MIN_RUNS = 3  # 与实现约定:低于该样本数不给可靠性结论

    async def _seed_case(
        self,
        prefix: str,
        *,
        enabled: bool = True,
        syncs: list[tuple[str, int]] | None = None,
        product: str = "dsh-product",
    ) -> None:
        """播种 DataSource + 带相对时间偏移(分钟)的 SyncLog 序列。

        syncs: [(status, minutes_ago), ...];列表顺序不限,started_at 由
        minutes_ow 决定,时间越近越"最新"。
        """
        factory = app.state.session_factory
        async with factory() as session:
            session.add(
                DataSource(
                    id=prefix,
                    type="web_crawl",
                    product=product,
                    enabled=enabled,
                    config={"base_url": f"https://{prefix}.example.com"},
                )
            )
            now = datetime.now(UTC)
            for status, minutes_ago in syncs or []:
                session.add(
                    SyncLog(
                        source_id=prefix,
                        source_type="web_crawl",
                        status=status,
                        started_at=now - timedelta(minutes=minutes_ago),
                        error_detail="boom" if status == "failed" else None,
                    )
                )
            await session.commit()

    async def _cleanup(self, prefix: str) -> None:
        factory = app.state.session_factory
        async with factory() as session:
            await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == prefix))
            await session.execute(DataSource.__table__.delete().where(DataSource.id == prefix))
            await session.commit()

    async def _get_item(self, auth_headers, prefix: str) -> dict:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/analytics/source-health", headers=auth_headers)
        assert resp.status_code == 200
        items = {i["source_id"]: i for i in resp.json()["items"]}
        return items[prefix]

    async def test_denominator_fields_explicit_partial_counts_in_denominator(self, auth_headers):
        """窗口/分子/分母显式:success+partial+failed → rate=1/3,partial 计分母不计成功。"""
        prefix = f"dsh-denom-{uuid.uuid4().hex[:8]}"
        await self._seed_case(
            prefix,
            syncs=[("success", 30), ("partial", 20), ("failed", 10)],
        )
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["window_days"] == 30
            assert item["total_syncs"] == 3
            assert item["success_syncs"] == 1
            assert item["partial_syncs"] == 1
            assert item["failed_syncs"] == 1
            assert item["sync_success_rate"] == pytest.approx(1 / 3, abs=1e-4)
        finally:
            await self._cleanup(prefix)

    async def test_latest_sync_status_and_error_surfaced(self, auth_headers):
        """当前态透出:最新一次 failed 的 status/error 必须可见(G003)。"""
        prefix = f"dsh-latest-{uuid.uuid4().hex[:8]}"
        await self._seed_case(
            prefix,
            syncs=[("success", 60), ("failed", 5)],
        )
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["last_sync_status"] == "failed"
            assert item["last_sync_error"] == "boom"
        finally:
            await self._cleanup(prefix)

    async def test_latest_sync_success_after_bad_history_coexists(self, auth_headers):
        """G002:最新成功 + 历史差 可合法共存且互不覆盖。"""
        prefix = f"dsh-coexist-{uuid.uuid4().hex[:8]}"
        await self._seed_case(
            prefix,
            syncs=[
                ("failed", 2880),
                ("failed", 1440),
                ("success", 720),
                ("success", 10),
            ],
        )
        try:
            item = await self._get_item(auth_headers, prefix)
            # 当前态:最新一次成功
            assert item["last_sync_status"] == "success"
            assert item["last_sync_error"] is None
            # 历史态:2/4 成功 → 低于 0.9,既有阈值语义保持(degraded)
            assert item["sync_success_rate"] == pytest.approx(0.5, abs=1e-4)
        finally:
            await self._cleanup(prefix)

    async def test_disabled_source_is_disabled_not_critical(self, auth_headers):
        """G005:禁用 ≠ 不健康。全失败历史 + 禁用 → disabled,不报 critical。"""
        prefix = f"dsh-disabled-{uuid.uuid4().hex[:8]}"
        await self._seed_case(
            prefix,
            enabled=False,
            syncs=[("failed", 30), ("failed", 20), ("failed", 10)],
        )
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["enabled"] is False
            assert item["health"] == "disabled"
        finally:
            await self._cleanup(prefix)

    async def test_insufficient_history_not_branded_degraded_or_zero(self, auth_headers):
        """G004:样本不足不给可靠性结论。2 次(含 1 失败)→ insufficient_data。"""
        prefix = f"dsh-insuff-{uuid.uuid4().hex[:8]}"
        await self._seed_case(prefix, syncs=[("success", 30), ("failed", 10)])
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["total_syncs"] == 2
            assert item["total_syncs"] < self.MIN_RUNS
            assert item["health"] == "insufficient_data"
        finally:
            await self._cleanup(prefix)

    async def test_zero_history_source_still_listed(self, auth_headers):
        """G004:从未同步的源也要出现在列表(总同步 0,insufficient_data,无最近同步)。"""
        prefix = f"dsh-zero-{uuid.uuid4().hex[:8]}"
        await self._seed_case(prefix, syncs=[])
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["total_syncs"] == 0
            assert item["sync_success_rate"] == 0.0
            assert item["health"] == "insufficient_data"
            assert item["last_sync"] is None
            assert item["last_sync_status"] is None
        finally:
            await self._cleanup(prefix)

    async def test_thresholds_healthy_and_critical_preserved(self, auth_headers):
        """既有阈值语义不变:全成功(≥3 次)→ healthy;1/3 → critical。"""
        prefix_ok = f"dsh-ok-{uuid.uuid4().hex[:8]}"
        prefix_bad = f"dsh-bad-{uuid.uuid4().hex[:8]}"
        await self._seed_case(prefix_ok, syncs=[("success", 30), ("success", 20), ("success", 10)])
        await self._seed_case(prefix_bad, syncs=[("success", 30), ("failed", 20), ("failed", 10)])
        try:
            ok = await self._get_item(auth_headers, prefix_ok)
            bad = await self._get_item(auth_headers, prefix_bad)
            assert ok["health"] == "healthy"
            assert bad["health"] == "critical"
        finally:
            await self._cleanup(prefix_ok)
            await self._cleanup(prefix_bad)

    async def test_ghost_sync_only_source_still_listed(self, auth_headers):
        """sync_log 有而 data_sources 无的幽灵行:保持可见,product=unknown。"""
        prefix = f"dsh-ghost-{uuid.uuid4().hex[:8]}"
        factory = app.state.session_factory
        async with factory() as session:
            session.add(SyncLog(source_id=prefix, source_type="web_crawl", status="failed"))
            await session.commit()
        try:
            item = await self._get_item(auth_headers, prefix)
            assert item["product"] == "unknown"
            assert item["failed_syncs"] == 1
        finally:
            await self._cleanup(prefix)

    async def test_response_field_set_extended_not_broken(self, auth_headers):
        """响应字段集合:新增语义字段,既有字段一个不少(T28 契约的超集)。"""
        prefix = f"dsh-schema-{uuid.uuid4().hex[:8]}"
        await self._seed_case(prefix, syncs=[("success", 10)])
        try:
            item = await self._get_item(auth_headers, prefix)
            expected = {
                # T28 既有字段(不破坏)
                "source_id",
                "source_type",
                "product",
                "enabled",
                "doc_count",
                "chunk_count",
                "sync_success_rate",
                "total_syncs",
                "failed_syncs",
                "health",
                "last_sync",
                # DSH-01 新增语义字段
                "window_days",
                "success_syncs",
                "partial_syncs",
                "last_sync_status",
                "last_sync_error",
            }
            assert expected.issubset(set(item.keys()))
        finally:
            await self._cleanup(prefix)
