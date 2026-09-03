"""阶段⑯:生成失败 / 本地化闭环 — /api/ask 失败路径 EN+ZH 全覆盖。

产品契约(冻结):
- 语言 authority 唯一 = resolve_answer_language(routes 与 rag 同函数同输入,
  确定性等值);任何 user-visible fallback / Conversation 持久化之前必须
  先取得语言 —— complete 前失败不得错落 language。
- 冻结文案:user_messages 表(service_unavailable / budget_declined /
  no_evidence);zh → 中文,其余 → 英文。
- Budget Declined:真实 Conversation 持久化(禁幽灵 uuid),
  分类 DECLINED(不进 generation_error taxonomy)。
- SSE:新增 message_key 为 additive;message 恒保留(旧客户端兼容)。
- Conversation.language 新写入归一 zh / en。

场景矩阵(EN + ZH × 6 类):
service_unavailable / budget_declined / no_evidence / empty_generation /
provider_error / stream_interrupted + language_hint / CJK 显式覆盖。
"""

import json
import uuid
from typing import Any

import pytest

from backend.main import app
from backend.utils.budget import BudgetConfig, BudgetLimiter
from backend.utils.user_messages import localized_message
from tests.api.test_reliability import (
    _ask_request,
    _make_mock_session_factory,
    _make_streaming_rag,
    _parse_sse_events,
    _persisted_objects,
)

EN_SERVICE_UNAVAILABLE = "The service is temporarily unavailable. Please try again later."
ZH_SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。"
EN_BUDGET = "The service is busy right now. Please try again shortly."
ZH_BUDGET = "服务繁忙,请稍后再试。"
EN_REJECT = "I couldn't find relevant information in the official sources."


@pytest.fixture(autouse=True)
def _reset_ask_rate_limit() -> None:
    """每个用例前重置 20/min 限流计数(本文件密频调用 /api/ask;
    先例:test_unified_v1_gate._reset_ask_rate_limit)。"""
    from backend.api.routes import limiter

    limiter.reset()


def _setup_budget_high() -> None:
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


def _conversation_of(session) -> Any:
    persisted = _persisted_objects(session)
    convs = [p for p in persisted if type(p).__name__ == "Conversation"]
    assert len(convs) == 1, f"期望恰好 1 条 Conversation,实际 {len(convs)}"
    return convs[0]


def _traces_of(session) -> list[Any]:
    return [p for p in _persisted_objects(session) if type(p).__name__ == "Trace"]


# --------------------------------------------------------------------------- #
# service_unavailable(provider_error / empty_generation)EN + ZH
# --------------------------------------------------------------------------- #


async def test_en_provider_error_gives_en_fallback() -> None:
    """AC1:英文问题首 token 前失败 → 英文兜底文案,kind=provider_error。"""
    _setup_budget_high()
    rag = _make_streaming_rag(exc=RuntimeError("All LLM providers unavailable"))
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post(
            "/api/ask", json={"message": "How do I troubleshoot an NE301 flash failure?"}
        )

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["token", "error", "done"]
    token = json.loads(events[0]["data"])
    error = json.loads(events[1]["data"])
    assert token["content"] == EN_SERVICE_UNAVAILABLE
    assert error["message"] == EN_SERVICE_UNAVAILABLE
    assert error["kind"] == "provider_error"
    # SSE 结构化身份(additive):message_key 与 message 并存
    assert error["message_key"] == "service_unavailable"
    # 异常细节不泄漏
    assert "providers unavailable" not in resp.text

    conv = _conversation_of(session)
    assert conv.is_answered is False
    assert conv.answer == EN_SERVICE_UNAVAILABLE
    assert conv.language == "en"  # complete 前失败不再是错落的默认值问题
    traces = _traces_of(session)
    assert len(traces) == 1 and traces[0].type == "generation_error"
    assert traces[0].config_snapshot["failure_kind"] == "provider_error"


async def test_zh_provider_error_gives_zh_fallback() -> None:
    """AC2:中文问题首 token 前失败 → 中文兜底文案(不是英文)。"""
    _setup_budget_high()
    rag = _make_streaming_rag(exc=RuntimeError("All LLM providers unavailable"))
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE301 烧写失败怎么排查?"})

    events = _parse_sse_events(resp.text)
    error = json.loads(events[1]["data"])
    assert error["message"] == ZH_SERVICE_UNAVAILABLE
    conv = _conversation_of(session)
    assert conv.answer == ZH_SERVICE_UNAVAILABLE
    assert conv.language == "zh"  # MF-4 修复:不再恒 "en"


async def test_zh_query_without_hint_language_normalized_zh() -> None:
    """AC4:无 hint 中文 query,Conversation.language 落 zh(非 zh-cn)。"""
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": "答案内容",
                "sources": [],
                "is_answered": True,
                "language": "zh-cn",  # rag 无 hint 时返回检测原值
                "response_time_ms": 5,
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 有哪些接口?"})

    assert resp.status_code == 200
    conv = _conversation_of(session)
    assert conv.language == "zh"


async def test_en_hint_with_cjk_query_failure_overrides_to_zh() -> None:
    """显式 CJK 覆盖(ML 冻结语义):en hint + 中文 query 失败 → zh 兜底。"""
    _setup_budget_high()
    rag = _make_streaming_rag(exc=RuntimeError("boom"))
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "设备无法开机", "language": "en"})

    error = json.loads(_parse_sse_events(resp.text)[1]["data"])
    assert error["message"] == ZH_SERVICE_UNAVAILABLE
    conv = _conversation_of(session)
    assert conv.language == "zh"


async def test_en_hint_latin_query_failure_stays_en() -> None:
    """en hint + 拉丁 query 失败 → en 兜底(hint 为默认语境)。"""
    _setup_budget_high()
    rag = _make_streaming_rag(exc=RuntimeError("boom"))
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post(
            "/api/ask", json={"message": "camera not powering on", "language": "en"}
        )

    error = json.loads(_parse_sse_events(resp.text)[1]["data"])
    assert error["message"] == EN_SERVICE_UNAVAILABLE
    assert _conversation_of(session).language == "en"


async def test_en_empty_generation_localized_and_persisted() -> None:
    """AC1/AC8:empty_generation EN 全链(文案/kind/persistence/trace)。"""
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {"type": "sources", "sources": []},
            {
                "type": "complete",
                "answer": "",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 10,
            },
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "what is inside the box"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["sources", "token", "error", "done"]
    assert json.loads(events[1]["data"])["content"] == EN_SERVICE_UNAVAILABLE
    error = json.loads(events[2]["data"])
    assert error["kind"] == "empty_generation"
    assert error["message_key"] == "service_unavailable"
    # done 与 sources 的 conversation_id 一致(契约不变)
    assert (
        json.loads(events[3]["data"])["conversation_id"]
        == json.loads(events[0]["data"])["conversation_id"]
    )
    conv = _conversation_of(session)
    assert conv.is_answered is False and conv.answer == EN_SERVICE_UNAVAILABLE
    assert conv.language == "en"
    traces = _traces_of(session)
    assert traces[0].type == "generation_error"
    assert traces[0].config_snapshot["failure_kind"] == "empty_generation"


async def test_zh_stream_interrupted_keeps_partial_zh_append_error() -> None:
    """AC2/AC8:中文部分 token 后中断 → 部分内容保留 + 中文 error,不重复兜底。"""
    import httpx

    _setup_budget_high()
    rag = _make_streaming_rag(
        [{"type": "token", "content": "请先检查供电:"}],
        exc=httpx.ReadTimeout("timed out"),
        exc_after_events=True,
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "设备开不了机"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["token", "error", "done"]
    assert json.loads(events[0]["data"])["content"] == "请先检查供电:"
    error = json.loads(events[1]["data"])
    assert error["kind"] == "stream_interrupted"
    assert error["message"] == ZH_SERVICE_UNAVAILABLE
    conv = _conversation_of(session)
    assert conv.answer == "请先检查供电:" and conv.is_answered is False
    assert conv.language == "zh"


# --------------------------------------------------------------------------- #
# Budget Declined — HARD CONTRACT
# --------------------------------------------------------------------------- #


async def test_budget_declined_en_persists_real_conversation() -> None:
    """AC5/AC6:EN 请求熔断 → 真实 Conversation + DECLINED 分类 + 英文文案。"""
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0))
    rag = _make_streaming_rag()
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post(
            "/api/ask", json={"message": "price of the starter kit?", "language": "en"}
        )

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["declined", "done"]
    declined = json.loads(events[0]["data"])
    done = json.loads(events[1]["data"])
    # 用户可见文案本地化 + 结构化身份
    assert declined["reason"] == EN_BUDGET
    assert declined["message_key"] == "budget_declined"
    # 真实 conversation_id:declined 与 done 一致,且真实持久化(非幽灵)
    assert declined["conversation_id"] == done["conversation_id"]
    real_id = uuid.UUID(done["conversation_id"])  # 可解析

    conv = _conversation_of(session)
    assert conv.id == real_id
    assert conv.is_answered is False
    assert conv.answer == EN_BUDGET
    assert conv.language == "en"
    # DECLINED 独立 trace type,不进 generation_error taxonomy
    traces = _traces_of(session)
    assert len(traces) == 1
    assert traces[0].type == "budget_declined"
    assert traces[0].type != "generation_error"
    assert traces[0].config_snapshot["outcome"] == "declined"


async def test_budget_declined_zh_persists_zh_language() -> None:
    """AC2/AC5:中文请求熔断 → 中文繁忙文案 + language=zh。"""
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0))
    rag = _make_streaming_rag()
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 参数怎么样"})

    events = _parse_sse_events(resp.text)
    declined = json.loads(events[0]["data"])
    assert declined["reason"] == ZH_BUDGET
    assert declined["message_key"] == "budget_declined"
    conv = _conversation_of(session)
    assert conv.language == "zh"
    assert conv.answer == ZH_BUDGET


# --------------------------------------------------------------------------- #
# Refusal(无证据)与失败的分界:无 error 事件 + reject_short
# --------------------------------------------------------------------------- #


async def test_refusal_complete_never_emits_error_event() -> None:
    """拒答 ≠ 失败:reject 语义经 complete(is_answered=False)下发,
    无 error 事件;language 经 resolver 前置而非等到 complete。"""
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": EN_REJECT,
                "sources": [],
                "is_answered": False,
                "language": "en",
                "response_time_ms": 5,
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "who won the world cup"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["token", "done"]  # 无 error
    assert json.loads(events[0]["data"])["content"] == EN_REJECT
    conv = _conversation_of(session)
    assert conv.is_answered is False
    traces = _traces_of(session)
    assert all(t.type != "generation_error" for t in traces)
    assert all(t.type == "reject_short" for t in traces)


# --------------------------------------------------------------------------- #
# 兼容护栏:正常流/社交回复/off-topic 不受影响
# --------------------------------------------------------------------------- #


async def test_normal_stream_language_preseeded_but_complete_wins() -> None:
    """正常完成:complete.language(rag 同 resolver)覆盖前置值,逐位等值。"""
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {"type": "token", "content": "Hello"},
            {
                "type": "complete",
                "answer": "Hello",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 42,
            },
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "hello there"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["token", "done"]
    conv = _conversation_of(session)
    assert conv.is_answered is True
    assert conv.language == "en"


async def test_social_reply_success_regression() -> None:
    """社交回复回归:social_reply trace,is_answered=True。"""
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": "Hello! I'm Ask Camthink.ai.",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 3,
                "intent": "smalltalk",
                "trace_payload": {
                    "type": "social_reply",
                    "stages": {},
                    "total_ms": 3,
                    "intent": "smalltalk",
                },
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "hi"})

    assert resp.status_code == 200
    conv = _conversation_of(session)
    assert conv.is_answered is True
    traces = _traces_of(session)
    assert traces[0].type == "social_reply"


# --------------------------------------------------------------------------- #
# FINAL REVIEW CORRECTION — Blocker A/B 回归
# --------------------------------------------------------------------------- #


def _make_failing_session_factory():
    """commit 必抛的 mock session factory(模拟 DB 持久化故障)。"""
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    session.add = MagicMock()
    session.commit.side_effect = RuntimeError("db down")
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


async def test_budget_declined_persistence_failure_emits_no_ghost_identity() -> None:
    """Blocker A:declined 持久化失败时,不得把未持久化的 UUID 冒充
    Conversation 身份下发给客户端(禁幽灵 conversation_id)。

    不变量:凡以下发、可用的 declined Conversation 身份,必对应一次
    成功持久化;持久化失败 → 不下发任何身份,但 DECLINED 用户语义保持
    (本地化繁忙文案 + 无 error 事件,不得变成 generation failure)。
    """
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0))
    rag = _make_streaming_rag()
    factory, session = _make_failing_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 参数怎么样"})

    events = _parse_sse_events(resp.text)
    # DECLINED != FAILURE:仍走 declined+done,无 error 事件
    assert [e["event"] for e in events] == ["declined", "done"]
    declined = json.loads(events[0]["data"])
    done = json.loads(events[1]["data"])
    # 本地化文案与结构化身份保留
    assert declined["reason"] == ZH_BUDGET
    assert declined["message_key"] == "budget_declined"
    # 持久化失败 → 绝不下发任何(幽灵)conversation 身份
    assert "conversation_id" not in declined
    assert "conversation_id" not in done
    # 持久化确实尝试过(语义未弱化:仍写了 Conversation+Trace)
    added_types = [type(o).__name__ for o in _persisted_objects(session)]
    assert "Conversation" in added_types and "Trace" in added_types


async def test_budget_declined_success_still_emits_real_id() -> None:
    """Blocker A 护栏:正常持久化路径保持真实 id 下发(不弱化)。"""
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0))
    rag = _make_streaming_rag()
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 参数怎么样"})

    events = _parse_sse_events(resp.text)
    declined = json.loads(events[0]["data"])
    done = json.loads(events[1]["data"])
    assert declined["conversation_id"] == done["conversation_id"]
    assert _conversation_of(session).id == uuid.UUID(done["conversation_id"])


async def test_complete_without_language_keeps_authoritative_zh() -> None:
    """Blocker B:complete 缺 language 不得把权威 zh 重置为硬编码 en。

    中文 query → 前置权威解析 zh → complete 无 language 键且零内容
    → 兜底文案仍中文 + Conversation.language 仍 zh。
    """
    _setup_budget_high()
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": "",
                "sources": [],
                "is_answered": True,
                "response_time_ms": 5,  # 故意省略 language 键
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE301 烧写失败怎么排查?"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["token", "error", "done"]
    # 用户可见兜底仍中文(authoritative zh 未被覆写)
    assert json.loads(events[0]["data"])["content"] == ZH_SERVICE_UNAVAILABLE
    assert json.loads(events[1]["data"])["message"] == ZH_SERVICE_UNAVAILABLE
    conv = _conversation_of(session)
    assert conv.language == "zh"


async def test_complete_without_language_keeps_authoritative_en() -> None:
    """Blocker B 英文等价:complete 缺 language → en 权威不被破坏。"""
    _setup_budget_high()
    # 零内容 complete(缺 language 键)→ empty_generation 兜底路径
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": "",
                "sources": [],
                "is_answered": True,
                "response_time_ms": 5,
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "camera flash failure"})

    events = _parse_sse_events(resp.text)
    # 零内容 → empty_generation 兜底;complete 缺 language → 仍英文
    assert [e["event"] for e in events] == ["token", "error", "done"]
    error = json.loads(events[1]["data"])
    assert error["message"] == EN_SERVICE_UNAVAILABLE
    assert _conversation_of(session).language == "en"


# --------------------------------------------------------------------------- #
# 纯函数:user_messages / conversation_language
# --------------------------------------------------------------------------- #


def test_localized_message_matrix() -> None:
    """冻结文案矩阵:zh→中文;en/ja/ko/fr→英文;未知键 fail-safe。"""
    assert localized_message("service_unavailable", "zh") == ZH_SERVICE_UNAVAILABLE
    assert localized_message("service_unavailable", "zh-cn") == ZH_SERVICE_UNAVAILABLE
    assert localized_message("service_unavailable", "en") == EN_SERVICE_UNAVAILABLE
    assert localized_message("service_unavailable", "ja") == EN_SERVICE_UNAVAILABLE
    assert localized_message("budget_declined", "zh") == ZH_BUDGET
    assert localized_message("budget_declined", "en") == EN_BUDGET
    assert localized_message("no_evidence", "zh") == "暂未在官方资料中找到相关信息。"
    assert (
        localized_message("no_evidence", "en")
        == "I couldn't find relevant information in the official sources."
    )
    # 未知键不炸,fail-safe 回落 service_unavailable
    assert localized_message("site_denied", "zh") == ZH_SERVICE_UNAVAILABLE
