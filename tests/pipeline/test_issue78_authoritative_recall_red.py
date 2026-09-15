"""Issue #78 RED proof — authoritative web-content candidate recall starvation.

Role B 设计+证明用 RED 套件(**不是修复**)。基线(``f4e6751``)上的预期结果:

- RED-1 / RED-2 / RED-5:**FAIL** —— 复现"权威 web 内容进不了候选池"的结构性失败;
- RED-3 / RED-4 / RED-6:PASS —— 代码导向/商务导向保持性控制 + 重排保留性控制。

边界保真度(避免"测 mock 而非测代码"):

- 被测代码全部为**真实实现**:``RAGOrchestrator._retrieve_and_fuse``(三路检索编排、
  ``INTENT_BOOST_FILTERS`` 桶配置消费、``rrf_fuse`` 融合)与
  ``backend.retrieval.rerank.RerankPipeline``(RED-6,真实重排管道 + 阈值 + chunk_type 权重);
- ``_ScriptedBoundarySearcher`` 只模拟 **Weaviate 边界**(生产实测轨迹):
  hybrid 路 return 生产实测的 top-30 构成(28 code + 2 blog,权威 chunk 在边界之外
  —— 见 #78 RCA 的 79 成员池 dump);symbol 路/桶路按真实原语语义
  (symbol=代码专属;bucket=按 source_types/chunk_types 过滤后返回语料内匹配项)。
  边界输出取自 #78 已受理 RCA,不是为本测试发明的排序。

GREEN 条件(#78 修复落地后):RED-1/2/5 的断言
``authoritative chunk ∈ fused pool`` 转为通过,且 RED-3/4/6 保持通过。
"""

import pytest

from backend.pipeline.rag import INTENT_BOOST_FILTERS, RAGOrchestrator
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


def _corpus() -> list[SearchResult]:
    return (
        [_code_chunk(i) for i in range(_N_CODE)]
        + [_store_chunk(i) for i in range(_N_STORE)]
        + [_blog_chunk(0), _blog_chunk(1)]
        + [AUTH_CONTACT_CHUNK, AUTH_SHIPPING_CHUNK]
    )


class _ScriptedBoundarySearcher:
    """Weaviate 边界模拟器:hybrid/symbol 路由生产实测脚本输出;bucket 按真实
    ``search_bucket`` 语义(过滤条件 → 语料匹配项,稳定序,limit 截断)在固定
    语料上求值,并记录全部调用 kwargs 供 seam 断言。"""

    def __init__(self, hybrid: list[SearchResult], symbols: list[SearchResult], corpus: list[SearchResult]):
        self._hybrid = list(hybrid)
        self._symbols = list(symbols)
        self._corpus = list(corpus)
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
        out = [
            c
            for c in self._corpus
            if (not source_types or c.source_type in source_types)
            and (not chunk_types or c.chunk_type in chunk_types)
        ]
        return out[:limit]


def _make_orch(searcher) -> RAGOrchestrator:
    return RAGOrchestrator(searcher, _NullReranker(), llm=None, system_prompt="sys")


class _NullReranker:
    def rerank(self, query, results, top_k=10):
        return list(results)[:top_k]

    def rerank_scored(self, query, results, top_k=10):
        return list(results)[:top_k], [(r, r.score) for r in results]


async def _fuse(orch, query: str, intent: str):
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
async def test_red1_hq_company_authority_starved_from_candidate_pool():
    corpus = _corpus()
    hybrid = _boundary_hybrid_top30()
    symbols = [c for c in corpus if c.chunk_type == "code"][:21]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    fused, path_counts, _ = await _fuse(
        orch, "where is your head office", "commercial"
    )

    # seam 诊断:commercial 桶只请求了 woocommerce —— 权威 web 内容没有任何桶可承载
    assert searcher.calls["bucket"], "bucket path must run for commercial intent"
    for call in searcher.calls["bucket"]:
        assert "web_crawl" not in (call.get("source_types") or [])

    # 不变量(RED on baseline):权威 chunk 必须能进入候选池
    assert AUTH_CONTACT in _ids(fused), (
        "authoritative contact chunk is serving in the corpus but never entered "
        "the fused candidate pool — no retrieval path carries its class "
        f"(pool={len(fused)}, path_counts={path_counts})"
    )


# --------------------------------------------------------------------------- #
# RED-2:shipping / support 权威饥饿(生产锚点 654f74b8… 的结构复现)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red2_shipping_authority_starved_from_candidate_pool():
    corpus = _corpus()
    hybrid = [c for c in _boundary_hybrid_top30() if c.chunk_type == "code"][:28] + [
        c for c in corpus if c.source_type == "woocommerce"
    ][:2]
    symbols = [c for c in corpus if c.chunk_type == "code"][:15]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    fused, _, _ = await _fuse(
        orch, "Do you ship internationally?", "commercial"
    )

    assert AUTH_SHIPPING in _ids(fused), (
        "authoritative shipping-policy chunk is serving in the corpus but never "
        f"entered the fused candidate pool (pool={len(fused)})"
    )


# --------------------------------------------------------------------------- #
# RED-3:代码导向查询保持性控制(基线 GREEN;修复后必须仍然 GREEN)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red3_code_oriented_queries_keep_code_competitive():
    corpus = _corpus()
    code = [c for c in corpus if c.chunk_type == "code"]
    searcher = _ScriptedBoundarySearcher(code[:30], code[:21], corpus)
    orch = _make_orch(searcher)

    fused, _, _ = await _fuse(
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
# RED-4:商务查询保持性控制(基线 GREEN;修复后必须仍然 GREEN)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red4_commerce_queries_keep_store_evidence_competitive():
    corpus = _corpus()
    hybrid = corpus[:30]
    searcher = _ScriptedBoundarySearcher(hybrid, [], corpus)
    orch = _make_orch(searcher)

    fused, _, _ = await _fuse(
        orch,
        "how much is the NE301 PoE camera and is it in stock",
        "commercial",
    )

    # commercial 桶语义保持:仍请求 woocommerce
    assert searcher.calls["bucket"]
    assert any(
        (call.get("source_types") or []) == ["woocommerce"]
        for call in searcher.calls["bucket"]
    )
    store_in_pool = [r for r in fused if r.source_type == "woocommerce"]
    assert store_in_pool, "commerce query must keep store evidence in the pool"


# --------------------------------------------------------------------------- #
# RED-5:非生产措辞的同类失败(证明结构性,非词汇特例)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red5_synthetic_company_query_same_structural_failure():
    corpus = _corpus()
    hybrid = _boundary_hybrid_top30()
    symbols = [c for c in corpus if c.chunk_type == "code"][:21]
    searcher = _ScriptedBoundarySearcher(hybrid, symbols, corpus)
    orch = _make_orch(searcher)

    query = "Which city is your company headquarters located in?"
    fused, _, _ = await _fuse(orch, query, "commercial")

    assert AUTH_CONTACT in _ids(fused), (
        "synthetic company-fact query (no production-case vocabulary) starves the "
        f"authoritative chunk identically — the failure is structural (pool={len(fused)})"
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
# 结构探针:真实 INTENT_BOOST_FILTERS 不存在能承载 web_crawl 的桶(模块常量级)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_red_seam_probe_no_bucket_carries_web_crawl_on_baseline():
    carrying = [
        intent
        for intent, cfg in INTENT_BOOST_FILTERS.items()
        if "web_crawl" in (cfg.get("source_types") or [])
        or (
            cfg.get("chunk_types")
            and intent in ("support", "commercial")
        )
    ]
    assert carrying, (
        f"no intent bucket can carry authoritative web_crawl content "
        f"(INTENT_BOOST_FILTERS={INTENT_BOOST_FILTERS})"
    )
