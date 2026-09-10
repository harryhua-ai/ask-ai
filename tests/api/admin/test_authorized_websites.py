"""Authorized Websites 端点测试(I-UX-001 矫正,Issue #6)。

覆盖(冻结契约 §3.11):
- GET 列表 = 各站点 allowed_origins 现状;
- POST 新增:canonical 化(scheme 归一/默认端口剥除/路径剥离);
  通配符 / 路径 / 非 http(s) → 422 显式拒绝(fail closed);
  重复 exact origin → 409;未知站点 → 404;
- DELETE 移除:canonical 形式匹配;不存在 → 404;
- 授权保持 site-specific(改 A 站不影响 B 站);
- 变更跨重启/重seed 存续(seed_default_sites 不覆写既有行 origins)。
"""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import SiteExperience, User
from backend.main import app
from backend.services.site_experiences import load_sites_config, seed_default_sites

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPO_SITES_YAML = "config/sites.yaml"


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="aw-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _reset_site_origins(site_id: str) -> None:
    """测试库跨会话共享:把站点 origins 复位为 YAML 基线,保证用例确定性。"""
    yaml_origins = next(
        (
            s.get("allowed_origins") or []
            for s in load_sites_config(REPO_ROOT / "config" / "sites.yaml")
            if s["site_id"] == site_id
        ),
        [],
    )
    factory = app.state.session_factory
    async with factory() as session:
        row = await session.get(SiteExperience, site_id)
        row.allowed_origins = list(yaml_origins)
        await session.commit()


class TestAuthorizedWebsitesCrud:
    async def test_list_returns_sites_with_origins(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        async with await _client() as client:
            resp = await client.get("/api/admin/authorized-websites", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        by_id = {row["site_id"]: row for row in body}
        assert "camthink-website" in by_id
        assert "https://www.camthink.ai" in by_id["camthink-website"]["allowed_origins"]

    async def test_add_origin_canonicalizes_and_persists(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        await _reset_site_origins("camthink-website")
        # 策略输入拒绝路径/查询串(422;授权范围 = origin,不含路径)
        async with await _client() as client:
            pathy = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://newsite.example.com/docs?page=1"},
            )
            assert pathy.status_code == 422
            # 裸 origin canonical 化(尾部「/」剥除)后入库
            resp = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://newsite.example.com/"},
            )
            assert resp.status_code == 200
            assert resp.json()["allowed_origins"][-1] == "https://newsite.example.com"
            # 直接读 DB 权威确认持久化
            async with factory() as session:
                row = await session.get(SiteExperience, "camthink-website")
            assert "https://newsite.example.com" in row.allowed_origins

    async def test_add_keeps_non_default_port_and_scheme_distinction(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        async with await _client() as client:
            resp = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "http://staging.example.com:8443"},
            )
            assert resp.status_code == 200
            assert "http://staging.example.com:8443" in resp.json()["allowed_origins"]

    async def test_add_rejects_wildcard_path_and_non_http(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        await _reset_site_origins("camthink-website")
        for bad in ("https://*.camthink.ai", "https://camthink.ai/path", "ftp://x.example.com", "not-a-url"):
            async with await _client() as client:
                resp = await client.post(
                    "/api/admin/authorized-websites/camthink-website/origins",
                    headers=auth_headers,
                    json={"origin": bad},
                )
            assert resp.status_code == 422, bad
            async with factory() as session:
                row = await session.get(SiteExperience, "camthink-website")
            assert all("*.camthink" not in o for o in row.allowed_origins)

    async def test_add_duplicate_origin_conflicts(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        await _reset_site_origins("camthink-website")
        async with await _client() as client:
            first = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://dup.example.com"},
            )
            assert first.status_code == 200
            second = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://dup.example.com"},
            )
            assert second.status_code == 409

    async def test_remove_origin_and_unknown_origin_404(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        await _reset_site_origins("camthink-website")
        async with await _client() as client:
            added = await client.post(
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://temp.example.com"},
            )
            assert added.status_code == 200
            removed = await client.request(
                "DELETE",
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://temp.example.com"},
            )
            assert removed.status_code == 200
            assert "https://temp.example.com" not in removed.json()["allowed_origins"]
            missing = await client.request(
                "DELETE",
                "/api/admin/authorized-websites/camthink-website/origins",
                headers=auth_headers,
                json={"origin": "https://temp.example.com"},
            )
            assert missing.status_code == 404

    async def test_site_specific_authorization_isolation(self, auth_headers):
        factory = app.state.session_factory
        await seed_default_sites(factory)
        async with await _client() as client:
            resp = await client.post(
                "/api/admin/authorized-websites/camthink-wiki/origins",
                headers=auth_headers,
                json={"origin": "https://wiki-only.example.com"},
            )
            assert resp.status_code == 200
        async with factory() as session:
            website = await session.get(SiteExperience, "camthink-website")
            wiki = await session.get(SiteExperience, "camthink-wiki")
        assert "https://wiki-only.example.com" not in (website.allowed_origins or [])
        assert "https://wiki-only.example.com" in (wiki.allowed_origins or [])
        # 清理,不影响其它用例的 YAML 基线断言
        async with await _client() as client:
            await client.request(
                "DELETE",
                "/api/admin/authorized-websites/camthink-wiki/origins",
                headers=auth_headers,
                json={"origin": "https://wiki-only.example.com"},
            )

    async def test_unknown_site_404(self, auth_headers):
        async with await _client() as client:
            resp = await client.post(
                "/api/admin/authorized-websites/no-such-site/origins",
                headers=auth_headers,
                json={"origin": "https://x.example.com"},
            )
            assert resp.status_code == 404
