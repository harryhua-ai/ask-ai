"""产品 taxonomy(Canonical Product Identity)单元测试。

冻结契约(Issue #5 Implementation §1):
- canonical product / aliases / shared-platform / unknown;
- 大小写与历史标签漂移必须 canonicalize;
- taxonomy 中没有的值不得猜测归属(canonicalize 返回 None → unknown)。
"""

import pytest

from backend.product_taxonomy import (
    DerivedProduct,
    get_taxonomy,
    load_taxonomy,
)


@pytest.fixture(scope="module")
def taxonomy():
    """仓库真实 taxonomy 配置(config/product_taxonomy.yaml)。"""
    return get_taxonomy()


# --------------------------------------------------------------------------- #
# canonicalize:原始标签 → canonical slug(大小写/历史漂移收敛)
# --------------------------------------------------------------------------- #


class TestCanonicalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # 精确与大小写漂移
            ("ne503", "ne503"),
            ("NE503", "ne503"),
            (" Ne301 ", "ne301"),
            # 历史标签漂移(生产实证,Discovery §5)
            ("AI-ToolStack", "aitoolstack"),
            ("ai-toolstack", "aitoolstack"),
            ("meta-hailo-os", "ne503"),
            ("neomind-dashboard", "neomind"),
            ("neomind-devicetype", "neomind"),
            ("neomind-extensions", "neomind"),
            ("neoruntime-apps", "neoruntime"),
            ("neoruntime-sdks", "neoruntime"),
            ("online-store", "commercial"),
            ("accessories", "commercial"),
        ],
    )
    def test_canonicalize_known_labels(self, taxonomy, raw, expected):
        assert taxonomy.canonicalize(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",          # 空
            "   ",       # 空白
            "wiki",      # 混合源标签:不可 canonicalize(推导规则负责)
            "website",   # 同上
            "some-junk", # 未登记
            "ne999",     # 不存在的型号:禁止猜测
        ],
    )
    def test_canonicalize_unknown_returns_none(self, taxonomy, raw):
        assert taxonomy.canonicalize(raw) is None


# --------------------------------------------------------------------------- #
# extract_products:文本 → canonical slugs(查询侧高置信信号)
# --------------------------------------------------------------------------- #


class TestExtractProducts:
    def test_single_model_zh_adjacency(self, taxonomy):
        # 中文无词边界:型号紧邻汉字也必须命中
        assert taxonomy.extract_products("NE503怎么升级固件?") == ("ne503",)

    def test_multiple_models_ordered_by_appearance(self, taxonomy):
        assert taxonomy.extract_products("ne301 和 ne503 哪个好") == ("ne301", "ne503")

    def test_alias_with_brand_prefix(self, taxonomy):
        assert taxonomy.extract_products("NeoEye NE503 的续航如何") == ("ne503",)

    def test_case_insensitive(self, taxonomy):
        assert taxonomy.extract_products("neoeye ne503 和 NEOEYE NE301") == ("ne503", "ne301")

    def test_platform_aliases(self, taxonomy):
        assert taxonomy.extract_products("NeoMind 怎么添加设备") == ("neomind",)
        assert taxonomy.extract_products("NG4500 vs ne301") == ("ng4500", "ne301")

    def test_digit_boundary_no_false_positive(self, taxonomy):
        # 数字边界:KNE503 / ne5030 不得命中
        assert taxonomy.extract_products("KNE503") == ()
        assert taxonomy.extract_products("ne5030 是什么") == ()
        assert taxonomy.extract_products("HTTP 301 跳转怎么配") == ()

    def test_no_product_returns_empty(self, taxonomy):
        assert taxonomy.extract_products("这个设备支持什么?") == ()
        assert taxonomy.extract_products("CamThink 有哪些产品?") == ()


# --------------------------------------------------------------------------- #
# deixis:设备指代词(歧义检测输入)
# --------------------------------------------------------------------------- #


class TestDeixis:
    @pytest.mark.parametrize(
        "text",
        [
            "这个设备支持什么?",
            "该设备怎么激活?",
            "这款产品防水吗",
            "这个摄像头能装在车上吗",
            "What can this device do?",
            "How do I reset this camera?",
        ],
    )
    def test_deixis_detected(self, taxonomy, text):
        assert taxonomy.has_device_deixis(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "怎么升级固件",
            "CamThink 有哪些产品?",
            "NE503 支持热成像吗?",
            "今天天气怎么样",
        ],
    )
    def test_no_deixis(self, taxonomy, text):
        assert taxonomy.has_device_deixis(text) is False


# --------------------------------------------------------------------------- #
# derive_product:文档级产品推导(ingest 与迁移共用同一条代码路径)
# --------------------------------------------------------------------------- #


class TestDeriveProduct:
    def test_wiki_series_path_rules(self, taxonomy):
        d = taxonomy.derive_product(
            "wiki",
            "wiki-documents-local/main/docs/6-neoeyes-ne503-series/1-quick-start.md",
            "https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/1-quick-start.md",
        )
        assert d == DerivedProduct(slug="ne503", reason="rule")

    def test_wiki_shared_section(self, taxonomy):
        d = taxonomy.derive_product(
            "wiki", "wiki-documents-local/main/docs/3-hardware-dev-resources/10-5g-module.md", ""
        )
        assert d == DerivedProduct(slug="hardware-common", reason="rule")

    def test_wiki_unmapped_tooling_doc_is_unknown(self, taxonomy):
        d = taxonomy.derive_product(
            "wiki", "wiki-documents-local/main/.image-upload/README_cn.md", ""
        )
        assert d == DerivedProduct(slug="unknown", reason="none")

    def test_label_canonicalization_fallback(self, taxonomy):
        d = taxonomy.derive_product("ne301", "ne301-local/main/README.md", "")
        assert d == DerivedProduct(slug="ne301", reason="canonical")

    def test_legacy_label_fallback(self, taxonomy):
        d = taxonomy.derive_product(
            "meta-hailo-os", "meta-hailo-os-local/main/README.md", ""
        )
        assert d.slug == "ne503"
        assert d.reason == "canonical"

    def test_website_product_url_rules(self, taxonomy):
        d = taxonomy.derive_product(
            "website", "website-camthink/product/neoeyes-ne503",
            "https://www.camthink.ai/product/neoeyes-ne503/",
        )
        assert d == DerivedProduct(slug="ne503", reason="rule")

    def test_website_url_variant_503(self, taxonomy):
        d = taxonomy.derive_product(
            "website", "website-camthink/product/neoeyes-503",
            "https://www.camthink.ai/product/neoeyes-503/",
        )
        assert d.slug == "ne503"

    def test_website_unmapped_page_is_unknown(self, taxonomy):
        d = taxonomy.derive_product(
            "website", "website-camthink/blog/zone-intrusion",
            "https://www.camthink.ai/blog/zone-intrusion-detection-camera-system-guide/",
        )
        assert d == DerivedProduct(slug="unknown", reason="none")

    def test_wiki_i18n_mirror_tree_follows_primary_series(self, taxonomy):
        """Unknown Closure(#5):i18n 镜像树翻译文档与主树同系列 → 同产品。

        `i18n/en/docusaurus-plugin-content-docs/current/<系列>/…` 是主树
        `docs/<系列>/…` 的翻译镜像;系列 token 相同,确定性规则(纯追加,
        既有冻结 token 不动)。UI 字符串/目录标签/镜像索引页不命中,留 unknown。
        """
        mirror = "wiki-documents-local/main/i18n/en/docusaurus-plugin-content-docs/current"
        cases = [
            (f"{mirror}/6-neoeyes-ne503-series/3-software-guide/0-system-architecture.md", "ne503"),
            (f"{mirror}/5-neoeyes-ne301-series/0-overview.md", "ne301"),
            (f"{mirror}/8-neoeyes-ne302-series/1-quick-start.md", "ne302"),
            (f"{mirror}/2-neoeyes-ne101-series/1-quick-start.md", "ne101"),
            (f"{mirror}/1-neoedge-ng4500-series/4-FAQs.md", "ng4500"),
            (f"{mirror}/0-neomind/developer-guide/1-overview.md", "neomind"),
            (f"{mirror}/3-hardware-dev-resources/1-ssd.md", "hardware-common"),
            (f"{mirror}/4-ai-application/0-cinfer-ai-Inference-service/0-quick-start.md", "ai-common"),
            (f"{mirror}/7-release-notes/0-firmware.md", "release-notes"),
        ]
        for path, expected in cases:
            d = taxonomy.derive_product("wiki", path, "")
            assert d.slug == expected, path
            assert d.reason == "rule", path

    def test_wiki_i18n_site_chrome_stays_unknown(self, taxonomy):
        """Unknown Closure(#5):镜像树的站点附件(UI 串/目录标签/索引)不命中规则。"""
        mirror = "wiki-documents-local/main/i18n/en/docusaurus-plugin-content-docs/current"
        for path in (
            "wiki-documents-local/main/i18n/en/code.json",
            "wiki-documents-local/main/i18n/en/docusaurus-theme-classic/navbar.json",
            f"{mirror}.json",
            f"{mirror}/index.md",
            f"{mirror}/sidebars.js",
        ):
            d = taxonomy.derive_product("wiki", path, "")
            assert d.slug == "unknown", path

    def test_website_ai_tool_stack_page_is_aitoolstack(self, taxonomy):
        """Unknown Closure(#5):/tools/ai-tool-stack 官方页 = aitoolstack 平台身份。

        与既有 ``/product/neomind`` 规则同类:URL 显式路径 + 平台别名身份,
        确定性规则,非兄弟页推断。工具族其它页面(battery-calculator、
        tools 索引)不因同前缀被过匹配,保持 unknown(非产品事实来源)。
        """
        hit = taxonomy.derive_product(
            "website", "website-camthink/tools/ai-tool-stack",
            "https://www.camthink.ai/tools/ai-tool-stack/",
        )
        assert hit == DerivedProduct(slug="aitoolstack", reason="rule")
        # 防过匹配:同前缀工具页不受该规则影响
        assert taxonomy.derive_product(
            "website", "website-camthink/tools/battery-calculator",
            "https://www.camthink.ai/tools/battery-calculator/",
        ).slug == "unknown"
        assert taxonomy.derive_product(
            "website", "website-camthink/tools",
            "https://www.camthink.ai/tools/",
        ).slug == "unknown"

    def test_woocommerce_labels_pass_through_canonical(self, taxonomy):
        assert taxonomy.derive_product("ne503", "woocommerce-mall/0", "").slug == "ne503"
        assert taxonomy.derive_product("accessories", "woocommerce-mall/1", "").slug == "commercial"

    def test_derivation_is_idempotent(self, taxonomy):
        """推导结果再推导必须幂等(migration 可安全重跑)。"""
        first = taxonomy.derive_product(
            "wiki", "wiki-documents-local/main/docs/6-neoeyes-ne503-series/a.md", ""
        )
        second = taxonomy.derive_product(first.slug, "same/source_id.md", "")
        assert second.slug == first.slug


# --------------------------------------------------------------------------- #
# eligible_slugs / eligible_labels:检索资格集合
# --------------------------------------------------------------------------- #


class TestEligibility:
    def test_exact_target_expands_shared_and_platform(self, taxonomy):
        slugs = taxonomy.eligible_slugs(("ne503",))
        # 目标自身
        assert "ne503" in slugs
        # 平台( applies_to 含 ne503)+ 其历史标签
        assert "neoruntime" in slugs
        # 共享桶
        assert "hardware-common" in slugs
        assert "ai-common" in slugs
        assert "release-notes" in slugs
        assert "knowledge" in slugs
        # sibling 与通用桶绝不入围
        assert "ne301" not in slugs
        assert "ne101" not in slugs
        assert "wiki" not in slugs
        assert "website" not in slugs
        assert "commercial" not in slugs

    def test_exact_target_includes_legacy_labels_for_retrieval(self, taxonomy):
        labels = set(taxonomy.eligible_labels(("ne503",)))
        assert "ne503" in labels
        assert "meta-hailo-os" in labels          # 历史标签(迁移前兜底)
        assert "neoruntime-apps" in labels
        assert "ne301" not in labels

    def test_neomind_target(self, taxonomy):
        slugs = taxonomy.eligible_slugs(("neomind",))
        assert "neomind" in slugs
        assert "ne301" not in slugs
        assert "knowledge" in slugs  # support 桶对全平台共享

    def test_comparison_mode_union(self, taxonomy):
        slugs = taxonomy.eligible_slugs(("ne301", "ne503"))
        assert "ne301" in slugs and "ne503" in slugs
        assert "neoruntime" in slugs  # 任一目标适用即入围(any-target 语义)
        assert "ne101" not in slugs

    def test_empty_targets_empty_scope(self, taxonomy):
        assert taxonomy.eligible_slugs(()) == frozenset()
        assert taxonomy.eligible_labels(()) == []


# --------------------------------------------------------------------------- #
# 展示名与实体查询
# --------------------------------------------------------------------------- #


class TestDisplayAndKinds:
    def test_display_name(self, taxonomy):
        assert taxonomy.display_name("ne503") == "NeoEye NE503"
        assert taxonomy.display_name("ne301") == "NeoEye NE301"

    def test_display_name_unmapped_returns_raw(self, taxonomy):
        assert taxonomy.display_name("wiki") == "wiki"

    def test_targetable_kinds_are_product_and_platform_only(self, taxonomy):
        assert taxonomy.is_targetable("ne503") is True
        assert taxonomy.is_targetable("neomind") is True
        # shared/support/store 不是可解析目标
        assert taxonomy.is_targetable("knowledge") is False
        assert taxonomy.is_targetable("commercial") is False
        assert taxonomy.is_targetable("ne999") is False


# --------------------------------------------------------------------------- #
# 加载与缓存
# --------------------------------------------------------------------------- #


def test_load_taxonomy_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_taxonomy(tmp_path / "nope.yaml")


def test_get_taxonomy_cached(taxonomy):
    assert get_taxonomy() is taxonomy
