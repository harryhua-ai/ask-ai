"""查询改写模块。

当用户在多轮对话中追问时,原始查询可能缺少上下文(如 "the product is NE301")。
本模块用 LLM 将追问 + 对话历史改写为自包含的独立查询,提升检索质量。

设计:
- 仅在有对话历史时触发(首轮问题直接透传)
- 使用轻量 LLM 调用,短 prompt,要求仅输出改写后的查询
- 改写失败时安全回退到原始查询,不阻塞主管道
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REWRITE_PROMPT = """你是查询改写助手。

用户在多轮对话中提出了一个新问题。请结合对话历史,把这个问题改写为一个自包含的独立查询——即使没有上下文也能理解。

规则:
- 只输出改写后的查询,不要解释,不要引号
- 保留用户原始意图,不要添加无关信息
- 如果问题已经自包含,原样返回
- 用与用户相同的语言输出

## 对话历史(最近 3 轮)

{history}

## 当前问题

{query}

## 改写后的查询(仅输出查询本身)
"""


async def rewrite_query(
    query: str,
    history: list[dict] | None,
    llm: Any,
) -> str:
    """有对话历史时,用 LLM 改写查询使其自包含。

    Args:
        query: 用户当前查询文本。
        history: OpenAI 风格的历史消息列表(可为 None 或空)。
        llm: LLMProvider / LLMRouter 实例。

    Returns:
        改写后的查询字符串。改写失败时回退到原始 query。
    """
    if not history or len(history) < 2:
        return query

    try:
        recent = history[-6:]
        lines = []
        for m in recent:
            role = "用户" if m.get("role") == "user" else "助手"
            content = m.get("content", "")
            if isinstance(content, str):
                lines.append(f"{role}: {content[:300]}")
        history_text = "\n".join(lines)

        prompt = _REWRITE_PROMPT.format(history=history_text, query=query)
        response = await llm.generate(
            [{"role": "user", "content": prompt}],
            task="query_rewrite",
        )
        rewritten = response.content.strip().strip('"').strip("'")
        if rewritten and rewritten != query:
            logger.info("查询改写: %r → %r", query, rewritten)
            return rewritten
        return query
    except Exception:  # noqa: BLE001
        logger.warning("查询改写失败,回退原始查询", exc_info=True)
        return query


_EXTRACT_PROMPT = """你是查询提取助手。

请从用户的输入中提取出最核心的搜索问题——一个简洁的、能直接用于知识库检索的查询。

规则:
- 只输出一个问题,不要解释,不要引号
- 保留核心技术意图(产品型号、错误信息、功能需求)
- 去除寒暄、签名、重复上下文
- 如果输入已经足够简洁明确,原样返回
- 用与用户相同的语言输出

## 用户输入

{query}

## 核心搜索问题(仅输出问题本身)
"""


async def extract_query(query: str, llm: Any) -> str:
    """用 LLM 从用户输入中提取核心搜索问题。

    所有长度的查询都会经过此处理。对于已经简洁明确的短查询,
    LLM 会原样返回;对于包含噪音的长文本(邮件、bug 报告等),
    LLM 会提取核心搜索意图,提升检索质量。

    Args:
        query: 用户查询文本。
        llm: LLMProvider / LLMRouter 实例。

    Returns:
        提取后的核心搜索问题。提取失败时回退到原始 query。
    """
    try:
        prompt = _EXTRACT_PROMPT.format(query=query)
        response = await llm.generate(
            [{"role": "user", "content": prompt}],
            task="query_rewrite",
        )
        extracted = response.content.strip().strip('"').strip("'")
        if extracted:
            logger.info("查询提取: %r → %r", query, extracted)
            return extracted
        return query
    except Exception:  # noqa: BLE001
        logger.warning("查询提取失败,回退原始查询", exc_info=True)
        return query
