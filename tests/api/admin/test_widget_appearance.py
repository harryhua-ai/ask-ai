"""Issue #24 REV1:Widget 外观端点 + site-config 统一外观 + P7 种子不覆写。

覆盖(REV1 统一语义 icon × shape × theme):
- GET /api/admin/widget-appearance 列表(归一化有效值;NULL 行 = current|
  rounded-square|auto;遗留 launcher_style 桥接 + legacy 回显);
- PUT 保存统一三字段(P1/P2)+ 重读恢复(P3)+ 未知站点 404 +
  非法枚举 422 显式拒绝(icon/shape/theme 各维);
- viewer 403(外观属编辑面);
- C1/C4:遗留 REV0 launcher_style 值不破坏读取(退役为 current,不静默迁移);
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
        launcher_icon=kwargs.get("launcher_icon"),
        launcher_shape=kwargs.get("launcher_shape"),
        launcher_style=kwargs.get("launcher_style"),
        launcher_theme=kwargs.get("launcher_theme"),
    )


async def test_appearance_list_defaults_and_effective_values(auth_headers, site_factory_clean):
    """未配置 → 兼容默认;REV1 持久值直读;非法持久值/遗留风格 → 有效值归一。"""
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        session.add(
            _site(
                "site-b",
                launcher_icon="bot-sparkle",
                launcher_shape="round",
                launcher_theme="dark",
            )
        )
        session.add(
            _site("site-c", launcher_icon="logo1.svg", launcher_shape="sometimes", launcher_theme="sometimes")
        )
        # C1/C4:REV0 遗留选择不崩溃、不静默迁移(退役为 current + legacy 回显)
        session.add(_site("site-d", launcher_style="chat-bubble", launcher_theme="dark"))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/widget-appearance", headers=auth_headers)
    assert resp.status_code == 200
    rows = {r["site_id"]: r for r in resp.json()}
    assert rows["site-a"]["launcher_icon"] == "current"
    assert rows["site-a"]["launcher_shape"] == "rounded-square"
    assert rows["site-a"]["launcher_theme"] == "auto"
    assert rows["site-b"]["launcher_icon"] == "bot-sparkle"
    assert rows["site-b"]["launcher_shape"] == "round"
    assert rows["site-b"]["launcher_theme"] == "dark"
    # 非法持久值服务端归一化回落(不外泄、不破坏 Widget)
    assert rows["site-c"]["launcher_icon"] == "current"
    assert rows["site-c"]["launcher_shape"] == "rounded-square"
    assert rows["site-c"]["launcher_theme"] == "auto"
    # 遗留桥:退役风格 → current;legacy_launcher_style 保留供 UI 提示
    assert rows["site-d"]["launcher_icon"] == "current"
    assert rows["site-d"]["launcher_theme"] == "dark"
    assert rows["site-d"]["legacy_launcher_style"] == "chat-bubble"


async def test_appearance_put_persists_trio_and_reloads(auth_headers, site_factory_clean):
    """P1/P2/P3:统一三字段保存与重读;P4 站点间互不污染;legacy 列零触碰。"""
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a", launcher_style="orbit-neural"))
        session.add(_site("site-b"))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={
                "launcher_icon": "robot-smile",
                "launcher_shape": "round",
                "launcher_theme": "dark",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["launcher_icon"] == "robot-smile"
        assert body["launcher_shape"] == "round"
        assert body["launcher_theme"] == "dark"

        # P3:重读恢复;P4:site-b 不被污染
        listing = (await client.get("/api/admin/widget-appearance", headers=auth_headers)).json()
        rows = {r["site_id"]: r for r in listing}
        assert rows["site-a"]["launcher_icon"] == "robot-smile"
        assert rows["site-a"]["launcher_shape"] == "round"
        assert rows["site-a"]["launcher_theme"] == "dark"
        assert rows["site-b"]["launcher_icon"] == "current"
        assert rows["site-b"]["launcher_theme"] == "auto"

        # C6:遗留 launcher_style 列零触碰(旧应用回滚按遗留值渲染,行为保真)
        async with factory() as session:
            row = await session.get(SiteExperience, "site-a")
            assert row.launcher_style == "orbit-neural"


async def test_appearance_put_rejects_unknown_values(auth_headers, site_factory_clean):
    factory = site_factory_clean
    async with factory() as session:
        session.add(_site("site-a"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = {"launcher_icon": "current", "launcher_shape": "round", "launcher_theme": "auto"}
        bad_icon = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={**base, "launcher_icon": "assistant-spark"},  # REV0 退役 id 不再可写
        )
        assert bad_icon.status_code == 422
        bad_shape = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={**base, "launcher_shape": "square"},
        )
        assert bad_shape.status_code == 422
        bad_theme = await client.put(
            "/api/admin/widget-appearance/site-a",
            headers=auth_headers,
            json={**base, "launcher_theme": "sometimes"},
        )
        assert bad_theme.status_code == 422
        unknown_site = await client.put(
            "/api/admin/widget-appearance/no-such-site",
            headers=auth_headers,
            json=base,
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
    """P7:YAML 种子不写外观列(icon/shape/theme/style 均存续)。"""
    factory = site_factory_clean
    site_id = "camthink-website"  # sites.yaml 中存在的 site_id
    async with factory() as session:
        session.add(
            _site(
                site_id,
                launcher_icon="bubble-sparkle-outline",
                launcher_shape="round",
                launcher_theme="dark",
            )
        )
        await session.commit()

    await seed_default_sites(factory)

    async with factory() as session:
        row = await session.get(SiteExperience, site_id)
        assert row is not None
        assert row.launcher_icon == "bubble-sparkle-outline"  # 种子未覆写
        assert row.launcher_shape == "round"
        assert row.launcher_theme == "dark"
