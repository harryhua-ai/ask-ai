"""#68 AC14(production-like):真实 /api/ask 链路上的权威国家持久化。

用 budget-declined 探针(不依赖 LLM/Weaviate,但走真实 ASGI app + 真实测试库 +
真实 resolver + 真实持久化)证明:
- 受信 ingress(对端 ∈ 受信 CIDR + 显式头)→ Conversation.country 落 ISO alpha-2
  且 country_source='ingress';
- 不可信/缺失路径(伪造头、无头)→ 落 Unknown(NULL),语言头不产生地理事实。
"""

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.config import load_settings
from backend.db.models import Conversation
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

# DSN 纪律:先 load_settings() 触发 dotenv 注入,再取 TEST_DATABASE_URL
# (session 级 loop 要求,与 test_issue92 同因)。
_load = load_settings(config_dir=Path(__file__).resolve().parents[2] / "config")
DSN = os.environ.get("TEST_DATABASE_URL", _load.postgres_dsn)

_SID_PREFIX = "country-probe-"


class _DecliningBudget:
    """强制走 budget-declined 持久化路径(真实探针,不调用 LLM)。"""

    def check_and_reserve(self, estimated_tokens: int) -> bool:
        return False


class _UnusedRag:
    """declined 路径永不触达 RAG;仅满足 FastAPI 依赖解析。"""


@pytest_asyncio.fixture(loop_scope="session")
async def ingress_app():
    """真实 ASGI app + 真实测试库(ASGITransport 不触发 lifespan,
    手动接线 app.state,与 tests/api/admin/conftest.py 同因);
    测试后恢复原值,避免污染其他测试。"""
    from backend.db.session import get_engine, get_session_factory, init_db

    original = {
        name: getattr(app.state, name, None)
        for name in ("settings", "budget", "session_factory", "rag")
    }
    engine = get_engine(DSN)
    await init_db(engine)
    from scripts.migrate_add_membership_currency import migrate as _migrate_membership

    await _migrate_membership(engine)
    app.state.settings = replace(
        load_settings(config_dir=Path(__file__).resolve().parents[2] / "config"),
        country_resolution_mode="ingress",
        country_ingress_header="geo-country",
        geo_trusted_proxy_cidrs=("127.0.0.0/8",),
        geoip_database_path="",
    )
    app.state.session_factory = get_session_factory(engine)
    app.state.budget = _DecliningBudget()
    app.state.rag = _UnusedRag()
    yield app
    await engine.dispose()
    for name, value in original.items():
        if value is not None:
            setattr(app.state, name, value)


async def _ask_and_persisted_country(client, *, sid, headers=None, client_addr=("127.0.0.1", 123)):
    transport = ASGITransport(app=app, client=client_addr)
    async with AsyncClient(transport=transport, base_url="http://test") as probe:
        resp = await probe.post(
            "/api/ask",
            json={"message": f"country probe {sid}", "session_id": sid},
            headers=headers or {},
        )
    assert resp.status_code == 200, resp.text
    conversation_id = None
    for line in resp.text.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            conversation_id = json.loads(line[len("data:"):])["conversation_id"]
    assert conversation_id, resp.text
    factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with factory() as session:
        conv = await session.get(Conversation, uuid.UUID(conversation_id))
        assert conv is not None
        return conv.country, conv.country_source


@pytest.mark.integration
async def test_trusted_ingress_country_persists_with_provenance(ingress_app):
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        country, source = await _ask_and_persisted_country(
            ingress_app, sid=sid, headers={"geo-country": "US"}
        )
        assert (country, source) == ("US", "ingress")
    finally:
        factory = ingress_app.state.session_factory
        async with factory() as session:
            await session.execute(delete(Conversation).where(Conversation.session_id == sid))
            await session.commit()


@pytest.mark.integration
async def test_spoofed_header_from_untrusted_peer_persists_unknown(ingress_app):
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        country, source = await _ask_and_persisted_country(
            ingress_app,
            sid=sid,
            headers={"geo-country": "US"},
            client_addr=("203.0.113.7", 123),  # 非受信对端:伪造头不是权威
        )
        assert (country, source) == (None, None)
    finally:
        factory = ingress_app.state.session_factory
        async with factory() as session:
            await session.execute(delete(Conversation).where(Conversation.session_id == sid))
            await session.commit()


@pytest.mark.integration
async def test_accept_language_alone_persists_unknown(ingress_app):
    """回归:Accept-Language 地区后缀不再产生任何地理事实。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        country, source = await _ask_and_persisted_country(
            ingress_app, sid=sid, headers={"accept-language": "en-US,en;q=0.9"}
        )
        assert (country, source) == (None, None)
    finally:
        factory = ingress_app.state.session_factory
        async with factory() as session:
            await session.execute(delete(Conversation).where(Conversation.session_id == sid))
            await session.commit()
