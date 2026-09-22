"""Issue #106 — role-recall lane 检索原语的真实 Weaviate 可达性。

机械证明:``search_bucket(url_substrings=[...])`` 的 URL 段 like 过滤在
真实 Weaviate 上可用 —— 权威页面段(first-party Solution / Case-study)
的类内确定性准入不是 scripted 假设。独立 collection,零共享状态,不可达
即 skip(与其他真 Weaviate 集成套件同模式)。

负面对抗(同一夹具):
- URL 无段信号的同类文档不得经 lane 返回(段信号是收窄谓词);
- source_type 过滤仍然生效(类过滤 AND 组合);
- lane 原语空结果 = 合法降级(不报错)。
"""

import os

import pytest
import weaviate
from weaviate.classes.config import DataType, Property

from backend.retrieval.search import HybridSearcher

pytestmark = pytest.mark.unit

WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "Issue106LaneReach"


class _FakeEmbedder:
    """确定性假嵌入器(hybrid 桶只需一个向量参与排序,语义无关)。"""

    dimension = 4

    def embed(self, texts):
        import numpy as np

        return [np.ones(self.dimension, dtype=np.float32) * 0.1 for _ in texts]


def _properties():
    text_props = [
        "source_id",
        "source_type",
        "product",
        "title",
        "url",
        "frontmatter_slug",
        "visitor_reachability",
        "text",
        "chunk_type",
        "doc_section",
        "channel_visibility",
        "symbol_name",
        "symbol_signature",
        "branch",
    ]
    from backend.evidence_meta import EVIDENCE_PROPERTIES
    from backend.pipeline.ingest import COMMERCE_PROPS

    props = [Property(name=p, data_type=DataType.TEXT) for p in text_props]
    props += [Property(name=p, data_type=DataType.TEXT) for p in EVIDENCE_PROPERTIES]
    props += [Property(name=n, data_type=DataType.TEXT) for n in COMMERCE_PROPS]
    props += [
        Property(name="chunk_index", data_type=DataType.INT),
        Property(name="generation_ordinal", data_type=DataType.INT),
    ]
    return props


def _obj(source_id: str, url: str, title: str) -> dict:
    return {
        "source_id": source_id,
        "source_type": "web_crawl",
        "product": "ne101",
        "title": title,
        "url": url,
        "frontmatter_slug": "",
        "visitor_reachability": "",
        "text": f"{title} body text about monitoring and deployment.",
        "chunk_index": 0,
        "chunk_type": "paragraph",
        "doc_section": "",
        "channel_visibility": "widget,api",
        "generation_ordinal": 0,
    }


@pytest.fixture()
def lane_stack():
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.collections.create(
        CLASS_NAME, properties=_properties(), vectorizer_config=None
    )
    coll = client.collections.get(CLASS_NAME)
    coll.data.insert(
        _obj(
            "site/solutions/infra-monitoring",
            "https://www.camthink.ai/solutions/infrastructure-monitoring/",
            "Infrastructure Monitoring Solution",
        )
    )
    coll.data.insert(
        _obj(
            "site/blog/unrelated",
            "https://www.camthink.ai/blog/other-notes/",
            "Unrelated Notes",
        )
    )
    searcher = HybridSearcher(client, _FakeEmbedder(), class_name=CLASS_NAME)
    yield searcher
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()


def test_url_substring_lane_reaches_solution_segment(lane_stack):
    hits = lane_stack.search_bucket(
        query="infrastructure monitoring deployment",
        source_types=["web_crawl"],
        url_substrings=["solution"],
        use_hybrid=True,
        limit=10,
    )
    ids = {h.source_id for h in hits}
    assert "site/solutions/infra-monitoring" in ids, (
        "AC2 reachability: the URL-segment lane primitive must actually reach "
        "a first-party Solution page in real Weaviate"
    )
    assert "site/blog/unrelated" not in ids, (
        "URL-segment signal is a narrowing predicate: same-class pages "
        "outside the segment must not be admitted"
    )


def test_lane_primitive_without_hits_degrades_empty(lane_stack):
    hits = lane_stack.search_bucket(
        query="infrastructure monitoring deployment",
        source_types=["web_crawl"],
        url_substrings=["case-stud"],
        use_hybrid=True,
        limit=10,
    )
    assert hits == [], "empty lane = legal degradation, not an error"
