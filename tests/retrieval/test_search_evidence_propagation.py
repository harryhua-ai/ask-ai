"""INC-2a 检索传播测试:evidence 语义在全部检索投影中存活(契约 A5/§13)。"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.evidence_meta import EVIDENCE_PROPERTIES
from backend.retrieval.search import HybridSearcher, SearchResult

_EVIDENCE_FULL = {
    "evidence_authority_class": "case-example",
    "evidence_temporality": "unknown",
    "evidence_sensitivity": "internal",
    "evidence_citation_eligibility": "background-declared",
    "evidence_origin": "DUDD",
}


def _searcher_with(objs: list, capture: dict | None = None) -> HybridSearcher:
    emb = MagicMock()
    emb.dimension = 8
    emb.embed.return_value = [np.ones(8)]
    client = MagicMock()
    collection = MagicMock()

    def _hybrid(**kwargs):
        if capture is not None:
            capture.setdefault("hybrid", []).append(kwargs)
        res = MagicMock()
        res.objects = objs
        return res

    def _bm25(**kwargs):
        if capture is not None:
            capture.setdefault("bm25", []).append(kwargs)
        res = MagicMock()
        res.objects = objs
        return res

    collection.query.hybrid.side_effect = _hybrid
    collection.query.bm25.side_effect = _bm25
    client.collections.get.return_value = collection
    return HybridSearcher(client, emb)


def _obj(with_evidence: bool = True) -> MagicMock:
    obj = MagicMock()
    obj.properties = {
        "text": "t",
        "source_id": "fs/case-1",
        "source_type": "filesystem",
        "product": "knowledge",
        "title": "case",
        "url": "",
        "chunk_index": 0,
        "chunk_type": "paragraph",
        "doc_section": "",
        "channel_visibility": ["widget", "api"],
        "symbol_name": "",
        "symbol_signature": "",
        "branch": "main",
    }
    if with_evidence:
        obj.properties.update(_EVIDENCE_FULL)
    obj.metadata = MagicMock(distance=0.05)
    return obj


@pytest.mark.unit
def test_main_hybrid_search_propagates_evidence():
    """主 hybrid 路径(不限 return_properties):对象上的证据字段进 SearchResult。"""
    searcher = _searcher_with([_obj(with_evidence=True)])
    results = searcher.search("q")
    r = results[0]
    assert r.evidence_authority_class == "case-example"
    assert r.evidence_sensitivity == "internal"
    assert r.evidence_citation_eligibility == "background-declared"
    assert r.evidence_temporality == "unknown"
    assert r.evidence_origin == "DUDD"


@pytest.mark.unit
def test_legacy_object_missing_evidence_reads_as_unknown():
    """存量对象缺证据属性 → 显式 unknown/空 origin,不越权解释(契约 §12)。"""
    searcher = _searcher_with([_obj(with_evidence=False)])
    r = searcher.search("q")[0]
    assert r.evidence_authority_class == "unknown"
    assert r.evidence_temporality == "unknown"
    assert r.evidence_sensitivity == "unknown"
    assert r.evidence_citation_eligibility == "unknown"
    assert r.evidence_origin == ""


@pytest.mark.unit
def test_searchresult_defaults_explicit_unknown():
    """直接构造(无证据参数)= 显式 unknown 缺省,零回归。"""
    r = SearchResult(
        text="t",
        source_id="s",
        source_type="github",
        product="p",
        title="t",
        url="u",
        score=0.5,
        chunk_index=0,
    )
    assert r.evidence_authority_class == "unknown"
    assert r.evidence_citation_eligibility == "unknown"
    assert r.evidence_origin == ""


@pytest.mark.unit
def test_symbol_and_bucket_paths_whitelist_include_evidence():
    """search_symbols / search_bucket 两条显式投影(bm25)都含全部证据属性
    (契约 §13:不静默丢失)。主 hybrid 路径不限投影(全量返回)。"""
    capture: dict = {}
    searcher = _searcher_with([], capture)
    searcher.search_symbols("sym")
    searcher.search_bucket("q", source_types=["filesystem"])
    assert len(capture.get("bm25", [])) == 2, "应两次调用 bm25(symbols + bucket)"
    for call in capture["bm25"]:
        assert set(EVIDENCE_PROPERTIES) <= set(call["return_properties"])


@pytest.mark.unit
def test_bucket_path_whitelist_includes_evidence():
    """search_bucket 显式投影包含全部证据属性(比较管线 boost 桶同源)。"""
    capture: dict = {}
    searcher = _searcher_with([], capture)
    searcher.search_bucket("q", source_types=["filesystem"])
    assert capture["bm25"], "应调用 bm25"
    returned = set(capture["bm25"][0]["return_properties"])
    assert set(EVIDENCE_PROPERTIES) <= returned
