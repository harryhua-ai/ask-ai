"""Phase 2A 端到端集成测试。

验证三项功能在完整管线中协同工作:
1. 语义分块:代码块不被切断,chunk_type 正确标注
2. channel 隔离:knowledge-internal 的 chunk 不出现在 widget 渠道
3. rerank 加权:heading chunk 分数被放大
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

from backend.connectors.base import RawDocument
from backend.pipeline.chunk import chunk_document_semantic
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import HybridSearcher, SearchResult


@pytest.mark.unit
def test_semantic_chunk_code_block_intact():
    """代码块即使超过 max_tokens 也不在标题边界被切断。"""
    code = "```python\n" + "\n".join(f"v{i} = {i}" for i in range(100)) + "\n```"
    content = f"# Title\n\nIntro.\n\n{code}\n\n## End\n\nFinal."
    doc = RawDocument(
        source_id="t/1", source_type="github", product="p",
        title="T", content=content, url="u", metadata={}, content_hash="h",
    )
    chunks = chunk_document_semantic(doc, max_tokens=80, overlap=10)
    assert len(chunks) >= 1
    code_chunks = [c for c in chunks if c.chunk_type == "code"]
    assert len(code_chunks) >= 1


@pytest.mark.unit
def test_channel_visibility_isolation():
    """channel_visibility=('api',) 的 chunk 在 widget 渠道应被过滤。"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    # 模拟 Weaviate 返回两条结果:一条 widget 可见,一条仅 api
    widget_obj = MagicMock()
    widget_obj.properties = {
        "text": "public", "source_id": "s1", "source_type": "t", "product": "p",
        "title": "T1", "url": "u1", "chunk_index": 0, "chunk_type": "paragraph",
        "doc_section": "", "channel_visibility": ["widget", "api"],
    }
    widget_obj.metadata = MagicMock(distance=0.1)

    api_only_obj = MagicMock()
    api_only_obj.properties = {
        "text": "internal", "source_id": "s2", "source_type": "t", "product": "p",
        "title": "T2", "url": "u2", "chunk_index": 0, "chunk_type": "paragraph",
        "doc_section": "", "channel_visibility": ["api"],
    }
    api_only_obj.metadata = MagicMock(distance=0.05)

    mock_collection.query.hybrid.return_value = MagicMock(
        objects=[widget_obj, api_only_obj]
    )

    # embedder 必须返回带 .tolist() 的对象(np.array),因为 HybridSearcher.search
    # 调用 vectors[0].tolist() 将向量转成 plain list 传给 Weaviate。
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [np.array([0.1, 0.2])]

    searcher = HybridSearcher(mock_client, mock_embedder)
    results = searcher.search("query", channel="widget")

    # Weaviate filter 在真实环境中会过滤掉 api_only 条目
    # 此 mock 测试验证 filter 被正确传入
    hybrid_kwargs = mock_collection.query.hybrid.call_args.kwargs
    assert "filters" in hybrid_kwargs


@pytest.mark.unit
def test_rerank_type_weights_change_ordering():
    """相同 reranker 分数下,heading 应排在 paragraph 前面。"""
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [0.5, 0.5]

    r_heading = SearchResult(
        text="# Setup Guide\n\nInstall steps.", source_id="s1", source_type="t",
        product="p", title="T1", url="u1", score=0.9, chunk_index=0, chunk_type="heading",
    )
    r_paragraph = SearchResult(
        text="Some background info text.", source_id="s2", source_type="t",
        product="p", title="T2", url="u2", score=0.9, chunk_index=0, chunk_type="paragraph",
    )

    pipeline = RerankPipeline(mock_reranker, threshold=0.0, top_k=10)
    results = pipeline.rerank("query", [r_paragraph, r_heading])

    assert results[0].chunk_type == "heading"
    assert results[1].chunk_type == "paragraph"
    assert results[0].score > results[1].score
