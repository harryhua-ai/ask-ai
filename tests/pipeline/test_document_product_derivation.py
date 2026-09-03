"""文档级产品推导接线(Issue #5 契约 §3)ingest 集成测试。

DataSource.product(源级出处)≠ document product identity(推导值):
ingest 写入 Weaviate/PG 账本的 ``product`` 必须是 taxonomy 推导结果
(wiki 系列目录/官网产品页规则 → canonical;不可判定 → unknown;禁止猜)。
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.connectors.base import RawDocument
from backend.pipeline.ingest import IngestionPipeline, _build_props


def _make_doc(**overrides) -> RawDocument:
    defaults = {
        "source_id": "wiki-documents-local/main/docs/6-neoeyes-ne503-series/1-quick-start.md",
        "source_type": "github",
        "product": "wiki",
        "title": "Quick Start",
        "content": "# NE503 快速开始\n\n第一步:安装。",
        "url": "https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/1-quick-start.md",
        "metadata": {"path": "docs/6-neoeyes-ne503-series/1-quick-start.md"},
        "content_hash": "hash-wiki-ne503",
    }
    defaults.update(overrides)
    return RawDocument(**defaults)  # type: ignore[arg-type]


def _make_pipeline() -> tuple[IngestionPipeline, MagicMock]:
    embedder = MagicMock()
    embedder.dimension = 8
    embedder.embed.side_effect = lambda texts: [np.array([0.1] * 8) for _ in texts]
    client = MagicMock()
    collection = MagicMock()
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    return IngestionPipeline(embedder, client, class_name="Document"), collection


@pytest.mark.unit
def test_build_props_derives_canonical_product():
    """chunk props 的 product = 推导值(wiki 系列目录 → ne503),非源标签。"""
    doc = _make_doc()
    chunks = [
        MagicMock(chunk_index=0, doc_section="", chunk_type="heading",
                  channel_visibility=("widget",), symbol_name="", symbol_signature="",
                  symbol_node_type="", symbol_tokens=""),
    ]
    props = _build_props(chunks[0], doc)
    assert props["product"] == "ne503"


@pytest.mark.unit
def test_ingest_writes_derived_product_to_weaviate():
    pipeline, collection = _make_pipeline()
    pipeline.ingest_document(_make_doc())
    kwargs = collection.data.insert_many.call_args[0][0]
    products = {obj.properties["product"] for obj in kwargs}
    assert products == {"ne503"}


@pytest.mark.unit
def test_ingest_legacy_label_canonicalized():
    """meta-hailo-os(历史标签)入库即 canonicalize 为 ne503。"""
    pipeline, collection = _make_pipeline()
    pipeline.ingest_document(
        _make_doc(
            source_id="meta-hailo-os-local/main/README.md",
            product="meta-hailo-os",
            title="OS README",
            content="# meta-hailo-os\n\nbuild steps。",
            metadata={"path": "README.md"},
            content_hash="hash-hailo",
        )
    )
    kwargs = collection.data.insert_many.call_args[0][0]
    assert {obj.properties["product"] for obj in kwargs} == {"ne503"}


@pytest.mark.unit
def test_ingest_unmapped_label_stays_unknown_not_guessed():
    """混合源未命中规则 → unknown(诚实;绝不猜成某个具体产品)。"""
    pipeline, collection = _make_pipeline()
    pipeline.ingest_document(
        _make_doc(
            source_id="wiki-documents-local/main/.image-upload/README.md",
            product="wiki",
            title="tooling",
            content="# image upload tool\n\nusage。",
            metadata={"path": ".image-upload/README.md"},
            content_hash="hash-tooling",
        )
    )
    kwargs = collection.data.insert_many.call_args[0][0]
    assert {obj.properties["product"] for obj in kwargs} == {"unknown"}
