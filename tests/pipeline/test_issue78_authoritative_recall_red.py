"""Issue #78 — authoritative web-content candidate recall (Role B RED→GREEN).

Role B RED 套件,随 #78 修复转 GREEN(设计/基线 RED 证据见
reports/issue-78-authoritative-recall-remediation-design-20260915.md §8;
基线 f4e6751 上 RED-1/2/5 + seam probe 曾 FAIL,RED-3/4/6 曾 PASS)。

语义:
- RED-1 / RED-2 / RED-5:权威 web chunk 必须能进入融合候选池;
- RED-3 / RED-4 / RED-6:代码导向/商务导向保持 + 重排保留控制;
- seam probe:`INTENT_BOOST_FILTERS` 必须存在能承载权威 web 内容的桶。

边界保真度:被测代码全部为真实实现(``_retrieve_and_fuse`` 三路编排、
``INTENT_BOOST_FILTERS`` 桶配置消费、``rrf_fuse``、``RerankPipeline``)。
``_ScriptedBoundarySearcher`` 只模拟 Weaviate 边界:hybrid/symbol 路为生产
实测脚本输出(RCA 79 成员池 dump);bucket 按真实 ``search_bucket`` 语义在
固定语料上求值 —— BM25 桶用稳定序代理,``use_hybrid`` 桶用确定性 dense
话题模型(生产 control 34ba7159 证明权威 chunk 入池靠 dense 语义分量,
纯词法代理无法表达该机制)。
"""

import pytest

from backend.pipeline.rag import (
    INTENT_BOOST_FILTERS,
    RAGOrchestrator,
    _bucket_specs,
)
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

AUTH_CONTACT = ("website-camthink/company/contact-us", 0)
AUTH_SHIPPING = ("website-camthink/shipping-policy", 0)

# 与生产实测一致的边界构成(见 #78 RCA §4):hybrid top-30 = 28 code + 2 blog,
# 权威 chunk(在 Weaviate gen0 服务中)位于边界之外。
_N_CODE = 28
_N_STORE = 30


def _code_chunk(i: int) -> SearchResult:
    return SearchResult(
        text=f"firmware module {i}: usb request head parser, descriptor header, dma address register",
        source_id=f"ne301-local/main/src/module_{i:02d}.c",
        source_type="github",
        product="ne301",
        title=f"module_{i:02d}.c",
        url=f"https://github.com/camthink-ai/ne301/blob/main/src/module_{i:02d}.c",
        score=0.5,
        chunk_index=0,
        chunk_type="code",
    )


def _store_chunk(i: int) -> SearchResult:
    return SearchResult(
        text=f"store item {i}: price $199, in stock, order online, shipping to most regions",
        source_id=f"woocommerce-mall/{4000 + i}",
        source_type="woocommerce",
        product="ne301" if i % 2 else "ne101",
        title=f"store item {i}",
        url=f"https://www.camthink.ai/store/item-{i}/",
        score=0.4,
        chunk_index=0,
        chunk_type="paragraph",
    )


def _blog_chunk(i: int) -> SearchResult:
    return SearchResult(
        text=f"blog post {i} about edge AI camera deployments and product updates",
        source_id=f"website-camthink/blog/post-{i}",
        source_type="web_crawl",
        product="website",
        title=f"blog post {i}",
        url=f"https://www.camthink.ai/blog/post-{i}/",
        score=0.3,
        chunk_index=0,
        chunk_type="paragraph",
    )


AUTH_CONTACT_CHUNK = SearchResult(
    text=(
        "Let's Start the Conversation. Talk to Our Team. Email sales@example.com "
        "Phone +86-592-0000000 Hours Mon-Fri 9:00-18:00. Headquarters Software Park "
        "Phase III, Xiamen 361024, Fujian, China. Part of Milesight Group."
    ),
    source_id=AUTH_CONTACT[0],
    source_type="web_crawl",
    product="website",
    title="Contact Us",
    url="https://www.camthink.ai/company/contact-us/",
    score=0.0,
    chunk_index=0,
    chunk_type="heading",
)

AUTH_SHIPPING_CHUNK = SearchResult(
    text=(
        "Delivery Policy. We deliver to most regions worldwide. Delivery time 5-7 "
        "business days. Carriers: DHL, FedEx. Customs duties may apply per region."
    ),
    source_id=AUTH_SHIPPING[0],
    source_type="web_crawl",
    product="website",
    title="Shipping Policy",
    url="https://www.camthink.ai/shipping-policy/",
    score=0.0,
    chunk_index=0,
    chunk_type="list",
)

# dense 话题模型(use_hybrid 桶的确定性语义代理;基线代码从不消费该模型)
_TOPIC_CONTACT = frozenset({"company-location"})
_TOPIC_SHIPPING = frozenset({"shipping-policy"})
_TOPICS: dict[tuple[str, int], frozenset] = {
    AUTH_CONTACT: _TOPIC_CONTACT,
    AUTH_SHIPPING: _TOPIC_SHIPPING,
}


def _corpus() -> list[SearchResult]:
    return (
        [_code_chunk(i) for i in range(_N_CODE)]
        + [_store_chunk(i) for i in range(_N_STORE)]
        + [_blog_chunk(0), _blog_chunk(1)]
        + [AUTH_CONTACT_CHUNK, AUTH_SHIPPING_CHUNK]
    )


class _ScriptedBoundarySearcher:
    """Weaviate 边界模拟器:hybrid/symbol 路为脚本输出;bucket 按真实
    ``search_bucket`` 语义求值 —— 无 ``use_hybrid`` 时稳定序代理(BM25 不可
    确定性复现,稳定序对被测编排语义无影响),``use_hybrid=True`` 时按
    dense 话题亲和度降序(类内语义匹配,镜像 control 轨迹的入池机制)。
    记录全部调用 kwargs 供 seam 断言。"""

    def __init__(
        self,
        hybrid: list[SearchResult],
        symbols: list[SearchResult],
        corpus: list[SearchResult],
        query_topics: frozenset | None = None,
    ):
        self._hybrid = list(hybrid)
        self._symbols = list(symbols)
        self._corpus = list(corpus)
        self._query_topics = query_topics or frozenset()
        self.calls: dict[str, list[dict]] = {"search": [], "symbols": [], "bucket": []}

    def search(self, **kw):
        self.calls["search"].append(kw)
        return list(self._hybrid)

    def search_symbols(self, **kw):
        self.calls["symbols"].append(kw)
        return list(self._symbols)

    def search_bucket(self, **kw):
        self.calls["bucket"].append(kw)
        source_types = kw.get("source_types")
        chunk_types = kw.get("chunk_types")
        limit = int(kw.get("limit") or 30)
        use_hybrid = bool(kw.get("use_hybrid", False))

        def _matches(c: SearchResult) -> bool:
            return (not source_types or c.source_type in source_types) and (
                not chunk_types or c.chunk_type in chunk_types
            )

        matches = [c for c in self._corpus if _matches(c)]
        if use_hybrid:
            matches.sort(
                key=lambda c: -len(_TOPICS.get((c.source_id, c.chunk_index), frozenset())
                                 & self._query_topics)
            )
        return matches[:limit]


def _make_orch(searcher) -> RAGOrchestrator:
    return RAGOrchestrator(searcher, _NullReranker(), llm=None, system_prompt="sys")


class _NullReranker:
    def rerank(self, query, results, top_k=10):
        return list(results)[:top_k]

    def rerank_scored(self, query, results, top_k=10):
        return list(results)[:top_k], [(r, r.score) for r in results]


async def _fuse(orch, query: str, intent: str, topics: frozenset | None = None):
    """直接驱动真实编排 seam;topics 仅注入边界模拟器(dense 代理)。"""
    searcher = orch._searcher
    if isinstance(searcher, _ScriptedBoundarySearcher) and topics is not None:
        searcher._query_topics = topics
    return await orch._retrieve_and_fuse(
        query,
        query,
        intent,
        product_filter=None,
        channel="widget",
        product_labels=None,
    )


def _ids(items) -> set:
    return {(r.source_id, r.chunk_index) for r in items}


def _boundary_hybrid_top30() -> list[SearchResult]:
    """生产实测的 class-blind hybrid top-30:28 code + 2 blog;权威 chunk 不在。"""
    corpus = _corpus()
    return [c for c in corpus if c.chunk_type == "code"] + [
        c for c in corpus if c.source_id.startswith("website-camthink/blog/")
    ]


# --------------------------------------------------------------------------- #
# RED-1:HQ / company 权威饥饿(生产锚点 cbafab32… 的结构复现)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red1_hq_company_authority_recalled_into_candidate_pool():
    corpus = _corpus()
    hybrid = _boundary_hybrid_top30()
    symbols = [c for c in corpus if c.chunk_type == "code"][:21]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    fused, path_counts, candidates, buckets = await _fuse(
        orch,
        "where is your head office",
        "commercial",
        topics=_TOPIC_CONTACT,
    )

    # 不变量:权威 chunk 必须进入候选池,且路径可归因到用户面桶
    assert AUTH_CONTACT in _ids(fused), (
        "authoritative contact chunk is serving in the corpus but never entered "
        f"the fused candidate pool (pool={len(fused)}, path_counts={path_counts})"
    )
    contact_paths = next(
        c["paths"] for c in candidates if (c["source_id"], c["chunk_index"]) == AUTH_CONTACT
    )
    assert any(p.startswith("boost:") for p in contact_paths), contact_paths
    # 桶归因:用户面桶(use_hybrid)有产出,证明入池路径
    user_facing = [b for b in buckets if b.get("use_hybrid")]
    assert user_facing and all(b["hits"] > 0 for b in user_facing), buckets
    # commercial 主桶语义保持:woocommerce 桶仍在
    assert any(
        (b.get("source_types") or []) == ["woocommerce"] for b in buckets
    ), buckets


# --------------------------------------------------------------------------- #
# RED-2:shipping / support 权威饥饿(生产锚点 654f74b8… 的结构复现)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red2_shipping_authority_recalled_into_candidate_pool():
    corpus = _corpus()
    hybrid = [c for c in _boundary_hybrid_top30() if c.chunk_type == "code"][:28] + [
        c for c in corpus if c.source_type == "woocommerce"
    ][:2]
    symbols = [c for c in corpus if c.chunk_type == "code"][:15]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    fused, _, _, _ = await _fuse(
        orch,
        "Do you ship internationally?",
        "commercial",
        topics=_TOPIC_SHIPPING,
    )

    assert AUTH_SHIPPING in _ids(fused), (
        "authoritative shipping-policy chunk is serving in the corpus but never "
        f"entered the fused candidate pool (pool={len(fused)})"
    )


# --------------------------------------------------------------------------- #
# RED-3:代码导向查询保持性控制(必须始终 GREEN)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red3_code_oriented_queries_keep_code_competitive():
    corpus = _corpus()
    code = [c for c in corpus if c.chunk_type == "code"]
    searcher = _ScriptedBoundarySearcher(code[:30], code[:21], corpus)
    orch = _make_orch(searcher)

    fused, _, _, _ = await _fuse(
        orch,
        "NE301 CMakeLists link libraries build configuration",
        "product",
    )

    code_in_pool = [r for r in fused if r.chunk_type == "code"]
    assert len(code_in_pool) >= 20, (
        "code-oriented query must keep code candidates strongly competitive "
        f"(got {len(code_in_pool)} code chunks in pool of {len(fused)})"
    )


# --------------------------------------------------------------------------- #
# RED-4:商务查询保持性控制(必须始终 GREEN)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red4_commerce_queries_keep_store_evidence_competitive():
    corpus = _corpus()
    hybrid = corpus[:30]
    searcher = _ScriptedBoundarySearcher(hybrid, [], corpus)
    orch = _make_orch(searcher)

    fused, _, _, _buckets = await _fuse(
        orch,
        "how much is the NE301 PoE camera and is it in stock",
        "commercial",
    )

    # commercial 主桶语义保持:仍请求 woocommerce
    assert any(
        (call.get("source_types") or []) == ["woocommerce"] for call in searcher.calls["bucket"]
    )
    store_in_pool = [r for r in fused if r.source_type == "woocommerce"]
    assert store_in_pool, "commerce query must keep store evidence in the pool"


# --------------------------------------------------------------------------- #
# RED-5:非生产措辞的同类失败(证明结构性,非词汇特例)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red5_synthetic_company_query_recalled_structurally():
    corpus = _corpus()
    hybrid = _boundary_hybrid_top30()
    symbols = [c for c in corpus if c.chunk_type == "code"][:21]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    query = "Which city is your company headquarters located in?"
    fused, _, _, _ = await _fuse(
        orch, query, "commercial", topics=_TOPIC_CONTACT
    )

    assert AUTH_CONTACT in _ids(fused), (
        "synthetic company-fact query (no production-case vocabulary) must admit "
        f"the authoritative chunk — the fix must be structural (pool={len(fused)})"
    )


# --------------------------------------------------------------------------- #
# RED-6:入池后重排可保留/晋升(真实 RerankPipeline;保护"不修重排器")
# --------------------------------------------------------------------------- #
class _ScriptedInnerReranker:
    """按文本是否含权威语义词给出确定性分数(真实 RerankPipeline 消费)。"""

    def rerank(self, query, documents):
        return [0.8 if "Headquarters" in d or "Delivery Policy" in d else 0.5 for d in documents]


@pytest.mark.unit
async def test_red6_reranker_retains_authority_once_admitted():
    corpus = _corpus()
    pool = [c for c in corpus if c.chunk_type == "code"][:9] + [AUTH_CONTACT_CHUNK]
    pipeline = RerankPipeline(_ScriptedInnerReranker())

    survivors = pipeline.rerank("where is the company", pool, top_k=10)

    assert AUTH_CONTACT in _ids(survivors)
    assert survivors[0].source_id == AUTH_CONTACT[0], (
        "once admitted, the existing reranker retains and promotes the "
        "authoritative chunk — the defect is pre-rerank (candidate entry), "
        "not the reranker"
    )


# --------------------------------------------------------------------------- #
# 结构探针:INTENT_BOOST_FILTERS 必须存在承载权威 web 内容的桶
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_red_seam_probe_bucket_carries_authoritative_web_content():
    carrying = []
    for intent, specs in INTENT_BOOST_FILTERS.items():
        for cfg in _bucket_specs(specs):
            carries = "web_crawl" in (cfg.get("source_types") or []) or (
                cfg.get("chunk_types")
                and intent in ("support", "commercial")
            )
            if carries:
                carrying.append(intent)
                break
    assert carrying, (
        "no intent bucket can carry authoritative web content "
        f"(INTENT_BOOST_FILTERS={INTENT_BOOST_FILTERS})"
    )
    assert set(carrying) >= {"support", "commercial"}
