"""P1 生成可靠性 — 确定性产品证据采集(零生产供应商依赖)。

用 mock RAGOrchestrator 驱动**真实** /api/ask SSE 端点,复现五类场景的
实际事件序列与落库状态,供验收报告引用。全部场景确定性可重放,
不依赖任何线上 LLM 供应商(符合任务 §12:不得以波动性生产供应商作为主测试)。

用法:
    PYTHONPATH=. python scripts/p1_reliability_evidence.py
"""

import asyncio
import json
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.utils.budget import BudgetConfig, BudgetLimiter  # noqa: E402

SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。"


def parse_sse(body: str) -> list[dict]:
    events, current = [], {}
    for raw in body.split("\n"):
        line = raw.rstrip("\r")
        if line == "":
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:") :].strip()
    if current:
        events.append(current)
    return events


def make_session_capture():
    session = AsyncMock()
    persisted: list = []

    def _add(obj):
        persisted.append(obj)

    session.add = _add
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, persisted


def make_rag(events=None, exc=None):
    rag = AsyncMock()

    async def stream(*args, **kwargs):
        for evt in events or []:
            yield json.dumps(evt)
        if exc is not None:
            raise exc

    rag.stream_answer = stream
    return rag


async def run_case(title: str, rag, budget: BudgetLimiter | None = None) -> list[dict]:
    print(f"\n{'=' * 72}\nCASE: {title}\n{'=' * 72}")
    factory, persisted = make_session_capture()
    app.state.rag = rag
    app.state.session_factory = factory
    app.state.budget = budget or BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "NE101 蜂窝网络注册失败"})
    print(f"HTTP {resp.status_code}")
    print("SSE 序列:")
    for evt in parse_sse(resp.text):
        print(f"  event: {evt['event']:<10} data: {evt['data']}")
    print("落库状态(应用边界捕获):")
    for obj in persisted:
        name = type(obj).__name__
        if name == "Conversation":
            print(
                f"  Conversation(answer={obj.answer!r}, is_answered={obj.is_answered}, "
                f"channel={obj.channel})"
            )
        elif name == "Trace":
            snap = getattr(obj, "config_snapshot", {}) or {}
            print(
                f"  Trace(type={obj.type!r}, stages.error={getattr(obj, 'stages', {}).get('error')}, "
                f"config_snapshot.failure_kind={snap.get('failure_kind')})"
            )
    return parse_sse(resp.text)


def check(name: str, ok: bool) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


async def main() -> int:
    all_ok = True

    # Case 1 — 零 token(复现验收基线 A05/E04-t2 签名)
    evts = await run_case(
        "1 零 token 正常结束(zero-token completion)",
        make_rag(
            [
                {"type": "sources", "sources": []},
                {
                    "type": "complete",
                    "answer": "",
                    "sources": [],
                    "is_answered": True,
                    "language": "en",
                    "response_time_ms": 47_500,
                },
            ]
        ),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "零内容完成不再是 sources→done 静默空白,且带 error(kind=empty_generation)",
        kinds == ["sources", "token", "error", "done"]
        and json.loads(evts[2]["data"])["kind"] == "empty_generation"
        and json.loads(evts[1]["data"])["content"] == SERVICE_UNAVAILABLE,
    )

    # Case 2 — 首 token 前异常
    evts = await run_case(
        "2 首 token 前供应商异常(error before first token)",
        make_rag(exc=RuntimeError("All LLM providers unavailable for task=generation")),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "首 token 前异常 → 兜底 token + error(kind=provider_error),异常细节不外泄",
        kinds == ["token", "error", "done"]
        and json.loads(evts[1]["data"])["kind"] == "provider_error"
        and "providers unavailable" not in resp_body(evts)
        and json.loads(evts[0]["data"])["content"] == SERVICE_UNAVAILABLE,
    )

    # Case 3 — 部分 token 后异常
    evts = await run_case(
        "3 部分 token 后流中断(error after partial tokens)",
        make_rag(
            [{"type": "token", "content": "请先检查电源与指示灯:"}],
            exc=TimeoutError("read timeout mid-stream"),
        ),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "部分内容保留 + error(kind=stream_interrupted),无重复兜底 token",
        kinds == ["token", "error", "done"]
        and json.loads(evts[0]["data"])["content"] == "请先检查电源与指示灯:"
        and json.loads(evts[1]["data"])["kind"] == "stream_interrupted",
    )

    # Case 4 — 正常成功(语义不变)
    evts = await run_case(
        "4 正常流式成功(normal success,语义须不变)",
        make_rag(
            [
                {"type": "sources", "sources": [{"url": "https://example.com/wiki"}]},
                {"type": "token", "content": "请检查"},
                {"type": "token", "content": " CEREG 配置。"},
                {
                    "type": "complete",
                    "answer": "请检查 CEREG 配置。",
                    "sources": [{"url": "https://example.com/wiki"}],
                    "is_answered": True,
                    "language": "zh-cn",
                    "response_time_ms": 12_500,
                },
            ]
        ),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "正常流 sources→token→done 无 error、无重复 done",
        kinds == ["sources", "token", "token", "done"]
        and json.loads(evts[3]["data"])["conversation_id"]
        == json.loads(evts[0]["data"])["conversation_id"],
    )

    # Case 5 — 有意拒答(证据不足)+ 预算熔断
    evts = await run_case(
        "5a 有意拒答:证据不足(insufficient-evidence refusal)",
        make_rag(
            [
                {
                    "type": "complete",
                    "answer": "暂未在官方资料中找到相关信息。",
                    "sources": [],
                    "is_answered": False,
                    "language": "zh-cn",
                    "response_time_ms": 3_400,
                }
            ]
        ),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "拒答文本作为 token 可见,不转 error/通用错误",
        kinds == ["token", "done"]
        and json.loads(evts[0]["data"])["content"] == "暂未在官方资料中找到相关信息。",
    )

    evts = await run_case(
        "5b 预算熔断(budget decline)",
        make_rag(),
        budget=BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0)),
    )
    kinds = [e["event"] for e in evts]
    all_ok &= check(
        "declined + done 既有形状不变",
        kinds == ["declined", "done"] and "reason" in json.loads(evts[0]["data"]),
    )

    print(f"\n{'=' * 72}\nEVIDENCE RESULT: {'ALL PASS' if all_ok else 'FAIL PRESENT'}\n{'=' * 72}")
    return 0 if all_ok else 1


def resp_body(evts: list[dict]) -> str:
    return json.dumps(evts, ensure_ascii=False)


if __name__ == "__main__":
    uuid.uuid4()  # 触发 uuid 模块初始化(与主流程一致)
    raise SystemExit(asyncio.run(main()))
