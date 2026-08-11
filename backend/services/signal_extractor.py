"""业务信号提取服务。

扫描已回答对话,用 LLM 提取场景应用与产品需求标签,聚合后写入 BusinessSignal 表。
手动触发(admin API),不进 cron。
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import BusinessSignal, Conversation
from backend.llm.registry import LLMRouter

logger = logging.getLogger(__name__)

MAX_CONVERSATIONS = 200
BATCH_SIZE = 50

SCENE_PROMPT = """你是一个产品分析师。请分析以下用户问题,提取最常见的场景应用和产品需求。

场景应用(scenes):用户在什么使用场景下提出这些问题(如"售前咨询""技术选型""故障排查")。
产品需求(requirements):用户希望产品具备什么功能或信息(如"价格透明""API 文档""兼容性说明")。

只返回 JSON,不要额外解释:
{"scenes": [{"label": "简短标签(≤10字)", "count": 出现次数}], "requirements": [{"label": "简短标签(≤10字)", "count": 出现次数}]}

用户问题:
"""


class SignalExtractor:
    """LLM 驱动的业务信号提取。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_router: LLMRouter,
    ) -> None:
        self._factory = session_factory
        self._llm = llm_router

    async def extract(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        """提取场景/需求信号并写入 BusinessSignal 表。

        Returns:
            {"scene_count": N, "requirement_count": M, "conversations_analyzed": K}
        """
        end = date_to or datetime.now(UTC)
        start = date_from or (end - timedelta(days=30))

        conversations = await self._fetch_conversations(start, end)
        if len(conversations) < 5:
            logger.info("SignalExtractor: 对话不足 5 条,跳过提取")
            return {
                "scene_count": 0,
                "requirement_count": 0,
                "conversations_analyzed": len(conversations),
            }

        all_scenes: dict[str, int] = {}
        all_requirements: dict[str, int] = {}

        for i in range(0, len(conversations), BATCH_SIZE):
            batch = conversations[i : i + BATCH_SIZE]
            try:
                scenes, requirements = await self._extract_batch(batch)
                for label, count in scenes.items():
                    all_scenes[label] = all_scenes.get(label, 0) + count
                for label, count in requirements.items():
                    all_requirements[label] = all_requirements.get(label, 0) + count
            except Exception:
                logger.exception("SignalExtractor: batch %d-%d 提取失败", i, i + len(batch))

        total = len(conversations)
        scene_signals = self._to_signals(all_scenes, total, "scene", start, end)
        req_signals = self._to_signals(all_requirements, total, "requirement", start, end)

        await self._persist(scene_signals + req_signals, start, end)

        logger.info(
            "SignalExtractor: 分析 %d 对话,提取 %d 场景 + %d 需求",
            total,
            len(scene_signals),
            len(req_signals),
        )
        return {
            "scene_count": len(scene_signals),
            "requirement_count": len(req_signals),
            "conversations_analyzed": total,
        }

    async def _fetch_conversations(self, start: datetime, end: datetime) -> list[str]:
        """获取时间范围内的已回答对话问题。"""
        async with self._factory() as session:
            q = (
                select(Conversation.question)
                .where(
                    Conversation.created_at >= start,
                    Conversation.created_at <= end,
                    Conversation.is_answered.is_(True),
                )
                .order_by(Conversation.created_at.desc())
                .limit(MAX_CONVERSATIONS)
            )
            rows = (await session.execute(q)).all()
            return [row[0] for row in rows]

    async def _extract_batch(self, questions: list[str]) -> tuple[dict[str, int], dict[str, int]]:
        """用 LLM 从一批问题中提取场景和需求。"""
        numbered = "\n".join(f"{i+1}. {q[:200]}" for i, q in enumerate(questions))
        messages = [
            {"role": "system", "content": "你是产品分析助手,只返回 JSON。"},
            {"role": "user", "content": SCENE_PROMPT + numbered},
        ]
        resp = await self._llm.generate(messages, task="generation")
        parsed = json.loads(resp.content)

        scenes: dict[str, int] = {}
        for item in parsed.get("scenes", []):
            label = item.get("label", "").strip()
            if label:
                scenes[label] = scenes.get(label, 0) + item.get("count", 1)

        requirements: dict[str, int] = {}
        for item in parsed.get("requirements", []):
            label = item.get("label", "").strip()
            if label:
                requirements[label] = requirements.get(label, 0) + item.get("count", 1)

        return scenes, requirements

    @staticmethod
    def _to_signals(
        counts: dict[str, int],
        total: int,
        sig_type: str,
        start: datetime,
        end: datetime,
    ) -> list[BusinessSignal]:
        """将计数字典转为 BusinessSignal 对象列表(取 top 10)。"""
        sorted_items = sorted(counts.items(), key=lambda x: -x[1])[:10]
        return [
            BusinessSignal(
                type=sig_type,
                label=label,
                count=count,
                pct=round(count / total * 100, 1) if total else 0.0,
                sample_conversation_ids=[],
                period_start=start,
                period_end=end,
            )
            for label, count in sorted_items
        ]

    async def _persist(self, signals: list[BusinessSignal], start: datetime, end: datetime) -> None:
        """写入 BusinessSignal 表(先清除当前时间段的旧数据)。"""
        async with self._factory() as session:
            await session.execute(
                delete(BusinessSignal).where(
                    BusinessSignal.period_start >= start,
                    BusinessSignal.period_end <= end,
                )
            )
            for sig in signals:
                session.add(sig)
            await session.commit()
