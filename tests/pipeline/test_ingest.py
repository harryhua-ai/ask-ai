"""数据灌入管道(ingestion pipeline)单元测试。

覆盖:
- brief 基础 case(单 doc 写 Weaviate)
- 空 content / chunk_document 返回 [] 时跳过 Weaviate
- 单 doc 失败时 ingest_all 错误隔离
- 单 chunk 写 Weaviate 失败时跳过,不影响其他 chunk
- 提供 session_factory 时调用 Postgres upsert
- delete_document 同步删 Weaviate + Postgres
- _ensure_collection 在 collection 不存在时创建
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.connectors.base import RawDocument
from backend.pipeline.ingest import IngestionPipeline
from weaviate.classes.config import DataType


def _make_doc(**overrides: object) -> RawDocument:
    """构造默认 RawDocument,允许测试覆盖字段。"""
    defaults: dict[str, object] = {
        "source_id": "test/1",
        "source_type": "github",
        "product": "ne503",
        "title": "Test",
        "content": "NE503 specs",
        "url": "https://github.com/test",
        "metadata": {"path": "README.md"},
        "content_hash": "abc123",
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return RawDocument(**defaults)  # type: ignore[arg-type]


def _make_embedder(dim: int = 1024) -> MagicMock:
    """构造返回固定向量的 MagicMock embedder。"""
    emb = MagicMock()
    emb.dimension = dim
    emb.embed.return_value = [np.array([0.1] * dim)]
    return emb


def _make_weaviate_client() -> MagicMock:
    """构造 MagicMock Weaviate client,模拟 collections.exists=True / get 成功。"""
    client = MagicMock()
    collection = MagicMock()
    collection.name = "Document"  # 模拟已存在 collection
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    return client


# --------------------------------------------------------------------------- #
# brief 基础测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingest_document_stores_in_weaviate():
    """brief 用例:单 doc 应触发 embed + collection.data.insert。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()
    collection = client.collections.get.return_value

    doc = _make_doc()
    pipeline = IngestionPipeline(embedder, client, class_name="Document")
    pipeline.ingest_document(doc)

    embedder.embed.assert_called_once_with(["NE503 specs"])
    assert collection.data.insert_many.called


@pytest.mark.unit
def test_ingest_document_returns_chunk_count():
    """成功写入时应返回 chunk 数(此处 content 短,只切出 1 个 chunk)。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    pipeline = IngestionPipeline(embedder, client)
    count = pipeline.ingest_document(_make_doc())

    assert count == 1


@pytest.mark.unit
def test_ingest_raises_when_embedder_returns_mismatched_count():
    """embedder 返回向量数少于 chunk 数时应 RuntimeError,避免 zip 静默截断。"""
    embedder = MagicMock()
    embedder.dimension = 1024
    # 长内容 → 至少 2 个 chunk,但 embedder 只返回 1 个向量
    long_content = "# Title\n\n" + ("NE503 specs. " * 500)
    embedder.embed.return_value = [np.array([0.1] * 1024)]

    client = _make_weaviate_client()
    collection = client.collections.get.return_value

    pipeline = IngestionPipeline(embedder, client, max_tokens=100, overlap=10)
    with pytest.raises(RuntimeError, match="embedder 返回"):
        pipeline.ingest_document(_make_doc(content=long_content))

    # 校验失败时不应写入任何 chunk
    collection.data.insert.assert_not_called()


# --------------------------------------------------------------------------- #
# 空文档处理
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingest_skips_empty_document():
    """content 为空时 chunk_document 返回 [],不写 Weaviate / Postgres。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()
    collection = client.collections.get.return_value
    session_factory = MagicMock()

    pipeline = IngestionPipeline(embedder, client, session_factory=session_factory)
    count = pipeline.ingest_document(_make_doc(content=""))

    assert count == 0
    embedder.embed.assert_not_called()
    collection.data.insert.assert_not_called()
    session_factory.assert_not_called()


# --------------------------------------------------------------------------- #
# 错误隔离
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingest_all_isolates_per_doc_failure():
    """一个 doc 抛异常时,后续 doc 仍被处理,失败 doc 计为 0。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    docs = [_make_doc(source_id="ok/1"), _make_doc(source_id="bad/1")]
    pipeline = IngestionPipeline(embedder, client)

    # 让第二个 doc 在 ingest_document 阶段就抛(模拟 embed 异常)
    with patch.object(
        pipeline,
        "ingest_document",
        side_effect=[1, RuntimeError("boom")],
    ):
        results = pipeline.ingest_all(docs)

    assert results == {"ok/1": 1, "bad/1": 0}


@pytest.mark.unit
def test_ingest_document_isolates_per_chunk_failure():
    """单个 chunk 写 Weaviate 失败时,其他 chunk 仍正常写入。"""
    embedder = MagicMock()
    embedder.dimension = 1024
    # 长内容 → 多个 chunk;side_effect 根据输入数量动态返回向量,
    # 避免硬编码向量数(因 max_tokens/overlap 组合决定最终 chunk 数)
    long_content = "# Title\n\n" + ("NE503 specs. " * 500)
    embedder.embed.side_effect = lambda texts: [np.array([0.1] * 1024) for _ in texts]

    client = _make_weaviate_client()
    collection = client.collections.get.return_value

    # insert_many 整批失败 → 回退逐条;逐条路径第一个 chunk insert+replace 都失败,
    # 其余正常(新行为:insert_many 整批 except 回退逐条 insert,insert 失败试 replace)
    def _insert_many_side_effect(*args, **kwargs):
        raise RuntimeError("weaviate boom")

    def _insert_side_effect(*args, **kwargs):
        if collection.data.insert.call_count == 1:
            raise RuntimeError("weaviate boom")

    def _replace_boom(*args, **kwargs):
        raise RuntimeError("weaviate boom")

    collection.data.insert_many.side_effect = _insert_many_side_effect
    collection.data.insert.side_effect = _insert_side_effect
    collection.data.replace.side_effect = _replace_boom

    pipeline = IngestionPipeline(embedder, client, max_tokens=100, overlap=10)
    count = pipeline.ingest_document(_make_doc(content=long_content))

    # insert_many 整批失败 1 次;回退逐条时第一个 chunk insert+replace 都失败,
    # 其余成功;返回值 = 逐条 insert 调用数 - 1(第一个失败)
    assert collection.data.insert_many.call_count == 1
    assert collection.data.insert.call_count >= 2
    assert count == collection.data.insert.call_count - 1


@pytest.mark.unit
def test_ingest_document_isolates_postgres_failure():
    """Postgres upsert 失败不应影响 Weaviate 写入的返回值。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()
    session_factory = MagicMock()
    # 进入 with 块即抛
    session_factory.side_effect = RuntimeError("pg down")

    pipeline = IngestionPipeline(embedder, client, session_factory=session_factory)
    count = pipeline.ingest_document(_make_doc())

    # Weaviate 写入仍然成功
    assert count == 1


# --------------------------------------------------------------------------- #
# Postgres 写入
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingest_document_writes_postgres_when_new():
    """新 doc 应在 Postgres 插入 Document 行(content_hash 不存在)。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    # session_factory 返回上下文管理器,session.execute().scalar_one_or_none() = None
    session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result

    @contextmanager
    def _factory():
        yield session

    session_factory = MagicMock(side_effect=_factory)

    pipeline = IngestionPipeline(embedder, client, session_factory=session_factory)
    pipeline.ingest_document(_make_doc())

    # 应调用 session.add 插入新行,且 commit
    assert session.add.called
    session.commit.assert_called_once()


@pytest.mark.unit
def test_ingest_document_writes_postgres_when_existing():
    """已存在的 doc 应更新 chunk_count 而非重复插入。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    existing_doc = MagicMock()
    session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_doc
    session.execute.return_value = scalar_result

    @contextmanager
    def _factory():
        yield session

    session_factory = MagicMock(side_effect=_factory)

    pipeline = IngestionPipeline(embedder, client, session_factory=session_factory)
    pipeline.ingest_document(_make_doc())

    # 已存在时不应 add,只 commit
    session.add.assert_not_called()
    session.commit.assert_called_once()
    # chunk_count 应被更新为 1
    assert existing_doc.chunk_count == 1


# --------------------------------------------------------------------------- #
# delete_document
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_delete_document_removes_from_weaviate_and_postgres():
    """delete_document 应同步删 Weaviate + Postgres(若 session_factory 提供)。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()
    collection = client.collections.get.return_value

    session = MagicMock()

    @contextmanager
    def _factory():
        yield session

    session_factory = MagicMock(side_effect=_factory)

    pipeline = IngestionPipeline(embedder, client, session_factory=session_factory)
    pipeline.delete_document("test/1")

    collection.data.delete_many.assert_called_once()
    session.execute.assert_called()  # 至少一次 select / delete
    session.commit.assert_called_once()


@pytest.mark.unit
def test_delete_document_works_without_postgres():
    """未提供 session_factory 时 delete_document 仍能仅删 Weaviate。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()
    collection = client.collections.get.return_value

    pipeline = IngestionPipeline(embedder, client)
    pipeline.delete_document("test/1")

    collection.data.delete_many.assert_called_once()


# --------------------------------------------------------------------------- #
# _ensure_collection
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ensure_collection_creates_when_missing():
    """collections.exists=False 时应调用 collections.create,再 get 拿到代理。"""
    embedder = _make_embedder()
    client = MagicMock()
    # exists 返回 False,触发 create 分支
    client.collections.exists.return_value = False
    created_collection = MagicMock(name="created_collection")
    client.collections.create.return_value = created_collection
    gotten_collection = MagicMock(name="gotten_collection")
    client.collections.get.return_value = gotten_collection

    # mock weaviate.classes.config 以避免真实依赖
    with (
        patch("weaviate.classes.config.Configure") as configure_cls,
        patch("weaviate.classes.config.Property") as _,
        patch("weaviate.classes.config.DataType") as _,
    ):
        configure_cls.Vectorizer.none.return_value = MagicMock()

        pipeline = IngestionPipeline(embedder, client)
        pipeline.ingest_document(_make_doc())

        client.collections.create.assert_called_once()
        # 新逻辑下,create 之后总是 get 一次拿代理(而非把 create 的返回值当代理)
        client.collections.get.assert_called_once_with("Document")


@pytest.mark.unit
def test_ensure_collection_cached():
    """第二次 ingest 复用已获取的 collection,不重复 get。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    pipeline = IngestionPipeline(embedder, client)
    pipeline.ingest_document(_make_doc())
    pipeline.ingest_document(_make_doc())

    # 第二次 ingest 不应再次 get(缓存命中)
    assert client.collections.get.call_count == 1


# --------------------------------------------------------------------------- #
# Phase 2A: 新增 property / 字段写入
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ensure_collection_creates_new_properties():
    """_ensure_collection 应创建 channel_visibility / doc_section / chunk_type property。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline

    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_collection = MagicMock()
    mock_client.collections.create.return_value = None
    mock_client.collections.get.return_value = mock_collection

    pipeline = IngestionPipeline(
        embedder=MagicMock(), weaviate_client=mock_client, class_name="Document",
    )
    pipeline._ensure_collection()

    mock_client.collections.create.assert_called_once()
    create_kwargs = mock_client.collections.create.call_args
    property_names = [p.name if hasattr(p, "name") else p.get("name")
                      for p in create_kwargs.kwargs.get("properties", [])]
    assert "channel_visibility" in property_names
    assert "doc_section" in property_names
    assert "chunk_type" in property_names

    # 校验 DataType 映射(channel_visibility 必须是 TEXT_ARRAY,供 Task 6 channel 过滤)
    props_list = create_kwargs.kwargs.get("properties", [])

    def _dtype(name: str):
        for p in props_list:
            p_name = p.name if hasattr(p, "name") else p.get("name")
            if p_name == name:
                return p.dataType if hasattr(p, "dataType") else p.get("dataType")
        return None

    assert _dtype("channel_visibility") == DataType.TEXT_ARRAY
    assert _dtype("doc_section") == DataType.TEXT
    assert _dtype("chunk_type") == DataType.TEXT


@pytest.mark.unit
def test_ingest_document_writes_new_fields():
    """ingest_document 应把 channel_visibility / doc_section / chunk_type 写入 Weaviate。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument

    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_client.collections.get.return_value = mock_collection

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

    pipeline = IngestionPipeline(
        embedder=mock_embedder, weaviate_client=mock_client, class_name="Document",
    )

    doc = RawDocument(
        source_id="test/1", source_type="github", product="ne503",
        title="T", content="# Title\n\nContent.", url="u",
        metadata={}, content_hash="h", channel_visibility=("api",),
    )
    pipeline.ingest_document(doc)

    mock_collection.data.insert_many.assert_called()
    data_objs = mock_collection.data.insert_many.call_args.args[0]
    props = data_objs[0].properties
    assert "channel_visibility" in props
    assert props["channel_visibility"] == ["api"]
    assert "chunk_type" in props
    assert "doc_section" in props


@pytest.mark.unit
def test_ingest_document_uses_semantic_chunking():
    """ingest_document 应使用 chunk_document_semantic 而非 chunk_document。"""
    from unittest.mock import MagicMock, patch
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument

    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1]]

    pipeline = IngestionPipeline(
        embedder=mock_embedder, weaviate_client=mock_client, class_name="Document",
    )

    doc = RawDocument(
        source_id="t/1", source_type="github", product="p",
        title="T", content="# Heading\n\nText.", url="u",
        metadata={}, content_hash="h",
    )

    with patch("backend.pipeline.ingest.chunk_document_semantic") as mock_chunk:
        mock_chunk.return_value = []
        pipeline.ingest_document(doc)
        mock_chunk.assert_called_once()


# --------------------------------------------------------------------------- #
# Task 6: 代码分块路由 + branch 元数据
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_route_code_to_chunk_code():
    """代码扩展名(.py)的 doc 应走 chunk_code 而非 chunk_document_semantic。"""
    from unittest.mock import MagicMock, patch
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1]]
    pipeline = IngestionPipeline(embedder=mock_embedder, weaviate_client=mock_client)
    doc = RawDocument(
        source_id="r/main/m.py", source_type="local_git", product="p",
        title="m", content="def foo():\n    return 1\n", url="u",
        metadata={"path": "m.py"}, content_hash="h", branch="main",
    )
    with patch("backend.pipeline.ingest.chunk_document_semantic") as mock_semantic, \
         patch("backend.pipeline.ingest.chunk_code") as mock_code:
        mock_code.return_value = []
        pipeline.ingest_document(doc)
        mock_code.assert_called_once()
        mock_semantic.assert_not_called()


@pytest.mark.unit
def test_route_markdown_to_semantic():
    """Markdown 扩展名(.md)的 doc 应走 chunk_document_semantic。"""
    from unittest.mock import MagicMock, patch
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1]]
    pipeline = IngestionPipeline(embedder=mock_embedder, weaviate_client=mock_client)
    doc = RawDocument(
        source_id="r/main/m.md", source_type="local_git", product="p",
        title="m", content="# Title\n\nText.", url="u",
        metadata={"path": "m.md"}, content_hash="h", branch="main",
    )
    with patch("backend.pipeline.ingest.chunk_document_semantic") as mock_semantic, \
         patch("backend.pipeline.ingest.chunk_code") as mock_code:
        mock_semantic.return_value = []
        pipeline.ingest_document(doc)
        mock_semantic.assert_called_once()
        mock_code.assert_not_called()


@pytest.mark.unit
def test_weaviate_gets_branch_property():
    """insert_many 的 DataObject properties 应含 branch 字段(取自 doc.branch)。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1]]
    pipeline = IngestionPipeline(embedder=mock_embedder, weaviate_client=mock_client)
    doc = RawDocument(
        source_id="r/hw-v1.2/m.py", source_type="local_git", product="p",
        title="m", content="def foo():\n    return 1\n", url="u",
        metadata={"path": "m.py"}, content_hash="h", branch="hw-v1.2",
    )
    pipeline.ingest_document(doc)
    data_objs = mock_collection.data.insert_many.call_args.args[0]
    props = data_objs[0].properties
    assert props.get("branch") == "hw-v1.2"


@pytest.mark.unit
def test_ensure_collection_creates_branch_property():
    """_ensure_collection 应在 collection properties 中定义 branch(TEXT)。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline
    from weaviate.classes.config import DataType
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_client.collections.get.return_value = MagicMock()
    pipeline = IngestionPipeline(embedder=MagicMock(), weaviate_client=mock_client)
    pipeline._ensure_collection()
    create_kwargs = mock_client.collections.create.call_args
    property_names = [p.name if hasattr(p, "name") else p.get("name")
                      for p in create_kwargs.kwargs.get("properties", [])]
    assert "branch" in property_names
    # 校验 DataType
    for p in create_kwargs.kwargs.get("properties", []):
        n = p.name if hasattr(p, "name") else p.get("name")
        if n == "branch":
            dt = p.dataType if hasattr(p, "dataType") else p.get("dataType")
            assert dt == DataType.TEXT


@pytest.mark.unit
def test_upsert_postgres_writes_branch():
    """_upsert_postgres 应把 doc.branch 写入 Document.branch(Task 7)。"""
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    import numpy as np

    from backend.connectors.base import RawDocument
    from backend.pipeline.ingest import IngestionPipeline

    embedder = MagicMock()
    embedder.embed.return_value = [np.array([0.1] * 8)]
    client = MagicMock()
    client.collections.exists.return_value = True
    session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None  # 新插入
    session.execute.return_value = scalar_result

    @contextmanager
    def _factory():
        yield session

    pipeline = IngestionPipeline(
        embedder, client, session_factory=MagicMock(side_effect=_factory)
    )
    doc = RawDocument(
        source_id="r/hw-v1.2/m.py",
        source_type="local_git",
        product="p",
        title="m",
        content="x",
        url="u",
        metadata={"path": "m.py"},
        content_hash="h1",
        branch="hw-v1.2",
    )
    pipeline.ingest_document(doc)
    # session.add 被调用,传入的 Document 对象应有 branch
    added = session.add.call_args[0][0]
    assert added.branch == "hw-v1.2"


def test_deterministic_uuid_stable_and_unique():
    """确定性 UUID:同 (source_id, chunk_index) 同 uuid;不同 chunk/branch 不同 uuid。"""
    from backend.pipeline.ingest import _deterministic_uuid
    u1 = _deterministic_uuid("r/main/f.py", 0)
    u2 = _deterministic_uuid("r/main/f.py", 0)
    u3 = _deterministic_uuid("r/main/f.py", 1)
    u4 = _deterministic_uuid("r/feat-a/f.py", 0)
    assert u1 == u2, "同 key 应生成同 uuid(幂等基础)"
    assert u1 != u3, "不同 chunk 应不同 uuid"
    assert u1 != u4, "不同 branch 应不同 uuid"


# --------------------------------------------------------------------------- #
# 函数级符号检索:symbol Property + _build_props
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ensure_collection_creates_symbol_properties():
    """_ensure_collection 应创建 symbol_name/signature/node_type/tokens 4 个 TEXT property。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline
    from weaviate.classes.config import DataType
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_client.collections.get.return_value = MagicMock()
    pipeline = IngestionPipeline(embedder=MagicMock(), weaviate_client=mock_client)
    pipeline._ensure_collection()
    create_kwargs = mock_client.collections.create.call_args
    property_names = [p.name if hasattr(p, "name") else p.get("name")
                      for p in create_kwargs.kwargs.get("properties", [])]
    assert "symbol_name" in property_names
    assert "symbol_tokens" in property_names
    assert "symbol_signature" in property_names
    assert "symbol_node_type" in property_names
    # 校验 DataType 均为 TEXT
    for p in create_kwargs.kwargs.get("properties", []):
        n = p.name if hasattr(p, "name") else p.get("name")
        if n in ("symbol_name", "symbol_tokens", "symbol_signature", "symbol_node_type"):
            dt = p.dataType if hasattr(p, "dataType") else p.get("dataType")
            assert dt == DataType.TEXT


@pytest.mark.unit
def test_build_props_contains_symbol():
    """_build_props 应把 Chunk 的 symbol_* 字段透传到 Weaviate properties。"""
    from backend.pipeline.ingest import _build_props
    from backend.pipeline.chunk import Chunk
    from backend.connectors.base import RawDocument
    doc = RawDocument(source_id="ne301/main.py", source_type="local_git",
                      product="ne301", title="main.py", content="x", url="",
                      metadata={"path": "main.py"}, content_hash="h", branch="main")
    chunk = Chunk(text="t", document=doc, chunk_index=0, total_chunks=1,
                  start_char=0, end_char=1, chunk_type="code",
                  symbol_name="battery_read_i2c", symbol_tokens="battery read i2c",
                  symbol_node_type="function_definition", symbol_signature="def ...")
    props = _build_props(chunk, doc)
    assert props["symbol_name"] == "battery_read_i2c"
    assert props["symbol_tokens"] == "battery read i2c"
    assert props["symbol_node_type"] == "function_definition"
    assert props["symbol_signature"] == "def ..."
    # 既有字段不回归
    assert props["source_id"] == "ne301/main.py"
    assert props["branch"] == "main"
    assert props["chunk_type"] == "code"
