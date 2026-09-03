"""Target Product Resolution(Issue #5 契约 §2)单元测试。

冻结优先级:explicit user product → 查询内显式型号 → page/host context →
conversation-established(仅指代追问)→ ambiguous => clarify。
禁止低置信度猜测:不可解析的显式 hint = unsupported;无信号不猜 = none。
"""

import pytest

from backend.pipeline.product_resolver import resolve_products


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
