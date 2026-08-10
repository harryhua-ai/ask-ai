"""业务信号 LLM 提取 pipeline。

取近 N 天 commercial+product intent 的 conversation,批量喂 LLM,
prompt 要求输出 JSON: [{"type":"scene|requirement","label":"...","count":N,"conv_ids":[...]}]。
聚合同 label 计数 + 占比,返回 dict 列表供 runner 落 BusinessSignal 表。
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_SCENE_PROMPT = """你是 CamThink 业务分析师。请分析以下用户对话,提取用户提到的**应用场景**分类。

要求:
- 只输出 JSON 数组,不要其他文字
- 每项格式: {{"type":"scene","label":"场景名称","count":出现次数,"conv_ids":["对话ID列表"]}}
- 场景如:工业视觉、安防监控、智慧城市、智能制造、教育、零售等
- 合并同义词(如"工业检测"和"工业视觉"合并)
- 按出现次数降序排列

## 对话列表

{conversations}
"""

_REQUIREMENT_PROMPT = """你是 CamThink 产品分析师。请分析以下用户对话,提取用户提到的**产品需求/功能期望**。

要求:
- 只输出 JSON 数组,不要其他文字
- 每项格式: {{"type":"requirement","label":"需求名称","count":出现次数,"conv_ids":["对话ID列表"]}}
- 需求如:4K 录制、开放 API、低功耗、边缘计算、AI 推理、多路视频等
- 合并同义词
- 按出现次数降序排列

## 对话列表

{conversations}
"""


def _format_conversations(conversations: list[Any]) -> str:
    """把对话列表格式化为 LLM prompt 文本。"""
    lines = []
    for conv in conversations:
        conv_id = str(conv.id) if hasattr(conv, "id") else "?"
        lines.append(f"[{conv_id}] Q: {conv.question} | A: {conv.answer or ''}")
    return "\n".join(lines)


async def extract_business_signals(
    llm: Any,
    conversations: list[Any],
    period_days: int = 7,
) -> list[dict[str, Any]]:
    """从对话列表提取业务信号(场景应用 + 产品需求)。

    Args:
        llm: LLM provider 实例(需实现 async generate(messages, task) -> LLMResponse)。
        conversations: Conversation 列表(需有 id/question/answer/intent_tag)。
        period_days: 统计周期天数(用于计算占比)。

    Returns:
        信号 dict 列表,字段:type/label/count/pct/sample_conversation_ids/period_start/period_end。
    """
    if not conversations:
        return []

    total = len(conversations)
    conv_text = _format_conversations(conversations)
    now = datetime.now(UTC)
    period_start = now - timedelta(days=period_days)

    results: list[dict[str, Any]] = []

    for signal_type, prompt_template in (
        ("scene", _SCENE_PROMPT),
        ("requirement", _REQUIREMENT_PROMPT),
    ):
        prompt = prompt_template.format(conversations=conv_text)
        messages = [{"role": "user", "content": prompt}]
        try:
            resp = await llm.generate(messages, task=signal_type)
            items = json.loads(resp.content)
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            logger.warning("业务信号提取失败(type=%s):%s", signal_type, str(exc)[:200])
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            label = item.get("label", "").strip()
            if not label:
                continue
            count = int(item.get("count", 0))
            conv_ids = item.get("conv_ids", [])
            results.append(
                {
                    "type": signal_type,
                    "label": label,
                    "count": count,
                    "pct": round(count / total, 4) if total else 0.0,
                    "sample_conversation_ids": conv_ids[:10],
                    "period_start": period_start.isoformat(),
                    "period_end": now.isoformat(),
                }
            )

    return results
