"""#28/#29/#31 答案智能共享矫正回归(证据资格/覆盖组合/信号词表)。

生产实证(2026-09-10 只读):
- store 全部 38 个 chunk 标签 commercial,被资格闸整体拦截 → 价格答案
  假性缺失「官方资料未载明 NE101 各型号的价格」(#28);
- /tools/battery-calculator/ 无推导规则 → product=unknown → 资格闸拦截
  (#29);两处都是「证据在库但到不了生成上下文」的结构性假缺失。
"""

import pytest

from backend.product_taxonomy import get_taxonomy


@pytest.fixture
def taxonomy():
    return get_taxonomy()


class TestStoreEvidenceEligibility:
    def test_store_slug_eligible_for_any_target(self, taxonomy):
        """#28:store 商业证据类(commercial)对任一目标产品入围。"""
        for target in ("ne101", "ne301", "ne503"):
            assert "commercial" in taxonomy.eligible_slugs((target,))

    def test_store_labels_include_legacy_tags(self, taxonomy):
        """检索侧原始标签闸含历史 store 标签(迁移前兜底,与 canonical 同入)。"""
        labels = set(taxonomy.eligible_labels(("ne101",)))
        assert {"commercial", "online-store", "accessories"} <= labels

    def test_store_not_targetable(self, taxonomy):
        """入围 ≠ 可作解析目标:store 仍是证据类,不是产品身份。"""
        assert taxonomy.is_targetable("commercial") is False

    def test_sibling_products_still_excluded(self, taxonomy):
        """资格闸原边界保持:sibling 产品与混合源标签不入围(§9 不松动)。"""
        slugs = taxonomy.eligible_slugs(("ne101",))
        assert "ne301" not in slugs
        assert "ne503" not in slugs
        assert "wiki" not in slugs
        assert "website" not in slugs


class TestToolsSharedBucket:
    def test_battery_calculator_derives_tools(self, taxonomy):
        """#29:官方电池计算器页 = tools 共享桶(不再是 unknown)。"""
        derived = taxonomy.derive_product(
            "website",
            "website-camthink/tools/battery-calculator",
            "https://www.camthink.ai/tools/battery-calculator/",
        )
        assert derived.slug == "tools"
        assert derived.reason == "rule"

    def test_tools_eligible_for_covered_products(self, taxonomy):
        """tools 桶对 applies_to 产品入围(计算器覆盖 NE101/NE301 等)。"""
        slugs = taxonomy.eligible_slugs(("ne101",))
        assert "tools" in slugs
        assert "tools" in taxonomy.eligible_slugs(("ne301",))

    def test_specific_tool_rule_beats_generic(self, taxonomy):
        """特异性优先:ai-tool-stack 仍是 aitoolstack(不被 /tools/ 遮蔽)。"""
        assert (
            taxonomy.derive_product(
                "website",
                "website-camthink/tools/ai-tool-stack",
                "https://www.camthink.ai/tools/ai-tool-stack/",
            ).slug
            == "aitoolstack"
        )

    def test_unrelated_pages_still_unknown(self, taxonomy):
        """非工具、非产品页保持 unknown(禁止猜测原则不变)。"""
        assert (
            taxonomy.derive_product(
                "website", "website-camthink/about", "https://www.camthink.ai/about/"
            ).slug
            == "unknown"
        )
