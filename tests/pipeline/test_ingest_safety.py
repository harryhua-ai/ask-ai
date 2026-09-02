"""Ingestion pipeline 技术安全第二道防线 + 文档级失败隔离测试(阶段1)。

- 伪装/无扩展名二进制内容在 chunk/tokenize/embed 之前被拒(管线层嗅探);
- 安全排除不计入 failed(文档级隔离:单坏文档不拖垮整轮);
- 含字面特殊 token(<|endoftext|>)的合法文档可正常灌入(R4 根因回归)。
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.connectors.base import RawDocument
from backend.pipeline.ingest import IngestionPipeline


def _doc(sid: str, content: str) -> RawDocument:
    return RawDocument(
        source_id=sid,
        source_type="github",
        product="t",
        title=sid,
        content=content,
        url="https://x",
        metadata={"path": f"{sid}.txt"},
        content_hash="h" + sid,
    )


def _pipeline(dim: int = 8) -> tuple[IngestionPipeline, MagicMock]:
    emb = MagicMock()
    emb.dimension = dim
    emb.embed.side_effect = lambda texts: [np.array([0.1] * dim) for _ in texts]
    client = MagicMock()
    client.collections.exists.return_value = True
    return IngestionPipeline(emb, client, class_name="Document"), emb


@pytest.mark.unit
def test_disguised_binary_rejected_before_chunk_and_embed():
    """二进制改名为 .txt:必须在 chunk/tokenize/embed 之前被拒(T3/T12)。"""
    pipeline, emb = _pipeline()
    chunk_spy = MagicMock(side_effect=AssertionError("chunker must not run"))
    with (
        patch("backend.pipeline.ingest.chunk_document_semantic", chunk_spy),
        patch("backend.pipeline.ingest.chunk_code", chunk_spy),
    ):
        count = pipeline.ingest_document(_doc("t/bin", "\x00\x01\x02HAILO" * 128))
    assert count == 0
    assert not emb.embed.called
    assert pipeline.safety_stats["reasons"].get("binary_content") == 1


@pytest.mark.unit
def test_ingest_all_safety_exclusion_is_document_level_not_failed():
    """单坏文档:计 0 + 安全排除,不进 failed(不触发 ingest_all raise)(T12/AC12)。"""
    pipeline, _ = _pipeline()
    docs = [
        _doc("t/good1", "正常文档内容 " * 50),
        _doc("t/bad", "\x7fELF\x00" + "\x01" * 512),
        _doc("t/good2", "另一篇正常文档 " * 50),
    ]
    results = pipeline.ingest_all(docs)  # 不得 raise
    assert results["t/bad"] == 0
    assert results["t/good1"] > 0 and results["t/good2"] > 0
    assert pipeline.safety_stats["excluded"] == 1


@pytest.mark.unit
def test_poor_decode_ratio_rejected():
    pipeline, emb = _pipeline()
    garbage = "abc\ufffd\ufffd\ufffd\ufffd" * 500  # 替换字符占比 ~50%
    count = pipeline.ingest_document(_doc("t/dec", garbage))
    assert count == 0 and not emb.embed.called
    assert pipeline.safety_stats["reasons"].get("poor_decode") == 1


@pytest.mark.unit
def test_special_token_literal_document_ingests_normally():
    """字面 <|endoftext|> 不再炸 tokenizer(R4 根因回归):正常出 chunk。"""
    pipeline, emb = _pipeline()
    content = "model output <|endoftext|> marker\n" * 40 + "tail"
    count = pipeline.ingest_document(_doc("t/tok", content))
    assert count >= 1
    assert emb.embed.called
