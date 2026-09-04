"""Cross-product Eval Matrix(Issue #5 契约 §11:11+ 确定性场景 A–K)。

每个场景与冻结契约/Planner 验收清单的 ID 一一对应;全部离线、确定性
(faithful searcher 模拟 Weaviate product_labels 硬过滤 + 脚本化 LLM),
可进 CI 作回归防线。XM-R1/G1/C1 等价场景(E/A/C)为发布阻断项。
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.product_taxonomy import get_taxonomy
from backend.retrieval.search import SearchResult

TAX = get_taxonomy()


# --------------------------------------------------------------------------- #
# 语料(NE301 / NE503 同主题强证据 + 共享 + unknown,标签为迁移后 canonical 值)
# --------------------------------------------------------------------------- #


def _sr(product, source_id, text, source_type="github", url="https://example.com/d"):
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=source_id.rsplit("/", 1)[-1],
        url=url,
        score=0.9,
        chunk_index=0,
    )


NE503_FW = _sr(
    "ne503",
    "wiki-documents-local/main/docs/6-neoeyes-ne503-series/5-troubleshooting.md",
    "NE503 固件升级:通过 NeoMind 平台推送升级包,或本地 USB 导入官方固件。",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/5-troubleshooting.md",
)
NE301_FW = _sr(
    "ne301",
    "wiki-documents-local/main/docs/5-neoeyes-ne301-series/5-troubleshooting.md",
    "NE301 固件升级:长按复位键进入 bootloader,经 SD 卡刷入固件文件。",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/5-neoeyes-ne301-series/5-troubleshooting.md",
)
SHARED_HW = _sr(
    "hardware-common",
    "wiki-documents-local/main/docs/3-hardware-dev-resources/10-5g-module.md",
    "共享硬件:5G 模组走 M.2 接口,供电需 12V DC 输入。",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/3-hardware-dev-resources/10-5g-module.md",
)
UNKNOWN_DOC = _sr(
    "unknown",
    "wiki-documents-local/main/.image-upload/README.md",
    "图片上传工具使用说明,与任何产品无关的内部工具文档。",
    url="https://github.com/camthink-ai/wiki-documents/blob/main/.image-upload/README.md",
)
KNOWLEDGE_CASE = _sr(
    "knowledge",
    "knowledge-support-cases/support/2026-04/ne301-firmware-fail.md",
    "历史工单:一台 NE301 固件升级失败,重新插 SD 卡后恢复。",
    source_type="filesystem",
    url="",
)


class FaithfulSearcher:
    """Weaviate 语义替身:product_labels / channel_visibility 均按属性硬过滤。"""

    def __init__(self, corpus):
        self.corpus = corpus
        self.calls = []

    def _pick(self, labels):
        if labels is None:
            return list(self.corpus)
        allowed = set(labels)
        return [c for c in self.corpus if c.product in allowed]

    def search(self, *, query, alpha=0.5, limit=50, product_filter=None, channel=None, product_labels=None):
        self.calls.append(product_labels)
        return self._pick(product_labels)

    def search_symbols(self, *, query, limit=30, product_filter=None, channel="widget", product_labels=None):
        return []

    def search_bucket(self, *, query, limit=30, channel=None, product_filter=None, product_labels=None, **bucket):
        self.calls.append(product_labels)
        picked = self._pick(product_labels)
        # support 桶只回 filesystem 案例
        return [c for c in picked if c.source_type == "filesystem"]


class ScriptedLLM:
    def __init__(self, intent="product", answer="根据官方资料,这是答案。"):
        self.intent = intent
        self.answer = answer
        self.generate_calls = 0
        self.last_messages = None

    async def generate(self, messages, task=None, **kwargs):
        self.generate_calls += 1
        content = str(messages[-1].get("content", ""))
        if task == "intent":
            return LLMResponse(
                content=json.dumps({"category": self.intent, "reason": "t", "confidence": 0.99}),
                model="t", tokens_input=1, tokens_output=1, latency_ms=1,
            )
        if task in ("query_rewrite", "lead_qualification"):
            return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)
        return LLMResponse(content=self.answer, model="t", tokens_input=1, tokens_output=1, latency_ms=1)

    def stream(self, messages, task=None, **kwargs):
        self.last_messages = messages

        async def _gen():
            yield self.answer

        return _gen()


def _rag(corpus, llm=None):
    searcher = FaithfulSearcher(corpus)
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda q, results, top_k=None: list(results)
    llm = llm or ScriptedLLM()
    return (
        RAGOrchestrator(searcher, reranker, llm, system_prompt="base", min_results_to_answer=1),
        searcher,
        llm,
    )


async def _collect(rag, query, **kwargs):
    return [json.loads(e) async for e in rag.stream_answer(query, "widget", **kwargs)]


def _complete(events):
    return next(e for e in events if e["type"] == "complete")


# --------------------------------------------------------------------------- #
# A/B:exact 问题 —— sibling 证据不得作答
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scenario_A_ne503_question_ne301_evidence_cannot_answer():
    """A:NE503 问题 + NE301 同主题强证据在场 → 回答与上下文均无 NE301。"""
    rag, searcher, llm = _rag([NE301_FW, NE503_FW])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user = llm.last_messages[-1]["content"]
    assert "NE503 固件升级" in user
    assert "SD 卡刷入固件" not in user          # NE301 步骤不得入上下文
    assert all(labels == TAX.eligible_labels(("ne503",)) for labels in searcher.calls)


@pytest.mark.unit
async def test_scenario_B_ne301_question_ne503_evidence_cannot_answer():
    """B:A 的镜像:NE301 问题 + NE503 强证据在场 → 无 NE503 内容。"""
    rag, _, llm = _rag([NE301_FW, NE503_FW])
    events = await _collect(rag, "NE301 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user = llm.last_messages[-1]["content"]
    assert "NE301 固件升级" in user
    assert "NeoMind 平台推送升级包" not in user  # NE503 步骤不得入上下文


# --------------------------------------------------------------------------- #
# C/D:歧义澄清 / 页面上下文确立目标
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scenario_C_ambiguous_without_context_clarifies():
    """C:「这个设备支持什么?」无可靠上下文 → 文本澄清(PRODUCT_AMBIGUOUS)。"""
    rag, searcher, llm = _rag([NE503_FW, NE301_FW])
    events = await _collect(rag, "这个设备支持什么?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_ambiguous"
    assert searcher.calls == [] and llm.generate_calls == 0  # 零检索零意图
    assert "NE301" in complete["answer"] and "NE503" in complete["answer"]


@pytest.mark.unit
async def test_scenario_D_page_context_resolves_target():
    """D:宿主页面确立 NE503 → 目标解析 ne503,检索收窄。"""
    rag, searcher, _ = _rag([NE503_FW])
    events = await _collect(rag, "怎么升级固件", page_context={"product": "NE503"})
    complete = _complete(events)
    assert complete["is_answered"] is True
    assert all(labels == TAX.eligible_labels(("ne503",)) for labels in searcher.calls)
    assert complete["trace_payload"]["stages"]["product_scope"]["source"] == "page_context"


# --------------------------------------------------------------------------- #
# E:exact 缺失 → insufficient,不 sibling 顶替(发布阻断项)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scenario_E_exact_absent_sibling_strong_insufficient():
    """E:NE503 证据零命中 + NE301 强证据在场 → insufficient;sibling 事实不出现在任何事件。"""
    rag, _, _ = _rag([NE301_FW])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_evidence_insufficient"
    assert "NeoEye NE503" in complete["answer"]
    blob = json.dumps(events, ensure_ascii=False)
    assert "SD 卡刷入" not in blob and "bootloader" not in blob  # sibling 事实零泄漏


# --------------------------------------------------------------------------- #
# F/G:共享证据按 shared 语义 / support intent 不可绕过
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scenario_F_shared_evidence_allowed_as_shared():
    """F:共享平台证据可作补充,归属标注为共享。"""
    rag, _, llm = _rag([NE503_FW, SHARED_HW])
    events = await _collect(rag, "NE503 怎么升级固件?顺便问下 5G 模组供电")
    complete = _complete(events)
    assert complete["is_answered"] is True
    user = llm.last_messages[-1]["content"]
    assert "产品: 硬件开发资源(共享)" in user
    assert "M.2" in user


@pytest.mark.unit
async def test_scenario_G_support_intent_cannot_bypass_boundary():
    """G:support intent 的 knowledge 桶被同一资格标签过滤;案例仅作背景。"""
    llm = ScriptedLLM(intent="support")
    rag, searcher, _ = _rag([NE301_FW, KNOWLEDGE_CASE], llm=llm)
    events = await _collect(rag, "NE503 固件升级失败怎么办?")
    assert all(labels == TAX.eligible_labels(("ne503",)) for labels in searcher.calls)
    # NE301 案例不得以任何形式进入上下文(knowledge 桶只回 knowledge 标签)
    blob = json.dumps(events, ensure_ascii=False) + str(llm.last_messages)
    assert "SD 卡刷入" not in blob


# --------------------------------------------------------------------------- #
# H:显式比较 —— 双产品允许且须归属
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_scenario_H_comparison_allowed_and_attributed():
    """H:NE301 vs NE503 → 双目标检索 + 分节归属生成规则。"""
    rag, searcher, llm = _rag([NE301_FW, NE503_FW])
    events = await _collect(rag, "NE301 和 NE503 的固件升级方式有什么区别?")
    complete = _complete(events)
    # Issue #19(RC1):comparison → per-target 检索(每个 target 以自身
    # 资格标签集独立调用一次;共享证据由单 target 资格集天然包含)
    # 每路 _retrieve_and_fuse 中 fake 记录 hybrid + symbols 两次调用
    expected_calls = (
        [TAX.eligible_labels(("ne301",))] * 2 + [TAX.eligible_labels(("ne503",))] * 2
    )
    assert searcher.calls == expected_calls  # 该 fake 直接记录 label 列表
    system = llm.last_messages[0]["content"]
    assert "比较多个产品" in system and "按产品分节" in system
    user = llm.last_messages[-1]["content"]
    assert "产品: NeoEye NE301" in user and "产品: NeoEye NE503" in user
    assert complete["trace_payload"]["stages"]["product_scope"]["mode"] == "comparison"


# --------------------------------------------------------------------------- #
# I/J/K:别名 canonicalize / wiki 路径推导 / unknown 不冒充
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NE503 怎么升级固件", ("ne503",)),
        ("ne503 固件", ("ne503",)),
        ("NeoEye NE503 续航", ("ne503",)),
        ("meta-hailo-os 怎么烧录", ("ne503",)),  # 历史标签别名(生产实证来源)
        ("NE301 和 ne-503", ("ne301", "ne503")),
    ],
)
def test_scenario_I_alias_and_case_variants_canonicalize(text, expected):
    """I:别名/大小写/历史标签 → canonical identity。"""
    assert TAX.extract_products(text) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/6-neoeyes-ne503-series/1-quick-start.md", "ne503"),
        ("docs/5-neoeyes-ne301-series/x.md", "ne301"),
        ("docs/8-neoeyes-ne302-series/x.md", "ne302"),
        ("docs/2-neoeyes-ne101-series/x.md", "ne101"),
        ("docs/1-neoedge-ng4500-series/x.md", "ng4500"),
        ("docs/0-neomind/guide.md", "neomind"),
        ("docs/3-hardware-dev-resources/ssd.md", "hardware-common"),
        ("docs/4-ai-application/app.md", "ai-common"),
        ("docs/7-release-notes/v1.md", "release-notes"),
    ],
)
def test_scenario_J_wiki_path_derivation(path, expected):
    """J:wiki 文档路径 → 正确的 per-document product。"""
    derived = TAX.derive_product("wiki", f"wiki-documents-local/main/{path}", "")
    assert derived.slug == expected


@pytest.mark.unit
async def test_scenario_K_unknown_document_never_becomes_target_evidence():
    """K:unknown/unmapped 文档不得静默变成目标证据(检索排除 + 洞察报告)。"""
    derived = TAX.derive_product("wiki", "wiki-documents-local/main/.image-upload/README.md", "")
    assert derived.slug == "unknown"
    rag, _, llm = _rag([UNKNOWN_DOC])
    events = await _collect(rag, "NE503 怎么升级固件?")
    complete = _complete(events)
    assert complete["is_answered"] is False
    assert complete["result_key"] == "product_evidence_insufficient"
    user = json.dumps(llm.last_messages, ensure_ascii=False)
    assert "图片上传工具" not in user  # unknown 文档不进上下文
