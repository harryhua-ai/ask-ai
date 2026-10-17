"""#114 AC3:受信国家信号(nginx GeoIP2 → ingress 头 → resolver)离线契约矩阵。

全部为**离线**验证:真实 ASGI app + 本地测试库 + 真实 resolver + 真实持久化,
RAG 以确定性假流替换(不调用 LLM/Weaviate),零生产 /ask 探针。
覆盖矩阵(与 deploy/prod/geoip2/README.md §3 一一对应):

- 可信 country header 正常入库(正常路径 + 预算拒绝路径,两分支均不回退);
- 外部伪造同名国家头(含直连后端攻击面)一律 Unknown;
- 空/错误/保留码(XX)→ Unknown;
- 不受信 peer → Unknown;
- proxy 身份头(X-Forwarded-For/X-Real-IP)变更**不得**绕过信任门
  (信任判据只有直连 peer,与 #144 RCA UNTRUSTED_PEER 断层语义一致);
- 三站点(site_id)+ legacy + admin 共享同一 API 路径,国家解析与站点无关;
- env 装配三元组解析(默认 off / ingress 三键 / 非法 CIDR 项跳过 fail-closed)。

DSN 纪律(R2 修正):TEST_DATABASE_URL 必须显式设置且指向专用测试库
(库名含 'test');缺失/非测试库/APP_MODE=prod 一律在收集期拒绝,绝不回落
配置默认 DSN。

隐私:测试只用 RFC 5737/loopback 合成地址与合成国家码,无任何真实访客 IP。
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import load_settings
from backend.db.models import Conversation, SiteExperience
from backend.main import app
from backend.utils.budget import BudgetConfig, BudgetLimiter

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _resolve_test_dsn() -> str:
    """AC3/AC5 fail-closed 测试库解析(R2 修正)。

    旧实现 ``os.environ.get("TEST_DATABASE_URL", _load.postgres_dsn)`` 会在
    TEST_DATABASE_URL 缺失时静默回落配置 DSN(POSTGRES_* 环境注入/`.env`/
    默认值 ask_ai —— 与生产库同名)。runner 若带生产 POSTGRES_* 而无显式
    测试 URL,本文件的 init_db/迁移/DELETE 会打进生产库。现在:

    - APP_MODE=prod → 一律拒绝(prod 环境禁写,与 backend.config 的迁移
      DSN 纪律同向);
    - TEST_DATABASE_URL 未显式设置 → 拒绝,绝不猜测任何默认 DSN;
    - 库名必须含 ``test``(专用测试库命名纪律,与仓库 .env 的 ask_ai_test
      口径一致)→ 拒绝 prod 形态/歧义连接。

    守卫先于任何 ``load_settings()`` 调用执行 ⇒ 失败在模块导入(收集)期
    抛出,本文件不可运行 = fail-closed。
    """
    if (os.environ.get("APP_MODE", "dev") or "dev").strip().lower() == "prod":
        raise RuntimeError(
            "APP_MODE=prod: 拒绝运行离线契约测试(生产环境禁止任何测试写面)。"
            "请在 dev/CI 环境以专用测试库运行。"
        )
    dsn = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError(
            "TEST_DATABASE_URL 未显式设置 —— 本测试拒绝回落默认 DSN(fail-closed;"
            "默认库名 ask_ai 与生产同名,runner 携带生产 POSTGRES_* 时会误写生产)。"
            "请显式注入专用测试库,例如 "
            "TEST_DATABASE_URL=postgresql+asyncpg://<user>:<pwd>@localhost:5432/ask_ai_test"
        )
    dbname = dsn.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in dbname.lower():
        # 库名不回显:DSN 串形不明的极端情况下回显可能带出凭据
        raise RuntimeError("TEST_DATABASE_URL 必须指向专用测试库(库名须含 'test';值不回显)")
    return dsn


DSN = _resolve_test_dsn()

_load = load_settings(config_dir=Path(__file__).resolve().parents[2] / "config")

_SID_PREFIX = "geoip2-probe-"
_INGRESS_HEADER = "geo-country"
# 受信直连 peer = nginx 网桥网关的仿真(仅 loopback,非真实 CIDR)
_TRUSTED_PEER = ("127.0.0.77", 111)
_TRUSTED_IP = "127.0.0.77"
# 合成站点(非真实站点标识;Origin 为 RFC 6761 保留测试域)
_SITES = {
    "camthink-website": "https://website.test",
    "camthink-wiki": "https://wiki.test",
    "camthink-store": "https://store.test",
}


class _DecliningBudget:
    """强制走 budget-declined 持久化路径(不依赖 LLM)。"""

    def check_and_reserve(self, estimated_tokens: int) -> bool:
        return False


def _open_budget() -> BudgetLimiter:
    return BudgetLimiter(BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000))


def _fake_rag() -> AsyncMock:
    """确定性假 RAG:token + complete 两事件,零外部依赖。"""
    rag = AsyncMock()

    async def _stream(*args, **kwargs) -> AsyncIterator[str]:
        yield json.dumps({"type": "token", "content": "ok"})
        yield json.dumps(
            {
                "type": "complete",
                "answer": "ok",
                "sources": [],
                "is_answered": True,
                "language": "zh",
                "response_time_ms": 1,
            }
        )

    rag.stream_answer = _stream
    return rag


@pytest_asyncio.fixture(loop_scope="session")
async def ingress_app():
    """真实 ASGI app + 真实测试库(ASGITransport 不触发 lifespan,手动接线);
    ingress 三元组按生产启用形态装配(头名/受信 peer 与 README 示例同构)。
    测试后恢复原值,不污染其他测试。"""
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
        country_ingress_header=_INGRESS_HEADER,
        geo_trusted_proxy_cidrs=("127.0.0.0/8",),
    )
    app.state.session_factory = get_session_factory(engine)
    yield app
    await engine.dispose()
    for name, value in original.items():
        if value is not None:
            setattr(app.state, name, value)


async def _seed_sites(factory) -> None:
    async with factory() as session:
        # R2 修正:只管理本测试组自己的合成站点行,不无差别清理共享表
        await session.execute(delete(SiteExperience).where(SiteExperience.site_id.in_(_SITES)))
        for site_id, origin in _SITES.items():
            session.add(
                SiteExperience(
                    site_id=site_id,
                    display_name=site_id,
                    allowed_origins=[origin],
                    starters=[],
                    enabled=True,
                )
            )
        await session.commit()


async def _cleanup_sites(factory) -> None:
    async with factory() as session:
        # 只清理本测试组的合成站点行(共享测试库中其它行不动)
        await session.execute(delete(SiteExperience).where(SiteExperience.site_id.in_(_SITES)))
        await session.commit()


async def _cleanup_conversation(factory, sid: str) -> None:
    async with factory() as session:
        await session.execute(delete(Conversation).where(Conversation.session_id == sid))
        await session.commit()


async def _ask(
    app,
    *,
    sid: str,
    headers: dict | None = None,
    client_addr: tuple = _TRUSTED_PEER,
    site_id: str | None = None,
    channel: str = "widget",
    decline: bool = False,
) -> tuple[str | None, str | None]:
    """发一条 /api/ask(合成内容),从库里读回持久化的 (country, country_source)。"""
    app.state.rag = _fake_rag()
    app.state.budget = _DecliningBudget() if decline else _open_budget()
    req_headers = {"origin": _SITES.get(site_id, "https://website.test")} if site_id else {}
    req_headers.update(headers or {})
    body: dict = {"message": f"geoip2 probe {sid}", "session_id": sid, "channel": channel}
    if site_id:
        body["site_id"] = site_id
    transport = ASGITransport(app=app, client=client_addr)
    async with AsyncClient(transport=transport, base_url="http://test") as probe:
        resp = await probe.post("/api/ask", json=body, headers=req_headers)
    assert resp.status_code == 200, resp.text
    conversation_id = None
    for line in resp.text.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            conversation_id = json.loads(line[len("data:") :])["conversation_id"]
    assert conversation_id, resp.text
    factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with factory() as session:
        conv = await session.get(Conversation, uuid.UUID(conversation_id))
        assert conv is not None, "两条持久化分支都必须落真实 Conversation"
        return conv.country, conv.country_source


# --------------------------------------------------------------------------- #
# AC3-1/2:正常路径(非 declined)—— 可信头入库 / 伪造头与直连攻击面 Unknown
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_normal_path_trusted_ingress_country_persists(ingress_app):
    """正常路径:受信 peer(nginx 网关仿真)+ geo 头 → country + source 双落。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(ingress_app, sid=sid, headers={_INGRESS_HEADER: "US"})
        assert got == ("US", "ingress")
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


@pytest.mark.integration
async def test_client_supplied_same_name_header_from_untrusted_peer_is_unknown(ingress_app):
    """客户端同名国家头 + 不受信直连 peer(绕过 nginx 直打后端的攻击面仿真)
    → Unknown。nginx 侧由 proxy_set_header 无条件覆盖(见 README §2),
    后端侧由受信 peer 门兜底 —— 纵深两道,任一缺位都不产生伪国家。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(
            ingress_app,
            sid=sid,
            headers={_INGRESS_HEADER: "US"},
            client_addr=("203.0.113.7", 111),  # 外部直连 peer,非受信
        )
        assert got == (None, None)
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


# --------------------------------------------------------------------------- #
# AC3-3:空 / 错误 / 保留码 → Unknown
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.parametrize("bad", ["XX", "usa", "U1", "   "])
async def test_invalid_and_reserved_codes_persist_unknown(ingress_app, bad):
    """保留码(XX)与非 ISO alpha-2 值(受信 peer 也不行)→ Unknown。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(ingress_app, sid=sid, headers={_INGRESS_HEADER: bad})
        assert got == (None, None)
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


# --------------------------------------------------------------------------- #
# AC3-4:proxy 身份头变更不得绕过信任门
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_proxy_identity_header_spoofing_cannot_bypass_trust_gate(ingress_app):
    """不受信直连 peer 伪造 X-Forwarded-For/X-Real-IP 冒充受信代理 → 仍 Unknown。
    信任判据只有 TCP 直连 peer(request.client.host),代理身份头不是输入。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(
            ingress_app,
            sid=sid,
            headers={
                _INGRESS_HEADER: "US",
                "x-forwarded-for": _TRUSTED_IP,
                "x-real-ip": _TRUSTED_IP,
            },
            client_addr=("203.0.113.9", 111),
        )
        assert got == (None, None)
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


@pytest.mark.integration
async def test_hostile_proxy_identity_headers_do_not_degrade_trusted_value(ingress_app):
    """受信直连 peer 上,恶意/垃圾 XFF 不影响权威值(解析只看直连 peer)。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(
            ingress_app,
            sid=sid,
            headers={
                _INGRESS_HEADER: "US",
                "x-forwarded-for": "1.2.3.4, 5.6.7.8",
                "x-real-ip": "6.6.6.6",
            },
        )
        assert got == ("US", "ingress")
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


# --------------------------------------------------------------------------- #
# AC3-5:三站点共享 API 路径 —— 国家解析与站点无关
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_three_sites_share_api_path_country_resolution(ingress_app):
    """三站点(site_id + Origin)+ legacy widget + admin,同一受信头在所有
    路径产出一致权威值 —— 单一 vhost/单一 API 路径,站点维度零分叉。"""
    factory = ingress_app.state.session_factory
    await _seed_sites(factory)
    try:
        cases: list[tuple[str | None, str]] = [(site_id, "widget") for site_id in _SITES]
        cases.append((None, "widget"))  # legacy 公共 widget
        cases.append((None, "admin"))
        for i, (site_id, channel) in enumerate(cases):
            sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
            got = await _ask(
                ingress_app,
                sid=sid,
                headers={_INGRESS_HEADER: "DE"},
                site_id=site_id,
                channel=channel,
                # 每用例独立 loopback 地址,避免 slowapi 20/min 同键限流
                client_addr=(f"127.0.0.{10 + i}", 111),
            )
            assert got == ("DE", "ingress"), f"site_id={site_id} channel={channel}"
            await _cleanup_conversation(factory, sid)
    finally:
        await _cleanup_sites(factory)


# --------------------------------------------------------------------------- #
# AC3-6:预算拒绝路径持久化不回退
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_budget_declined_path_persists_trusted_country(ingress_app):
    """budget-declined 分支:可信头 → 真实 declined Conversation 带国家事实。"""
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(
            ingress_app,
            sid=sid,
            headers={_INGRESS_HEADER: "JP"},
            decline=True,
        )
        assert got == ("JP", "ingress")
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


@pytest.mark.integration
async def test_budget_declined_path_untrusted_peer_stays_unknown(ingress_app):
    sid = f"{_SID_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        got = await _ask(
            ingress_app,
            sid=sid,
            headers={_INGRESS_HEADER: "JP"},
            client_addr=("203.0.113.11", 111),
            decline=True,
        )
        assert got == (None, None)
    finally:
        await _cleanup_conversation(ingress_app.state.session_factory, sid)


# --------------------------------------------------------------------------- #
# AC2 装配面:env 三元组解析(compose env_file → load_settings)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_env_assembly_default_is_off(monkeypatch):
    """未注入任何键(= #144 生产基线)→ off / 无头名 / 无人可信。"""
    for key in ("COUNTRY_RESOLUTION_MODE", "COUNTRY_INGRESS_HEADER", "GEO_TRUSTED_PROXY_CIDRS"):
        monkeypatch.delenv(key, raising=False)
    s = load_settings(config_dir=Path(__file__).resolve().parents[2] / "config")
    assert s.country_resolution_mode == "off"
    assert s.country_ingress_header == ""
    assert s.geo_trusted_proxy_cidrs == ()


@pytest.mark.unit
async def test_env_assembly_ingress_triple_parsed(monkeypatch):
    """geoip2.env.example 的装配形态 → 三键正确解析;CIDR 空白容差。"""
    monkeypatch.setenv("COUNTRY_RESOLUTION_MODE", "ingress")
    monkeypatch.setenv("COUNTRY_INGRESS_HEADER", "geo-country")
    monkeypatch.setenv("GEO_TRUSTED_PROXY_CIDRS", " 127.0.0.0/8 , 10.0.0.0/8 ")
    s = load_settings(config_dir=Path(__file__).resolve().parents[2] / "config")
    assert s.country_resolution_mode == "ingress"
    assert s.country_ingress_header == "geo-country"
    assert s.geo_trusted_proxy_cidrs == ("127.0.0.0/8", "10.0.0.0/8")


@pytest.mark.unit
async def test_env_assembly_invalid_cidr_entry_is_dropped_fail_closed(monkeypatch):
    """非法 CIDR 项被解析器丢弃(信任面只收不放);全部非法 = 无人可信。"""
    from dataclasses import replace as _replace

    from backend.services.geo_country import resolve_request_country

    monkeypatch.setenv("GEO_TRUSTED_PROXY_CIDRS", "10.0.0.0/8,not-a-cidr")
    s = load_settings(config_dir=Path(__file__).resolve().parents[2] / "config")
    # settings 层保存原始串(不谎报);收敛发生在 resolver 的解析门
    assert "not-a-cidr" in s.geo_trusted_proxy_cidrs
    s_ingress = _replace(s, country_resolution_mode="ingress", country_ingress_header="geo-country")

    class _Req:
        def __init__(self) -> None:
            self.headers = {"geo-country": "US"}
            self.client = type("Client", (), {"host": "10.1.2.3"})()

    # 合法项仍生效:合法网段内的 peer 受信
    assert resolve_request_country(_Req(), s_ingress) == ("US", "ingress")

    # 全部非法 = 信任面为空 → 任何人都不受信(fail-closed,不崩启动)
    s_all_bad = _replace(s_ingress, geo_trusted_proxy_cidrs=("not-a-cidr", "300.1.2.3/8"))
    assert resolve_request_country(_Req(), s_all_bad) == (None, None)


@pytest.mark.unit
async def test_configured_header_name_is_case_insensitive(monkeypatch):
    """头名配置大小写差异是格式而非语义(env 写法与 nginx 片段可各自大小写)。"""
    from dataclasses import replace as _replace

    from backend.services.geo_country import resolve_request_country

    class _Req:
        def __init__(self) -> None:
            self.headers = {"geo-country": "US"}
            self.client = type("Client", (), {"host": "10.1.2.3"})()

    s = _replace(
        _load,
        country_resolution_mode="ingress",
        country_ingress_header="GEO-COUNTRY",
        geo_trusted_proxy_cidrs=("10.0.0.0/8",),
    )
    assert resolve_request_country(_Req(), s) == ("US", "ingress")
