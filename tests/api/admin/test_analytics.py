"""Analytics API 集成测试(Coverage Gaps + Top Questions + Source Analytics)。

遵循 codebase 现有模式:每个测试内创建 client + headers,
通过 pytestmark 与 admin conftest 的 session 级 _setup_app_state fixture 对齐。
"""

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
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
            resp = await client.get(
                "/api/admin/analytics/coverage-gaps", headers=viewer_headers
            )
        assert resp.status_code == 200

    async def test_viewer_cannot_refresh(self, viewer_headers):
        """viewer 不能触发聚类刷新(应返回 403)。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/analytics/coverage-gaps/refresh", headers=viewer_headers
            )
        assert resp.status_code == 403
