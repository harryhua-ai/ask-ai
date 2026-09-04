"""Issue #24:Widget 外观端点 + site-config 外观字段 + P7 种子不覆写。

覆盖:
- GET /api/admin/widget-appearance 列表(归一化值;NULL 行 = current|auto);
- PUT 保存(P1/P2)+ 重读恢复(P3)+ 未知站点 404 + 非法枚举 422 显式拒绝;
- viewer 403(外观属编辑面);
- site-config 对授权 Origin 返回归一化外观;非法持久值服务端回落(P6);
- P7:seed_default_sites 不写外观列 → Admin 值跨 YAML 重启存续。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import SiteExperience, User
from backend.main import app
from backend.services.site_experiences import seed_default_sites

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="i24-admin@test.com",
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


@pytest_asyncio.fixture(loop_scope="session")
async def site_factory_clean():
    """清空 site_experiences(隔离;恢复不必要——种子可重建)。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(SiteExperience.__table__.delete())
        await session.commit()
    yield factory
    async with factory() as session:
        await session.execute(SiteExperience.__table__.delete())
        await session.commit()


def _site(site_id: str, **kwargs) -> SiteExperience:
    return SiteExperience(
        site_id=site_id,
        display_name=kwargs.get("display_name", site_id),
        allowed_origins=kwargs.get("origins", ["https://x.test"]),
        starters=[],
        enabled=True,
        launcher_style=kwargs.get("launcher_style"),
        launcher_theme=kwargs.get("launcher_theme"),
    )


async def test_appearance_list_defaults_for_unconfigured_sites(auth_headers, site_factory_clean):
    """P5/P6:未配置/非法持久值 → 列表呈现归一化默认(current|auto)。"""
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        session.add(_site("site-b", launcher_style="assistant-spark", launcher_theme="dark"))
        session.add(_site("site-c", launcher_style="logo1.svg", launcher_theme="sometimes"))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/widget-appearance", headers=auth_headers)
    assert resp.status_code == 200
    rows = {r["site_id"]: r for r in resp.json()}
    assert rows["site-a"]["launcher_style"] == "current"
    assert rows["site-a"]["launcher_theme"] == "auto"
    assert rows["site-b"]["launcher_style"] == "assistant-spark"
    assert rows["site-b"]["launcher_theme"] == "dark"
    # P6:非法持久值服务端归一化回落(不外泄、不破坏 Widget)
    assert rows["site-c"]["launcher_style"] == "current"
    assert rows["site-c"]["launcher_theme"] == "auto"


async def test_appearance_put_persists_and_reloads(auth_headers, site_factory_clean):
    """P1/P2/P3:保存风格与主题;重读恢复;P4 站点间互不污染。"""
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        session.add(_site("site-b"))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={"launcher_style": "chat-bubble", "launcher_theme": "dark"},
        )
        assert resp.status_code == 200
        assert resp.json()["launcher_style"] == "chat-bubble"

        # P3:重读恢复;P4:site-b 不被污染
        listing = (await client.get("/api/admin/widget-appearance", headers=auth_headers)).json()
        rows = {r["site_id"]: r for r in listing}
        assert rows["site-a"]["launcher_style"] == "chat-bubble"
        assert rows["site-a"]["launcher_theme"] == "dark"
        assert rows["site-b"]["launcher_style"] == "current"
        assert rows["site-b"]["launcher_theme"] == "auto"


async def test_appearance_put_rejects_unknown_values(auth_headers, site_factory_clean):
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad_style = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={"launcher_style": "logo1.svg", "launcher_theme": "auto"},
        )
        assert bad_style.status_code == 422
        bad_theme = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={"launcher_style": "current", "launcher_theme": "sometimes"},
        )
        assert bad_theme.status_code == 422
        unknown_site = await client.put(
            "/api/admin/widget-appearance/no-such-site",
            headers=auth_headers,
            json={"launcher_style": "current", "launcher_theme": "auto"},
        )
        assert unknown_site.status_code == 404


async def test_appearance_requires_editor_role(site_factory_clean):
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        user_id = uuid.uuid4()
        session.add(
            User(
                id=user_id,
                email="i24-viewer@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/widget-appearance",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        async with factory() as session:
            await session.execute(User.__table__.delete().where(User.id == user_id))
            await session.commit()


async def test_p7_seed_does_not_overwrite_admin_appearance(site_factory_clean):
    """P7:YAML 种子不写外观列 → Admin 值跨种子(重启等价)存续。"""
    factory = site_factory_clean
    site_id = "camthink-website"  # sites.yaml 中存在的 site_id
    async with factory() as session:
        session.add(_site(site_id, launcher_style="orbit-neural", launcher_theme="dark"))
        await session.commit()

    await seed_default_sites(factory)

    async with factory() as session:
        row = await session.get(SiteExperience, site_id)
        assert row is not None
        assert row.launcher_style == "orbit-neural"  # 种子未覆写
        assert row.launcher_theme == "dark"
