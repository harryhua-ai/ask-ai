"""INC-2a 摄取传播测试:evidence 语义写入 Weaviate props(契约 A3/A4)。"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.connectors.base import RawDocument
from backend.evidence_meta import EVIDENCE_PROPERTIES
from backend.pipeline.ingest import COLLECTION_PROPERTIES, IngestionPipeline, _build_props


def _make_doc(source_type: str = "github", visibility: tuple = ("widget", "api")) -> RawDocument:
    return RawDocument(
        source_id="test/README.md",
        source_type=source_type,
        product="ne503",
        title="Test",
        content="NE503 specs 2.5W",
        url="https://github.com/test",
        metadata={"path": "README.md"},
        content_hash="abc123",
        channel_visibility=visibility,
    )


@pytest.mark.unit
def test_build_props_carries_evidence_meta():
    """_build_props 输出含 5 个证据字段,且与分类规则一致。"""
    props = _build_props(
        type(
            "C",
            (),
            {
                "text": "x",
                "chunk_index": 0,
                "doc_section": "",
                "chunk_type": "",
                "channel_visibility": ("widget", "api"),
                "symbol_name": "",
                "symbol_signature": "",
                "symbol_node_type": "",
                "symbol_tokens": "",
            },
        )(),
        _make_doc("github"),
    )
    for key in EVIDENCE_PROPERTIES:
        assert key in props, f"缺少 {key}"
    assert props["evidence_authority_class"] == "unknown"
    assert props["evidence_temporality"] == "unknown"
    # 修订 SAFETY-01:缺失 internal 标记 ⇒ sensitivity unknown(非 public)
    assert props["evidence_sensitivity"] == "unknown"
    assert props["evidence_citation_eligibility"] == "citable-numbered"
    assert props["evidence_origin"] == "UUUD"


@pytest.mark.unit
def test_build_props_filesystem_classification():
    """filesystem 源:case-example / internal / background-declared。"""
    doc = _make_doc("filesystem")
    props = _build_props(
        type(
            "C",
            (),
            {
                "text": "x",
                "chunk_index": 0,
                "doc_section": "",
                "chunk_type": "",
                "channel_visibility": ("widget", "api"),
                "symbol_name": "",
                "symbol_signature": "",
                "symbol_node_type": "",
                "symbol_tokens": "",
            },
        )(),
        doc,
    )
    # 修订 SAFETY-01:filesystem 仅凭 source_type 不得成为 case-example;
    # sensitivity 无显式标记 ⇒ unknown;组合语义镜像保留在 citation 维度
    assert props["evidence_authority_class"] == "unknown"
    assert props["evidence_sensitivity"] == "unknown"
    assert props["evidence_citation_eligibility"] == "background-declared"
    assert props["evidence_origin"] == "UUUD"


@pytest.mark.unit
def test_collection_properties_include_evidence():
    """建表 schema 单一定义点包含 5 个证据 property(新增安装路径)。"""
    names = [name for name, _ in COLLECTION_PROPERTIES]
    for key in EVIDENCE_PROPERTIES:
        assert key in names
    # 既有 16 字段保持在前(顺序不破坏旧迁移对照)
    assert names.index("symbol_tokens") < names.index("evidence_authority_class")


def _ingest_and_capture_props(tmp_path=None):
    """走完整 ingest_document,捕获写 Weaviate 的对象属性。"""
    client = MagicMock()
    collection = MagicMock()
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    emb = MagicMock()
    emb.dimension = 8
    emb.embed.side_effect = lambda texts: [np.ones(8) for _ in texts]
    pipeline = IngestionPipeline(emb, client, class_name="Document")
    doc = _make_doc("github")
    pipeline.ingest_document(doc)
    objs = collection.data.insert_many.call_args[0][0]
    return [o.properties for o in objs]


@pytest.mark.unit
def test_ingest_document_writes_evidence_props():
    """端到端:新摄取 chunk 落库即带证据语义(契约 A3)。"""
    props_list = _ingest_and_capture_props()
    assert props_list, "应有 chunk 写入"
    for props in props_list:
        assert props["evidence_sensitivity"] == "unknown"
        assert props["evidence_citation_eligibility"] == "citable-numbered"
        assert props["evidence_authority_class"] == "unknown"
        assert props["evidence_temporality"] == "unknown"
        assert props["evidence_origin"] == "UUUD"
