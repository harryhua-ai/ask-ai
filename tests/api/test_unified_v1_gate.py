"""Unified V1 Integration Gate — INT-V1 组合契约持久回归(全 mock,零 Weaviate)。

G001(INT-V1-001 Trust Boundary × Multi-Site):显式 site_id + page_context 在场,
受限/幽灵源仍被 P0 拦截,内部知识不因站点上下文获得可见性。
G002(INT-V1-002 Citation × Page Context):page_context 只做软加分与非信任背景段,
可见引用编号仍只映射检索到的公开源;页面背景绝不成为引用来源。
G003(INT-V1-003 Reliability × Multi-Site):已授权站点请求遇零内容生成,
仍走显式可恢复失败(sources → 兜底 token → error → done),绝不静默空白。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.pipeline.rag import RAGOrchestrator
from backend.services.source_visibility import SourceVisibilityGuard
from backend.utils.budget import BudgetConfig, BudgetLimiter
from tests.api.test_routes import _parse_sse_events
from tests.pipeline.test_rag import _make_llm_response, _make_sr

STORE_ORIGIN = "https://store.camthink.ai"

PUBLIC_SR = _make_sr(
    text="NE301 工作温度为 -20°C 至 +50°C。",
    source_id="website-camthink/product/neoeyes-301",
    source_type="web_crawl",
    product="ne301",
)
RESTRICTED_SR = _make_sr(
    text="内部工单:ICCID 8901xxxx,APN data641003,内部参考价 $55。",
    source_id="knowledge-cases/support/case.md",
    source_type="filesystem",
    product="ne301",
)
UNKNOWN_SR = _make_sr(
    text="幽灵 chunk:内部跟进记录。",
    source_id="ghost-legacy/notes.md",
    source_type="filesystem",
    product="ne301",
)

PAGE_CONTEXT = {
    "url": f"{STORE_ORIGIN}/products/ne503",
    "title": "NE503 产品页 · 内部升级门户",
    "product": "ne503",
    "page_type": "product",
}


class MappingGuard(SourceVisibilityGuard):
    def __init__(self, mapping: dict[str, tuple[str, ...]]):
        async def _load():
            return mapping

        super().__init__(loader=_load, ttl=60)


class FakeLLM:
    def __init__(self, stream_chunks):
        self.generate = AsyncMock(return_value=_make_llm_response(content="answer"))
        self.stream_chunks = stream_chunks
        self.stream_messages: list | None = None

    async def stream(self, messages, task=None):
        self.stream_messages = messages
        for c in self.stream_chunks:
            yield c


def _build(searcher_results, *, mapping, stream_chunks):
    searcher = MagicMock()
    searcher.search.return_value = list(searcher_results)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda query, results, top_k: list(results)
    llm = FakeLLM(stream_chunks)
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
        visibility_guard=MappingGuard(mapping),
    )
    return rag, llm


# --------------------------------------------------------------------------- #
# G001/G002 — RAG 层:站点上下文 × P0 可见性 × 引用编号
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_int_v1_g001_site_context_cannot_unlock_internal_sources():
    """G001:site_id 已授权 + page_context 在场 → 内部/幽灵源仍被拦,行为与
    无站点上下文完全一致(P0 是唯一可见性权威)。"""
    mapping = {
        "website-camthink": ("widget", "api"),
        "knowledge-cases": ("internal",),
    }
    rag, llm = _build(
        [PUBLIC_SR, RESTRICTED_SR, UNKNOWN_SR],
        mapping=mapping,
        stream_chunks=["NE301 工作温度为 -20°C 至 +50°C。[1]"],
    )

    events = [
        json.loads(e)
        async for e in rag.stream_answer(
            "工作温度",
            "widget",
            page_context=dict(PAGE_CONTEXT),
            site_name="CamThink Store",
        )
    ]

    complete = next(e for e in events if e["type"] == "complete")
    assert complete["is_answered"] is True
    # 可见 sources 只剩公开源:站点上下文没有额外放行任何候选
    assert len(complete["sources"]) == 1
    assert "example.com" in complete["sources"][0]["url"]
    # 内部值既不进生成上下文,也不外发 token
    user_msg = llm.stream_messages[-1]["content"]
    assert "8901xxxx" not in user_msg and "$55" not in user_msg
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "8901xxxx" not in tokens and "内部跟进记录" not in tokens


@pytest.mark.asyncio
async def test_int_v1_g002_page_context_hints_but_never_cites():
    """G002:page_context 软加分不改变引用编号映射;背景段只进 user 消息的
    非信任标签区,绝不成为 sources 成员或 system 消息内容。"""
    mapping = {"website-camthink": ("widget", "api")}
    rag, llm = _build(
        [PUBLIC_SR],
        mapping=mapping,
        stream_chunks=["NE301 工作温度为 -20°C 至 +50°C。[1]"],
    )

    events = [
        json.loads(e)
        async for e in rag.stream_answer(
            "工作温度",
            "widget",
            page_context=dict(PAGE_CONTEXT),
            site_name="CamThink Store",
        )
    ]

    complete = next(e for e in events if e["type"] == "complete")
    # 引用编号仍只映射可见公开源;页面 URL/标题不是引用来源
    assert len(complete["sources"]) == 1
    assert complete["sources"][0]["url"] == PUBLIC_SR.url
    assert all(STORE_ORIGIN not in (s.get("url") or "") for s in complete["sources"])
    assert "[1]" in complete["answer"]
    # 背景段只进 user 消息,且带非信任标签;system 消息不含站点/页面背景
    system_msg = llm.stream_messages[0]["content"]
    user_msg = llm.stream_messages[-1]["content"]
    assert "站点: CamThink Store" in user_msg and "页面标题" in user_msg
    assert "CamThink Store" not in system_msg and PAGE_CONTEXT["title"] not in system_msg


# --------------------------------------------------------------------------- #
# G003 — /api/ask 全链:已授权站点 × 零内容生成
# --------------------------------------------------------------------------- #


def _make_site_row() -> MagicMock:
    row = MagicMock()
    row.site_id = "camthink-store"
    row.enabled = True
    row.allowed_origins = [STORE_ORIGIN]
    row.starters = ["Is NE503 suitable for my project?"]
    row.display_name = "CamThink Store"
    row.welcome = "Shopping for a CamThink device?"
    row.language = "en"
    return row


def _make_site_factory(site_row):
    session = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(return_value=site_row)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


@pytest.fixture(autouse=True)
def _budget_state():
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


@pytest.fixture(autouse=True)
def _reset_ask_rate_limit():
    from backend.api.routes import limiter

    limiter.reset()


SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。"


@pytest.mark.unit
async def test_int_v1_g003_authorized_site_zero_generation_fails_explicitly():
    """G003:站点已授权 + 零内容生成 → 兜底 token + error + done,绝不静默空白;
    失败对话仍如实记 site_id 与 generation_error,不得伪装成功。"""
    captured: dict = {}

    async def stream_answer(*args, **kwargs):
        captured.update(kwargs)
        yield json.dumps({"type": "sources", "sources": [], "conversation_id": "c1"})
        yield json.dumps(
            {
                "type": "complete",
                "answer": "",
                "sources": [],
                "is_answered": True,  # 旧缺陷签名:零内容也标成功
                "language": "en",
                "response_time_ms": 5,
            }
        )

    rag = AsyncMock()
    rag.stream_answer = stream_answer

    factory, session = _make_site_factory(_make_site_row())
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "Is NE503 suitable?",
                "site_id": "camthink-store",
                "page_context": dict(PAGE_CONTEXT),
            },
            headers={"Origin": STORE_ORIGIN},
        )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["sources", "token", "error", "done"]
    # 站点/页面上下文已贯通 rag(site_name + page_context + channel=widget)
    assert captured["site_name"] == "CamThink Store"
    assert captured["page_context"]["product"] == "ne503"
    assert captured["channel"] == "widget"
    # 显式可恢复失败,绝不静默空白(阶段⑯:EN query → 英文冻结文案)
    assert json.loads(events[1]["data"])["content"] == (
        "The service is temporarily unavailable. Please try again later."
    )
    assert json.loads(events[2]["data"])["kind"] == "empty_generation"
    # 持久化如实:is_answered=False + site_id 落值 + Trace=generation_error
    persisted = [call.args[0] for call in session.add.call_args_list]
    conv = persisted[0]
    assert conv.is_answered is False
    assert conv.site_id == "camthink-store"
    traces = [p for p in persisted if type(p).__name__ == "Trace"]
    assert len(traces) == 1
    assert traces[0].type == "generation_error"
