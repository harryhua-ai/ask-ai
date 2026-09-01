"""LLM 自定义端点授权(端点信任)管理端点测试。

冻结契约(CAMTHINK_V1_ADMIN_P1 LLM-02/LLM-03):
- 自定义/私有 api_base 默认拒绝;只有管理员通过产品工作流显式授权后才可用;
- 授权持久化在 DB(llm_allowed_hosts 表),可查看、可撤销,不依赖 .env;
- 无通配符、无自动信任;SSRF 校验(协议/内网 DNS)不放宽;
- 授权写操作仅 admin 角色;读取 viewer+。

覆盖:
- POST 授权:公网主机 public 级;私有 IP 字面量自动 private 级(allow_private=True)
- 输入归一化:剥 scheme/port/path、转小写;通配符/空值拒绝
- 重复授权 409;撤销 204/404;editor 写 403;viewer 可读不可写
- validate_llm_api_base 纯函数:authorized_public/authorized_private 语义
- 私有族判定:is_global=False 的地址(含 CGNAT 100.64/10)按私有族处理
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.auth.jwt import create_access_token, hash_password
from backend.api.admin.schemas import validate_llm_api_base
from backend.db.models import LLMAllowedHost, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")

# 本文件创建的授权行 host 清单,teardown 精确清理
_TEST_HOSTS = {
    "api.together.xyz",
    "api.openrouter.ai",
    "100.124.85.19",
    "10.201.3.7",
    "127.0.0.1",
    "api.example.com",  # 归一化测试用,单独清理避免误伤 conftest 环境变量语义
}


@pytest_asyncio.fixture(loop_scope="session")
async def role_headers():
    """创建 admin / editor / viewer 三个用户,返回 {role: headers}。"""
    factory = app.state.session_factory
    out: dict[str, dict] = {}
    ids: list[str] = []
    for role in ("admin", "editor", "viewer"):
        user_id = uuid.uuid4()
        ids.append(user_id)
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{role}-hosts-{str(user_id)[:8]}@test.com",
                    role=role,
                    password_hash=hash_password("pass123"),
                )
            )
            await session.commit()
        token = create_access_token(str(user_id), role, app.state.settings.jwt_secret)
        out[role] = {"Authorization": f"Bearer {token}"}
    yield out
    async with factory() as session:
        await session.execute(delete(LLMAllowedHost).where(LLMAllowedHost.host.in_(_TEST_HOSTS)))
        await session.execute(User.__table__.delete().where(User.id.in_(ids)))
        await session.commit()


async def _cleanup_hosts() -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(delete(LLMAllowedHost).where(LLMAllowedHost.host.in_(_TEST_HOSTS)))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def clean_hosts():
    """每个测试前后清空本文件的授权行,保证互不干扰。"""
    await _cleanup_hosts()
    yield
    await _cleanup_hosts()


# ---------------------------------------------------------------------------
# POST 授权
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_authorize_public_host_creates_public_tier(role_headers, clean_hosts):
    """管理员授权公网主机 → 201,public 级(allow_private=False),记录 created_by。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "api.together.xyz", "note": "P1 验收:第三方公网供应商"},
            headers=role_headers["admin"],
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["host"] == "api.together.xyz"
    assert body["allow_private"] is False
    assert body["note"] == "P1 验收:第三方公网供应商"
    assert body["created_by"]


@pytest.mark.asyncio(loop_scope="session")
async def test_authorize_host_input_normalized(role_headers, clean_hosts):
    """授权输入剥 scheme/port/path 并转小写:HTTPS://Api.Together.XYZ:8443/v1 → api.together.xyz。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "HTTPS://Api.Together.XYZ:8443/v1"},
            headers=role_headers["admin"],
        )
    assert resp.status_code == 201
    assert resp.json()["host"] == "api.together.xyz"


@pytest.mark.asyncio(loop_scope="session")
async def test_authorize_private_ip_gets_private_tier(role_headers, clean_hosts):
    """私有/非全局 IP 字面量授权 → 自动 private 级(allow_private=True)。

    含 RFC1918(10.x)、loopback(127.x)与 CGNAT/Tailscale(100.64/10,is_global=False)。
    """
    for host in ("10.201.3.7", "127.0.0.1", "100.124.85.19"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/llm-allowed-hosts",
                json={"host": host, "note": "自建网关"},
                headers=role_headers["admin"],
            )
        assert resp.status_code == 201, host
        assert resp.json()["allow_private"] is True, host


@pytest.mark.asyncio(loop_scope="session")
async def test_authorize_host_rejects_wildcard_and_empty(role_headers, clean_hosts):
    """通配符/空主机/纯 scheme 一律 422:授权必须精确到主机,无全局放行。"""
    for bad in ("*", "", "https://", "*.example.com", "host with space"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/llm-allowed-hosts",
                json={"host": bad},
                headers=role_headers["admin"],
            )
        assert resp.status_code == 422, f"host={bad!r} 应拒绝"


@pytest.mark.asyncio(loop_scope="session")
async def test_authorize_host_duplicate_409(role_headers, clean_hosts):
    """重复授权同一主机 → 409(授权记录唯一)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "api.openrouter.ai"},
            headers=role_headers["admin"],
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "api.openrouter.ai"},
            headers=role_headers["admin"],
        )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# 角色边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_editor_and_viewer_cannot_authorize(role_headers, clean_hosts):
    """授权是管理员专属:editor / viewer POST → 403。"""
    for role in ("editor", "viewer"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/llm-allowed-hosts",
                json={"host": "api.together.xyz"},
                headers=role_headers[role],
            )
        assert resp.status_code == 403, role


@pytest.mark.asyncio(loop_scope="session")
async def test_viewer_can_list_hosts(role_headers, clean_hosts):
    """授权列表 viewer+ 可读(与其它 LLM 配置读取一致)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "api.together.xyz"},
            headers=role_headers["admin"],
        )
        assert created.status_code == 201
        listed = await client.get("/api/admin/llm-allowed-hosts", headers=role_headers["viewer"])
    assert listed.status_code == 200
    hosts = {item["host"] for item in listed.json()}
    assert "api.together.xyz" in hosts


@pytest.mark.asyncio(loop_scope="session")
async def test_list_hosts_requires_auth():
    """未认证读取授权列表 → 401。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/llm-allowed-hosts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 撤销
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_revoke_host_admin_204_then_404(role_headers, clean_hosts):
    """管理员撤销授权 → 204;再删 → 404;editor 撤销 → 403。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/llm-allowed-hosts",
            json={"host": "api.openrouter.ai"},
            headers=role_headers["admin"],
        )
        assert created.status_code == 201
        editor_del = await client.delete(
            "/api/admin/llm-allowed-hosts/api.openrouter.ai", headers=role_headers["editor"]
        )
        assert editor_del.status_code == 403
        ok = await client.delete(
            "/api/admin/llm-allowed-hosts/api.openrouter.ai", headers=role_headers["admin"]
        )
        assert ok.status_code == 204
        again = await client.delete(
            "/api/admin/llm-allowed-hosts/api.openrouter.ai", headers=role_headers["admin"]
        )
    assert again.status_code == 404


# ---------------------------------------------------------------------------
# validate_llm_api_base 纯函数:授权集合语义
# ---------------------------------------------------------------------------


class TestValidateApiBaseAuthz:
    """validate_llm_api_base 的显式授权参数语义(不依赖 DB)。"""

    def test_unauthorized_public_host_denied_by_default(self):
        with pytest.raises(ValueError, match="尚未授权"):
            validate_llm_api_base("https://api.together.xyz/v1")

    def test_authorized_public_host_allowed(self):
        url = validate_llm_api_base(
            "https://api.together.xyz/v1", authorized_public=frozenset({"api.together.xyz"})
        )
        assert url == "https://api.together.xyz/v1"

    def test_private_literal_denied_even_if_public_authorized(self):
        """public 级授权不放行私有 IP 字面量:两级信任不混淆。"""
        with pytest.raises(ValueError, match="内网|私有|默认拒绝"):
            validate_llm_api_base(
                "http://10.201.3.7:13000/v1", authorized_public=frozenset({"10.201.3.7"})
            )

    def test_private_tier_authorization_allows_private_literal(self):
        url = validate_llm_api_base(
            "http://10.201.3.7:13000/v1", authorized_private=frozenset({"10.201.3.7"})
        )
        assert url == "http://10.201.3.7:13000/v1"

    def test_cgnat_range_requires_private_tier(self):
        """100.64/10(CGNAT/Tailscale,is_global=False)按私有族处理:默认拒绝。"""
        with pytest.raises(ValueError):
            validate_llm_api_base("http://100.124.85.19:13000/v1")

    def test_malformed_scheme_denied_even_authorized(self):
        """协议校验在任何授权之下都不放宽。"""
        with pytest.raises(ValueError):
            validate_llm_api_base(
                "ftp://api.together.xyz/v1", authorized_public=frozenset({"api.together.xyz"})
            )

    def test_prod_https_still_required_for_public_authorized_host(self, monkeypatch):
        """prod 模式下 public 级授权主机仍强制 https。"""
        monkeypatch.setenv("APP_MODE", "prod")
        with pytest.raises(ValueError, match="https"):
            validate_llm_api_base(
                "http://api.together.xyz/v1", authorized_public=frozenset({"api.together.xyz"})
            )

    def test_prod_private_authorized_host_allows_http(self, monkeypatch):
        """prod 模式下 private 级授权即显式信任内网通道,允许 http(免公网 https 要求)。"""
        monkeypatch.setenv("APP_MODE", "prod")
        url = validate_llm_api_base(
            "http://10.201.3.7:13000/v1", authorized_private=frozenset({"10.201.3.7"})
        )
        assert url == "http://10.201.3.7:13000/v1"

    def test_builtin_hosts_still_pre_authorized(self):
        """内置三家主机无需 DB 授权(既有产品语义不变)。"""
        url = validate_llm_api_base("https://api.deepseek.com/v1")
        assert url == "https://api.deepseek.com/v1"
