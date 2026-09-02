"""P1 热重载闭环:Admin 定制变更 → 运行时快照原子刷新 → 下一条生成即用新配置。

冻结契约:
- DB 持久化成功 → 运行时刷新;失败时运行时保持上一份有效快照;
- 刷新失败必须显式上报,不得用陈旧状态伪装成功;
- 原子快照替换(并发请求只见旧或新完整态);
- 组合顺序不变:system_prompt → 风格语气 → 边界规则 → 运行时 intent_styles。
"""

import uuid as uuid_mod
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Customization, CustomizationBinding, User
from backend.main import app
from backend.pipeline.rag import RAGOrchestrator
from backend.utils.language import detect_language

pytestmark = pytest.mark.asyncio(loop_scope="session")

_CUST = "hot-cust"
_OTHER = "hot-cust-other"


def _make_rag(llm_capture: dict) -> RAGOrchestrator:
    """真实 RAGOrchestrator,外部边界(检索/rerank/LLM)用 mock。"""
    from types import SimpleNamespace as NS

    hit = NS(
        uuid="u",
        source_id="website-camthink/x",
        source_type="web_crawl",
        title="t",
        url="https://x",
        text="evidence",
        chunk_index=0,
        product="website",
        score=0.9,
        vector=[0.1] * 8,
    )

    class _Searcher:
        def search(self, **kw):
            return [hit]

        def search_symbols(self, **kw):
            return []

        def search_bucket(self, **kw):
            return []

    class _Reranker:
        def rerank(self, q, c, top_k=5, **kw):
            return c

    class _LLM:
        async def stream(self, messages, task="generation", **kw):
            llm_capture["messages"] = messages
            yield "ok"

        async def generate(self, messages, task="generation", **kw):
            llm_capture["messages"] = messages
            return NS(content="answer")

    return RAGOrchestrator(
        searcher=_Searcher(),
        reranker=_Reranker(),
        llm=_LLM(),
        system_prompt="INITIAL_WIDGET_PROMPT",
        channel_customizations={"widget": "INITIAL_WIDGET_PROMPT"},
        intent_styles={"product": "INTENT_STYLE_TAIL"},
        override_matcher=None,
        visibility_guard=None,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def hot_env():
    """真实 app + DB:置入可控 RAG 实例,创建两个测试定制,结束后还原。"""
    llm_capture: dict = {}
    original_rag = getattr(app.state, "rag", None)
    original_snapshot = None
    if original_rag is not None:
        original_snapshot = (
            dict(original_rag._channel_customizations),
            original_rag._system_prompt,
        )
    app.state.rag = _make_rag(llm_capture)

    factory = app.state.session_factory
    user_id = uuid_mod.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="hot-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        session.add(
            Customization(
                id=_CUST,
                name="热重载主配置",
                system_prompt="OLD_BASE_PROMPT",
                style_tone=None,
                guardrails=None,
            )
        )
        session.add(
            Customization(
                id=_OTHER,
                name="热重载备用配置",
                system_prompt="OTHER_BASE_PROMPT",
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    headers = {"Authorization": f"Bearer {token}"}
    yield headers, llm_capture
    async with factory() as session:
        await session.execute(
            delete(CustomizationBinding).where(
                CustomizationBinding.customization_id.in_([_CUST, _OTHER])
            )
        )
        await session.execute(delete(Customization).where(Customization.id.in_([_CUST, _OTHER])))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()
    if original_rag is not None and original_snapshot is not None:
        original_rag.set_customization_snapshot(*original_snapshot)
    else:
        app.state.rag = original_rag


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sys_content(rag, channel: str = "widget") -> str:
    """经由真实 _build_messages 组合出的最终 system 内容(与生成路径同源)。"""
    msgs = rag._build_messages(
        "What is CamThink NeoEyes?",
        "evidence-context",
        detect_language("What is CamThink NeoEyes?"),
        [],
        channel,
        intent="product",
    )
    assert msgs[0]["role"] == "system"
    return msgs[0]["content"]


# --------------------------------------------------------------------------- #
# G001 PATCH system_prompt → 下一条生成使用新 prompt,无需重启
# --------------------------------------------------------------------------- #


async def test_g001_patch_system_prompt_hot_reloads(hot_env):
    headers, llm_capture = hot_env
    rag = app.state.rag
    async with _client() as client:
        resp = await client.patch(
            f"/api/admin/customizations/{_CUST}",
            headers=headers,
            json={"system_prompt": "NEW_BASE_PROMPT_V2"},
        )
        assert resp.status_code == 200
    # 绑定 whatsapp → hot-cust,断言 whatsapp 渠道走新配置(不碰 widget default)
    async with _client() as client:
        resp = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _CUST},
        )
        assert resp.status_code == 200
    content = _sys_content(rag, channel="whatsapp")
    assert "NEW_BASE_PROMPT_V2" in content
    assert "OLD_BASE_PROMPT" not in content
    # 经真实生成路径再次确认(捕获 LLM messages)
    if getattr(rag, "_override_matcher", None) is None:
        pass
    llm_capture.clear()
    await rag.answer("What is CamThink NeoEyes?", channel="whatsapp")
    assert "NEW_BASE_PROMPT_V2" in llm_capture["messages"][0]["content"]


# --------------------------------------------------------------------------- #
# G002 style_tone / guardrails 更新进入下一条 system 消息
# --------------------------------------------------------------------------- #


async def test_g002_patch_style_and_guardrails_hot_reloads(hot_env):
    headers, _ = hot_env
    rag = app.state.rag
    async with _client() as client:
        resp = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _CUST},
        )
        assert resp.status_code == 200
        resp = await client.patch(
            f"/api/admin/customizations/{_CUST}",
            headers=headers,
            json={
                "system_prompt": "BASE_V3",
                "style_tone": "STYLE_V3",
                "guardrails": "GUARD_V3",
            },
        )
        assert resp.status_code == 200
    content = _sys_content(rag, channel="whatsapp")
    assert "BASE_V3" in content and "STYLE_V3" in content and "GUARD_V3" in content
    assert content.find("BASE_V3") < content.find("STYLE_V3") < content.find("GUARD_V3")


# --------------------------------------------------------------------------- #
# G003 绑定 A → B:下一请求用 B
# --------------------------------------------------------------------------- #


async def test_g003_rebind_channel_uses_new_customization(hot_env):
    headers, _ = hot_env
    rag = app.state.rag
    async with _client() as client:
        r = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _CUST},
        )
        assert r.status_code == 200
    assert "OLD_BASE_PROMPT" in rag._channel_customizations["whatsapp"]
    async with _client() as client:
        r = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _OTHER},
        )
        assert r.status_code == 200
    assert "OTHER_BASE_PROMPT" in rag._channel_customizations["whatsapp"]
    assert "OLD_BASE_PROMPT" not in rag._channel_customizations["whatsapp"]


# --------------------------------------------------------------------------- #
# G004 持久化失败:运行时保持上一份有效快照
# --------------------------------------------------------------------------- #


async def test_g004_failed_persistence_keeps_previous_snapshot(hot_env):
    headers, _ = hot_env
    rag = app.state.rag
    async with _client() as client:
        r = await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _CUST},
        )
        assert r.status_code == 200
    before = dict(rag._channel_customizations)
    # 持久化失败:不存在的主键 → 404(事务未发生)
    async with _client() as client:
        r = await client.patch(
            "/api/admin/customizations/not-exist",
            headers=headers,
            json={"system_prompt": "SHOULD_NOT_APPLY"},
        )
        assert r.status_code == 404
    # 持久化失败:重复 ID → 409
    async with _client() as client:
        r = await client.post(
            "/api/admin/customizations",
            headers=headers,
            json={"id": _CUST, "name": "dup", "system_prompt": "SHOULD_NOT_APPLY"},
        )
        assert r.status_code == 409
    assert rag._channel_customizations == before
    assert "SHOULD_NOT_APPLY" not in rag._channel_customizations.get("whatsapp", "")


# --------------------------------------------------------------------------- #
# G005 刷新失败:显式上报,不用陈旧状态伪装成功
# --------------------------------------------------------------------------- #


async def test_g005_refresh_failure_is_explicit_and_snapshot_stale_marked(hot_env):
    headers, _ = hot_env
    rag = app.state.rag

    async def _boom(state):
        raise RuntimeError("reload exploded")

    with patch("backend.api.admin.customizations.refresh_runtime_customizations", new=_boom):
        async with _client() as client:
            r = await client.patch(
                f"/api/admin/customizations/{_CUST}",
                headers=headers,
                json={"system_prompt": "PERSISTED_BUT_NOT_ACTIVATED"},
            )
            assert r.status_code == 500
            assert "刷新失败" in r.json()["detail"]
    # 运行时仍是旧快照(未被伪装成已激活)
    assert "PERSISTED_BUT_NOT_ACTIVATED" not in rag._channel_customizations.get("whatsapp", "")


# --------------------------------------------------------------------------- #
# G006 组合顺序:system → style → guardrails → 运行时 intent style
# --------------------------------------------------------------------------- #


async def test_g006_composition_order_preserved(hot_env):
    headers, _ = hot_env
    rag = app.state.rag
    async with _client() as client:
        await client.put(
            "/api/admin/customization-bindings/whatsapp",
            headers=headers,
            json={"customization_id": _CUST},
        )
        await client.patch(
            f"/api/admin/customizations/{_CUST}",
            headers=headers,
            json={
                "system_prompt": "ORD_SYS",
                "style_tone": "ORD_STYLE",
                "guardrails": "ORD_GUARD",
            },
        )
    content = _sys_content(rag, channel="whatsapp")
    i_sys = content.find("ORD_SYS")
    i_style = content.find("ORD_STYLE")
    i_guard = content.find("ORD_GUARD")
    i_intent = content.find("INTENT_STYLE_TAIL")
    assert -1 not in (i_sys, i_style, i_guard, i_intent)
    assert i_sys < i_style < i_guard < i_intent
