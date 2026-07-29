"""RAG 编排管道。

把前面已完成的组件串联成完整的 RAG 链路:

    query → HybridSearcher → RerankPipeline → (可选 Pruner)
         → 空结果拒答 → LLM 生成 → RAGAnswer

关键设计:
- ``RAGAnswer`` 为 ``frozen=True`` dataclass,包含答案文本、来源列表、
  是否成功回答、重排后的候选、语言、端到端延迟。
- 重排结果为空时直接返回固定的拒答话术(``REJECT_ANSWER``),
  ``is_answered=False``,不调用 LLM,节省成本。
- ``answer`` 为同步生成入口;``stream_answer`` 为流式生成入口,
  返回 ``AsyncIterator[str]``,事件序列:``sources → token(s) → complete``。
- searcher / reranker / llm 异常向上传播,由端点层(Task 16)统一处理。
- ``conversation_history`` 截断到最近 ``conversation_max_turns * 2`` 条
  消息(每轮 = 1 user + 1 assistant)。
- ``_extract_sources`` 按归一化路径去重(中英文翻译版只保留一条),最多 5 条。
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from backend.retrieval.search import SearchResult
from backend.utils.language import detect_language

logger = logging.getLogger(__name__)

REJECT_ANSWER = "暂未在官方资料中找到相关信息。"

SOURCE_LABELS = {
    "github": "[GitHub]",
    "wiki": "[Wiki]",
    "website": "[官网]",
    "blog": "[博客]",
    "filesystem": "[知识库]",
}


@dataclass(frozen=True)
class RAGAnswer:
    """RAG 管道同步生成的最终结果(不可变)。

    Attributes:
        answer: 答案文本(LLM 生成或拒答话术)。
        sources: 去重后的来源列表,每项为
            ``{"url", "title", "type", "product"}`` 字典。
        is_answered: 是否成功基于检索资料作答。``False`` 表示命中拒答。
        reranked_results: 重排(及可选裁剪)后的 ``SearchResult`` 列表,
            便于上层做引用渲染 / 调试。
        language: 检测到的用户查询语言代码(如 ``zh-cn`` / ``en``)。
        response_time_ms: 端到端处理耗时(毫秒)。
    """

    answer: str
    sources: list[dict]
    is_answered: bool
    reranked_results: list[SearchResult]
    language: str
    response_time_ms: int


_I18N_PREFIXES = (
    "/i18n/en/docusaurus-plugin-content-docs/current/",
    "/i18n/zh-CN/docusaurus-plugin-content-docs/current/",
)


def _normalize_source_path(url: str) -> str:
    """归一化来源 URL,使同一文档的翻译版本去重。

    去除 Docusaurus i18n 路径前缀,使 ``docs/foo.md`` 与
    ``i18n/en/.../foo.md`` 映射到同一 key。
    """
    for prefix in _I18N_PREFIXES:
        if prefix in url:
            return url.replace(prefix, "/docs/")
    return url


class RAGOrchestrator:
    """RAG 编排器:检索 → 重排 → (裁剪) → 拒答/生成。

    依赖的三个外部组件以 ``Any`` 接收以避免 Protocol 跨模块耦合,
    但各自必须满足以下契约:

    - **searcher**(实现 :class:`backend.retrieval.search.HybridSearcher` 接口):
      提供 ``search(query, alpha, limit, product_filter) -> list[SearchResult]``。
    - **reranker**(实现 :class:`backend.retrieval.rerank.RerankPipeline` 接口):
      提供 ``rerank(query, results, top_k) -> list[SearchResult]``。
    - **llm**(实现 :class:`backend.llm.base.LLMProvider` 协议或
      :class:`backend.llm.registry.LLMRouter`):
      提供 ``async generate(messages, task) -> LLMResponse`` 与
      ``async stream(messages, task) -> AsyncIterator[str]``。
    - **pruner**(可选,Phase 3 预留):提供 ``prune(query, results) -> list[SearchResult]``。
    """

    def __init__(
        self,
        searcher: Any,
        reranker: Any,
        llm: Any,
        system_prompt: str,
        alpha: float = 0.5,
        recall_limit: int = 50,
        top_k: int = 10,
        conversation_max_turns: int = 5,
        pruner: Any = None,  # Phase 3 预留:Pruner Protocol
    ) -> None:
        """初始化 RAG 编排器。

        Args:
            searcher: HybridSearcher 实例(或等价 Protocol)。
            reranker: RerankPipeline 实例(或等价 Protocol)。
            llm: LLMRouter / LLMProvider 实例(或等价 Protocol)。
            system_prompt: 系统提示词,拼到 messages 最前。
            alpha: dense vs sparse 权重,透传给 searcher。
            recall_limit: 召回阶段的结果上限,透传给 searcher。
            top_k: 重排截断上限,透传给 reranker。
            conversation_max_turns: 对话历史保留的最大轮数
                (每轮 = 1 user + 1 assistant 消息)。
            pruner: 可选的结果裁剪器(Phase 3)。
        """
        self._searcher = searcher
        self._reranker = reranker
        self._llm = llm
        self._system_prompt = system_prompt
        self._alpha = alpha
        self._recall_limit = recall_limit
        self._top_k = top_k
        self._max_turns = conversation_max_turns
        self._pruner = pruner

    def _build_context(self, results: list[SearchResult]) -> str:
        """把重排后的候选拼接成 LLM 上下文文本。

        Args:
            results: 重排后的 SearchResult 列表。

        Returns:
            Markdown 格式的上下文字符串,每条结果包含序号、来源标签、
            标题、URL 与正文。
        """
        parts = []
        for i, r in enumerate(results, 1):
            label = SOURCE_LABELS.get(r.source_type, f"[{r.source_type}]")
            parts.append(f"[{i}] {label} {r.title}\nURL: {r.url}\n\n{r.text}")
        return "\n\n---\n\n".join(parts)

    def _build_messages(
        self,
        query: str,
        context: str,
        language: str,
        history: list[dict] | None,
    ) -> list[dict]:
        """构造 OpenAI 风格的 messages 列表。

        结构:``system → (截断后的 history) → user``。
        history 截断到最近 ``conversation_max_turns * 2`` 条消息。
        """
        messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        if history:
            # 每轮对话 = 1 user + 1 assistant,故 max_turns * 2 为消息条数上限
            messages.extend(history[-self._max_turns * 2 :])
        user_content = f"""请根据以下检索到的官方资料回答问题。

## 检索到的资料

{context}

## 问题

{query}

## 要求
- 只依据上面的资料回答,不编造
- 用 Markdown 格式
- 来源引用用内联格式,如:[Wiki] NE503 技术规格
- 用 {language} 回答
"""
        messages.append({"role": "user", "content": user_content})
        return messages

    def _extract_sources(self, results: list[SearchResult]) -> list[dict]:
        """从重排结果中提取来源元数据,按归一化路径去重。

        同一文档的多个翻译版本(如 ``docs/`` 与 ``i18n/en/...``)只保留
        rerank 分数最高的那个,避免来源列表出现重复条目。

        Args:
            results: 重排后的 SearchResult 列表(rerank 降序)。

        Returns:
            去重后的来源字典列表,字段:``url`` / ``title`` / ``type`` / ``product``。
        """
        seen: set[str] = set()
        sources: list[dict] = []
        for r in results:
            norm = _normalize_source_path(r.url)
            if norm in seen:
                continue
            seen.add(norm)
            sources.append(
                {
                    "url": r.url,
                    "title": r.title,
                    "type": r.source_type,
                    "product": r.product,
                }
            )
        return sources[:5]

    async def answer(
        self,
        query: str,
        channel: str = "widget",
        conversation_history: list[dict] | None = None,
        product_filter: str | None = None,
    ) -> RAGAnswer:
        """同步生成 RAG 答案。

        流程:
            1. 语言检测。
            2. searcher.search 召回。
            3. reranker.rerank 精排。
            4. (可选)pruner 裁剪。
            5. 结果为空 → 返回拒答(``is_answered=False``),不调 LLM。
            6. 拼 context + messages → llm.generate。
            7. 提取去重 sources,返回 RAGAnswer。

        Args:
            query: 用户查询文本。
            channel: 渠道标识(如 ``widget`` / ``api``),预留供路由 / 限流使用。
            conversation_history: OpenAI 风格的历史消息列表(可选)。
            product_filter: 产品过滤条件,透传给 searcher。

        Returns:
            :class:`RAGAnswer`。

        Raises:
            Exception: searcher / llm 异常向上传播(由端点层处理)。
        """
        start = time.monotonic()
        language = detect_language(query)

        results = self._searcher.search(
            query=query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
        )

        reranked = self._reranker.rerank(query, results, top_k=self._top_k)

        if self._pruner:
            reranked = self._pruner.prune(query, reranked)

        if not reranked:
            elapsed = int((time.monotonic() - start) * 1000)
            return RAGAnswer(
                answer=REJECT_ANSWER,
                sources=[],
                is_answered=False,
                reranked_results=[],
                language=language,
                response_time_ms=elapsed,
            )

        context = self._build_context(reranked)
        messages = self._build_messages(query, context, language, conversation_history)

        llm_response = await self._llm.generate(messages, task="generation")
        sources = self._extract_sources(reranked)
        elapsed = int((time.monotonic() - start) * 1000)

        return RAGAnswer(
            answer=llm_response.content,
            sources=sources,
            is_answered=True,
            reranked_results=reranked,
            language=language,
            response_time_ms=elapsed,
        )

    async def stream_answer(
        self,
        query: str,
        channel: str = "widget",
        conversation_history: list[dict] | None = None,
        product_filter: str | None = None,
    ) -> AsyncIterator[str]:
        """流式生成 RAG 答案,Yield JSON 字符串事件。

        事件序列:
            - 命中拒答:仅 yield 一个 ``complete`` 事件(``is_answered=False``)。
            - 正常回答:``sources`` → 一个或多个 ``token`` → ``complete``。

        每个事件均为 ``json.dumps(...)`` 生成的字符串,便于上层直接作为
        SSE ``data:`` 字段发送。

        Args:
            query: 用户查询文本。
            channel: 渠道标识。
            conversation_history: OpenAI 风格的历史消息列表(可选)。
            product_filter: 产品过滤条件,透传给 searcher。

        Yields:
            str: 序列化后的 JSON 事件。

        Raises:
            Exception: searcher / llm 异常向上传播。
        """
        start = time.monotonic()
        language = detect_language(query)

        results = self._searcher.search(
            query=query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
        )

        reranked = self._reranker.rerank(query, results, top_k=self._top_k)

        if self._pruner:
            reranked = self._pruner.prune(query, reranked)

        if not reranked:
            elapsed = int((time.monotonic() - start) * 1000)
            yield json.dumps(
                {
                    "type": "complete",
                    "answer": REJECT_ANSWER,
                    "sources": [],
                    "is_answered": False,
                    "language": language,
                    "response_time_ms": elapsed,
                }
            )
            return

        context = self._build_context(reranked)
        messages = self._build_messages(query, context, language, conversation_history)
        sources = self._extract_sources(reranked)

        yield json.dumps({"type": "sources", "sources": sources})

        full_answer = ""
        async for chunk in self._llm.stream(messages, task="generation"):
            full_answer += chunk
            yield json.dumps({"type": "token", "content": chunk})

        elapsed = int((time.monotonic() - start) * 1000)
        yield json.dumps(
            {
                "type": "complete",
                "answer": full_answer,
                "sources": sources,
                "is_answered": True,
                "language": language,
                "response_time_ms": elapsed,
            }
        )
