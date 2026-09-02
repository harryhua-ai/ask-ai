"""技术洞察证据包场景 seed 脚本(EVIDENCE-01..04)。

用法:指向隔离证据库(8024 后端连接 ask_ai_obs_evidence)运行:
    POSTGRES_DB=ask_ai_obs_evidence PYTHONPATH=. python scripts/evidence_seed_tech_insights.py <scenario>

scenario ∈ {high_anomaly_zero_failure, real_failures, healthy, no_data}
- 所有 trace 落在最近 24h(命中「近 7 天」默认视图);
- high_anomaly_zero_failure / healthy 额外落上一等长窗口数据,验证历史基线;
- no_data 清空全部 trace/conversation,验证零数据状态。
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from backend.config import load_settings
from backend.db.models import Conversation, Trace
from backend.db.session import get_engine, get_session_factory

FAST = {
    "intent": {"ms": 80, "category": "product", "reason": "能力咨询"},
    "rewrite": {"ms": 120, "extracted": "x", "rewritten": "x"},
    "retrieve": {"ms": 300, "hybrid_count": 20, "effective_min": 1,
                 "path_counts": {"hybrid": 18, "symbol": 1, "boost": 1}},
    "rerank": {"ms": 400, "top_score": 0.8, "count": 5, "pruned": 2},
    "generate": {"ms": 2600, "ttft_ms": 900, "tokens_output": 300},
    "output": {"ms": 0, "sources_count": 5},
}

QUESTION_POOL = [
    "NG4500 的算力规格是什么?",
    "如何接入 CamThink SDK?",
    "设备的保修政策是怎样的?",
    "NE301 支持哪些传感器?",
    "如何配置 WiFi 配网?",
    "设备的功耗是多少?",
]


async def seed(scenario: str) -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    factory = get_session_factory(engine)
    now = datetime.now(UTC)

    async with factory() as session:
        await session.execute(delete(Trace))
        await session.execute(delete(Conversation))
        await session.commit()

    if scenario == "no_data":
        print("evidence DB cleared (no_data scenario)")
        await engine.dispose()
        return

    async def add_trace(session, *, trace_type="rag", stages=None, total_ms=3500,
                        age_hours=5.0, failure_kind=None, answered=True):
        conv = Conversation(
            id=uuid.uuid4(),
            question=QUESTION_POOL[int(total_ms) % len(QUESTION_POOL)],
            channel="widget",
            is_answered=answered,
            response_time_ms=total_ms,
        )
        session.add(conv)
        snapshot = {"failure_kind": failure_kind} if failure_kind else {}
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=0,
                type=trace_type,
                stages=stages or {},
                total_ms=total_ms,
                intent="product",
                created_at=now - timedelta(hours=age_hours),
                config_snapshot=snapshot,
            )
        )

    async with factory() as session:
        if scenario == "high_anomaly_zero_failure":
            # 9/12 生成阶段超 NORMAL_MAX(30s)但全部成功;零失败 → degraded
            for i in range(9):
                slow = {**FAST, "generate": {"ms": 41000 + i * 900, "ttft_ms": 38000,
                                             "tokens_output": 300}}
                await add_trace(session, stages=slow, total_ms=43000 + i * 900,
                                age_hours=2 + i * 0.2)
            for i in range(3):
                await add_trace(session, stages=FAST, total_ms=3500, age_hours=3 + i)
            # 上一等长窗口有数据 → 历史基线成立
            for i in range(6):
                conv = Conversation(id=uuid.uuid4(), question="上周问题", channel="widget",
                                    is_answered=True)
                session.add(conv)
                session.add(Trace(
                    conversation_id=conv.id, turn_index=0, type="rag",
                    stages=FAST, total_ms=4000 + i * 200,
                    created_at=now - timedelta(days=8 + i * 0.2), config_snapshot={},
                ))
        elif scenario == "real_failures":
            # 3 条真实失败(provider_error/empty_generation/stream_interrupted)
            # + 2 条降级恢复(rerank fallback)+ 10 条正常 → critical
            kinds = ["provider_error", "empty_generation", "stream_interrupted"]
            for kind in kinds:
                await add_trace(
                    session,
                    trace_type="generation_error",
                    stages={"error": {"kind": kind}},
                    total_ms=5200,
                    age_hours=1.5,
                    failure_kind=kind,
                    answered=False,
                )
            for i in range(2):
                rec = {**FAST, "rerank": {"ms": 380, "fallback": True, "fallback_count": 8}}
                await add_trace(session, stages=rec, total_ms=3600, age_hours=4 + i)
            for i in range(10):
                await add_trace(session, stages=FAST, total_ms=3400 + i * 60, age_hours=2 + i * 0.3)
        elif scenario == "healthy":
            for i in range(12):
                await add_trace(session, stages=FAST, total_ms=3300 + i * 70, age_hours=1 + i * 0.4)
            for i in range(8):
                conv = Conversation(id=uuid.uuid4(), question="上周问题", channel="widget",
                                    is_answered=True)
                session.add(conv)
                session.add(Trace(
                    conversation_id=conv.id, turn_index=0, type="rag",
                    stages=FAST, total_ms=3900 + i * 100,
                    created_at=now - timedelta(days=8 + i * 0.2), config_snapshot={},
                ))
        else:
            raise SystemExit(f"unknown scenario: {scenario}")
        await session.commit()
    await engine.dispose()
    print(f"scenario seeded: {scenario}")


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1]))
