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

from backend.pipeline.citation import (
    PUBLIC_SOURCE_TYPES,
    CitationStreamFilter,
    build_citation_context,
    normalize_source_path,
    validate_citations,
)
from backend.pipeline.intent import classify_intent
from backend.pipeline.query_rewrite import extract_query, rewrite_query
from backend.retrieval.search import SearchResult
from backend.utils.language import detect_language

logger = logging.getLogger(__name__)

REJECT_ANSWER = "暂未在官方资料中找到相关信息。"
REJECT_OFF_TOPIC = "我只能回答与 CamThink 产品相关的问题。"
REJECT_BUSINESS = "关于商务合作或价格咨询,请联系我们的销售团队。"


class EmptyGenerationError(RuntimeError):
    """LLM 流正常结束但零可用生成内容。

    属异常完成而非成功:供应商可能返回 200 + 空 delta 流(或仅空白内容)。
    由 SSE 层捕获并降级为用户可见的失败状态,禁止以
    ``complete(answer="", is_answered=True)`` 伪装成功。
    """


# Per-intent boost 桶配置:与主 hybrid 结果 RRF 融合,让 intent 相关 source 获得加权。
# - support:故障案例/排查文档多 ingest 为 source_type="filesystem",提升其召回权重。
# - product:产品功能/参数文档多分布于正文 chunk(paragraph/heading/list/table)。
# - commercial:P1#5 接 WooCommerce 后启用 source_type="woocommerce"。
INTENT_BOOST_FILTERS: dict[str, dict] = {
    "support": {"source_types": ["filesystem"]},
    "product": {"chunk_types": ["paragraph", "heading", "list", "table"]},
    "commercial": {"source_types": ["woocommerce"]},
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
        intent: 命中的意图分类(``commercial`` / ``product`` / ``support`` /
            ``off_topic``),便于上层落库 / 分析。
    """

    answer: str
    sources: list[dict]
    is_answered: bool
    reranked_results: list[SearchResult]
    language: str
    response_time_ms: int
    intent: str = "product"
    trace_payload: dict | None = None


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
        recall_limit: int = 30,
        top_k: int = 10,
        conversation_max_turns: int = 5,
        pruner: Any = None,  # Phase 3 预留:Pruner Protocol
        min_results_to_answer: int = 3,
        channel_customizations: dict[str, str] | None = None,
        override_matcher: Any = None,  # Phase 3A: OverrideMatcher
        intent_styles: dict[str, str] | None = None,
        visibility_guard: Any = None,  # P0: 源可见性纵深守卫(PC-01)
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
            channel_customizations: 渠道到 system_prompt 的映射(Phase 2B)。
                渠道未命中时回退到 ``system_prompt``,确保 Phase 1 行为不变。
            override_matcher: 可选的人工答案覆盖匹配器(Phase 3A)。
                命中时跳过整个 RAG 管线直接返回覆盖答案。
            intent_styles: 意图到回答风格 prompt 片段的映射。在 channel base
                prompt 之后正交叠加(空字符串 / 缺省时不附加)。
            visibility_guard: 可选的源可见性纵深守卫(P0 PC-01)。提供
                ``async allows(source_id, channel) -> bool``;在候选进入
                rerank / LLM 上下文之前按源最新配置复核,拦截 chunk 元数据
                滞后/缺失导致的受限内容。守卫自身故障时 fail-open(主防线
                是 chunk 级 channel_visibility 检索过滤)。守卫异常时 fail-closed:丢弃全部
                候选,由拒答门兜底(授权失败不得变成授权旁路)。
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
        self._min_results = min_results_to_answer
        self._channel_customizations = channel_customizations or {}
        self._override_matcher = override_matcher
        self._intent_styles = intent_styles or {}
        self._visibility_guard = visibility_guard

    def _config_snapshot(self) -> dict[str, Any]:
        """当前编排器配置快照,写入 trace 供后续对照。"""
        return {
            "alpha": self._alpha,
            "recall_limit": self._recall_limit,
            "top_k": self._top_k,
            "min_results": self._min_results,
            "has_pruner": self._pruner is not None,
        }

    async def _retrieve_and_fuse(
        self,
        extracted: str,
        search_query: str,
        intent_category: str,
        *,
        product_filter: str | None,
        channel: str,
    ) -> tuple[list[SearchResult], dict[str, int]]:
        """统一检索 + 三路 RRF 融合(answer / stream_answer 共用,保证 parity)。

        主 hybrid(search_query) + 符号 BM25(extracted) + intent boost 桶(extracted)
        → 单次 rrf_fuse 三路融合。任一路异常 / 为空均降级,不中断主流程。

        Returns:
            (融合去重后的 SearchResult 列表, 各路命中数 dict)
        """
        results = self._searcher.search(
            query=search_query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
            channel=channel,
        )

        symbol_results: list[SearchResult] = []
        try:
            symbol_results = self._searcher.search_symbols(
                query=extracted,
                limit=self._recall_limit,
                product_filter=product_filter,
                channel=channel,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("符号召回失败,降级:%s", str(exc)[:200])

        bucket_results: list[SearchResult] = []
        bucket_cfg = INTENT_BOOST_FILTERS.get(intent_category)
        if bucket_cfg:
            try:
                # boost 桶跨产品(support 案例存为 product="knowledge"),不透传 product_filter
                bucket_results = self._searcher.search_bucket(
                    query=extracted,
                    limit=self._recall_limit,
                    channel=channel,
                    **bucket_cfg,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("boost 桶召回失败,降级:%s", str(exc)[:200])

        from backend.retrieval.rrf import rrf_fuse

        path_counts = {
            "hybrid": len(results),
            "symbol": len(symbol_results),
            "boost": len(bucket_results),
        }

        fused = results
        try:
            fused = rrf_fuse(results, symbol_results, bucket_results, k=60)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RRF 融合失败,降级 hybrid 单路:%s", str(exc)[:200])

        # P0 PC-01:生成前按源最新可见性配置复核(纵深守卫)。
        # 主防线 = 三路检索的 chunk 级 channel_visibility 过滤;守卫拦截
        # chunk 元数据滞后/缺失(迁移未跑完、幽灵 chunk)的残余泄漏。
        return await self._apply_visibility_guard(fused, channel), path_counts

    async def _apply_visibility_guard(
        self,
        results: list[SearchResult],
        channel: str,
    ) -> list[SearchResult]:
        """可见性纵深守卫:守卫缺失/故障一律放行,不阻塞检索链路。"""
        if self._visibility_guard is None:
            return results
        try:
            return [r for r in results if await self._visibility_guard.allows(r.source_id, channel)]
        except Exception as exc:  # noqa: BLE001
            # P0-rework Case C:授权子系统故障不得变成授权旁路 → fail-closed:
            # 丢弃全部候选(下游拒答门兜底)——可用性损失,而非安全损失。
            logger.error(
                "visibility guard 异常,fail-closed 丢弃全部 %d 候选:%s",
                len(results),
                str(exc)[:200],
            )
            return []

    @staticmethod
    def _rerank_snippets(
        results: list[SearchResult], top: int = 5, text_preview: int = 300
    ) -> list[dict]:
        """提取 top N reranked 结果摘要(写入 trace),含正文预览供审查比对。"""
        return [
            {
                "title": r.title,
                "score": round(r.score, 3) if r.score else None,
                "source_type": r.source_type,
                "product": r.product,
                "url": r.url,
                "text": r.text[:text_preview] if r.text else "",
            }
            for r in results[:top]
        ]

    def _build_messages(
        self,
        query: str,
        context: str,
        language: str,
        history: list[dict] | None,
        channel: str = "widget",
        intent: str = "product",
        log_text: str = "",
        image_context: str = "",
    ) -> list[dict]:
        """构造 OpenAI 风格的 messages 列表。

        结构:``system → (截断后的 history) → user``。
        history 截断到最近 ``conversation_max_turns * 2`` 条消息。

        system_prompt 由 channel(base)与 intent(风格)正交叠加:
        先取渠道专属 prompt(未命中回退默认),再附加意图风格片段(若有)。

        Args:
            channel: 渠道标识。当 ``channel_customizations`` 命中该渠道时,
                使用渠道专属 system_prompt;否则回退到默认 ``self._system_prompt``,
                确保 Phase 1 行为不变。
            intent: 意图分类。命中 ``intent_styles`` 时在 base prompt 之后附加
                对应风格片段;未命中 / 空串时不附加(零回归)。
        """
        base = self._channel_customizations.get(channel, self._system_prompt)
        style = self._intent_styles.get(intent, "")
        system_prompt = f"{base}\n\n{style}" if style else base
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if history:
            # 每轮对话 = 1 user + 1 assistant,故 max_turns * 2 为消息条数上限
            messages.extend(history[-self._max_turns * 2 :])
        # 附件段(条件拼接,空则不出现;Phase 1a 仅 log_text,image_context 1b)
        attachment_section = ""
        if log_text:
            attachment_section += f"\n\n## 用户上传的日志\n\n{log_text}"
        if image_context:
            attachment_section += f"\n\n## 用户上传的截图分析\n\n{image_context}"
        user_content = f"""请根据以下检索到的官方资料回答问题。

## 检索到的资料

{context}{attachment_section}

## 问题

{query}

## 要求
- 只依据上面的资料回答,不编造
- 引用标记 [N] 只能使用「可引用资料」的编号;「背景资料」仅供理解上下文,禁止引用
- 精确数值(价格/电压/电流/温度/尺寸/版本号/协议等)必须与所引资料原文一致;
  资料未载明时,明确说明"官方资料未载明该数值",严禁编造数值或以相近数值搭配 [N] 冒充有据
- 资料中的客户案例/历史工单仅是第三方历史参考,**不是当前用户的事实**;
  严禁把案例中的设备标识(如 ICCID/IMSI/序列号)、客户身份或案例结论说成
  当前用户的情况;需要引用案例时必须明确表述为"一个历史案例"
- 用 Markdown 格式,用 **粗体** 做小节标题
- 在每段末尾用 [N] 标注该段引用的资料序号,不在句中穿插
- 不要使用 emoji
- 不要输出文档路径
- 回答简洁,直答问题
- 用 {language} 回答
"""
        messages.append({"role": "user", "content": user_content})
        return messages

    def _extract_sources(self, results: list[SearchResult]) -> list[dict]:
        """从重排结果中提取来源元数据,按归一化路径去重 + 过滤内部源。

        同一文档的多个翻译版本(如 ``docs/`` 与 ``i18n/en/...``)只保留
        rerank 分数最高的那个,避免来源列表出现重复条目。

        **对外源白名单**:只返回 ``PUBLIC_SOURCE_TYPES`` 中的类型(github/woocommerce/
        官网等公开源)。filesystem(support 内部案例)虽参与检索与生成,但不作为
        对外展示的 source(避免内部客户工单路径外泄)。过滤不补足——若某问题召回
        的公开源不足 5 条,sources 列表就短,不强行用内部源填充。

        Args:
            results: 重排后的 SearchResult 列表(rerank 降序)。

        Returns:
            去重 + 过滤后的来源字典列表,字段:``url`` / ``title`` / ``type`` / ``product``。
        """
        seen: set[str] = set()
        sources: list[dict] = []
        for r in results:
            if r.source_type not in PUBLIC_SOURCE_TYPES:
                continue
            norm = normalize_source_path(r.url)
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
        stages: dict[str, Any] = {}

        # Phase 3A: 人工答案覆盖前置检查
        if self._override_matcher:
            override = await self._override_matcher.match(query)
            if override:
                elapsed = int((time.monotonic() - start) * 1000)
                return RAGAnswer(
                    answer=override.override_answer,
                    sources=override.override_sources or [],
                    is_answered=True,
                    reranked_results=[],
                    language=language,
                    response_time_ms=elapsed,
                    intent="product",
                    trace_payload={
                        "type": "rag",
                        "stages": stages,
                        "total_ms": elapsed,
                        "intent": "product",
                        "confidence": None,
                        "config_snapshot": self._config_snapshot(),
                    },
                )

        t_intent = time.monotonic()
        intent = await classify_intent(query, self._llm)
        stages["intent"] = {
            "ms": int((time.monotonic() - t_intent) * 1000),
            "category": intent.category,
            "reason": intent.reason,
        }
        if intent.category == "off_topic":
            elapsed = int((time.monotonic() - start) * 1000)
            return RAGAnswer(
                answer=REJECT_OFF_TOPIC,
                sources=[],
                is_answered=False,
                reranked_results=[],
                language=language,
                response_time_ms=elapsed,
                intent=intent.category,
                trace_payload={
                    "type": "reject_short",
                    "stages": stages,
                    "total_ms": elapsed,
                    "intent": intent.category,
                    "confidence": intent.confidence,
                    "config_snapshot": self._config_snapshot(),
                },
            )
        # commercial/product/support 进入 RAG 管线
        # (commercial 原「过渡期拒答」已废:WooCommerce 产品已灌库,走 woocommerce boost 桶作答)
        # product/commercial/support 降低检索阈值(能力咨询/购买咨询容忍少结果)
        effective_min = (
            1 if intent.category in ("product", "support", "commercial") else self._min_results
        )

        t_rewrite = time.monotonic()
        extracted = await extract_query(query, self._llm)
        search_query = await rewrite_query(extracted, conversation_history, self._llm)
        stages["rewrite"] = {
            "ms": int((time.monotonic() - t_rewrite) * 1000),
            "extracted": extracted,
            "rewritten": search_query,
        }

        # 统一检索 + 三路 RRF 融合(hybrid + symbol + intent boost 桶)
        t_ret = time.monotonic()
        fused, path_counts = await self._retrieve_and_fuse(
            extracted,
            search_query,
            intent.category,
            product_filter=product_filter,
            channel=channel,
        )
        stages["retrieve"] = {
            "ms": int((time.monotonic() - t_ret) * 1000),
            "hybrid_count": len(fused),
            "min_results_met": len(fused) >= effective_min,
            "effective_min": effective_min,
            "path_counts": path_counts,
        }

        t_rr = time.monotonic()
        reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
        pruned_count = 0
        pre_prune_count = len(reranked)

        if self._pruner:
            reranked = await self._pruner.prune(search_query, reranked)
            pruned_count = pre_prune_count - len(reranked)
        stages["rerank"] = {
            "ms": int((time.monotonic() - t_rr) * 1000),
            "top_score": reranked[0].score if reranked else None,
            "count": len(reranked),
            "pruned": pruned_count,
            "results": self._rerank_snippets(reranked),
        }

        if len(reranked) < effective_min:
            # P1 兜底:rerank 把候选全滤光(threshold 过高)但召回非空时,
            # 降级用 fused top-N 作上下文继续生成,而非直接拒答。
            # 场景:Q98(DeepInspect)/Q104(纺织检测)等场景术语召回命中,
            # 但 reranker 给分 < 0.3 被滤光。真无召回(fused 也空)才拒答。
            fallback = fused[: self._top_k] if fused else []
            if not fallback:
                elapsed = int((time.monotonic() - start) * 1000)
                return RAGAnswer(
                    answer=REJECT_ANSWER,
                    sources=[],
                    is_answered=False,
                    reranked_results=[],
                    language=language,
                    response_time_ms=elapsed,
                    intent=intent.category,
                    trace_payload={
                        "type": "reject_short",
                        "stages": stages,
                        "total_ms": elapsed,
                        "intent": intent.category,
                        "confidence": intent.confidence,
                        "config_snapshot": self._config_snapshot(),
                    },
                )
            # 降级:用 fused top-N 作上下文,标记 fallback 供 trace 追踪
            reranked = fallback
            stages["rerank"]["fallback"] = True
            stages["rerank"]["fallback_count"] = len(fallback)
            logger.info(
                "rerank 滤光但 fused 非空(%d),降级用 fused top-N",
                len(fallback),
            )

        sources = self._extract_sources(reranked)
        # 引用完整性:LLM 编号集 = 访客可见集合(权威编号上下文)
        cite_ctx = build_citation_context(reranked, sources)
        messages = self._build_messages(
            query,
            cite_ctx.context,
            language,
            conversation_history,
            channel,
            intent=intent.category,
        )

        t_gen = time.monotonic()
        llm_response = await self._llm.generate(messages, task="generation")
        stages["generate"] = {
            "ms": int((time.monotonic() - t_gen) * 1000),
            "latency_ms": getattr(llm_response, "latency_ms", None),
            "tokens_output": getattr(llm_response, "tokens_output", None),
        }
        # 引用终验(幂等):剔除悬空/无据标记,不改正文
        final_answer, cite_stats = validate_citations(
            llm_response.content, len(sources), cite_ctx.source_texts
        )
        stages["output"] = {"ms": 0, "sources_count": len(sources)}
        stages["citation_integrity"] = {**cite_ctx.stats, **cite_stats}

        elapsed = int((time.monotonic() - start) * 1000)
        return RAGAnswer(
            answer=final_answer,
            sources=sources,
            is_answered=True,
            reranked_results=reranked,
            language=language,
            response_time_ms=elapsed,
            intent=intent.category,
            trace_payload={
                "type": "rag",
                "stages": stages,
                "total_ms": elapsed,
                "intent": intent.category,
                "confidence": intent.confidence,
                "config_snapshot": self._config_snapshot(),
            },
        )

    async def stream_answer(
        self,
        query: str,
        channel: str = "widget",
        conversation_history: list[dict] | None = None,
        product_filter: str | None = None,
        attachments: list | None = None,
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

        # Phase 3A: 人工答案覆盖前置检查
        if self._override_matcher:
            override = await self._override_matcher.match(query)
            if override:
                sources = override.override_sources or []
                yield json.dumps({"type": "sources", "sources": sources})
                yield json.dumps({"type": "token", "content": override.override_answer})
                elapsed = int((time.monotonic() - start) * 1000)
                yield json.dumps(
                    {
                        "type": "complete",
                        "answer": override.override_answer,
                        "sources": sources,
                        "is_answered": True,
                        "language": language,
                        "response_time_ms": elapsed,
                        "intent": "product",
                        "trace_payload": {
                            "type": "override",
                            "stages": {},
                            "total_ms": elapsed,
                            "intent": "product",
                            "confidence": None,
                            "config_snapshot": self._config_snapshot(),
                        },
                    }
                )
                return

        # 意图识别(4 分类):off_topic 直接拒答;commercial/product/support 进入检索
        # (commercial 原「过渡期拒答」策略已废:WooCommerce 产品数据已灌库,commercial
        #  意图走 woocommerce boost 桶召回产品信息作答,不再拒答。intent.py 注释同步)
        # 评审 C1:有附件时跳过 off_topic 拒答——「分析这个日志」这类泛化
        # 日志排查语会被判 off_topic,但附件就是 context,必须放行。
        t_intent = time.monotonic()
        intent = await classify_intent(query, self._llm)
        intent_ms = int((time.monotonic() - t_intent) * 1000)
        if not attachments:
            if intent.category == "off_topic":
                elapsed = int((time.monotonic() - start) * 1000)
                yield json.dumps(
                    {
                        "type": "complete",
                        "answer": REJECT_OFF_TOPIC,
                        "sources": [],
                        "is_answered": False,
                        "language": language,
                        "response_time_ms": elapsed,
                        "intent": intent.category,
                        "trace_payload": {
                            "type": "reject_short",
                            "stages": {
                                "intent": {
                                    "ms": intent_ms,
                                    "category": intent.category,
                                    "reason": intent.reason,
                                }
                            },
                            "total_ms": elapsed,
                            "intent": intent.category,
                            "confidence": intent.confidence,
                            "config_snapshot": self._config_snapshot(),
                        },
                    }
                )
                return
        # 评审 C1 第二道门:有附件时 effective_min=0,即使检索为空也走生成(附件作 fallback)
        has_attachments = bool(attachments)
        if has_attachments:
            effective_min = 0
        else:
            effective_min = (
                1 if intent.category in ("product", "support", "commercial") else self._min_results
            )

        t0 = time.monotonic()
        extracted = await extract_query(query, self._llm)
        search_query = await rewrite_query(extracted, conversation_history, self._llm)
        rewrite_ms = int((time.monotonic() - t0) * 1000)

        # 统一检索 + 三路 RRF 融合(与 answer 共用 _retrieve_and_fuse,保证 parity)
        t1 = time.monotonic()
        fused, path_counts = await self._retrieve_and_fuse(
            extracted,
            search_query,
            intent.category,
            product_filter=product_filter,
            channel=channel,
        )
        search_ms = int((time.monotonic() - t1) * 1000)

        t2 = time.monotonic()
        reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
        rerank_ms = int((time.monotonic() - t2) * 1000)
        pre_prune_count = len(reranked)
        pruned_count = 0

        if self._pruner:
            reranked = await self._pruner.prune(query, reranked)
            pruned_count = pre_prune_count - len(reranked)

        if len(reranked) < effective_min:
            # P1 兜底:rerank 滤光但 fused 非空时降级用 fused top-N(与 answer 同策略)
            fallback = fused[: self._top_k] if fused else []
            if not fallback:
                elapsed = int((time.monotonic() - start) * 1000)
                yield json.dumps(
                    {
                        "type": "complete",
                        "answer": REJECT_ANSWER,
                        "sources": [],
                        "is_answered": False,
                        "language": language,
                        "response_time_ms": elapsed,
                        "intent": intent.category,
                        "trace_payload": {
                            "type": "reject_short",
                            "stages": {
                                "intent": {
                                    "ms": intent_ms,
                                    "category": intent.category,
                                    "reason": intent.reason,
                                },
                                "rewrite": {
                                    "ms": rewrite_ms,
                                    "extracted": extracted,
                                    "rewritten": search_query,
                                },
                                "retrieve": {
                                    "ms": search_ms,
                                    "hybrid_count": len(fused),
                                    "effective_min": effective_min,
                                    "path_counts": path_counts,
                                },
                                "rerank": {
                                    "ms": rerank_ms,
                                    "top_score": reranked[0].score if reranked else None,
                                    "count": len(reranked),
                                    "pruned": pruned_count,
                                    "results": self._rerank_snippets(reranked),
                                },
                            },
                            "total_ms": elapsed,
                            "intent": intent.category,
                            "confidence": intent.confidence,
                            "config_snapshot": self._config_snapshot(),
                        },
                    }
                )
                return
            # 降级:用 fused top-N 作上下文
            reranked = fallback
            rerank_fallback = True
            logger.info(
                "stream rerank 滤光但 fused 非空(%d),降级用 fused top-N",
                len(fallback),
            )
        else:
            rerank_fallback = False

        # 附件日志文本(Phase 1a:直接拼接,截断在 extract_log_text 入库时已做)
        log_text = ""
        attachment_summary: list[dict] = []
        if attachments:
            for att in attachments:
                kind = getattr(att, "kind", None)
                text = getattr(att, "extracted_text", None)
                if kind == "log" and text:
                    log_text += text + "\n---\n"
                attachment_summary.append(
                    {
                        "kind": kind or "unknown",
                        "text_length": len(text) if text else 0,
                        "text_preview": text[:200] if text else "",
                    }
                )
        sources = self._extract_sources(reranked)
        # 引用完整性:LLM 编号集 = 访客可见集合(权威编号上下文)
        cite_ctx = build_citation_context(reranked, sources)
        messages = self._build_messages(
            query,
            cite_ctx.context,
            language,
            conversation_history,
            channel,
            intent=intent.category,
            log_text=log_text,
            image_context="",
        )

        yield json.dumps({"type": "sources", "sources": sources})

        # 流式确定性校验:悬空/无据标记在下行前剔除(跨 token 拆分安全)
        citation_filter = CitationStreamFilter(
            n_sources=len(sources), source_texts=cite_ctx.source_texts
        )
        full_answer = ""
        t3 = time.monotonic()
        first_token_ms: int | None = None
        async for chunk in self._llm.stream(messages, task="generation"):
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - t3) * 1000)
            out = citation_filter.feed(chunk)
            if out:
                full_answer += out
                yield json.dumps({"type": "token", "content": out})
        out = citation_filter.finish()
        if out:
            full_answer += out
            yield json.dumps({"type": "token", "content": out})

        # PC-01:零可用内容(空流 / 仅空白 / 唯一内容是被剔除的悬空引用)
        # = 异常完成,禁止以 complete(is_answered=True) 伪装成功;抛给 SSE 层
        # 统一降级为用户可见失败(与首 token 前异常共用同一条降级通道)。
        if not full_answer.strip():
            logger.error(
                "LLM 流正常结束但零可用内容: query=%d chars, sources=%d, llm_ms=%d",
                len(query),
                len(sources),
                int((time.monotonic() - t3) * 1000),
            )
            raise EmptyGenerationError("LLM stream completed with empty content")

        # 幂等终验(防御纵深):正常情况下与流式校验结果一致
        final_answer, residual_stats = validate_citations(
            full_answer, len(sources), cite_ctx.source_texts
        )
        if residual_stats["dangling_dropped"] or residual_stats["unsupported_dropped"]:
            logger.warning(
                "终验发现流式校验残余剔除: %s",
                residual_stats,
            )

        llm_ms = int((time.monotonic() - t3) * 1000)
        elapsed = int((time.monotonic() - start) * 1000)

        logger.info(
            "RAG timing: rewrite=%dms search=%dms rerank=%dms ttft=%dms llm_total=%dms total=%dms "
            "(query=%d chars, answer=%d chars, sources=%d)",
            rewrite_ms,
            search_ms,
            rerank_ms,
            first_token_ms or 0,
            llm_ms,
            elapsed,
            len(query),
            len(full_answer),
            len(sources),
        )

        yield json.dumps(
            {
                "type": "complete",
                "answer": final_answer,
                "sources": sources,
                "is_answered": True,
                "language": language,
                "response_time_ms": elapsed,
                "intent": intent.category,
                "timing": {
                    "rewrite_ms": rewrite_ms,
                    "search_ms": search_ms,
                    "rerank_ms": rerank_ms,
                    "first_token_ms": first_token_ms,
                    "llm_ms": llm_ms,
                },
                "trace_payload": {
                    "type": "rag",
                    "stages": {
                        "intent": {
                            "ms": intent_ms,
                            "category": intent.category,
                            "reason": intent.reason,
                        },
                        "rewrite": {
                            "ms": rewrite_ms,
                            "extracted": extracted,
                            "rewritten": search_query,
                        },
                        "retrieve": {
                            "ms": search_ms,
                            "hybrid_count": len(fused),
                            "effective_min": effective_min,
                            "path_counts": path_counts,
                        },
                        "rerank": {
                            "ms": rerank_ms,
                            "top_score": reranked[0].score if reranked else None,
                            "count": len(reranked),
                            "pruned": pruned_count,
                            "results": self._rerank_snippets(reranked),
                        },
                        "generate": {
                            "ms": llm_ms,
                            "ttft_ms": first_token_ms,
                            "tokens_output": len(full_answer),
                        },
                        "output": {"ms": 0, "sources_count": len(sources)},
                        "citation_integrity": {
                            **cite_ctx.stats,
                            **citation_filter.stats,
                        },
                    },
                    "total_ms": elapsed,
                    "intent": intent.category,
                    "confidence": intent.confidence,
                    "config_snapshot": self._config_snapshot(),
                    "attachments": attachment_summary,
                },
            }
        )
