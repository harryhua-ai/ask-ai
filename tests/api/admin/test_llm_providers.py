"""LLM 供应商 CRUD + 路由 + 连通性测试端点测试。

覆盖:
- list_providers(viewer+ 可读、未认证 401、api_key 已脱敏)
- create_provider(201、重复 ID 409、api_key 在 DB 中已加密)
- update_provider(PATCH、404、传入 api_key 被加密、
  不传 api_key 时保留原密文、传入 "********" 时保留原密文)
- delete_provider(DELETE、404)
- list_routing(viewer+ 可读,含 Task 9 迁移项)
- update_routing(创建、更新)
- test_provider(连通性测试 —— 通过 mock 避免真实网络调用;异常返回脱敏错误)

清理策略:仅删除本测试创建的 LLMProviderModel(id 以 "test-prov" 开头)和
LLMRouting(task 以 "test-" 开头),不触碰 Task 9 迁移的 deepseek 供应商 / generation 路由。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.crypto import decrypt_api_key
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import LLMProviderModel, LLMRouting, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")

# 测试用 ID 前缀,teardown 时按前缀清理,绝不触碰迁移的 deepseek
_TEST_PROV_PREFIX = "test-prov"
_TEST_PROV_ID = "test-prov-list"
_TEST_PROV_ID_2 = "test-prov-create"
_TEST_PROV_ID_3 = "test-prov-patch"
_TEST_PROV_ID_4 = "test-prov-del"
_TEST_PROV_ID_5 = "test-prov-conn"
_TEST_PROV_ID_6 = "test-prov-patch-no-key"
_TEST_PROV_ID_7 = "test-prov-patch-masked"
_TEST_TASK = "test-task"


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户并返回 Authorization 头。

    测试结束后仅清理本测试创建的 LLMProvider / LLMRouting / User,
    保留 Task 9 迁移的 deepseek 供应商与 generation / query_decomposition 路由。
    """
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="llm-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理:仅删除本测试创建的 provider(按 id 前缀)与路由(按 task 前缀),
    # 以及测试用户。不删除 deepseek 供应商或迁移的路由。
    async with factory() as session:
        await session.execute(
            delete(LLMProviderModel).where(LLMProviderModel.id.like(f"{_TEST_PROV_PREFIX}%"))
        )
        await session.execute(delete(LLMRouting).where(LLMRouting.task == _TEST_TASK))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_providers_requires_auth():
    """未认证访问 GET /api/admin/llm-providers 返回 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/llm-providers")
    assert resp.status_code == 401


async def test_list_providers_includes_deepseek_and_masks_key(auth_headers):
    """viewer+ 鉴权后能列出 Task 9 迁移的 deepseek,且 api_key 被脱敏。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/llm-providers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Task 9 迁移的 deepseek 必须保留
    deepseek = next((p for p in data if p["id"] == "deepseek"), None)
    assert deepseek is not None, "Task 9 deepseek 供应商丢失"
    # api_key 必须脱敏,绝不能泄露明文或密文
    assert deepseek["config"]["api_key"] == "********"
    # 其他字段正常返回
    assert deepseek["type"] == "openai_compatible"
    assert deepseek["enabled"] is True
    assert deepseek["config"]["model"]


async def test_create_provider_success_and_encrypts_key(auth_headers):
    """POST 创建成功返回 201;DB 中的 api_key 已被加密,响应中已脱敏。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_2,
                "type": "openai_compatible",
                "enabled": True,
                "config": {
                    "api_base": "https://api.example.com/v1",
                    "api_key": "sk-test-secret-key-12345",
                    "model": "gpt-test",
                    "max_tokens": 2048,
                    "temperature": 0.5,
                },
            },
            headers=auth_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == _TEST_PROV_ID_2
    # 响应中 api_key 必须脱敏
    assert body["config"]["api_key"] == "********"
    assert body["config"]["model"] == "gpt-test"

    # 验证 DB 中的 api_key 已被加密(非明文,且能用 encryption_key 解回原文)
    factory = app.state.session_factory
    encryption_key = app.state.settings.encryption_key
    async with factory() as session:
        row = (
            await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_2)
            )
        ).scalar_one()
        db_api_key = row.config["api_key"]
    assert db_api_key != "sk-test-secret-key-12345", "api_key 未被加密"
    assert db_api_key != "********", "脱敏占位符被写入了 DB"
    assert decrypt_api_key(db_api_key, encryption_key) == "sk-test-secret-key-12345"


async def test_create_provider_duplicate_id_409(auth_headers):
    """ID 冲突返回 409,且不会覆盖已有行。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 第一次创建成功
        resp1 = await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://a.example.com/v1",
                    "api_key": "sk-orig",
                    "model": "m1",
                },
            },
            headers=auth_headers,
        )
        assert resp1.status_code == 201
        # 再次创建同 ID → 409
        resp2 = await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://b.example.com/v1",
                    "api_key": "sk-dup",
                    "model": "m2",
                },
            },
            headers=auth_headers,
        )
    assert resp2.status_code == 409


async def test_update_provider_partial_and_encrypts_key(auth_headers):
    """PATCH 仅更新非 None 字段;传入新 api_key 会被加密。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先创建
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_3,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://orig.example.com/v1",
                    "api_key": "sk-orig",
                    "model": "m-orig",
                },
            },
            headers=auth_headers,
        )
        # 更新 enabled 与 api_key
        resp = await client.patch(
            f"/api/admin/llm-providers/{_TEST_PROV_ID_3}",
            json={"enabled": False, "config": {"api_key": "sk-rotated"}},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["config"]["api_key"] == "********"
    # 未更新的字段保持原值
    assert body["config"]["model"] == "m-orig"

    # 验证 DB 中 api_key 已轮换为新的加密值
    factory = app.state.session_factory
    encryption_key = app.state.settings.encryption_key
    async with factory() as session:
        row = (
            await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_3)
            )
        ).scalar_one()
    assert decrypt_api_key(row.config["api_key"], encryption_key) == "sk-rotated"


async def test_update_provider_without_api_key_preserves_ciphertext(auth_headers):
    """PATCH config 不含 api_key 时,DB 中已加密的 api_key 密文保持不变。

    回归覆盖 C1:旧实现把 DB 中已加密的 api_key 当明文再次加密,
    导致密文被二次加密、永久无法解密。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_6,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://orig.example.com/v1",
                    "api_key": "sk-keep-me",
                    "model": "m-orig",
                    "max_tokens": 4096,
                },
            },
            headers=auth_headers,
        )
        # 读取 PATCH 前的 DB 密文
        factory = app.state.session_factory
        encryption_key = app.state.settings.encryption_key
        async with factory() as session:
            before = (
                await session.execute(
                    select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_6)
                )
            ).scalar_one()
            ciphertext_before = before.config["api_key"]
        # 解密验证初始值
        assert decrypt_api_key(ciphertext_before, encryption_key) == "sk-keep-me"

        # PATCH 只改 max_tokens,不传 api_key
        resp = await client.patch(
            f"/api/admin/llm-providers/{_TEST_PROV_ID_6}",
            json={"config": {"max_tokens": 8192}},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["config"]["max_tokens"] == 8192
    assert body["config"]["api_key"] == "********"

    # 验证 DB 中 api_key 密文未变,且仍能解回原始明文(未被二次加密)
    async with factory() as session:
        after = (
            await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_6)
            )
        ).scalar_one()
        ciphertext_after = after.config["api_key"]
    assert ciphertext_after == ciphertext_before, "PATCH 其他字段不应改变 api_key 密文"
    assert decrypt_api_key(ciphertext_after, encryption_key) == "sk-keep-me"


async def test_update_provider_with_masked_placeholder_preserves_ciphertext(auth_headers):
    """PATCH config 中 api_key 为 "********" 时,DB 密文保持不变。

    回归覆盖 C2:旧实现把前端回显的占位符 "********" 当明文加密回写,
    覆盖了 DB 中的真实密文。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_7,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://orig.example.com/v1",
                    "api_key": "sk-keep-me",
                    "model": "m-orig",
                },
            },
            headers=auth_headers,
        )
        factory = app.state.session_factory
        encryption_key = app.state.settings.encryption_key
        async with factory() as session:
            before = (
                await session.execute(
                    select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_7)
                )
            ).scalar_one()
            ciphertext_before = before.config["api_key"]

        # 前端把列表接口返回的 "********" 原样回传
        resp = await client.patch(
            f"/api/admin/llm-providers/{_TEST_PROV_ID_7}",
            json={"config": {"api_key": "********", "model": "m-new"}},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["config"]["model"] == "m-new"
    assert body["config"]["api_key"] == "********"

    # DB 密文必须未变,且仍能解回原始明文
    async with factory() as session:
        after = (
            await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == _TEST_PROV_ID_7)
            )
        ).scalar_one()
        ciphertext_after = after.config["api_key"]
    assert ciphertext_after == ciphertext_before, "前端回显的 '********' 不应覆盖 DB 中的真实密文"
    assert decrypt_api_key(ciphertext_after, encryption_key) == "sk-keep-me"


async def test_update_provider_with_empty_api_key_preserves_ciphertext(auth_headers):
    """PATCH 显式传入空 api_key 时按留空不修改语义处理。"""
    provider_id = "test-prov-empty-key"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": provider_id,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://empty-key.example.com/v1",
                    "api_key": "sk-keep-me",
                    "model": "m-orig",
                },
            },
            headers=auth_headers,
        )
        factory = app.state.session_factory
        encryption_key = app.state.settings.encryption_key
        async with factory() as session:
            before = (
                await session.execute(
                    select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
                )
            ).scalar_one()
            ciphertext_before = before.config["api_key"]

        response = await client.patch(
            f"/api/admin/llm-providers/{provider_id}",
            json={"config": {"api_key": ""}},
            headers=auth_headers,
        )

    assert response.status_code == 200
    async with factory() as session:
        after = (
            await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
            )
        ).scalar_one()
        ciphertext_after = after.config["api_key"]
    assert ciphertext_after == ciphertext_before
    assert decrypt_api_key(ciphertext_after, encryption_key) == "sk-keep-me"

    """更新不存在的 ID 返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/admin/llm-providers/{_TEST_PROV_PREFIX}-nonexistent",
            json={"enabled": False},
            headers=auth_headers,
        )
    assert resp.status_code == 404


async def test_delete_provider_and_404(auth_headers):
    """DELETE 成功后再次删除返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先创建
        create_resp = await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_4,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://delete.example.com/v1",
                    "api_key": "sk-del",
                    "model": "m-del",
                },
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        # 删除成功 → 204
        del_resp = await client.delete(
            f"/api/admin/llm-providers/{_TEST_PROV_ID_4}", headers=auth_headers
        )
        assert del_resp.status_code == 204
        # 再次删除 → 404
        del_resp2 = await client.delete(
            f"/api/admin/llm-providers/{_TEST_PROV_ID_4}", headers=auth_headers
        )
    assert del_resp2.status_code == 404


async def test_list_routing_includes_migrated(auth_headers):
    """GET /api/admin/llm-routing 列出路由,含 generation / intent / query_rewrite。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/llm-routing", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    tasks = {r["task"] for r in data}
    assert "generation" in tasks, "generation 路由丢失"
    assert "intent" in tasks, "intent 路由丢失"
    assert "query_rewrite" in tasks, "query_rewrite 路由丢失"
    assert "query_decomposition" not in tasks, "历史命名错误路由应已被迁移脚本删除"
    # 迁移的 generation 链路必须指向 deepseek（对象格式 {provider, model}）
    gen_route = next(r for r in data if r["task"] == "generation")
    assert gen_route["chain"] == [{"provider": "deepseek", "model": None}]


async def test_update_routing_creates_and_updates(auth_headers):
    """PUT /api/admin/llm-routing/{task}:
    - 首次 PUT 创建路由
    - 再次 PUT 更新路由
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 首次 PUT 创建 test-task 路由（写入侧只接受对象格式 chain）
        resp1 = await client.put(
            f"/api/admin/llm-routing/{_TEST_TASK}",
            json={"chain": [{"provider": "deepseek", "model": None}]},
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        # 再次 PUT 更新 chain
        resp2 = await client.put(
            f"/api/admin/llm-routing/{_TEST_TASK}",
            json={"chain": [{"provider": "deepseek"}, {"provider": "another-provider"}]},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        # 验证最终 chain
        list_resp = await client.get("/api/admin/llm-routing", headers=auth_headers)
    assert list_resp.status_code == 200
    routes = list_resp.json()
    test_route = next(r for r in routes if r["task"] == _TEST_TASK)
    assert test_route["chain"] == [
        {"provider": "deepseek", "model": None},
        {"provider": "another-provider", "model": None},
    ]


async def test_connectivity_test_mocked(auth_headers):
    """POST /api/admin/llm-providers/:id/test 通过 mock 验证返回结构。

    说明:不真实调用 DeepSeek API(会触发外部网络 + 消耗 token),
    改为 mock LLMRegistry.create 返回的 provider.health_check。
    """
    # 先创建一个测试 provider
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_5,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://mock.example.com/v1",
                    "api_key": "sk-mock",
                    "model": "m-mock",
                },
            },
            headers=auth_headers,
        )

        # mock health_check 返回 True
        mock_provider = AsyncMock()
        mock_provider.health_check = AsyncMock(return_value=True)
        with patch(
            "backend.api.admin.llm_providers.LLMRegistry.create",
            return_value=mock_provider,
        ):
            resp = await client.post(
                f"/api/admin/llm-providers/{_TEST_PROV_ID_5}/test",
                headers=auth_headers,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_id"] == _TEST_PROV_ID_5
    assert body["success"] is True
    assert body["latency_ms"] is not None
    assert body["latency_ms"] >= 0
    assert body["error"] is None
    # 确认 health_check 确实被调用(mock 生效)
    mock_provider.health_check.assert_awaited_once()


async def test_connectivity_test_handles_failure(auth_headers):
    """连通性测试在 LLM 抛异常时返回 success=False 与脱敏错误,不泄露 api_key 或内部细节。

    回归覆盖 I1:旧实现把 str(exc) 直接回传,若异常消息包含 URL / auth header
    则可能泄露解密后的 api_key。修复后只返回通用消息,不泄露异常类型名
    (避免放大 SSRF oracle)。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 复用前一个测试创建的 _TEST_PROV_ID_5(若不存在则创建)
        await client.post(
            "/api/admin/llm-providers",
            json={
                "id": _TEST_PROV_ID_5,
                "type": "openai_compatible",
                "config": {
                    "api_base": "https://mock.example.com/v1",
                    "api_key": "sk-mock",
                    "model": "m-mock",
                },
            },
            headers=auth_headers,
        )

        # mock LLMRegistry.create 抛异常,异常消息中嵌入 api_key 模拟 HTTP 客户端泄露
        leaked_msg = "HTTP 401 Unauthorized: Bearer sk-mock rejected"
        with patch(
            "backend.api.admin.llm_providers.LLMRegistry.create",
            side_effect=RuntimeError(leaked_msg),
        ):
            resp = await client.post(
                f"/api/admin/llm-providers/{_TEST_PROV_ID_5}/test",
                headers=auth_headers,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["latency_ms"] is None
    # 返回的是脱敏的通用消息,不包含原始异常文本
    assert body["error"] is not None
    assert "RuntimeError" not in body["error"], "错误消息不应泄露异常类型名（SSRF oracle）"
    assert "LLM 连通性测试失败" in body["error"], "错误消息应为脱敏的通用文案"
    # 关键:绝不泄露原始异常文本或 api_key
    assert "connection" not in body["error"].lower(), "不应包含原始异常文本"
    assert "sk-mock" not in body["error"], "错误消息中绝不包含 api_key"
    assert "Bearer" not in body["error"], "错误消息中绝不包含 auth header 片段"


# ===== Task 4: reload + fetch-models 端点测试 =====
# 沿用文件既有的 auth_headers fixture 和 _TEST_PROV_PREFIX 惯例，
# 仅使用 test-prov / test- 前缀的 id/task，不触碰迁移的 deepseek / generation。

from backend.auth.crypto import encrypt_api_key


@pytest.mark.asyncio(loop_scope="session")
async def test_reload_reconfigures_router(auth_headers):
    """reload 端点调 app.state.llm.reconfigure，DB 中的 provider 进 router。

    核心副作用断言：reconfigure 必须被调用（否则 reload 是空操作）。
    """
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            LLMProviderModel(
                id="test-prov-reload",
                type="openai_compatible",
                enabled=True,
                config={
                    "api_base": "https://api.test.com/v1",
                    "api_key": "k",
                    "model": "m1",
                    "available_models": ["m1"],
                },
            )
        )
        session.add(
            LLMRouting(
                task="test-reload-task", chain=[{"provider": "test-prov-reload", "model": None}]
            )
        )
        await session.commit()

    # 用假 router 捕获 reconfigure 调用
    fake_router = AsyncMock()
    fake_router.reconfigure = MagicMock()
    app.state.llm = fake_router

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/admin/llm-providers/reload", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["providers_count"] >= 1
        assert "test-reload-task" in body["routing"]
        # 核心副作用：reconfigure 必须被同步调用一次（reconfigure 是同步方法）
        fake_router.reconfigure.assert_called_once()
    finally:
        # 清理：恢复真实 router 引用（避免污染后续测试）
        del app.state.llm
        async with factory() as session:
            await session.execute(
                delete(LLMProviderModel).where(LLMProviderModel.id == "test-prov-reload")
            )
            await session.execute(delete(LLMRouting).where(LLMRouting.task == "test-reload-task"))
            await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_reload_skips_invalid_provider(auth_headers):
    """构造失败的 provider 记入 skipped，reload 仍成功。"""
    factory = app.state.session_factory
    async with factory() as session:
        # 未注册的 type → LLMRegistry.create 抛 KeyError
        session.add(
            LLMProviderModel(
                id="test-prov-bad-type",
                type="nonexistent_type",
                enabled=True,
                config={"api_base": "", "api_key": "", "model": ""},
            )
        )
        await session.commit()

    fake_router = AsyncMock()
    fake_router.reconfigure = MagicMock()
    app.state.llm = fake_router

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/admin/llm-providers/reload", headers=auth_headers)
        assert resp.status_code == 200
        assert "test-prov-bad-type" in resp.json()["skipped"]
    finally:
        del app.state.llm
        async with factory() as session:
            await session.execute(
                delete(LLMProviderModel).where(LLMProviderModel.id == "test-prov-bad-type")
            )
            await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_fetch_models_returns_list(auth_headers):
    """fetch-models 调 list_models 并返回 models 列表(mock 网络调用)。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            LLMProviderModel(
                id="test-prov-fetch",
                type="openai_compatible",
                enabled=True,
                config={
                    "api_base": "https://api.test.com/v1",
                    "api_key": encrypt_api_key("sk-test", app.state.settings.encryption_key),
                    "model": "m1",
                },
            )
        )
        await session.commit()

    with patch(
        "backend.llm.deepseek.DeepseekProvider.list_models",
        new=AsyncMock(return_value=["m1", "m2"]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/llm-providers/test-prov-fetch/fetch-models", headers=auth_headers
            )
    assert resp.status_code == 200
    assert resp.json()["models"] == ["m1", "m2"]

    async with factory() as session:
        await session.execute(
            delete(LLMProviderModel).where(LLMProviderModel.id == "test-prov-fetch")
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_fetch_models_sanitizes_error(auth_headers):
    """list_models 抛错时返回脱敏消息，不泄露异常细节。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            LLMProviderModel(
                id="test-prov-fetch-err",
                type="openai_compatible",
                enabled=True,
                config={
                    "api_base": "https://api.test.com/v1",
                    "api_key": encrypt_api_key("sk-test", app.state.settings.encryption_key),
                    "model": "m1",
                },
            )
        )
        await session.commit()

    with patch(
        "backend.llm.deepseek.DeepseekProvider.list_models",
        new=AsyncMock(side_effect=Exception("secret internal detail with sk-leak")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/llm-providers/test-prov-fetch-err/fetch-models", headers=auth_headers
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"] == []
    assert "secret" not in body.get("error", "")
    assert "sk-leak" not in body.get("error", "")

    async with factory() as session:
        await session.execute(
            delete(LLMProviderModel).where(LLMProviderModel.id == "test-prov-fetch-err")
        )
        await session.commit()
