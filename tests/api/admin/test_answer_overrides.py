"""答案覆盖 Admin CRUD API 测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import AnswerOverride, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    """创建管理员用户并返回 Authorization 头;测试结束后清理覆盖与用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="ao-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理:删除测试创建的覆盖和用户
    async with factory() as session:
        await session.execute(
            AnswerOverride.__table__.delete().where(AnswerOverride.created_by == "ao-admin@test.com")
        )
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def viewer_headers():
    """创建 viewer 用户并返回 Authorization 头;测试结束后清理用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="ao-viewer@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.integration
async def test_create_and_list_override(admin_headers):
    """admin 创建覆盖后,list 中可见。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/answer-overrides",
            json={
                "match_pattern": "保修期_ao_test",
                "match_type": "keyword",
                "override_answer": "保修期为 2 年",
                "override_sources": [{"url": "https://example.com/w", "title": "Warranty"}],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["match_pattern"] == "保修期_ao_test"
        assert data["is_active"] is True

        resp = await client.get("/api/admin/answer-overrides", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(o["match_pattern"] == "保修期_ao_test" for o in items)


@pytest.mark.integration
async def test_update_override(admin_headers):
    """admin 更新覆盖内容。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/admin/answer-overrides",
            json={
                "match_pattern": "update_test_ao",
                "match_type": "keyword",
                "override_answer": "old answer",
            },
            headers=admin_headers,
        )
        assert create.status_code == 201
        oid = create.json()["id"]

        resp = await client.patch(
            f"/api/admin/answer-overrides/{oid}",
            json={"override_answer": "new answer"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["override_answer"] == "new answer"


@pytest.mark.integration
async def test_delete_override(admin_headers):
    """admin 删除覆盖。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/admin/answer-overrides",
            json={
                "match_pattern": "delete_test_ao",
                "match_type": "keyword",
                "override_answer": "temp",
            },
            headers=admin_headers,
        )
        assert create.status_code == 201
        oid = create.json()["id"]

        resp = await client.delete(f"/api/admin/answer-overrides/{oid}", headers=admin_headers)
        assert resp.status_code == 204

        resp = await client.get("/api/admin/answer-overrides", headers=admin_headers)
        items = resp.json()["items"]
        assert not any(o["id"] == oid for o in items)


@pytest.mark.integration
async def test_viewer_cannot_create(viewer_headers):
    """viewer 角色不能创建覆盖。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/answer-overrides",
            json={
                "match_pattern": "viewer_test_ao",
                "match_type": "keyword",
                "override_answer": "answer",
            },
            headers=viewer_headers,
        )
        assert resp.status_code == 403
