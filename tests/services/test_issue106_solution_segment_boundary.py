"""Issue #106 observation — first-party Solution 段的 product/authority 元数据边界。

v1.6.4 生产验收实锤:官方 Solution 页
``website-camthink/solutions/infrastructure-monitoring``(indexed+active)
在产品域方案查询中被两道**既有资格契约**挡在 role lane 之外:

1. **product 元数据**:`derive_product` 的 website 规则表只认产品 token
   URL(case 页 slug 含 NE101 → ne101),方案段页面无产品 token → unknown
   → 产品资格闸(§5/§9)拦截。这与 #29 官方工具页(/tools/)的"答案假性
   缺失"完全同构 —— 当时确立的解法 = **URL 显式段 + taxonomy 共享桶
   身份**(跨机型第一方证据;非兄弟页推断、非代码硬编码)。
2. **authority 元数据**:`_has_solution_signal` 只认 title/章节词面;
   case 侧谓词(`_is_published_case_page`)是 URL 段信号 OR 词面 ——
   solution 侧缺 URL 段信号,官方方案段页面(title 描述性命名,不含
   "solution" 字样)即使被召回也无法通过 admit 校验。

修复(全部 generic,零 exact-URL / 零产品特判代码):

- taxonomy:`solutions` 共享桶(shared kind,applies_to 相交即入资格集)
  + website 派生规则 ``/solutions/`` → solutions(镜像 #29 /tools/);
- 谓词:`_has_solution_signal` 增补 URL 段结构信号(与 case 谓词同构,
  词表纪律不变)。

product isolation 不削弱:共享桶只按 applies_to 展开(不在 applies_to
的产品查询仍不可见);无段信号的页面仍 unknown/拒绝。
"""

import pytest

from backend.pipeline.evidence_selection import _has_solution_signal
from backend.product_taxonomy import get_taxonomy

pytestmark = pytest.mark.unit


def _taxonomy():
    return get_taxonomy()


class TestSolutionSegmentProductBoundary:
    def test_website_solutions_segment_derives_shared_bucket(self):
        """官方方案段页面 → solutions 共享桶身份(镜像 #29 /tools/ 先例)。"""
        d = _taxonomy().derive_product(
            "website",
            "website-camthink/solutions/infrastructure-monitoring",
            "https://www.camthink.ai/solutions/infrastructure-monitoring/",
        )
        assert d.slug == "solutions", (
            "the first-party solutions segment must carry the shared-bucket "
            "identity; leaving it unknown lets the product qualification gate "
            "block official Solution evidence from product-scoped solution "
            "queries (production-proven false absence)"
        )
        assert d.reason == "rule"

    def test_solutions_bucket_enters_product_eligibility(self):
        """solutions 桶按 applies_to 展开进产品资格集(NE101 查询可见)。"""
        tax = _taxonomy()
        assert "solutions" in tax.eligible_slugs(("ne101",))
        assert "solutions" in tax.eligible_slugs(("ng4500",))

    def test_bucket_stays_out_of_unrelated_products(self):
        """product isolation 不削弱:applies_to 之外的产品仍不可见。"""
        from backend.product_taxonomy import load_taxonomy, _DEFAULT_CONFIG_PATH

        tax = load_taxonomy(_DEFAULT_CONFIG_PATH)
        # 明确契约:非 applies_to 产品(如 aitoolstack 平台)不得见到 solutions 桶
        assert "solutions" not in tax.eligible_slugs(("aitoolstack",))

    def test_unmapped_page_stays_unknown(self):
        """规则不越界:非 solutions 段页面照旧 unknown(禁止猜测)。"""
        d = _taxonomy().derive_product(
            "website",
            "website-camthink/blog/zone-intrusion",
            "https://www.camthink.ai/blog/zone-intrusion-detection-camera-system-guide/",
        )
        assert d.slug == "unknown"


class TestSolutionAuthorityUrlSignal:
    def test_solution_page_admitted_by_url_segment_signal(self):
        """URL /solutions/ 段 = 官方方案段结构信号(与 case 谓词同构)。

        生产 Solution 页标题是描述性命名("Visual Data Collection for
        Infrastructure Monitoring Systems",不含 "solution" 字样),词面
        信号天然缺席 —— URL 段是仅存的 generic 结构事实。
        """
        page = _Page(
            title="Visual Data Collection for Infrastructure Monitoring Systems",
            url="https://www.camthink.ai/solutions/infrastructure-monitoring/",
        )
        assert _has_solution_signal(page) is True, (
            "the solution authority predicate must accept the first-party "
            "/solutions/ URL segment as structural evidence, mirroring the "
            "case predicate's URL-segment signals; a described-titled "
            "official solution page is otherwise silently excluded even "
            "after the role lane recalls it"
        )

    def test_lexical_signal_path_unchanged(self):
        """词面信号保真:title 含 solution 仍命中(既有路径零回归)。"""
        page = _Page(
            title="Infrastructure Monitoring Solution",
            url="https://www.camthink.ai/unknown-path/",
        )
        assert _has_solution_signal(page) is True

    def test_non_solution_page_stays_excluded(self):
        """负面:无段信号 + 无词面的页面仍被拒绝(URL 信号不冒充)。"""
        page = _Page(
            title="Delivery Logistics Notes",
            url="https://www.camthink.ai/blog/our-solution-to-delivery/",
        )
        # URL 含 "solution" 子串但非 /solutions/ 段结构 → 不得命中
        assert _has_solution_signal(page) is False

    def test_case_predicate_symmetry(self):
        """对称性证据:case 谓词早已是 URL 段 OR 词面;solution 侧补齐后
        两侧谓词形状一致(同一纪律)。"""
        from backend.pipeline.evidence_selection import _is_published_case_page

        case_page = _Page(
            title="NexAscent Deployment Story",
            url="https://www.camthink.ai/case-studies/nexascent-water-meter-ocr-ne101/",
        )
        assert _is_published_case_page(case_page) is True


class _Page:
    """最小 SearchResult 鸭子类型(title/url/doc_section)。"""

    def __init__(self, title: str, url: str, doc_section: str = ""):
        self.title = title
        self.url = url
        self.doc_section = doc_section
