"""CIT-03:引用产品资格校验(citation correctness,Issue #5 契约 §7)。

target-specific claim 的 [N] 必须落在 target 产品或合格共享证据上;
sibling 编号默认不支持 target-specific claim → 剔除标记 + stats 记账。
校验保持既有语义:只剔标记,不改写正文;参数缺省时行为与基线逐字节一致。
"""


from backend.pipeline.citation import (
    CitationStreamFilter,
    build_citation_context,
    validate_citations,
)
from backend.retrieval.search import SearchResult


def _sr(
    product: str, text: str, url: str = "https://x/1", source_type: str = "github"
) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=f"src-{product}",
        source_type=source_type,
        product=product,
        title="T",
        url=url,
        score=0.9,
        chunk_index=0,
    )


def _sources(*results: SearchResult) -> list[dict]:
    return [
        {"url": r.url, "title": r.title, "type": r.source_type, "product": r.product}
        for r in results
    ]


class TestBuildContextProductAttribution:
    def test_context_carries_product_attribution_line(self):
        reranked = [_sr("ne503", "NE503 功耗 2.5W")]
        ctx = build_citation_context(reranked, _sources(reranked[0]))
        assert "NeoEye NE503" in ctx.context
        assert ctx.source_products == {1: "ne503"}

    def test_unmapped_label_shown_verbatim(self):
        reranked = [_sr("wiki", "混合源内容")]
        ctx = build_citation_context(reranked, _sources(reranked[0]))
        assert "产品: wiki" in ctx.context
        assert ctx.source_products == {1: "wiki"}

    def test_background_chunks_have_no_number_and_no_product_map(self):
        fs = _sr("knowledge", "内部案例背景", url="fs://a", source_type="filesystem")
        ctx = build_citation_context([fs], [])
        assert "[1]" not in ctx.context
        assert ctx.source_products == {}


class TestMarkerEligibility:
    def test_ineligible_sibling_marker_dropped(self):
        """sibling 编号不支持 target-specific claim → 剔除。"""
        f = CitationStreamFilter(
            n_sources=2,
            source_texts={1: ["ne301 text"], 2: ["ne503 text"]},
            source_products={1: "ne301", 2: "ne503"},
            eligible_slugs={"ne503", "hardware-common", "knowledge"},
        )
        out = f.feed("功耗是 2.5W[1],另外[2]也说明了。")
        out += f.finish()
        assert out == "功耗是 2.5W,另外[2]也说明了。"
        assert f.stats["ineligible_product_dropped"] == 1
        assert f.stats["dangling_dropped"] == 0

    def test_eligible_marker_kept(self):
        f = CitationStreamFilter(
            n_sources=2,
            source_texts={1: ["ne503 text 2.5W"], 2: ["shared"]},
            source_products={1: "ne503", 2: "hardware-common"},
            eligible_slugs={"ne503", "hardware-common"},
        )
        out = f.feed("功耗 2.5W[1],结构见[2]。")
        out += f.finish()
        assert out == "功耗 2.5W[1],结构见[2]。"
        assert f.stats["ineligible_product_dropped"] == 0

    def test_comparison_mode_allows_both_targets(self):
        f = CitationStreamFilter(
            n_sources=2,
            source_texts={1: ["ne301 6.1uA"], 2: ["ne503 2.5W"]},
            source_products={1: "ne301", 2: "ne503"},
            eligible_slugs={"ne301", "ne503", "hardware-common"},
        )
        out = f.feed("NE301 为 6.1uA[1];NE503 为 2.5W[2]。")
        out += f.finish()
        assert "[1]" in out and "[2]" in out

    def test_backward_compat_without_products(self):
        """缺省参数时行为与基线一致(编号/数值校验照常,无产品检查)。"""
        f = CitationStreamFilter(n_sources=1, source_texts={1: ["text 2.5W"]})
        out = f.feed("功耗 2.5W[1][9]")
        out += f.finish()
        assert out == "功耗 2.5W[1]"
        assert "ineligible_product_dropped" not in f.stats or f.stats["ineligible_product_dropped"] == 0


def test_validate_citations_product_aware():
    answer = "NE301 续航 6.1uA[1]。"
    final, stats = validate_citations(
        answer,
        n_sources=2,
        source_texts={1: ["ne301"], 2: ["ne503"]},
        source_products={1: "ne301", 2: "ne503"},
        eligible_slugs={"ne503"},
    )
    assert final == "NE301 续航 6.1uA。"
    assert stats["ineligible_product_dropped"] == 1
