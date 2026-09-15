"""Issue #84 RED:authoritative 文档已删除/更名后,旧 identity 向量仍具 serving 资格。

生产事故(canonical replay case,会话 01a0a460-f24d-7d76-b365-48888c653821):

- 权威上游 ``wiki-documents`` 中 ``2-sdk-reference.md`` 已删除(两处 identity
  均 404);
- #71 membership 对账已把账本行墓碑(Document.lifecycle='deleted',墓碑时刻
  09:22:20,早于会话 09:23:45)——账本面正确;
- 但旧 identity 的 Weaviate 对象属 legacy 初始代(generation_ordinal=0),而
  ordinal 0 因数百在服文档共享而始终位于**全局在服代集合**;
- 检索资格仅由全局 generation_ordinal 过滤 + HISTORICAL 前缀排除构成,
  **不存在 per-document lifecycle 资格过滤** → 旧 chunk 进入候选集
  (hybrid rank 23 → rerank kept → citation_no=5)→ 回答引用旧 URL → 404。

本文件冻结 GREEN 后必须成立的产品不变量(Acceptance 3/4/5):

1. 墓碑/被接替 identity 的向量对象,即使其 generation_ordinal 仍被其他
   在服文档共享,也不得进入检索证据;
2. 同代共存下,新权威 identity / 其他在服文档必须可正常检索(零误伤)。

测试以 fixture 级假 Weaviate 复现生产过滤机制:服务端 INT
``generation_ordinal`` contains_any 过滤(经既有测试接缝
``_generation_ordinal_filter`` 注入,与 ``tests/retrieval/test_search_generation_filter.py``
同一 monkeypatch 面),不依赖生产数据、不依赖 Postgres。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.retrieval.search import HybridSearcher

# 事故真实 identity(生产 lineage replay 证据;
# source_id 身份 = <source>/<branch>/<rel_path>,URL 由 connector 以同键构造)。
STALE_SOURCE_ID = (
    "wiki-documents-local/main/docs/6-neoeyes-ne503-series/"
    "4-application-guide/1-app-development/reference/2-sdk-reference.md"
)
STALE_URL_404 = (
    "https://github.com/camthink-ai/wiki-documents/blob/main/docs/"
    "6-neoeyes-ne503-series/4-application-guide/1-app-development/reference/"
    "2-sdk-reference.md"
)
SUCCESSOR_SOURCE_ID = (
    "wiki-documents-local/main/docs/6-neoeyes-ne503-series/"
    "4-application-guide/2-sdk-reference-new.md"
)
SUCCESSOR_URL = (
    "https://github.com/camthink-ai/wiki-documents/blob/main/docs/"
    "6-neoeyes-ne503-series/4-application-guide/2-sdk-reference-new.md"
)
SERVING_SOURCE_ID = "wiki-documents-local/main/docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md"

# 生产在服代集合事实(2026-09-15 replay):legacy ordinal 0 因海量在服文档
# current_version 挂靠而始终 active;墓碑文档对象同属 ordinal 0。
ACTIVE_ORDINALS = [0]


class _GenerationOrdinalFilter:
    """服务端 INT 在服代过滤的等价形态(monkeypatch 注入用)。"""


class _AllOf:
    def __init__(self, parts):
        self.parts = parts


class _FakeQuery:
    """按生产语义应用已注入过滤的假 Weaviate query 面(hybrid/bm25)。"""

    def __init__(self, objects):
        self._objects = objects

    @staticmethod
    def _passes(props, flt):
        if flt is None:
            return True
        if isinstance(flt, _GenerationOrdinalFilter):
            return props.get("generation_ordinal") in flt.ordinals
        if isinstance(flt, _AllOf):
            return all(_FakeQuery._passes(props, p) for p in flt.parts)
        # 本测试只建模生产在用的 INT 在服代过滤;其他过滤形态按服务端
        # 透传处理(不得因假件缺能力而掩盖被测不变量)。
        return True

    def hybrid(self, *, filters=None, **_kw):
        return SimpleNamespace(
            objects=[
                SimpleNamespace(properties=p, metadata=SimpleNamespace(distance=0.2))
                for p in self._objects
                if self._passes(p, filters)
            ]
        )

    def bm25(self, *, filters=None, **_kw):
        return self.hybrid(filters=filters)


class _FakeCollection:
    def __init__(self, objects):
        self.query = _FakeQuery(objects)


class _FakeClient:
    def __init__(self, collection):
        self._collections = SimpleNamespace(get=lambda _name: collection)

    @property
    def collections(self):  # weaviate 客户端同形:client.collections.get(name)
        return self._collections


class _FakeEmbedder:
    dimension = 8

    def embed(self, texts):
        return [np.array([0.1] * 8) for _ in texts]


def _obj(source_id, url, *, generation_ordinal=0, text="chunk body"):
    """生产同构 Weaviate 对象 properties(INC-2a 证据属性缺省同检索读面)。"""
    return {
        "source_id": source_id,
        "source_type": "github",
        "product": "ne503",
        "title": "2-sdk-reference",
        "text": text,
        "url": url,
        "chunk_index": 0,
        "generation_ordinal": generation_ordinal,
        "channel_visibility": ["widget", "api"],
    }


@pytest.fixture()
def incident_collection(monkeypatch):
    """同代共存场景:在服文档 + 墓碑旧 identity(+更名场景的新 identity),
    全部 generation_ordinal=0 —— 与生产 replay 完全同构。"""
    objects = [
        _obj(SERVING_SOURCE_ID, "https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md"),
        _obj(STALE_SOURCE_ID, STALE_URL_404, text="SDK reference (authoritative copy deleted upstream)"),
        _obj(SUCCESSOR_SOURCE_ID, SUCCESSOR_URL, text="SDK reference (new authoritative path)"),
    ]
    collection = _FakeCollection(objects)

    def _fake_filter(ordinals):
        f = _GenerationOrdinalFilter()
        f.ordinals = sorted(ordinals)
        return f

    monkeypatch.setattr(
        "backend.retrieval.search._generation_ordinal_filter", _fake_filter
    )
    # 生产 wiring(main.py lifespan):全局在服代集合供给(含 ordinal 0)。
    monkeypatch.setattr(
        HybridSearcher,
        "_active_generation_ordinals",
        lambda self: list(ACTIVE_ORDINALS),
    )
    return collection


def _make_searcher(collection) -> HybridSearcher:
    return HybridSearcher(
        _FakeClient(collection),
        _FakeEmbedder(),
        generation_filter_provider=lambda: list(ACTIVE_ORDINALS),
    )


def test_tombstoned_identity_not_served_even_in_shared_generation(incident_collection):
    """RED(事故主形态):账本已墓碑的旧 identity 不得进入检索证据。

    生产事实:墓碑先于会话(09:22:20 < 09:23:45),但其 gen-0 对象通过全局
    在服代过滤进入候选集并被引用(citation_no=5 → 404)。GREEN 后本断言
    必须成立;当前实现无 per-document 资格过滤 → 必然失败(RED)。
    """
    searcher = _make_searcher(incident_collection)
    results = searcher.search("NE503 SDK 在哪里")

    served_ids = [r.source_id for r in results]
    assert STALE_SOURCE_ID not in served_ids, (
        "墓碑文档的向量对象仍在全局在服代过滤下进入检索证据:"
        f"served={served_ids}(事故:旧 URL {STALE_URL_404} 已 404)"
    )


def test_serving_documents_unaffected_by_stale_exclusion(incident_collection):
    """同代共存零误伤:在服文档与新权威 identity 必须仍可检索(Acceptance 5)。"""
    searcher = _make_searcher(incident_collection)
    results = searcher.search("NE503 SDK 在哪里")
    served_ids = {r.source_id for r in results}
    assert SERVING_SOURCE_ID in served_ids
    assert SUCCESSOR_SOURCE_ID in served_ids


def test_withdrawn_url_never_exposed_as_evidence(incident_collection):
    """RED(URL 面):墓碑 identity 的 source URL 不得出现在任何检索结果中。"""
    searcher = _make_searcher(incident_collection)
    results = searcher.search("NE503 SDK 在哪里")
    assert STALE_URL_404 not in {r.url for r in results}


def test_bucket_and_symbol_paths_share_the_same_invariant(incident_collection):
    """RED(boost 桶/符号召回与主路径同一资格不变量)。"""
    searcher = _make_searcher(incident_collection)
    bucket_ids = [
        r.source_id
        for r in searcher.search_bucket(
            "SDK", source_types=["github"], channel="widget"
        )
    ]
    assert STALE_SOURCE_ID not in bucket_ids
    symbol_ids = [
        r.source_id for r in searcher.search_symbols("BatteryReadI2C", channel="widget")
    ]
    assert STALE_SOURCE_ID not in symbol_ids


def test_incident_fixture_matches_production_shape(incident_collection):
    """表征性锚点(当前必 FAIL 的前提自证):fixture 与生产机制同构 ——
    旧对象 ordinal ∈ 全局在服代集合(=0),即当前过滤器放行它。"""
    w = MagicMock()
    w.collections.get.return_value = incident_collection
    s = _make_searcher(incident_collection)
    results = s.search("NE503 SDK 在哪里")
    stale_served = [r for r in results if r.source_id == STALE_SOURCE_ID]
    assert stale_served, (
        "前提自证失败:当前实现下墓碑对象应被放行(该断言锚定 RED 前提;"
        "GREEN 后本测试需随机制更新)"
    )
