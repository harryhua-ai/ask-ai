"""MSW:page_context 软检索加分的纯函数单元测试(契约 §11:SOFT BOOST,非硬过滤)。

冻结语义:
- boost = 命中产品线索的候选 score 乘性加权 + 稳定重排;
- **绝不过滤、绝不增删候选**(G009:用户明确问 NE301 时 NE301 仍可居首);
- 无线索 / 空结果 → 恒等返回(零回归)。
"""

import pytest

from backend.pipeline.rag import (
    PAGE_CONTEXT_BOOST_WEIGHT,
    apply_page_context_boost,
    product_hint,
)
from tests.pipeline.test_rag import _make_sr


@pytest.mark.unit
def test_product_hint_prefers_product_then_id_then_sku():
    assert product_hint({"product": "NE503"}) == "ne503"
    assert product_hint({"product_id": "NE-503"}) == "ne-503"
    # 规则:空白直接移除;跨写法匹配由 apply 的双向子串容忍兜住(cmne503x ⊃ ne503)
    assert product_hint({"sku": "CM NE503X"}) == "cmne503x"
    assert product_hint({"product": "", "product_id": "NE301"}) == "ne301"
    assert product_hint({}) is None
    assert product_hint(None) is None


@pytest.mark.unit
def test_product_hint_strips_junk():
    assert product_hint({"product": "NE 503!"}) == "ne503"


@pytest.mark.unit
def test_boost_no_hint_is_identity():
    results = [_make_sr(product="ne301", score=0.9), _make_sr(product="ne503", score=0.8)]
    out = apply_page_context_boost(results, None)
    assert out == results
    out = apply_page_context_boost(results, {})
    assert out == results


@pytest.mark.unit
def test_boost_empty_results_is_identity():
    assert apply_page_context_boost([], {"product": "NE503"}) == []


@pytest.mark.unit
def test_boost_reorders_matched_product_up():
    """NE503 线索:近分的 ne503 候选乘加权后超过 ne301。"""
    a = _make_sr(product="ne301", score=0.9, title="A")
    b = _make_sr(product="ne503", score=0.8, title="B")
    out = apply_page_context_boost([a, b], {"product": "NE503"})
    assert [r.title for r in out] == ["B", "A"]
    assert out[0].score == pytest.approx(0.8 * PAGE_CONTEXT_BOOST_WEIGHT)
    assert out[1].score == pytest.approx(0.9)


@pytest.mark.unit
def test_boost_never_filters_or_adds():
    """G009:NE503 线索不构成硬过滤 —— 低分 ne503 加权后仍低于明确的 ne301
    高分,ne301 保持第一,且候选集合不变。"""
    a = _make_sr(product="ne301", score=0.95, title="A")
    b = _make_sr(product="ne503", score=0.5, title="B")
    out = apply_page_context_boost([a, b], {"product": "NE503"})
    assert len(out) == 2
    assert {r.product for r in out} == {"ne301", "ne503"}
    assert out[0].title == "A"


@pytest.mark.unit
def test_boost_is_stable_for_equal_keys():
    a = _make_sr(product="ne301", score=0.9, title="A")
    b = _make_sr(product="ne301", score=0.9, title="B")
    out = apply_page_context_boost([a, b], {"product": "ne503"})
    assert [r.title for r in out] == ["A", "B"]


@pytest.mark.unit
def test_boost_substring_match_both_directions():
    """线索 'ne503-pro' 命中 product 'ne503'(双向子串);不命中 ne301。"""
    a = _make_sr(product="ne301", score=0.9, title="A")
    b = _make_sr(product="ne503", score=0.8, title="B")
    out = apply_page_context_boost([a, b], {"product": "NE503-Pro"})
    assert [r.title for r in out] == ["B", "A"]
