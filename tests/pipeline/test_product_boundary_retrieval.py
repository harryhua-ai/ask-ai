"""Retrieval / Generation 产品边界(Issue #5 契约 §5/§6/§8)编排器级测试。

- 目标产品已明确 → 三路检索均带资格标签(sibling 检索级排除);
- rerank 滤光兜底(fused top-N)不 reintroduce sibling(闸门在 Weaviate 侧);
- 防御性二次过滤:检索闸门被绕过时(模拟过滤缺陷)上下文仍无 sibling;
- 证据不足 → PRODUCT_EVIDENCE_INSUFFICIENT(不借 sibling 顶替);
- 歧义 → PRODUCT_AMBIGUOUS 文本澄清;显式 hint 不可解析 → PRODUCT_NOT_SUPPORTED;
- 生成上下文携带逐证据产品归属 + 产品边界冻结规则;
- 未启用边界(none mode)行为与基线逐字节兼容。
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.product_taxonomy import get_taxonomy
from backend.retrieval.search import SearchResult

# --------------------------------------------------------------------------- #
# 测试语料与替身
# --------------------------------------------------------------------------- #


def _sr(
    *,
    product: str,
    text: str,
    source_id: str = "src",
    source_type: str = "github",
    url: str = "https://example.com/doc",
) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title="T",
        url=url,
        score=0.9,
        chunk_index=0,
    )


NE503_DOC = _sr(
    product="ne503",
    text="NE503 固件升级步骤:进入系统设置,选择固件升级,导入升级包。",
    source_id="wiki-ne503",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/1-quick-start.md",
)
NE301_DOC = _sr(
    product="ne301",
    text="NE301 固件升级步骤:长按复位键 10 秒后通过 SD 卡导入固件。",
    source_id="wiki-ne301",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/5-neoeyes-ne301-series/1-quick-start.md",
)
SHARED_DOC = _sr(
    product="hardware-common",
    text="共享硬件说明:设备均支持 Type-C 供电与 PoE 802.3af。",
    source_id="wiki-hw-common",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/3-hardware-dev-resources/1-typec.md",
)
LEGACY_DOC = _sr(
    product="meta-hailo-os",
    text="meta-hailo-os 烧录步骤:使用 balenaEtcher 写入 SD 卡。",
    source_id="meta-hailo-os-local",
    url="https://github.com/camthink-ai/meta-hailo-os/blob/main/README.md",
)
WIKI_LABEL_DOC = _sr(
    product="wiki",
    text="迁移前 wiki 标签的 NE503 文档内容。",
    source_id="wiki-documents-local/main/docs/6-neoeyes-ne503-series/x.md",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/x.md",
)


class FaithfulSearcher:
    """忠实模拟 Weaviate 行为:product_labels 作为硬过滤(闸门语义)。"""

    def __init__(self, corpus: list[SearchResult]) -> None:
        self.corpus = corpus
        self.calls: list[dict] = []

    def _filter(self, product_labels):
        if product_labels is None:
            return list(self.corpus)
        allowed = set(product_labels)
        return [c for c in self.corpus if c.product in allowed]

    def search(self, *, query, alpha=0.5, limit=50, product_filter=None, channel=None, product_labels=None):
        self.calls.append({"path": "search", "product_labels": product_labels})
        return self._filter(product_labels)

    def search_symbols(self, *, query, limit=30, product_filter=None, channel="widget", product_labels=None):
        self.calls.append({"path": "search_symbols", "product_labels": product_labels})
        return []

    def search_bucket(self, *, query, limit=30, channel=None, product_filter=None, product_labels=None, **bucket):
        self.calls.append({"path": "search_bucket", "product_labels": product_labels, "bucket": bucket})
        return []


class LeakySearcher(FaithfulSearcher):
    """模拟检索闸门缺陷:忽略 product_labels 返回全量(供防御过滤验证)。"""

    def _filter(self, product_labels):
        return list(self.corpus)


class ScriptedLLM:
    """确定性 LLM 替身:intent/extract/rewrite 脚本化,generation 输出固定答案。"""

    def __init__(self, intent: str = "product", answer: str = "这是答案。") -> None:
        self.intent = intent
        self.answer = answer
        self.generate_calls: list[dict] = []
        self.last_messages = None

    async def generate(self, messages, task=None, **kwargs):
        self.generate_calls.append({"task": task})
        content = str(messages[-1].get("content", ""))
        if task == "intent":
            payload = json.dumps(
                {"category": self.intent, "reason": "test", "confidence": 0.99}
            )
            return LLMResponse(content=payload, model="t", tokens_input=1, tokens_output=1, latency_ms=1)
        if task in ("query_rewrite", "lead_qualification"):
            return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)
        return LLMResponse(content=self.answer, model="t", tokens_input=1, tokens_output=1, latency_ms=1)

    def stream(self, messages, task=None, **kwargs):
        self.last_messages = messages

        async def _gen():
            yield self.answer

        return _gen()


def _build(corpus, *, llm=None, searcher=None):
    searcher = searcher if searcher is not None else FaithfulSearcher(corpus)
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda query, results, top_k=None: list(results)
    llm = llm if llm is not None else ScriptedLLM()
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base prompt",
        min_results_to_answer=1,
    )
    return rag, searcher, llm


async def _collect(rag, query, **kwargs):
    events = []
    async for chunk in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(chunk))
    return events


def _complete(events):
    completes = [e for e in events if e["type"] == "complete"]
    assert len(completes) == 1
    return completes[0]


TAX = get_taxonomy()


# --------------------------------------------------------------------------- #
# 检索闸门
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_exact_scope_passes_eligible_labels_to_all_paths():
    rag, searcher, _ = _build([NE503_DOC])
    await _collect(rag, "NE503 怎么升级固件?")
    paths = {c["path"]: c["product_labels"] for c in searcher.calls}
    expected = TAX.eligible_labels(("ne503",))
    assert set(paths) == {"search", "search_symbols", "search_bucket"}
    for path, labels in paths.items():
        if path == "search_bucket":
            # product intent 的 bucket 是 chunk_type 桶,同样必须带资格标签
            assert labels == expected
        else:
            assert labels == expected
    assert "ne301" not in set(expected)


@pytest.mark.unit
async def test_support_intent_bucket_cannot_bypass_boundary():
    """G:support intent 的 knowledge 桶同样携带资格标签,不得成为跨产品后门。"""
    llm = ScriptedLLM(intent="support")
    rag, searcher, _ = _build([NE503_DOC], llm=llm)
    await _collect(rag, "NE503 无法开机怎么办")
    bucket_call = next(c for c in searcher.calls if c["path"] == "search_bucket")
    assert bucket_call["product_labels"] == TAX.eligible_labels(("ne503",))


@pytest.mark.unit
async def test_page_context_establishes_scoped_retrieval():
    """D:宿主页面确立 NE503 → 检索收窄到 ne503 资格集。"""
    rag, searcher, _ = _build([NE503_DOC])
    await _collect(rag, "怎么升级固件", page_context={"product": "NE503"})
    assert searcher.calls[0]["product_labels"] == TAX.eligible_labels(("ne503",))


@pytest.mark.unit
async def test_explicit_product_hint_scopes_retrieval():
    rag, searcher, _ = _build([NE503_DOC])
    await _collect(rag, "怎么升级固件", product_hint="ne503")
    assert searcher.calls[0]["product_labels"] == TAX.eligible_labels(("ne503",))


@pytest.mark.unit
async def test_legacy_labels_eligible_pre_migration():
    """迁移前:历史标签(meta-hailo-os)经资格展开仍可命中(不过度拒答)。"""
    rag, _, llm = _build([LEGACY_DOC])
    events = await _collect(rag, "NE503 怎么烧录系统?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user_content = llm.last_messages[-1]["content"]
    assert "balenaEtcher" in user_content  # 历史标签证据进入了生成上下文


@pytest.mark.unit
async def test_premigration_wiki_label_excluded_over_refusal_not_contamination():
    """迁移前 wiki 混合标签不入 ne503 资格集 → 拒答而非 sibling 冒充(诚实过拒)。"""
    rag, _, _ = _build([WIKI_LABEL_DOC])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_evidence_insufficient"


# --------------------------------------------------------------------------- #
# 兜底与防御过滤
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rerank_wipe_fallback_stays_eligible():
    """rerank 滤光 → fused top-N 兜底;fused 已过闸门,sibling 不会回流。"""
    corpus = [NE503_DOC, NE301_DOC]
    rag, _, llm = _build(corpus)
    rag._reranker.rerank.side_effect = lambda query, results, top_k=None: []  # 全滤光
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user_content = llm.last_messages[-1]["content"]
    assert "NE301" not in user_content or "产品: NeoEye NE301" not in user_content
    assert "NE503 固件升级步骤" in user_content


@pytest.mark.unit
async def test_defensive_filter_drops_leaked_sibling():
    """检索闸门被绕过(缺陷注入)→ 防御性过滤仍把 sibling 挡在上下文外。"""
    rag, _, llm = _build([NE503_DOC, NE301_DOC], searcher=LeakySearcher([NE503_DOC, NE301_DOC]))
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user_content = llm.last_messages[-1]["content"]
    assert "SD 卡导入固件" not in user_content  # NE301 步骤不得入上下文
    assert complete["trace_payload"]["stages"]["product_scope"]["ineligible_filtered"] == 1


# --------------------------------------------------------------------------- #
# 结构化不足/歧义/不支持语义
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scoped_zero_results_is_product_insufficient():
    """E:exact 证据缺失 + sibling 在库 → 不足语义,绝不 sibling 顶替。"""
    rag, _, _ = _build([NE301_DOC])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_evidence_insufficient"
    assert "NeoEye NE503" in complete["answer"]
    json_text = json.dumps(events)
    assert "NE301" not in json_text or "NE301 固件升级" not in json_text


@pytest.mark.unit
async def test_ambiguous_query_yields_clarify_without_retrieval():
    """C:指代 + 无上下文 → 文本澄清;零检索、零意图 LLM。"""
    rag, searcher, llm = _build([NE503_DOC])
    events = await _collect(rag, "这个设备支持什么?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_ambiguous"
    assert searcher.calls == []
    assert llm.generate_calls == []
    assert "NE301" in complete["answer"] and "NE503" in complete["answer"]


@pytest.mark.unit
async def test_unsupported_explicit_hint_short_circuits():
    rag, searcher, _ = _build([NE503_DOC])
    events = await _collect(rag, "介绍一下它", product_hint="NE999")
    complete = _complete(events)
    assert complete["result_key"] == "product_not_supported"
    assert complete["is_answered"] is False
    assert searcher.calls == []


# --------------------------------------------------------------------------- #
# 生成边界
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_generation_context_carries_attribution_and_boundary_rules():
    rag, _, llm = _build([NE503_DOC, SHARED_DOC])
    events = await _collect(rag, "NE503 怎么升级固件?")
    _complete(events)
    system = llm.last_messages[0]["content"]
    user = llm.last_messages[-1]["content"]
    assert "产品边界" in system
    assert "NeoEye NE503" in system
    assert "严禁把其他产品" in system
    assert "产品: NeoEye NE503" in user
    assert "产品: 硬件开发资源(共享)" in user


@pytest.mark.unit
async def test_comparison_mode_prompt_and_scope():
    """H:显式比较 → 双目标资格集 + 归属生成规则。"""
    rag, searcher, llm = _build([NE503_DOC, NE301_DOC])
    events = await _collect(rag, "NE301 和 NE503 哪个续航长?")
    complete = _complete(events)
    # Issue #19(RC1):comparison → per-target 检索;每路融合含
    # hybrid + symbols + bucket 三次 searcher 调用,标签 = 该 target 资格集
    assert [c["product_labels"] for c in searcher.calls] == (
        [TAX.eligible_labels(("ne301",))] * 3 + [TAX.eligible_labels(("ne503",))] * 3
    )
    system = llm.last_messages[0]["content"]
    assert "比较" in system
    assert "NeoEye NE301" in system and "NeoEye NE503" in system
    assert complete["trace_payload"]["stages"]["product_scope"]["mode"] == "comparison"


@pytest.mark.unit
async def test_answered_complete_carries_result_key():
    rag, _, _ = _build([NE503_DOC])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["result_key"] == "answered"


# --------------------------------------------------------------------------- #
# 零回归:none mode 与基线行为一致
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_none_mode_unscoped_backward_compatible():
    rag, searcher, llm = _build([NE503_DOC])
    events = await _collect(rag, "CamThink 的产品线是怎么划分的?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    assert complete["result_key"] == "answered"
    assert searcher.calls[0]["product_labels"] is None
    assert "产品边界" not in llm.last_messages[0]["content"]
    assert "product_scope" not in complete["trace_payload"]["stages"]
