"""P0-A: prune 文档局部性不变量(PRUNE IS DOCUMENT-LOCAL)回归测试。

背景(PA-0F 生产事故):`_prune_stale_chunks` 用 TEXT 属性 `source_id` 的
`equal` 过滤删除陈旧 chunk,而 Weaviate 对 TEXT 的过滤是**分词语义**:
`equal("site/blog")` 会命中 `site/blog/ai-species` 等所有共享 token 的兄弟
文档 → 收缩文档的 prune 误删同前缀兄弟文档的 chunks(生产实证:web_crawl
359 → 163,逐篇"4/4 成功"后仅剩 chunk 0)。

修复契约:prune 只能删除由**本文档自己的** (source_id, chunk_index) 决定性
UUID(`uuid5(NAMESPACE_URL, f"{source_id}#{i}")`)点名的对象;旧 chunk 上界
取自 Postgres 账本读数,账本不可得时 fail-safe 不删(残留交一致性校验披露)。

- 单元测试:结构断言(delete 过滤只含 by_id CONTAINS_ANY + 自己的 uuid 列表)。
- 集成测试:真实 Weaviate 1.28 上证明文档局部性,并固化「TEXT equal 分词
  陷阱」语义守卫(旧破坏行为的复现回归)。
"""

import uuid as uuid_mod
from contextlib import contextmanager

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import Base, Document
from backend.pipeline.ingest import IngestionPipeline, _deterministic_uuid


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # sqlite 测试库无 JSONB,等价渲染为 JSON
    return "JSON"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #


def _make_doc(**overrides: object) -> RawDocument:
    defaults: dict[str, object] = {
        "source_id": "site/blog/ai-species",
        "source_type": "web_crawl",
        "product": "website",
        "title": "AI species",
        "content": "NE503 specs",
        "url": "https://site/blog/ai-species",
        "metadata": {"path": "ai-species.html"},
        "content_hash": "h1",
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return RawDocument(**defaults)  # type: ignore[arg-type]


def _make_embedder(dim: int = 8) -> object:
    from unittest.mock import MagicMock

    emb = MagicMock()
    emb.dimension = dim
    emb.embed.side_effect = lambda texts: [np.array([0.1] * dim) for _ in texts]
    return emb


def _make_client() -> tuple:
    from unittest.mock import MagicMock

    client = MagicMock()
    collection = MagicMock()
    collection.name = "Document"
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    return client, collection


def _own_uuids(sid: str, lo: int, hi: int) -> list[str]:
    return [_deterministic_uuid(sid, i) for i in range(lo, hi)]


def _is_id_contains_any(where: object, expected_uuids: list[str]) -> bool:
    """断言 delete 过滤是 by_id CONTAINS_ANY 且值恰为期望 uuid 列表。"""
    if where is None or getattr(where, "value", None) is None:
        return False
    if getattr(where.operator, "name", None) != "CONTAINS_ANY":
        return False
    # by_id 过滤的 target 不携带普通属性名(source_id 过滤会带 property="source_id")
    if getattr(getattr(where, "target", None), "property", None) == "source_id":
        return False
    return sorted(str(v) for v in where.value) == sorted(expected_uuids)


@pytest.fixture
def sqlite_session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    yield maker
    engine.dispose()


def _seed_ledger(session_factory, source_id: str, chunk_count: int) -> None:
    with session_factory() as s:
        s.add(
            Document(
                content_hash=f"h-{source_id}",
                source_id=source_id,
                source_type="web_crawl",
                product="website",
                title="t",
                url=f"https://x/{source_id}",
                branch="",
                chunk_count=chunk_count,
            )
        )
        s.commit()


def _ledger_count(session_factory, source_id: str) -> int | None:
    with session_factory() as s:
        row = s.query(Document).filter(Document.source_id == source_id).one_or_none()
        return None if row is None else row.chunk_count


# --------------------------------------------------------------------------- #
# 单元:prune 结构不变量
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_prune_uses_only_own_deterministic_uuids():
    """prune 只能发 by_id CONTAINS_ANY,且 uuid 列表恰为本文档 stale 区间。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)

    pipe._prune_stale_chunks("site/blog", 1, previous_count=4)

    collection.data.delete_many.assert_called_once()
    where = collection.data.delete_many.call_args.kwargs["where"]
    assert _is_id_contains_any(where, _own_uuids("site/blog", 1, 4))


@pytest.mark.unit
def test_prune_no_shrink_is_noop():
    """previous_count <= current_count(无收缩/增长)不得发任何删除。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)

    pipe._prune_stale_chunks("site/blog", 4, previous_count=4)
    pipe._prune_stale_chunks("site/blog", 6, previous_count=4)

    collection.data.delete_many.assert_not_called()


@pytest.mark.unit
def test_prune_unknown_previous_count_is_fail_safe_noop():
    """账本读数不可得(previous_count=None)→ fail-safe 不删,只告警。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)

    pipe._prune_stale_chunks("site/blog", 1, previous_count=None)

    collection.data.delete_many.assert_not_called()


@pytest.mark.unit
def test_prune_uuid_list_is_document_local_by_construction():
    """同 token / 同前缀兄弟文档的 uuid 不可能出现在本文档的 stale 列表里。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)

    pipe._prune_stale_chunks("site/blog", 1, previous_count=6)

    where = collection.data.delete_many.call_args.kwargs["where"]
    got = sorted(str(v) for v in where.value)
    forbidden: set[str] = set()
    for sibling in (
        "site/blog/ai-species",
        "site/blog/5-things",
        "site/blog/x",
        "other/site/blog",
        "site/blogg",
    ):
        forbidden.update(_own_uuids(sibling, 0, 10))
    assert not (set(got) & forbidden)
    assert got == sorted(_own_uuids("site/blog", 1, 6))


# --------------------------------------------------------------------------- #
# 单元:账本读数
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_get_stored_chunk_count_reads_ledger(sqlite_session_factory):
    _seed_ledger(sqlite_session_factory, "site/blog", 4)
    pipe = IngestionPipeline(
        _make_embedder(), _make_client()[0], session_factory=sqlite_session_factory
    )
    assert pipe._get_stored_chunk_count("site/blog") == 4
    assert pipe._get_stored_chunk_count("site/never-seen") is None


@pytest.mark.unit
def test_get_stored_chunk_count_without_session_is_none():
    pipe = IngestionPipeline(_make_embedder(), _make_client()[0])
    assert pipe._get_stored_chunk_count("site/blog") is None


# --------------------------------------------------------------------------- #
# 单元:灌入路径集成(收缩/增长/幂等/部分失败)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingest_document_shrink_prunes_only_own_stale_chunks(sqlite_session_factory):
    """文档 4 chunk → 1 chunk:只删自己的 #1..#3,账本同步为 1。"""
    client, collection = _make_client()
    _seed_ledger(sqlite_session_factory, "site/blog/ai-species", 4)
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    pipe.ingest_document(_make_doc(content="short", content_hash="h2"))

    collection.data.delete_many.assert_called_once()
    where = collection.data.delete_many.call_args.kwargs["where"]
    assert _is_id_contains_any(where, _own_uuids("site/blog/ai-species", 1, 4))
    assert _ledger_count(sqlite_session_factory, "site/blog/ai-species") == 1


@pytest.mark.unit
def test_ingest_document_first_ingest_no_ledger_no_prune():
    """首次灌入(账本无行)→ 无旧集合,不得发删除。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)
    pipe.ingest_document(_make_doc())
    collection.data.delete_many.assert_not_called()


@pytest.mark.unit
def test_ingest_document_grow_updates_ledger_without_prune(sqlite_session_factory):
    """2 → 4 chunk 增长:无 stale,不发删除;账本更新为 4。"""
    client, collection = _make_client()
    _seed_ledger(sqlite_session_factory, "site/blog/ai-species", 2)
    long_content = " ".join(["word"] * 4000)  # 足够切出多 chunk
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    pipe.ingest_document(_make_doc(content=long_content, content_hash="h3"))
    collection.data.delete_many.assert_not_called()
    assert _ledger_count(sqlite_session_factory, "site/blog/ai-species") > 2


@pytest.mark.unit
def test_repeated_identical_ingest_is_idempotent_no_prune(sqlite_session_factory):
    """重复同内容灌入:第二轮 previous==current,无删除;账本计数稳定。"""
    client, collection = _make_client()
    doc = _make_doc(content=" ".join(["word"] * 1500), content_hash="h4")
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    first = pipe.ingest_document(doc)
    calls_after_first = collection.data.delete_many.call_count
    second = pipe.ingest_document(doc)
    assert first == second > 0
    # 第二轮可能收缩(分块确定性 → 不收缩);只要不新增删除即可
    assert collection.data.delete_many.call_count == calls_after_first
    assert _ledger_count(sqlite_session_factory, doc.source_id) == first


@pytest.mark.unit
def test_batch_path_prunes_document_local_for_each_doc(sqlite_session_factory):
    """ingest_all 批路径:两个 token 重叠兄弟各自收缩,删除互不越界。"""
    client, collection = _make_client()
    _seed_ledger(sqlite_session_factory, "site/blog", 4)
    _seed_ledger(sqlite_session_factory, "site/blog/ai-species", 3)
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    pipe.ingest_all(
        [
            _make_doc(source_id="site/blog", content="x", content_hash="b1"),
            _make_doc(source_id="site/blog/ai-species", content="y", content_hash="b2"),
        ]
    )
    where_args = [c.kwargs["where"] for c in collection.data.delete_many.call_args_list]
    assert any(_is_id_contains_any(w, _own_uuids("site/blog", 1, 4)) for w in where_args)
    assert any(_is_id_contains_any(w, _own_uuids("site/blog/ai-species", 1, 3)) for w in where_args)


@pytest.mark.unit
def test_batch_partial_failure_no_prune(sqlite_session_factory):
    """批路径写库彻底失败 → 不 prune(防误删后又写失败造成更大缺口)。"""
    client, collection = _make_client()
    _seed_ledger(sqlite_session_factory, "site/blog", 4)
    collection.data.insert_many.side_effect = Exception("read-only")
    collection.data.replace.side_effect = Exception("read-only")
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    with pytest.raises(RuntimeError, match="灌入失败"):
        pipe.ingest_all([_make_doc(source_id="site/blog", content="x", content_hash="b9")])
    collection.data.delete_many.assert_not_called()


# --------------------------------------------------------------------------- #
# 单元:delete_document(增量同步删除路径同样必须 document-local)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_delete_document_removes_only_own_uuids_and_ledger_row(sqlite_session_factory):
    client, collection = _make_client()
    _seed_ledger(sqlite_session_factory, "site/blog", 3)
    pipe = IngestionPipeline(_make_embedder(), client, session_factory=sqlite_session_factory)
    pipe.delete_document("site/blog")

    collection.data.delete_many.assert_called_once()
    where = collection.data.delete_many.call_args.kwargs["where"]
    assert _is_id_contains_any(where, _own_uuids("site/blog", 0, 3))
    assert _ledger_count(sqlite_session_factory, "site/blog") is None


@pytest.mark.unit
def test_delete_document_without_ledger_is_fail_safe():
    """账本无行(计数不可知)→ 不发删除(不能退回 token 化过滤)。"""
    client, collection = _make_client()
    pipe = IngestionPipeline(_make_embedder(), client)
    pipe.delete_document("site/ghost")
    collection.data.delete_many.assert_not_called()


# --------------------------------------------------------------------------- #
# 集成:真实 Weaviate 1.28(不可达时 skip;本地已实证)
# --------------------------------------------------------------------------- #


def _real_weaviate_collection():
    import weaviate

    port = int(__import__("os").environ.get("P0A_WEAVIATE_PORT", "21100"))
    try:
        client = weaviate.connect_to_local("localhost", port)
    except Exception:  # noqa: BLE001 - 本地无 Weaviate 时跳过集成断言
        return None
    return client


@pytest.fixture
def real_client():
    client = _real_weaviate_collection()
    if client is None:
        pytest.skip("local Weaviate 1.28 不可达(P0A_WEAVIATE_PORT)")
    import weaviate.classes.config as wc

    if client.collections.exists("ProbeP0A"):
        client.collections.delete("ProbeP0A")
    client.collections.create(
        "ProbeP0A",
        properties=[
            wc.Property(name="source_id", data_type=wc.DataType.TEXT),
            wc.Property(name="chunk_index", data_type=wc.DataType.INT),
        ],
    )
    yield client
    client.collections.delete("ProbeP0A")
    client.close()


@pytest.fixture
def real_coll(real_client):
    return real_client.collections.get("ProbeP0A")


def _seed_real(coll, docs: dict[str, int]) -> None:
    import weaviate.classes.data as wd

    objs = [
        wd.DataObject(
            properties={"source_id": sid, "chunk_index": i},
            vector=[0.1] * 4,
            uuid=_deterministic_uuid(sid, i),
        )
        for sid, n in docs.items()
        for i in range(n)
    ]
    coll.data.insert_many(objs)


def _survivors(coll) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for item in coll.iterator(return_properties=["source_id", "chunk_index"]):
        out.setdefault(item.properties["source_id"], []).append(int(item.properties["chunk_index"]))
    return {k: sorted(v) for k, v in sorted(out.items())}


def test_weaviate_text_equal_is_tokenized_semantics_guard(real_coll):
    """语义守卫(旧破坏行为复现回归):TEXT equal('site/blog') 会命中
    同 token 兄弟文档 —— 平台行为一旦变化,本测试揭示其不再成立。"""
    from weaviate.classes.query import Filter

    _seed_real(real_coll, {"site/blog": 1, "site/blog/ai-species": 1, "site/index": 1})
    res = real_coll.query.fetch_objects(
        filters=Filter.by_property("source_id").equal("site/blog"), limit=100
    )
    matched = {o.properties["source_id"] for o in res.objects}
    assert "site/blog/ai-species" in matched  # 分词过匹配:这就是旧缺陷的土壤


def test_old_prune_filter_destructive_repro_real_weaviate(real_coll):
    """旧 prune 过滤的破坏性复现(固化事故):收缩文档的 filter-prune 会删光
    兄弟文档 chunk 1+。本测试用旧表达式在真实 Weaviate 上重演 PA-0F 症状。"""
    from weaviate.classes.query import Filter

    docs = {"site/blog": 4, "site/blog/ai-species": 4, "site/blog/5-things": 3, "site/index": 2}
    _seed_real(real_coll, docs)
    real_coll.data.delete_many(
        where=Filter.by_property("source_id").equal("site/blog")
        & Filter.by_property("chunk_index").greater_or_equal(1)
    )
    survivors = _survivors(real_coll)
    assert survivors["site/blog/ai-species"] == [0]  # 事故同款:4 → 仅剩 chunk 0
    assert survivors["site/blog/5-things"] == [0]
    assert survivors["site/index"] == [0, 1]  # 不含 blog token → 幸免


def test_prune_document_local_real_weaviate(real_coll, sqlite_session_factory):
    """核心验收:真实 Weaviate 上 prune 只删本文档 stale chunks。"""
    _seed_real(
        real_coll,
        {"site/blog": 4, "site/blog/ai-species": 4, "site/blog/5-things": 3, "site/index": 2},
    )
    pipe = IngestionPipeline(_make_embedder(), None, class_name="ProbeP0A")
    pipe._collection = real_coll
    pipe._prune_stale_chunks("site/blog", 1, previous_count=4)
    survivors = _survivors(real_coll)
    assert survivors == {
        "site/blog": [0],
        "site/blog/ai-species": [0, 1, 2, 3],
        "site/blog/5-things": [0, 1, 2],
        "site/index": [0, 1],
    }


def test_full_ingest_shrink_real_weaviate(real_client, sqlite_session_factory):
    """端到端:真实 Weaviate + 真实 chunker,文档多 chunk 收缩到 1,
    兄弟文档不受影响。"""
    sib = "site/blog/ai-species"
    _seed_real(real_client.collections.get("ProbeP0A"), {sib: 4})
    _seed_ledger(sqlite_session_factory, sib, 4)

    pipe = IngestionPipeline(
        _make_embedder(dim=4),
        real_client,
        class_name="ProbeP0A",
        max_tokens=30,
        overlap=0,
        session_factory=sqlite_session_factory,
    )
    sid = "site/blog"
    long_text = " ".join(f"paragraph{i}" for i in range(300))
    pipe.ingest_document(_make_doc(source_id=sid, content=long_text, content_hash="L1"))
    coll = real_client.collections.get("ProbeP0A")
    after_long = _survivors(coll)[sid]
    assert len(after_long) >= 3
    # 收缩:同 doc 换短内容
    pipe.ingest_document(_make_doc(source_id=sid, content="tiny", content_hash="L2"))
    survivors = _survivors(coll)
    assert survivors[sid] == [0]
    assert survivors[sib] == [0, 1, 2, 3]  # 兄弟文档不受影响
    assert _ledger_count(sqlite_session_factory, sid) == 1
    assert _ledger_count(sqlite_session_factory, sib) == 4
