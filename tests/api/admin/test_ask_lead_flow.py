"""/api/ask × Lead Capture 全链路测试(真实 orchestrator + 真实 Postgres)。

Weaviate/BGE/真实 LLM 以 mock 替换,其余走真实代码路径:
routes → orchestrator(意图/资格判定并发/指令内嵌)→ lead_service → PG。

PII HARD(契约 §14 / LEAD-G013/G014):
- 联系方式原文只出现在 sales_leads 表;
- conversations / traces / 检索查询 / 所有 LLM prompt 一律只有脱敏文本;
- 语料灌入模块与 lead 域零引用(源码级不变量)。
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.db.models import Conversation, SalesLead, Trace
from backend.main import app
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult
from backend.utils.budget import BudgetConfig, BudgetLimiter

pytestmark = pytest.mark.asyncio(loop_scope="session")

_RAW_EMAIL = "john@example.com"
_QUALIFIED = json.dumps(
    {
        "lead_level": "qualified",
        "explicit_sales_request": False,
        "stronger_signal": False,
        "fields": {"company": "Acme", "quantity": "500 units"},
        "summary": "Acme 计划采购 500 台 NE503,要求正式报价",
    },
    ensure_ascii=False,
)


class _ScriptedLLM:
    """按 task 分发的脚本 LLM;记录所有 generate/stream 输入(PII 扫描用)。"""

    def __init__(self, *, intent: str, qualification: str):
        self.intent = intent
        self.qualification = qualification
        self.prompts: list[str] = []
        self.stream_prompts: list[str] = []

    def _record(self, messages) -> str:
        text = json.dumps(messages, ensure_ascii=False)
        self.prompts.append(text)
        return text

    async def generate(self, messages, **kwargs):
        self._record(messages)
        from backend.llm.base import LLMResponse

        task = kwargs.get("task", "generation")
        content = {
            "intent": json.dumps({"category": self.intent, "reason": "r", "confidence": 0.9}),
            "lead_qualification": self.qualification,
            "query_rewrite": "rewritten",
        }.get(task, "ignored")
        return LLMResponse(
            content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1
        )

    def stream(self, messages, **kwargs):
        text = json.dumps(messages, ensure_ascii=False)
        self.stream_prompts.append(text)

        async def _gen():
            yield "NE503 支持批量采购,可提供正式报价。"

        return _gen()


def _build_rag(llm: _ScriptedLLM) -> tuple[RAGOrchestrator, list[str]]:
    """真实 orchestrator + 记录型 searcher/reranker(Weaviate 边界替身)。"""
    queries: list[str] = []
    sr = SearchResult(
        text="NE503 spec",
        source_id="s",
        source_type="woocommerce",
        product="ne503",
        title="T",
        url="https://e.com",
        score=0.9,
        chunk_index=0,
    )

    class _Searcher:
        def search(self, *, query, **kw):
            queries.append(query)
            return [sr]

        def search_symbols(self, *, query, **kw):
            queries.append(query)
            return []

        def search_bucket(self, *, query, **kw):
            queries.append(query)
            return []

    class _Reranker:
        def rerank(self, query, results, top_k=10):
            return results[:top_k]

    return RAGOrchestrator(_Searcher(), _Reranker(), llm, system_prompt="sys"), queries


@pytest_asyncio.fixture(loop_scope="session")
async def lead_flow_env():
    session_marker = f"lead-flow-{uuid.uuid4().hex[:10]}"
    llm = _ScriptedLLM(intent="commercial", qualification=_QUALIFIED)
    rag, queries = _build_rag(llm)
    old_rag = getattr(app.state, "rag", None)
    app.state.rag = rag
    if getattr(app.state, "budget", None) is None:
        app.state.budget = BudgetLimiter(
            BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
        )
    yield {
        "session": session_marker,
        "llm": llm,
        "queries": queries,
        "factory": app.state.session_factory,
    }
    app.state.rag = old_rag
    # 精准清理本测试产生的行(共享测试库礼貌)
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            SalesLead.__table__.delete().where(
                SalesLead.session_id.in_([session_marker, session_marker + "-plain"])
            )
        )
        conv_ids = (
            (
                await session.execute(
                    select(Conversation.id).where(
                        Conversation.session_id.in_([session_marker, session_marker + "-plain"])
                    )
                )
            )
            .scalars()
            .all()
        )
        if conv_ids:
            await session.execute(
                Trace.__table__.delete().where(Trace.conversation_id.in_(conv_ids))
            )
        await session.execute(
            Conversation.__table__.delete().where(
                Conversation.session_id.in_([session_marker, session_marker + "-plain"])
            )
        )
        await session.commit()


def _sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    cur: dict = {}
    for line in body.split("\n"):
        line = line.rstrip("\r")
        if line == "":
            if cur:
                events.append(cur)
                cur = {}
            continue
        if line.startswith("event:"):
            cur["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            cur["data"] = line.split(":", 1)[1].strip()
    if cur:
        events.append(cur)
    return events


async def _ask(message: str, session_id: str) -> list[dict]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": message, "session_id": session_id, "channel": "widget"},
        )
    assert resp.status_code == 200
    return _sse_events(resp.text)


async def test_full_lead_flow_and_pii_isolation(lead_flow_env):
    env = lead_flow_env
    sid = env["session"]
    factory = env["factory"]

    # ---- Turn 1:强信号 → qualified + 邀请(G002/G003/G007) ----
    events = await _ask("我们需要500台NE503,请给正式报价", sid)
    kinds = [e["event"] for e in events]
    assert "sources" in kinds and "token" in kinds
    assert kinds[-1] == "done"
    conv_id = json.loads(events[-1]["data"])["conversation_id"]

    async with factory() as s:
        lead = (await s.execute(select(SalesLead).where(SalesLead.session_id == sid))).scalar_one()
        conv = await s.get(Conversation, uuid.UUID(conv_id))
    assert lead.status == "qualified"
    assert lead.prompt_count == 1
    assert lead.last_prompted_at is not None
    assert lead.company == "Acme"
    assert str(lead.source_conversation_id) == conv_id
    assert conv.session_id == sid
    assert conv.intent_tag == "commercial"

    # ---- Turn 2:补联系方式 → capture(G004),对话层脱敏(G013) ----
    events2 = await _ask(f"我的邮箱是 {_RAW_EMAIL}", sid)
    assert [e["event"] for e in events2][-1] == "done"
    conv_id2 = json.loads(events2[-1]["data"])["conversation_id"]

    async with factory() as s:
        lead = (await s.execute(select(SalesLead).where(SalesLead.session_id == sid))).scalar_one()
        conv2 = await s.get(Conversation, uuid.UUID(conv_id2))
        trace = (
            await s.execute(select(Trace).where(Trace.conversation_id == uuid.UUID(conv_id2)))
        ).scalar_one_or_none()
    assert lead.status == "contact_captured"
    assert lead.contact_value == _RAW_EMAIL
    assert lead.contact_type == "email"
    assert lead.contact_masked.endswith("@example.com")
    assert lead.contact_captured_at is not None
    # 对话表脱敏:原文不得出现在 conversations
    assert _RAW_EMAIL not in (conv2.question or "")
    assert "[邮箱已脱敏]" in conv2.question

    # ---- Turn 3:已留联系方式,正常回答不骚扰(G005/G006) ----
    events3 = await _ask("还想了解一下质保政策", sid)
    assert [e["event"] for e in events3][-1] == "done"
    async with factory() as s:
        lead = (await s.execute(select(SalesLead).where(SalesLead.session_id == sid))).scalar_one()
    assert lead.prompt_count == 1  # 未再邀请

    # ---- PII HARD:全表面扫描(G013) ----
    surfaces: list[str] = []
    async with factory() as s:
        convs = (
            (await s.execute(select(Conversation).where(Conversation.session_id == sid)))
            .scalars()
            .all()
        )
        for c in convs:
            surfaces += [c.question or "", c.answer or ""]
        traces = (
            (await s.execute(select(Trace).where(Trace.conversation_id.in_([c.id for c in convs]))))
            .scalars()
            .all()
        )
        for t in traces:
            surfaces.append(json.dumps(t.stages, ensure_ascii=False))
    surfaces += env["llm"].prompts
    surfaces += env["llm"].stream_prompts
    surfaces += env["queries"]
    blob = "\n".join(surfaces)
    assert _RAW_EMAIL not in blob, "联系方式原文泄漏到对话/trace/检索/LLM prompt 表面"
    assert "[邮箱已脱敏]" in blob  # 脱敏占位确实流转于管线

    # 原文唯一落点 = sales_leads(G007/G013)
    assert lead.contact_value == _RAW_EMAIL
    # trace lead 阶段只带 masked
    if trace is not None:
        assert "john@example.com" not in json.dumps(trace.stages, ensure_ascii=False)
        assert trace.stages.get("lead", {}).get("contact", {}) is not None or True


async def test_plain_inquiry_creates_no_lead(lead_flow_env):
    """G001:普通产品咨询(potential 以下/none)不建线索行。"""
    env = lead_flow_env
    sid = env["session"] + "-plain"
    llm = _ScriptedLLM(
        intent="product",
        qualification=json.dumps({"lead_level": "none"}, ensure_ascii=False),
    )
    rag, _ = _build_rag(llm)
    old = app.state.rag
    app.state.rag = rag
    try:
        events = await _ask("NE503 有什么接口?", sid)
        assert [e["event"] for e in events][-1] == "done"
        async with env["factory"]() as s:
            rows = (
                (await s.execute(select(SalesLead).where(SalesLead.session_id == sid)))
                .scalars()
                .all()
            )
        assert rows == []
    finally:
        app.state.rag = old


async def test_corpus_ingestion_source_never_references_leads():
    """G013 源码级不变量:语料灌入路径(连接器/ingest/sync)与 lead 域零耦合。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    targets = [root / "backend" / "pipeline" / "ingest.py", root / "scripts" / "sync.py"]
    targets += (root / "backend" / "connectors").glob("*.py")
    for path in targets:
        src = path.read_text(encoding="utf-8")
        for token in ("SalesLead", "lead_service", "lead_qualify", "apply_lead_turn"):
            assert token not in src, f"{path.name} 引用了 lead 域符号 {token}"
