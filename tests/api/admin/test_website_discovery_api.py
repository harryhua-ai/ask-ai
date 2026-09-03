"""#17 Website Simple Mode:preview-website 端点测试(离线,mock 抓取层)。

覆盖:robots/回退发现的 happy path、零发现显式呈现(不伪装成功)、
非法 URL 400、未登录 401、跨域跳过原因进 warnings。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin import data_sources as ds_mod
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = "https://www.example.com"

ROBOTS = f"User-agent: *\nSitemap: {BASE}/sitemap_index.xml\n"
INDEX_XML = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{base}/pages.xml</loc></sitemap>
</sitemapindex>
""".format(base=BASE)
PAGES_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/products/ne301/</loc></url>
  <url><loc>{base}/docs/quickstart/</loc></url>
  <url><loc>{base}/login</loc></url>
</urlset>
""".format(base=BASE)


def _fake_fetch_map(mapping):
    return lambda url: mapping.get(url)


@pytest_asyncio.fixture(loop_scope="session")
async def editor_headers():
    """临时管理员(只读端点,admin 即可);测试后清理。"""
    factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"wsd-{user_id}@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


async def _post(client, headers, payload):
    return await client.post(
        "/api/admin/data-sources/preview-website", json=payload, headers=headers
    )


async def test_preview_website_happy_path(editor_headers, monkeypatch):
    monkeypatch.setattr(
        ds_mod,
        "_website_fetch_text",
        _fake_fetch_map(
            {
                f"{BASE}/robots.txt": ROBOTS,
                f"{BASE}/sitemap_index.xml": INDEX_XML,
                f"{BASE}/pages.xml": PAGES_XML,
            }
        ),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, editor_headers, {"base_url": BASE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "web_crawl"
    assert body["totals"]["files"] == 3
    assert body["target"]["discovery_mode"] == "robots"
    recs = {c["path"]: c["recommendation"] for c in body["candidates"]}
    assert recs[f"{BASE}/products/ne301/"] == "include"
    assert recs[f"{BASE}/docs/quickstart/"] == "include"
    assert recs[f"{BASE}/login/"] == "exclude"
    # 推荐配置 = 连接器词表(可直写 config JSONB)
    assert body["recommended_config"]["base_url"] == BASE
    assert "/store/" in body["recommended_config"]["exclude_patterns"]
    # 人读理由随候选返回(前端无需自己映射)
    reason_by_path = {c["path"]: c["reason"] for c in body["candidates"]}
    assert reason_by_path[f"{BASE}/products/ne301/"] == "属于产品文档,建议纳入"


async def test_preview_website_zero_discovery_is_explicit(editor_headers, monkeypatch):
    """零发现:200 + 零候选 + 冻结告警(不伪装成功,不抛 500)。"""
    monkeypatch.setattr(ds_mod, "_website_fetch_text", _fake_fetch_map({}))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, editor_headers, {"base_url": BASE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["files"] == 0
    assert body["candidates"] == []
    assert body["target"]["discovery_mode"] == "none"
    assert any("未发现任何 sitemap" in w for w in body["warnings"])
    assert body["capability_notes"]


async def test_preview_website_explicit_sitemap_override(editor_headers, monkeypatch):
    """Advanced sitemap override:显式地址生效且 discovery_mode=explicit。"""
    seen: list[str] = []

    def _fetch(url):
        seen.append(url)
        return {f"{BASE}/custom.xml": PAGES_XML}.get(url)

    monkeypatch.setattr(ds_mod, "_website_fetch_text", _fetch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(
            client, editor_headers, {"base_url": BASE, "sitemap_url": f"{BASE}/custom.xml"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"]["discovery_mode"] == "explicit"
    assert body["totals"]["files"] == 3
    assert seen == [f"{BASE}/custom.xml"]  # 不再请求 robots/回退


async def test_preview_website_invalid_url_400(editor_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for bad in ("not-a-url", "ftp://x.com"):
            resp = await _post(client, editor_headers, {"base_url": bad})
            assert resp.status_code == 400, bad
        # 空串在请求模型层即被拒(422 = schema 校验)
        resp = await _post(client, editor_headers, {"base_url": ""})
        assert resp.status_code == 422
        resp = await _post(
            client,
            editor_headers,
            {"base_url": BASE, "sitemap_url": "javascript:alert(1)"},
        )
        assert resp.status_code == 400


async def test_preview_website_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, {}, {"base_url": BASE})
    assert resp.status_code == 401


async def test_preview_website_cross_domain_reason_surfaced(editor_headers, monkeypatch):
    """跨域 sitemap 显式跳过,原因进 warnings(不得静默)。"""
    robots = ROBOTS + "Sitemap: https://cdn.example.com/external.xml\n"
    monkeypatch.setattr(
        ds_mod,
        "_website_fetch_text",
        _fake_fetch_map(
            {
                f"{BASE}/robots.txt": robots,
                f"{BASE}/sitemap_index.xml": INDEX_XML,
                f"{BASE}/pages.xml": PAGES_XML,
            }
        ),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, editor_headers, {"base_url": BASE})
    body = resp.json()
    assert body["target"]["cross_domain_skipped"] == ["https://cdn.example.com/external.xml"]
    assert any("跨域" in w for w in body["warnings"])
