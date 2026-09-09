"""I-UX-001:Widget Experience 端点 + 迁移契约 + Trusted Action 生命周期。

覆盖(冻结契约 I-UX-001 §3/§5/§14-§16/§23):
- GET /api/admin/widget-experience 列表(experience 字段 + trusted_actions);
- PUT 保存(合法值落库;未知枚举 422 显式拒绝;未知站点 404;viewer 403);
- 迁移契约:既有站点 experience 列 NULL → site-config 返回 None(legacy 保持);
  seed_default_sites 新建行缺省 mini_entry(新站点 = C),既有行绝不覆写;
- site-config 仅下发 published 动作(Role A 修正 B:访客曝光闸 = PUBLISHED,
  draft/verified 永不外泄,verified 保留 Admin 面与生命周期有效性);
- Trusted Action 生命周期:新建默认 draft;Test(真实 ASK-AI 管道,stub 注入)
  落 last_test_result;Verify 需先 Test;Publish 需 verified;语义编辑
  (query/action_type)失效回落 draft;纯 label 编辑状态保持;删除;
- 非法 action_type / state 422。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import SiteExperience, SiteTrustedAction, User
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
                email="iux-admin@test.com",
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
async def viewer_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="iux-viewer@test.com",
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


@pytest_asyncio.fixture(loop_scope="session")
async def experience_env():
    """清空站点与动作表(隔离);返回 session factory。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(SiteTrustedAction.__table__.delete())
        await session.execute(SiteExperience.__table__.delete())
        await session.commit()
    yield factory
    async with factory() as session:
        await session.execute(SiteTrustedAction.__table__.delete())
        await session.execute(SiteExperience.__table__.delete())
        await session.commit()


def _client(headers) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers)


async def test_experience_list_and_put_roundtrip(auth_headers, experience_env):
    """列表含 experience 字段;PUT 合法值落库重读;未配置字段保持 NULL。"""
    factory = experience_env
    async with factory() as session:
        session.add(SiteExperience(site_id="s-exp", display_name="S", allowed_origins=[], starters=[]))
        await session.commit()
    async with _client(auth_headers) as c:
        listed = (await c.get("/api/admin/widget-experience")).json()
        row = next(r for r in listed if r["site_id"] == "s-exp")
        assert row["entry_mode"] is None  # 迁移契约:未配置 = NULL = legacy
        assert row["trusted_actions"] == []
        put = await c.put(
            "/api/admin/widget-experience/s-exp",
            json={
                "entry_mode": "mini_entry",
                "proactive_timing": "balanced",
                "launcher_motion": "soft_pulse",
                "launcher_size": "large",
                "launcher_brand": "custom",
                "launcher_color": "#3366ff",
                "chat_theme": "dark",
                "chat_size": "large",
                "greeting_override": "Questions about NE503?",
            },
        )
        assert put.status_code == 200
        assert put.json()["entry_mode"] == "mini_entry"
        reread = (await c.get("/api/admin/widget-experience")).json()
        row2 = next(r for r in reread if r["site_id"] == "s-exp")
        assert row2["launcher_motion"] == "soft_pulse"
        assert row2["launcher_color"] == "#3366ff"
        assert row2["chat_theme"] == "dark"
        assert row2["greeting_override"] == "Questions about NE503?"


async def test_experience_put_rejects_unknown_enums(auth_headers, experience_env):
    factory = experience_env
    async with factory() as session:
        session.add(SiteExperience(site_id="s-bad", display_name="S", allowed_origins=[], starters=[]))
        await session.commit()
    async with _client(auth_headers) as c:
        for body in (
            {"entry_mode": "wizard"},
            {"proactive_timing": "now"},
            {"launcher_motion": "explode"},
            {"launcher_size": "huge"},
            {"launcher_brand": "acme"},
            {"chat_theme": "sepia"},
            {"chat_size": "giant"},
            {"launcher_icon": "rocket"},
            {"launcher_color": "red"},
        ):
            resp = await c.put("/api/admin/widget-experience/s-bad", json=body)
            assert resp.status_code == 422, body
        missing = await c.put("/api/admin/widget-experience/no-such-site", json={"entry_mode": "pill"})
        assert missing.status_code == 404


async def test_experience_viewer_forbidden(viewer_headers, experience_env):
    async with _client(viewer_headers) as c:
        assert (await c.get("/api/admin/widget-experience")).status_code == 403


async def test_seed_new_site_defaults_mini_entry_and_preserves_existing(
    auth_headers, experience_env, tmp_path
):
    """迁移契约:新建行缺省 mini_entry;既有行 NULL 保持(不覆写 Admin 域)。"""
    factory = experience_env
    # 既有站点:模拟升级前状态(entry_mode = NULL,Admin 未配置)
    async with factory() as session:
        session.add(SiteExperience(site_id="s-legacy", display_name="L", allowed_origins=[], starters=[]))
        await session.commit()
    cfg = tmp_path / "sites.yaml"
    cfg.write_text(
        """
sites:
  - site_id: s-legacy
    display_name: Legacy
    allowed_origins: ["https://legacy.test"]
    starters: []
  - site_id: s-brand-new
    display_name: New
    allowed_origins: ["https://new.test"]
    starters: []
""",
        encoding="utf-8",
    )
    seeded = await seed_default_sites(factory, cfg)
    assert seeded == 2
    async with factory() as session:
        legacy = await session.get(SiteExperience, "s-legacy")
        assert legacy.entry_mode is None  # 既有站点:legacy 行为保持
        fresh = await session.get(SiteExperience, "s-brand-new")
        assert fresh.entry_mode == "mini_entry"  # 新站点:默认 C


async def _make_action(factory, site_id="s-act", state="draft", **kwargs) -> uuid.UUID:
    async with factory() as session:
        if await session.get(SiteExperience, site_id) is None:
            session.add(SiteExperience(site_id=site_id, display_name=site_id, allowed_origins=[], starters=[]))
            await session.commit()
        row = SiteTrustedAction(
            site_id=site_id,
            action_type=kwargs.get("action_type", "PRODUCT_SPECIFICATIONS"),
            label=kwargs.get("label", "Specifications"),
            query=kwargs.get("query", "What are the specifications of {product}?"),
            state=state,
        )
        session.add(row)
        await session.commit()
        return row.id


async def test_action_lifecycle_test_verify_publish(auth_headers, experience_env, monkeypatch):
    """draft → Test(真实管道 stub)→ Verify → Publish;Verify 必须先 Test。"""
    factory = experience_env
    action_id = await _make_action(factory)

    class _StubRAG:
        async def answer(self, query, **kwargs):
            from backend.pipeline.rag import RAGAnswer

            return RAGAnswer(
                answer=f"real answer for {query}",
                sources=[{"url": "https://x.test/doc", "title": "Doc", "type": "wiki", "product": "NE503"}],
                is_answered=True,
                reranked_results=[],
                language="en",
                response_time_ms=1,
            )

    # 测试 lifespan 不构建 RAG(免模型加载);端点动态读取 app.state.rag → 注入 stub
    monkeypatch.setattr(app.state, "rag", _StubRAG(), raising=False)

    async with _client(auth_headers) as c:
        # Verify 前必须 Test
        early = await c.post(f"/api/admin/widget-experience/actions/{action_id}/verify")
        assert early.status_code == 400
        # Publish 前必须 verified
        early_pub = await c.post(
            f"/api/admin/widget-experience/actions/{action_id}/state", json={"state": "published"}
        )
        assert early_pub.status_code == 400
        # Test = 真实 ASK-AI 管道输出(此处 stub 注入;生产即 rag.answer 全管道)
        tested = await c.post(f"/api/admin/widget-experience/actions/{action_id}/test")
        assert tested.status_code == 200
        body = tested.json()
        assert body["last_test_result"]["answer"] == "real answer for What are the specifications of {product}?"
        assert body["last_test_result"]["sources"][0]["url"] == "https://x.test/doc"
        # Verify
        verified = await c.post(f"/api/admin/widget-experience/actions/{action_id}/verify")
        assert verified.status_code == 200
        assert verified.json()["state"] == "verified"
        # Publish
        published = await c.post(
            f"/api/admin/widget-experience/actions/{action_id}/state", json={"state": "published"}
        )
        assert published.status_code == 200
        assert published.json()["state"] == "published"


async def test_action_semantic_edit_invalidates_label_edit_preserves(auth_headers, experience_env):
    """query/action_type 语义编辑 → 回落 draft;label 编辑状态保持。"""
    factory = experience_env
    action_id = await _make_action(factory, state="verified")
    async with _client(auth_headers) as c:
        kept = await c.patch(
            f"/api/admin/widget-experience/actions/{action_id}", json={"label": "Specs"}
        )
        assert kept.status_code == 200
        assert kept.json()["state"] == "verified"  # 纯展示编辑不失效
        invalidated = await c.patch(
            f"/api/admin/widget-experience/actions/{action_id}",
            json={"query": "List all sensors of {product}"},
        )
        assert invalidated.status_code == 200
        assert invalidated.json()["state"] == "draft"  # 语义编辑失效回落草稿


async def test_site_config_exposes_only_published_actions(experience_env):
    """访客曝光闸(Role A 修正 B):site-config 只下发 published。

    draft/verified 均 Admin 面、生命周期有效,但绝不进入访客 site-config
    —— PUBLISHED 才是发布闸(verified 不可访客可见)。
    """
    from httpx import ASGITransport, AsyncClient as _AC

    factory = experience_env
    async with factory() as session:
        session.add(
            SiteExperience(
                site_id="s-pub",
                display_name="Pub",
                allowed_origins=["https://pub.test"],
                starters=[],
                enabled=True,
                entry_mode="mini_entry",
            )
        )
        await session.commit()
    await _make_action(factory, site_id="s-pub", state="draft", label="Draft One")
    await _make_action(factory, site_id="s-pub", state="verified", label="Verified One")
    await _make_action(factory, site_id="s-pub", state="published", label="Published One")
    async with _AC(
        transport=ASGITransport(app=app),
        base_url="https://pub.test",
        headers={"Origin": "https://pub.test"},
    ) as c:
        resp = await c.get("/api/widget/site-config?site_id=s-pub")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entry_mode"] == "mini_entry"
    types = [a["label"] for a in body["trusted_actions"]]
    assert types == ["Published One"]  # 仅 published
    assert "Verified One" not in types  # verified 不是访客发布闸
    assert "Draft One" not in types


async def test_action_validation_422(auth_headers, experience_env):
    factory = experience_env
    action_id = await _make_action(factory)
    async with _client(auth_headers) as c:
        bad_type = await c.post(
            f"/api/admin/widget-experience/{'s-act'}/actions",
            json={"action_type": "MAGIC_TRICK", "label": "X", "query": "Q"},
        )
        assert bad_type.status_code == 422
        bad_state = await c.post(
            f"/api/admin/widget-experience/actions/{action_id}/state", json={"state": "famous"}
        )
        assert bad_state.status_code == 422
        gone = await c.delete(f"/api/admin/widget-experience/actions/{uuid.uuid4()}")
        assert gone.status_code == 404
