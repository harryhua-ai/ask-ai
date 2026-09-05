"""Issue #19 comparison correctness — 单元测试(Track A v1.0.1)。

覆盖 Discovery 冻结合约的可确定性单元面:
- per-target 候选合并的结构化归属保证(RC1: starvation 不可再发生);
- 比较不足语义键与文案(Evidence Contract / Empty-Generation Contract);
- 商店设备身份派生与类别映射排序(Store Identity Contract,RC2)。
"""

from types import SimpleNamespace

import pytest

from backend.pipeline.product_resolver import resolve_products
from backend.pipeline.rag import _merge_per_target_candidates
from backend.product_taxonomy import get_taxonomy
from backend.utils.user_messages import (
    COMPARISON_EVIDENCE_INSUFFICIENT_KEY,
    MESSAGE_KEYS,
)


@pytest.fixture(scope="module")
def taxonomy():
    return get_taxonomy()


def _r(
    product: str,
    source_id: str,
    chunk_index: int,
    score: float = 0.5,
    chunk_type: str = "paragraph",
):
    return SimpleNamespace(
        product=product,
        source_id=source_id,
        chunk_index=chunk_index,
        score=score,
        text="",
        title="",
        url="",
        chunk_type=chunk_type,
    )


class TestPerTargetMerge:
    def test_starved_side_gets_structured_quota(self, taxonomy):
        """RC1 核心回归:单侧在单融合列表中被语义排序挤出 → per-target
        路检索 + 轮转配额后,双侧标注证据都必须在候选中。"""
        # 模拟 F1 场景:ne302 路检索回大量 ne302;ne301 路仅回 1 条
        # (商店页,迁移后已标 ne301)
        fused_ne302 = [_r("ne302", f"wiki/302/{i}", i) for i in range(6)]
        fused_ne301 = [_r("ne301", "store/ne301", 0)]
        targets = ("ne302", "ne301")
        own, _rest, stage = _merge_per_target_candidates(
            [fused_ne302, fused_ne301], targets, taxonomy, top_k=4
        )
        assert own["ne301"], "per-target 配额必须保证每侧标注证据进入候选"
        assert own["ne302"]
        assert stage["per_target_quota"]["missing_after_merge"] == []
        assert stage["per_target_quota"]["quota"] == 2

    def test_official_evidence_fills_quota_before_code(self, taxonomy):
        """T-COMPARISON-EVIDENCE-CORRECTNESS C1/C2(H1 修复):目标自有候选
        分层选取 —— 非代码官方产品证据先占配额,代码只补余量。"""
        fused = [
            [_r("ne301", f"fw/{i}", i, chunk_type="code") for i in range(5)]
            + [_r("ne301", "wiki/301/overview", 0, chunk_type="paragraph")]
        ]
        own, _rest, stage = _merge_per_target_candidates(fused, ("ne301",), taxonomy, top_k=4)
        kept_types = [r.chunk_type for r in own["ne301"]]
        # tier1 官方证据先占坑(排首),代码只补余量(quota=4,tier1 池=1)
        assert kept_types[0] == "paragraph", "官方产品证据必须先于代码进入配额"
        assert kept_types.count("code") == 3
        assert stage["per_target_quota"]["tier1_kept"]["ne301"] == 1

    def test_missing_side_is_reported(self, taxonomy):
        fused = [[_r("ne302", "wiki/302/0", 0)], []]
        own, _rest, stage = _merge_per_target_candidates(
            fused, ("ne302", "ne301"), taxonomy, top_k=4
        )
        assert stage["per_target_quota"]["missing_after_merge"] == ["ne301"]
        assert own["ne301"] == []

    def test_shared_evidence_counts_for_neither_target(self, taxonomy):
        # top_k=5 → quota=2/侧,rest_cap=1(共享/平台证据有回填槽位)
        fused = [[_r("aitoolstack", "store/x", 0), _r("ne301", "wiki/301/0", 0)]]
        _own, rest, stage = _merge_per_target_candidates(
            fused, ("ne302", "ne301"), taxonomy, top_k=5
        )
        assert stage["per_target_quota"]["own_kept"]["ne301"] == 1
        assert stage["per_target_quota"]["own_kept"]["ne302"] == 0
        assert stage["per_target_quota"]["missing_after_merge"] == ["ne302"]
        # 共享/平台证据仍可作 rest 槽位保留
        assert any((r.product or "") == "aitoolstack" for r in rest)

    def test_cross_path_dedupe(self, taxonomy):
        fused = [
            [_r("ne302", "wiki/302/0", 0)],
            [_r("ne302", "wiki/302/0", 0), _r("ne301", "wiki/301/0", 0)],
        ]
        own, rest, _ = _merge_per_target_candidates(fused, ("ne302", "ne301"), taxonomy, top_k=6)
        merged = own["ne302"] + own["ne301"] + rest
        keys = [(r.source_id, r.chunk_index) for r in merged]
        assert len(keys) == len(set(keys))


class TestComparisonInsufficiencySemantics:
    def test_key_is_frozen(self):
        assert "comparison_evidence_insufficient" in MESSAGE_KEYS

    def test_reply_names_missing_side(self, taxonomy):
        from backend.pipeline.product_resolver import ProductResolution
        from backend.pipeline.rag import _comparison_insufficient_reply

        resolution = ProductResolution("comparison", ("ne302", "ne301"), "query")
        text, key = _comparison_insufficient_reply("zh-cn", resolution, taxonomy, ("ne301",))
        assert key == COMPARISON_EVIDENCE_INSUFFICIENT_KEY
        assert "NE301" in text and "NE302" in text

    def test_resolver_produces_comparison_for_f1_query(self, taxonomy):
        r = resolve_products("NE302 和 NE301 有什么区别?", taxonomy=taxonomy)
        assert r.mode == "comparison"
        assert r.targets == ("ne302", "ne301")


class TestStoreDeviceIdentity:
    def _connector(self):
        from backend.connectors.registry import ConnectorRegistry, SourceConfig

        cfg = SourceConfig(
            id="woocommerce-mall",
            type="woocommerce",
            product="commercial",
            enabled=True,
            config={
                "store_url": "https://store.example.com",
                "consumer_key": "ck_test",
                "consumer_secret": "cs_test",
            },
            sync_interval="1h",
        )
        return ConnectorRegistry.create(cfg)

    def test_device_identity_from_name(self, taxonomy):
        from backend.connectors.woocommerce import _device_identity_from_text

        assert _device_identity_from_text("NeoEyes NE301 Wireless Edge AI Camera ne301") == "ne301"
        assert _device_identity_from_text("NG4500 Jetson Orin Nano/NX AI Box ng4500") == "ng4500"
        # 平台桶不是设备身份
        assert _device_identity_from_text("AI ToolStack Suite aitoolstack") is None
        assert _device_identity_from_text("") is None

    def test_category_device_wins_over_broad(self):
        connector = self._connector()
        assert (
            connector._category_to_product([{"name": "AI Cameras"}, {"name": "NE301"}]) == "ne301"
        )
        assert connector._category_to_product([{"name": "AI Cameras"}]) == "aitoolstack"

    def test_product_to_document_prefers_name_identity(self, taxonomy):
        connector = self._connector()
        doc = connector._product_to_document(
            {
                "id": 2092,
                "name": "NeoEyes NE301 Wireless Edge AI Camera",
                "slug": "ne301",
                "price": "69",
                "categories": [{"name": "AI Cameras"}, {"name": "NE301"}],
                "short_description": "",
                "description": "",
            }
        )
        assert doc.product == "ne301"
