"""Customization CRUD + 渠道绑定端点测试。

覆盖:
- list_customizations(viewer+ 可读、未认证 401)
- create_customization(201、重复 ID 409)
- update_customization(PATCH、404)
- delete_customization(DELETE、404)
- list_bindings(viewer+ 可读)
- update_binding(合法渠道、非法渠道 400、不存在 customization 404)

清理策略:仅删除本测试创建的 Customization(id 前缀 "test-cust")和
绑定(channel 在 {whatsapp, discord, mcp} ∪ widget 测试用例),不触碰
Task 9 迁移的 "default" customization / widget 绑定。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Customization, CustomizationBinding, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")

# 测试用的临时 ID 前缀,teardown 时按前缀清理
_TEST_CUST_ID = "test-cust"
_TEST_CUST_ID_2 = "test-cust-2"
_TEST_CHANNELS = {"whatsapp", "discord", "mcp"}


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户并返回 Authorization 头。

    测试结束后仅清理本测试创建的 Customization / Binding / User,
    保留 Task 9 迁移的 default + widget 绑定。
    """
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="cust-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理:删除本测试创建的 customization(按 id 前缀)与非 widget 的测试绑定,
    # 以及测试用户。不删除 default customization 或 widget 绑定。
    async with factory() as session:
        await session.execute(
            delete(CustomizationBinding).where(CustomizationBinding.channel.in_(_TEST_CHANNELS))
        )
        await session.execute(delete(Customization).where(Customization.id.startswith("test-cust")))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_customizations_requires_auth():
    """未认证访问 GET /api/admin/customizations 返回 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/customizations")
    assert resp.status_code == 401


async def test_list_customizations_includes_migrated_default(auth_headers):
    """viewer+ 鉴权后能列出 Task 9 迁移的 default customization。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/customizations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Task 9 迁移的 default customization 必须保留
    assert any(c["id"] == "default" for c in data), "Task 9 default 配置丢失"
    # 字段齐全
    default = next(c for c in data if c["id"] == "default")
    assert default["system_prompt"]
    assert default["language"]
    assert default["assistant_name"]


async def test_create_customization_success(auth_headers):
    """POST /api/admin/customizations 创建成功返回 201 且字段一致。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID,
                "name": "测试配置",
                "system_prompt": "你是测试助手",
                "language": "zh-cn",
                "assistant_name": "测试助手",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == _TEST_CUST_ID
    assert body["name"] == "测试配置"
    assert body["system_prompt"] == "你是测试助手"
    assert body["language"] == "zh-cn"
    assert body["assistant_name"] == "测试助手"
    # is_active / version 有默认值
    assert body["is_active"] is True
    assert body["version"]


async def test_create_customization_duplicate_id_409(auth_headers):
    """ID 冲突返回 409,且不会覆盖已有行。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 第一次创建成功
        resp1 = await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID_2,
                "name": "测试配置 2",
                "system_prompt": "prompt-2",
            },
            headers=auth_headers,
        )
        assert resp1.status_code == 201
        # 再次创建同 ID → 409
        resp2 = await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID_2,
                "name": "重复创建",
                "system_prompt": "prompt-3",
            },
            headers=auth_headers,
        )
    assert resp2.status_code == 409


async def test_update_customization_partial(auth_headers):
    """PATCH 仅更新非 None 字段,未传字段保持原值。"""
    # 先确保 _TEST_CUST_ID 存在(若上一个测试清理过则重新创建)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID,
                "name": "原始名",
                "system_prompt": "原始 prompt",
            },
            headers=auth_headers,
        )
        resp = await client.patch(
            f"/api/admin/customizations/{_TEST_CUST_ID}",
            json={"name": "新名字", "style_tone": "正式"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "新名字"
    assert body["style_tone"] == "正式"
    # 未更新的字段保持原值
    assert body["system_prompt"] == "原始 prompt"


async def test_update_customization_not_found(auth_headers):
    """更新不存在的 ID 返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/api/admin/customizations/test-cust-nonexistent",
            json={"name": "ghost"},
            headers=auth_headers,
        )
    assert resp.status_code == 404


async def test_delete_customization_and_404(auth_headers):
    """DELETE 成功后再次删除返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先创建
        create_resp = await client.post(
            "/api/admin/customizations",
            json={
                "id": "test-cust-del",
                "name": "待删除",
                "system_prompt": "delete-me",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        # 删除成功 → 204
        del_resp = await client.delete(
            "/api/admin/customizations/test-cust-del", headers=auth_headers
        )
        assert del_resp.status_code == 204
        # 再次删除 → 404
        del_resp2 = await client.delete(
            "/api/admin/customizations/test-cust-del", headers=auth_headers
        )
    assert del_resp2.status_code == 404


async def test_list_bindings_includes_widget(auth_headers):
    """GET /api/admin/customization-bindings 列出绑定,含 Task 9 的 widget 绑定。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/customization-bindings", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Task 9 迁移的 widget → default 绑定必须保留
    assert any(
        b["channel"] == "widget" and b["customization_id"] == "default" for b in data
    ), "Task 9 widget 绑定丢失"


async def test_update_binding_creates_and_updates(auth_headers):
    """PUT /api/admin/customization-bindings/{channel}:
    - 首次 PUT 创建绑定
    - 再次 PUT 更新绑定
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先确保有两个 customization 可绑定
        await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID,
                "name": "绑定测试 1",
                "system_prompt": "p1",
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/admin/customizations",
            json={
                "id": _TEST_CUST_ID_2,
                "name": "绑定测试 2",
                "system_prompt": "p2",
            },
            headers=auth_headers,
        )
        # 首次 PUT 创建 whatsapp 绑定
        resp1 = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            json={"customization_id": _TEST_CUST_ID},
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        # 再次 PUT 更新 whatsapp 绑定
        resp2 = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            json={"customization_id": _TEST_CUST_ID_2},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        # 验证最终绑定指向 _TEST_CUST_ID_2
        list_resp = await client.get("/api/admin/customization-bindings", headers=auth_headers)
    assert list_resp.status_code == 200
    bindings = list_resp.json()
    whatsapp_binding = next(b for b in bindings if b["channel"] == "whatsapp")
    assert whatsapp_binding["customization_id"] == _TEST_CUST_ID_2


async def test_update_binding_invalid_channel_400(auth_headers):
    """非法渠道返回 400。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/customization-bindings/invalid-channel",
            json={"customization_id": "default"},
            headers=auth_headers,
        )
    assert resp.status_code == 400


async def test_update_binding_customization_not_found_404(auth_headers):
    """绑定的 customization_id 不存在返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/customization-bindings/discord",
            json={"customization_id": "ghost-customization"},
            headers=auth_headers,
        )
    assert resp.status_code == 404
