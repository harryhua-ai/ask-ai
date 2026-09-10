"""#45 灌入字符契约 + 文档级失败诊断回归。

生产事故(RCA 2026-09-10):部署 EMBEDDER_MAX_LENGTH=1024(字符)且服务端
对超长 text 显式 413 拒绝,而分块器按 token(600)封顶 —— website-camthink
两个页面所有 chunk 均超 1024 字符 → 整文档灌入必败,小时级 cron 重试全部
无效(09-03 起持续)。本文件锁定三层矫正:
1. 灌入边界字符契约(超限 chunk 硬切,embed 不再收到超限文本);
2. 文档级失败结构化(stage/分类/可重试性;413=permanent 不再误导重试);
3. 零成功写不覆写/不留 0 行账本(自愈与诊断缺口可见)。
"""

import hashlib

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.pipeline.chunk import Chunk
from backend.pipeline.ingest import (
    DocFailure,
    IngestFailures,
    IngestionPipeline,
    _enforce_char_limit,
    classify_ingest_failure,
)


# --------------------------------------------------------------------------- #
# 纯函数层:切分与分类
# --------------------------------------------------------------------------- #


def _chunk(text: str, index: int, total: int) -> Chunk:
    return Chunk(
        text=text,
        document=None,  # type: ignore[arg-type]
        chunk_index=index,
        total_chunks=total,
        start_char=0,
        end_char=len(text),
    )


class TestEnforceCharLimit:
    def test_no_limit_is_noop(self):
        chunks = [_chunk("x" * 500, 0, 1)]
        assert _enforce_char_limit(chunks, None) is chunks

    def test_within_limit_is_noop(self):
        chunks = [_chunk("x" * 50, 0, 1), _chunk("y" * 50, 1, 2)]
        out = _enforce_char_limit(chunks, 1024)
        assert [c.text for c in out] == [c.text for c in chunks]
        assert [(c.chunk_index, c.total_chunks) for c in out] == [(0, 1), (1, 2)]

    def test_oversized_chunk_split_into_limit_slices(self):
        text = "a" * 2500
        out = _enforce_char_limit([_chunk(text, 0, 1)], 1024)
        assert len(out) == 3
        assert all(len(c.text) <= 1024 for c in out)
        assert "".join(c.text for c in out) == text  # 无损
        assert [c.chunk_index for c in out] == [0, 1, 2]
        assert all(c.total_chunks == 3 for c in out)


class TestClassifyIngestFailure:
    def test_413_is_permanent_non_retryable(self):
        error_class, retryable = classify_ingest_failure(
            "internal embeddings HTTP 413: text exceeds max_length=1024"
        )
        assert error_class == "permanent_data_too_large"
        assert retryable is False

    def test_422_is_permanent_config(self):
        error_class, retryable = classify_ingest_failure(
            "internal embeddings HTTP 422: batch too large: 20 > 16"
        )
        assert error_class == "permanent_config"
        assert retryable is False

    def test_transport_is_retryable(self):
        for detail in (
            "internal embeddings unreachable: <urlopen error timed out>",
            "internal embeddings HTTP 503: embedding unavailable",
        ):
            error_class, retryable = classify_ingest_failure(detail)
            assert error_class == "retryable_transport"
            assert retryable is True

    def test_default_class_is_retryable(self):
        error_class, retryable = classify_ingest_failure("weaviate insert failed", "error")
        assert error_class == "error"
        assert retryable is True


# --------------------------------------------------------------------------- #
# 管道层:端到端(embed 服务端同款 413 判定)
# --------------------------------------------------------------------------- #


class _ServerStrictEmbedder:
    """模拟内部嵌入端点契约:任一 text 超过 max_chars → 413 RuntimeError。"""

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.embedded_texts: list[str] = []

    @property
    def dimension(self):
        return 4

    def embed(self, texts):
        for t in texts:
            if len(t) > self.max_chars:
                raise RuntimeError(
                    f"internal embeddings HTTP 413: text exceeds max_length={self.max_chars}"
                )
        self.embedded_texts.extend(texts)
        return [np.zeros(4, dtype=np.float32) for _ in texts]


def _doc(source_id: str, content: str) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        source_type="web_crawl",
        product="website",
        title="t",
        content=content,
        url="https://example.com/x",
        metadata={},
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


def _mock_client():
    """MagicMock Weaviate client:insert_many 全成功(errors 空)。"""
    from unittest.mock import MagicMock

    client = MagicMock()
    collection = MagicMock()
    collection.name = "Document"
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    result = MagicMock()
    result.errors = {}
    collection.data.insert_many.return_value = result
    return client


def test_pipeline_with_char_limit_ingests_oversized_document():
    """根因修复端到端:分块器产出超限 chunk,管道按字符契约预切 → 灌入成功。"""
    embedder = _ServerStrictEmbedder(max_chars=64)
    pipeline = IngestionPipeline(
        embedder, _mock_client(), class_name="Document", max_chunk_chars=64
    )
    count = pipeline.ingest_all([_doc("doc/oversized", "word " * 400)])["doc/oversized"]
    assert count > 0
    assert embedder.embedded_texts, "embed 必须被调用"
    assert all(len(t) <= 64 for t in embedder.embedded_texts), "embed 不得收到超限文本"


def test_413_without_limit_becomes_structured_permanent_failure():
    """无字符上限(旧行为)时 413 失败必须结构化:class=permanent、retryable=false。"""
    embedder = _ServerStrictEmbedder(max_chars=64)
    pipeline = IngestionPipeline(embedder, _mock_client(), class_name="Document")
    with pytest.raises(IngestFailures) as ei:
        pipeline.ingest_all([_doc("doc/oversized", "word " * 400)])
    failures: list[DocFailure] = ei.value.failures
    assert len(failures) == 1
    f = failures[0]
    assert f.source_id == "doc/oversized"
    assert f.error_class == "permanent_data_too_large"
    assert f.retryable is False
    assert f.stage == "EMBED"
    assert "413" in f.detail
    assert "灌入失败" in str(ei.value)


# --------------------------------------------------------------------------- #
# 账本守护:零成功写不覆写既有行/不留 0 行(与既有 ledger 测试同库模式)
# --------------------------------------------------------------------------- #


def _failing_write_client():
    """insert_many 块失败 + replace 全失败的客户端(写库彻底失败场景)。"""
    from unittest.mock import MagicMock

    client = MagicMock()
    collection = MagicMock()
    collection.name = "Document"
    client.collections.exists.return_value = True
    client.collections.get.return_value = collection
    collection.data.insert_many.side_effect = RuntimeError("weaviate down")
    collection.data.replace.side_effect = RuntimeError("weaviate down")
    return client


@pytest.fixture
def sync_factory():
    """与测试库同库的同步 sessionmaker(_upsert_postgres 为同步路径)。

    自建表 + 自清理:本文件不经过 conftest db_engine 生命周期,必须保证表
    存在,且测试写入的 documents 行(本文件全部 source_id 以 ``doc/`` 开头)
    不泄漏进共用同一测试库的其他套件。
    """
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    from backend.config import load_settings
    from backend.db.models import Base, Document

    load_dotenv()  # 载入仓库 .env(TEST_DATABASE_URL → ask_ai_test),与 CI 口径一致
    dsn = os.environ.get(
        "TEST_DATABASE_URL",
        load_settings(config_dir=Path(__file__).parents[2] / "config").postgres_dsn,
    )
    engine = create_engine(dsn.replace("+asyncpg", ""))
    try:
        # 与 conftest db_engine 的 drop-all 清理策略共存:每次 setup 重建表
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine)
    finally:
        try:
            with sessionmaker(bind=engine)() as session:
                session.query(Document).filter(Document.source_id.like("doc/%")).delete()
                session.commit()
        except Exception:  # noqa: BLE001 - 清理尽力而为,不遮蔽测试结果
            pass
        engine.dispose()


def _seed_row(sync_factory, source_id: str, chunk_count: int) -> None:
    from backend.db.models import Document

    with sync_factory() as session:
        session.add(
            Document(
                content_hash=f"hash-{source_id}",
                source_id=source_id,
                source_type="web_crawl",
                product="website",
                title="t",
                url="https://example.com/x",
                chunk_count=chunk_count,
            )
        )
        session.commit()


def _ledger_chunk_count(sync_factory, source_id: str):
    from backend.db.models import Document

    with sync_factory() as session:
        return session.execute(
            select(Document.chunk_count).where(Document.source_id == source_id)
        ).scalar_one_or_none()


def test_zero_success_does_not_mask_existing_ledger_row(sync_factory):
    """既有账本行 chunk_count=5,本轮全失败 → 账本保留 5(自愈可见),不得覆写 0。"""
    _seed_row(sync_factory, "doc/masked", chunk_count=5)
    pipeline = IngestionPipeline(
        _ServerStrictEmbedder(max_chars=64),
        _failing_write_client(),
        class_name="Document",
        session_factory=sync_factory,
    )
    with pytest.raises(IngestFailures):
        pipeline.ingest_all([_doc("doc/masked", "word " * 400)])
    assert _ledger_chunk_count(sync_factory, "doc/masked") == 5


def test_zero_success_first_ingest_leaves_no_zero_row(sync_factory):
    """首灌全失败 → 不落 chunk_count=0 行(失败不得伪装成合法空文档)。"""
    pipeline = IngestionPipeline(
        _ServerStrictEmbedder(max_chars=64),
        _failing_write_client(),
        class_name="Document",
        session_factory=sync_factory,
    )
    with pytest.raises(IngestFailures):
        pipeline.ingest_all([_doc("doc/fresh-fail", "word " * 400)])
    assert _ledger_chunk_count(sync_factory, "doc/fresh-fail") is None


def test_full_success_still_upserts_ledger(sync_factory):
    """全部成功路径行为不变:账本照常记录 chunk_count(守护不误伤正常路径)。"""
    embedder = _ServerStrictEmbedder(max_chars=64)
    pipeline = IngestionPipeline(
        embedder,
        _mock_client(),
        class_name="Document",
        session_factory=sync_factory,
        max_chunk_chars=64,
    )
    pipeline.ingest_all([_doc("doc/ok", "word " * 60)])
    assert (_ledger_chunk_count(sync_factory, "doc/ok") or 0) > 0
