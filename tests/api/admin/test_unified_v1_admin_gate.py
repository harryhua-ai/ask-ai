"""Unified V1 Integration Gate — 管理端组合契约(INT-V1-004/005)持久回归。

G004(INT-V1-005 Multi-Site Schema × Admin):legacy 对话(site_id NULL)与
站点对话在 Admin 对话审查与技术洞察中共存可用,legacy 行不消失。
G008(INT-V1-004 Website Coverage × Deletion):删除源后,同步宇宙(配置表)
不再包含该源 ⇒ WEB-01 一致性/自愈路径无法复活它;伴随源不受影响。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, DataSource, Document, SyncLog, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_MARKER = "uv1gate-marker"
_USER_EMAIL = "uv1gate@test.com"


async def _seed_user(role: str = "admin"):
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role=role,
                password_hash=hash_password("pass"),
            )
        )
        await session.commit()
    return {"Authorization": f"Bearer {create_access_token(str(user_id), role, app.state.settings.jwt_secret)}"}


async def _cleanup_user():
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.commit()


# --------------------------------------------------------------------------- #
# G004 — legacy(NULL site_id)× 站点对话 × Admin 审查/洞察
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture(loop_scope="session")
async def g004_seed():
    factory = app.state.session_factory
    headers = await _seed_user()
    async with factory() as session:
        legacy = _conv("legacy 提问", site_id=None)
        scoped = _conv("scoped 提问", site_id="camthink-store")
        session.add(legacy)
        session.add(scoped)
        await session.flush()
        session.add(
            Trace(
                conversation_id=legacy.id,
                turn_index=0,
                type="rag",
                stages={"intent": {"ms": 40}},
                total_ms=120,
                intent="commercial",
                config_snapshot={},
            )
        )
        await session.commit()
        legacy_id, scoped_id = legacy.id, scoped.id
    yield headers
    async with factory() as session:
        for cid in (legacy_id, scoped_id):
            row = await session.get(Conversation, cid)
            if row:
                await session.delete(row)
        await session.execute(
            Trace.__table__.delete().where(Trace.conversation_id.in_([legacy_id, scoped_id]))
        )
        await session.commit()
    await _cleanup_user()


def _conv(question: str, *, site_id: str | None) -> Conversation:
    return Conversation(
        question=f"{_MARKER} {question}",
        answer="ok",
        channel="widget",
        is_answered=True,
        site_id=site_id,
    )


async def test_int_v1_g004_legacy_null_site_rows_survive_in_admin(g004_seed):
    """G004:NULL site_id 的 legacy 对话与站点对话同窗可见;洞察端点正常出数。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/conversations?q={_MARKER}", headers=g004_seed
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    by_site = {c["question"]: c for c in items}
    assert any(_MARKER in q for q in by_site)
    # legacy 行:site_id 为 NULL;站点行:site_id 落值 —— 两行都有效返回
    legacy_rows = [c for c in items if "legacy" in c["question"]]
    scoped_rows = [c for c in items if "scoped" in c["question"]]
    assert legacy_rows and scoped_rows
    if "site_id" in legacy_rows[0]:
        assert legacy_rows[0]["site_id"] is None
        assert scoped_rows[0]["site_id"] == "camthink-store"

    # 技术洞察(7d 窗口)正常出数,legacy 对话的 trace 计入
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp2 = await client.get(
            "/api/admin/tech/performance?range=7d", headers=g004_seed
        )
    assert resp2.status_code == 200
    kpi = resp2.json()["kpi"]
    assert kpi["trace_total"] >= 1


# --------------------------------------------------------------------------- #
# G008 — 删除生命周期 × WEB-01 同步/自愈(不复活)
# --------------------------------------------------------------------------- #

_G008_A = "uv1g008-a"
_G008_B = "uv1g008-b"


@pytest_asyncio.fixture(loop_scope="session")
async def g008_seed():
    factory = app.state.session_factory
    headers = await _seed_user()
    async with factory() as session:
        for sid in (_G008_A, _G008_B):
            await session.execute(
                DataSource.__table__.delete().where(DataSource.id == sid)
            )
        await session.execute(
            Document.__table__.delete().where(
                Document.source_id.in_(["uv1g008-a/doc", "uv1g008-b/doc"])
            )
        )
        session.add(
            DataSource(
                id=_G008_A,
                type="web_crawl",
                product="ne101",
                enabled=True,
                config={"start_url": "https://example.com/a"},
                sync_interval="24h",
            )
        )
        session.add(
            DataSource(
                id=_G008_B,
                type="web_crawl",
                product="ne301",
                enabled=True,
                config={"start_url": "https://example.com/b"},
                sync_interval="24h",
            )
        )
        for sid in ("uv1g008-a/doc", "uv1g008-b/doc"):
            session.add(
                Document(
                    content_hash=uuid.uuid4().hex,
                    source_id=sid,
                    source_type="web_crawl",
                    product="x",
                    title=sid,
                    url="https://example.com",
                    metadata_={},
                    branch="",
                    chunk_count=2,
                )
            )
        await session.commit()
    yield headers
    async with factory() as session:
        await session.execute(
            DataSource.__table__.delete().where(
                DataSource.id.in_([_G008_A, _G008_B])
            )
        )
        await session.execute(
            Document.__table__.delete().where(
                Document.source_id.in_(["uv1g008-a/doc", "uv1g008-b/doc"])
            )
        )
        await session.execute(
            SyncLog.__table__.delete().where(
                SyncLog.source_id.in_([_G008_A, _G008_B])
            )
        )
        await session.commit()
    await _cleanup_user()


@pytest.fixture
def g008_purge(monkeypatch):
    calls: list[dict] = []

    def _fake(weaviate_url, class_name, prefix, ledger):
        calls.append({"prefix": prefix, "ledger": list(ledger)})
        return {"ledger_chunks": 2, "orphans": 0}

    monkeypatch.setattr(
        "backend.api.admin.data_sources._purge_source_corpus_sync", _fake
    )
    return calls


async def test_int_v1_g008_deleted_source_not_resurrected_by_sync(g008_seed, g008_purge):
    """G008:删除 uv1g008-a 后 → 同步宇宙不含它(配置行即权威),
    WEB-01 一致性/自愈只对幸存源运行;被删源的配置/账本/同步日志保持不存在。"""
    from scripts.sync import _load_configs_from_db, _sync_one

    factory = app.state.session_factory

    # 1) 删除 uv1g008-a(向量 purge mock,204)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/admin/data-sources/{_G008_A}", headers=g008_seed)
    assert resp.status_code == 204
    assert [c["prefix"] for c in g008_purge] == [_G008_A]

    # 2) 同步宇宙 = 配置表:被删源已不在(⇒ run_sync/cron/自愈都触不到它)
    configs = await _load_configs_from_db(factory)
    config_ids = {c.id for c in configs}
    assert _G008_A not in config_ids
    assert _G008_B in config_ids

    # 3) 幸存源跑一轮同步(mock connector/pipeline/一致性校验,零 Weaviate)
    connector = MagicMock()
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([])
    connector.fetch_deleted.return_value = []
    pipeline = MagicMock()
    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch(
            "scripts.sync.verify_source_vectors",
            new_callable=AsyncMock,
            return_value=MagicMock(is_healthy=True),
        ),
    ):
        cfg_b = next(c for c in configs if c.id == _G008_B)
        await _sync_one(cfg_b, pipeline, factory, triggered_by="manual")

    # 4) 被删源:配置/账本/同步日志三者保持不存在(未被任何路径复活)
    async with factory() as session:
        assert (
            await session.get(DataSource, _G008_A)
        ) is None
        docs = (
            await session.execute(
                select(Document).where(Document.source_id.like(f"{_G008_A}/%"))
            )
        ).scalars().all()
        assert docs == []
        logs = (
            await session.execute(
                select(SyncLog).where(SyncLog.source_id == _G008_A)
            )
        ).scalars().all()
        assert logs == []
        # 伴随源:配置在、账本在、同步照常(账本被同步路径触碰与否均不许波及删除)
        assert (await session.get(DataSource, _G008_B)) is not None
        keep_docs = (
            await session.execute(
                select(Document).where(Document.source_id == "uv1g008-b/doc")
            )
        ).scalars().all()
        assert len(keep_docs) == 1
