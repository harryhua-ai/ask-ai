"""Target Product Resolution(Issue #5 契约 §2)单元测试。

冻结优先级:explicit user product → 查询内显式型号 → page/host context →
conversation-established(仅指代追问)→ ambiguous => clarify。
禁止低置信度猜测:不可解析的显式 hint = unsupported;无信号不猜 = none。
"""

import pytest

from backend.pipeline.product_resolver import has_comparison_intent, resolve_products


@pytest.fixture(scope="module")
def taxonomy():
    from backend.product_taxonomy import get_taxonomy

    return get_taxonomy()


def _resolve(taxonomy, query, *, page_context=None, history=None, explicit_hint=None):
    return resolve_products(
        query,
        page_context=page_context,
        history=history,
        explicit_hint=explicit_hint,
        taxonomy=taxonomy,
    )


class TestExplicitHint:
    def test_known_hint_resolves_exact(self, taxonomy):
        r = _resolve(taxonomy, "怎么升级固件", explicit_hint="NE503")
        assert r.mode == "exact"
        assert r.targets == ("ne503",)
        assert r.source == "explicit"

    def test_unknown_hint_is_unsupported(self, taxonomy):
        r = _resolve(taxonomy, "怎么升级固件", explicit_hint="NE999")
        assert r.mode == "unsupported"
        assert r.targets == ()

    def test_hint_outranks_query_mention(self, taxonomy):
        r = _resolve(taxonomy, "NE301 参数", explicit_hint="ne503")
        assert r.mode == "exact"
        assert r.targets == ("ne503",)


class TestQueryMention:
    def test_single_query_product(self, taxonomy):
        r = _resolve(taxonomy, "NE503怎么升级固件?")
        assert r.mode == "exact"
        assert r.targets == ("ne503",)
        assert r.source == "query"

    def test_two_products_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "NE301 和 NE503 哪个续航长?")
        assert r.mode == "comparison"
        assert r.targets == ("ne301", "ne503")

    def test_query_mention_outranks_page_context(self, taxonomy):
        r = _resolve(
            taxonomy,
            "NE301 多少钱",
            page_context={"product": "NE503"},
        )
        assert r.mode == "exact"
        assert r.targets == ("ne301",)
        assert r.source == "query"


class TestPageContext:
    def test_page_context_establishes_target(self, taxonomy):
        r = _resolve(taxonomy, "怎么升级固件", page_context={"product": "NE503"})
        assert r.mode == "exact"
        assert r.targets == ("ne503",)
        assert r.source == "page_context"

    def test_page_context_product_id_canonicalizes(self, taxonomy):
        r = _resolve(taxonomy, "怎么升级固件", page_context={"product_id": "ne503"})
        assert r.mode == "exact"
        assert r.targets == ("ne503",)

    def test_page_context_unmapped_value_ignored_not_guessed(self, taxonomy):
        r = _resolve(taxonomy, "CamThink 有哪些产品?", page_context={"product": "some-gadget"})
        assert r.mode == "none"
        assert r.targets == ()


class TestConversationHistory:
    def test_deixis_with_history_establishes_target(self, taxonomy):
        history = [
            {"role": "user", "content": "NE503 支持热成像吗?"},
            {"role": "assistant", "content": "NeoEye NE503 支持……"},
        ]
        r = _resolve(taxonomy, "这个设备的续航怎么样?", history=history)
        assert r.mode == "exact"
        assert r.targets == ("ne503",)
        assert r.source == "history"

    def test_history_without_deixis_not_applied(self, taxonomy):
        history = [{"role": "user", "content": "NE503 支持热成像吗?"}]
        r = _resolve(taxonomy, "你们公司在哪里?", history=history)
        assert r.mode == "none"

    def test_history_conflict_is_ambiguous(self, taxonomy):
        history = [
            {"role": "user", "content": "NE301 好用吗?"},
            {"role": "user", "content": "NE503 好用吗?"},
        ]
        r = _resolve(taxonomy, "这个设备防水吗?", history=history)
        assert r.mode == "ambiguous"


class TestAmbiguityAndNone:
    def test_deixis_without_context_is_ambiguous(self, taxonomy):
        r = _resolve(taxonomy, "这个设备支持什么?")
        assert r.mode == "ambiguous"
        assert r.targets == ()

    def test_plain_question_without_signals_is_none(self, taxonomy):
        r = _resolve(taxonomy, "CamThink 是哪家公司?")
        assert r.mode == "none"
        assert r.source == "none"


class TestComparisonIntentGate:
    """I002-COMPARISON-GATE-CORRECTIVE-V1 §11:多实体共现 ≠ 比较意图。

    比较模式需查询内正证据(确定性比较/取舍语);集成/兼容/配置类
    Product→Platform 关系保留全部目标作用域,走常规 exact 路径。
    """

    # A. RCA 回归类(zh):HOW_TO 提及平台,不是产品对比
    def test_zh_integration_howto_not_comparison(self, taxonomy):
        r = _resolve(taxonomy, "NE101 如何接入 AI ToolStack？")
        assert r.mode == "exact"
        assert r.targets == ("ne101", "aitoolstack")
        assert r.detail.get("multi_entity") is True

    # B. EN 等价
    def test_en_integration_howto_not_comparison(self, taxonomy):
        r = _resolve(taxonomy, "How do I connect NE101 to AI ToolStack?")
        assert r.mode == "exact"
        assert r.targets == ("ne101", "aitoolstack")

    # C. 兼容关系问句
    def test_en_compatibility_not_comparison(self, taxonomy):
        r = _resolve(taxonomy, "Does NE101 work with AI ToolStack?")
        assert r.mode == "exact"
        assert r.targets == ("ne101", "aitoolstack")

    # C 变体:部署关系(HOW do I deploy X using Y)
    def test_deploy_using_not_comparison(self, taxonomy):
        r = _resolve(taxonomy, "How do I deploy NE503 using AI ToolStack?")
        assert r.mode == "exact"
        assert r.targets == ("ne503", "aitoolstack")

    # D. 显式英文比较
    def test_en_explicit_compare_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "Compare NE101 and NE503.")
        assert r.mode == "comparison"
        assert r.targets == ("ne101", "ne503")

    # D 变体
    def test_en_vs_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "NE101 vs NE503: which is better for edge vision?")
        assert r.mode == "comparison"

    # E. 显式中文比较
    def test_zh_difference_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "NE101 和 NE503 有什么区别？")
        assert r.mode == "comparison"
        assert r.targets == ("ne101", "ne503")

    # F. 取舍比较
    def test_zh_choice_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "NE101 和 NE503 哪个更适合部署这个方案？")
        assert r.mode == "comparison"

    # F 变体:还是(双实体语境下取舍)
    def test_zh_haishi_choice_is_comparison(self, taxonomy):
        r = _resolve(taxonomy, "选 NE101 还是 NE503？")
        assert r.mode == "comparison"

    # 实体保真(§6):平台实体仍被识别,只是不再触发比较
    def test_entities_remain_detected(self, taxonomy):
        r = _resolve(taxonomy, "NE101 如何接入 AI ToolStack？")
        assert "aitoolstack" in r.targets and "ne101" in r.targets

    # 对照:单实体不受影响;显式 hint 优先级不变
    def test_single_entity_unaffected(self, taxonomy):
        r = _resolve(taxonomy, "NE101 怎么升级固件?")
        assert r.mode == "exact"
        assert r.targets == ("ne101",)
        assert "multi_entity" not in r.detail

    # 确定性检测器直测:边界用例
    def test_marker_precision(self, taxonomy):
        assert has_comparison_intent("NE301 和 NE503 相比如何")
        assert has_comparison_intent("How does NE101 compare with NE503?")
        assert not has_comparison_intent("NE101 如何接入 AI ToolStack？")
        assert not has_comparison_intent("分别介绍 NE101 和 NE503 的包装清单")
