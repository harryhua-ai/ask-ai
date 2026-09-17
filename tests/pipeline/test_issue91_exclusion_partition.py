"""Issue #91 P0 RED→GREEN:确定性永久安全排除在原子生成代之前的分区。

生产机制(2026-09-17 只读取证,ne301-local 三连轮):
    membership 枚举(零内容读取)必然包含 content 级排除物(二进制/私钥)
    → #82 补灌按 missing 全量补灌 → GenerationBuilder Phase 1 对排除物记
    permanent_safety_excluded 进 failed 列表 → 合法全集嵌入完成后整代
    IngestFailures 零激活 → 下轮同 missing 重演(GPU 小时级放大)。

目标语义(契约,#91 Final Acceptance Contract):
    永久排除在原子 eligible 生成代**之前**分区:可审计、绝不入服务真值、
    不再作为 actionable missing 反复补灌;瞬态失败依旧 fail-closed;
    生成代原子性只对 eligible 集承诺。

真实 Postgres + 真实 Weaviate(不可达 skip,与 test_generation_builder 同模式);
嵌入用确定性 fake(计数断言「排除物零嵌入」)。
"""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    IndexGeneration,
)
from backend.pipeline.generation_builder import GenerationBuilder
from backend.pipeline.ingest import IngestFailures
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "I91PartProbe"
SRC = "i91part-src"
PREFIX = f"{SRC}/"

ELIGIBLE_A = PREFIX + "main/docs/overview.md"
ELIGIBLE_B = PREFIX + "main/docs/setup.md"
ELIGIBLE_C = PREFIX + "main/docs/faq.md"
BINARY_DOC = PREFIX + "main/fw/morsefirmware/bcf_aw_hm593.mbin"
SECRET_DOC = PREFIX + "main/etc/id_rsa"


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _doc(sid: str, content: str) -> RawDocument:
    return RawDocument(
        source_id=sid,
        source_type="github",
        product="probe",
        title=sid.rsplit("/", 1)[-1],
        content=content,
        url=f"https://x/{sid}",
        metadata={"path": sid},
        content_hash=_hash(content),
        branch=sid.split("/")[1],
    )


def _eligible_doc(sid: str) -> RawDocument:
    return _doc(
        sid,
        f"# {sid.rsplit('/', 1)[-1]}\n\n"
        "alpha paragraph about connectors and sync.\n\n"
        "beta paragraph about retrieval and ranking.\n\n"
        "gamma paragraph about lifecycle and generations.\n\n"
        "delta paragraph about activation and versions.\n\n"
        "epsilon paragraph about membership reconciliation.\n\n"
        "zeta paragraph about atomic generations.\n\n",
    )


# 生产同类形态:固件二进制(头采样窗口 NUL)与私钥 armor(确定性 content 判定)
BINARY_CONTENT = "BCF\x00\x00\x01\x02\x03firmware-bytes-padded-to-look-binary\x00\x00"
SECRET_CONTENT = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/yGWy7fW2UsXm7XKQ\n"
    "-----END RSA PRIVATE KEY-----\n"
)


class _FakeEmbedder:
    """确定性假嵌入器:记录每批文本(断言排除物零嵌入 / eligible 只嵌一次)。"""

    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("fake embedder boom")
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


@pytest.fixture()
def stack():
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(既有真 Weaviate 集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    embedder = _FakeEmbedder()
    from backend.pipeline.ingest import IngestionPipeline

    pipeline = IngestionPipeline(
        embedder,
        client,
        class_name=CLASS_NAME,
        max_tokens=40,
        overlap=0,
        session_factory=sync_factory,
        max_chunk_chars=2000,
    )
    builder = GenerationBuilder(pipeline, sync_factory)

    yield SimpleNamespace(
        client=client,
        sync_factory=sync_factory,
        pipeline=pipeline,
        builder=builder,
        embedder=embedder,
    )

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    sync_engine.dispose()


def _purge(s) -> None:
    from backend.db.models import DocumentVersionChunk

    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersionChunk).where(
            DocumentVersionChunk.version_id.in_(select(DocumentVersion.id))
        )
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    from backend.db.models import IngestionExclusion

    for row in s.execute(
        select(IngestionExclusion).where(
            IngestionExclusion.source_id.like(f"{PREFIX}%")
        )
    ).scalars():
        s.delete(row)
    s.commit()


def _exclusion_rows(sync_factory, sid: str):
    from backend.db.models import IngestionExclusion

    with sync_factory() as s:
        return (
            s.execute(
                select(IngestionExclusion).where(IngestionExclusion.source_id == sid)
            )
            .scalars()
            .all()
        )


# --------------------------------------------------------------------------- #
# RED-1/GREEN:排除物分区,eligible 集原子激活(AC2/AC3)
# --------------------------------------------------------------------------- #


def test_excluded_partitioned_eligible_generation_activates(stack):
    """3 合法 + 1 固件二进制:合法集完成原子激活,排除物分区留痕、零激活伤害。

    基线(baseline RED):build_generation 对含 permanent_safety_excluded 的
    批次整代 raise IngestFailures(生产零激活机制原样复现),本测试第一个
    断言点即失败于该 raise。
    """
    builder = stack.builder
    docs = [
        _eligible_doc(ELIGIBLE_A),
        _eligible_doc(ELIGIBLE_B),
        _eligible_doc(ELIGIBLE_C),
        _doc(BINARY_DOC, BINARY_CONTENT),
    ]
    accounting = builder.build_generation(docs, source_id=SRC)

    assert sorted(accounting.new_docs) == sorted(
        [ELIGIBLE_A, ELIGIBLE_B, ELIGIBLE_C]
    ), "eligible 集必须完成激活(基线:整代 IngestFailures 零激活)"
    assert accounting.generation_status == "ready"
    assert accounting.excluded_docs == [BINARY_DOC], (
        "排除物必须进入分区账目,而不是 failed 列表"
    )

    # eligible 真值:账本 + 版本就位
    with stack.sync_factory() as s:
        serving = {
            str(sid)
            for (sid,) in s.execute(
                select(Document.source_id).where(
                    Document.source_id.like(f"{PREFIX}%"),
                    Document.lifecycle.in_(lifecycle.DocLifecycle.SERVING),
                )
            )
        }
    assert serving == {ELIGIBLE_A, ELIGIBLE_B, ELIGIBLE_C}
    # 排除物绝不入服务真值(AC8/AC9:不为凑成员数而入账)
    with stack.sync_factory() as s:
        assert (
            s.execute(
                select(Document).where(Document.source_id == BINARY_DOC)
            ).scalar_one_or_none()
            is None
        )


def test_secret_content_partitioned_same_semantics(stack):
    """私钥 armor(生产 .h/.c 形态)同分区语义:可审计、零入账、eligible 激活。"""
    builder = stack.builder
    docs = [_eligible_doc(ELIGIBLE_A), _doc(SECRET_DOC, SECRET_CONTENT)]
    accounting = builder.build_generation(docs, source_id=SRC)
    assert accounting.new_docs == [ELIGIBLE_A]
    assert accounting.excluded_docs == [SECRET_DOC]
    rows = _exclusion_rows(stack.sync_factory, SECRET_DOC)
    assert len(rows) == 1 and rows[0].reason == "secret_content"


# --------------------------------------------------------------------------- #
# AC2:排除登记可审计 + 幂等重确认
# --------------------------------------------------------------------------- #


def test_exclusion_row_auditable_and_idempotent(stack):
    """分区必须持久化(reason/detail/stage/内容指纹),重复确认不产生重复行。"""
    builder = stack.builder
    builder.build_generation(
        [_eligible_doc(ELIGIBLE_A), _doc(BINARY_DOC, BINARY_CONTENT)], source_id=SRC
    )
    rows = _exclusion_rows(stack.sync_factory, BINARY_DOC)
    assert len(rows) == 1, "排除登记必须存在(基线:零持久化)"
    row = rows[0]
    assert row.reason == "binary_content"
    assert row.content_hash == _hash(BINARY_CONTENT)
    assert row.stage == "SAFETY_FILTER"
    assert row.detail

    # 同内容再次进入构建(如 force_rebuild/补灌重复):幂等,不重复嵌,不重复建行
    embedder = stack.embedder
    before = sum(len(c) for c in embedder.calls)
    builder.build_generation(
        [_doc(BINARY_DOC, BINARY_CONTENT)], source_id=SRC, force_rebuild=True
    )
    after = sum(len(c) for c in embedder.calls)
    assert after == before, "已排除内容绝不被重复嵌入(AC6/AC12)"
    assert len(_exclusion_rows(stack.sync_factory, BINARY_DOC)) == 1


# --------------------------------------------------------------------------- #
# AC7:瞬态失败依旧整代 fail-closed(不得退化成 partial activation)
# --------------------------------------------------------------------------- #


def test_transient_embed_failure_still_fails_closed(stack):
    """embed 瞬态失败 → 整代 IngestFailures + 零激活;不产生排除登记。"""
    builder = stack.builder
    stack.embedder.fail = True
    with pytest.raises(IngestFailures):
        builder.build_generation(
            [_eligible_doc(ELIGIBLE_A), _eligible_doc(ELIGIBLE_B)], source_id=SRC
        )
    with stack.sync_factory() as s:
        assert (
            s.execute(
                select(Document).where(Document.source_id.like(f"{PREFIX}%"))
            ).scalars().all()
            == []
        ), "瞬态失败必须零激活(fail-closed 保持)"
        from backend.db.models import IngestionExclusion

        assert (
            s.execute(
                select(IngestionExclusion).where(
                    IngestionExclusion.source_id.like(f"{PREFIX}%")
                )
            ).scalars().all()
            == []
        ), "瞬态失败绝不冒记为永久排除"


# --------------------------------------------------------------------------- #
# 政策自愈:内容变安全 → 激活时清除陈旧排除登记
# --------------------------------------------------------------------------- #


def test_reincoming_safe_content_clears_stale_exclusion(stack):
    """同身份内容变安全(哈希变化 → 重新判定通过):正常激活,陈旧排除行清除。"""
    builder = stack.builder
    builder.build_generation(
        [_doc(BINARY_DOC, BINARY_CONTENT)], source_id=SRC, force_rebuild=True
    )
    assert len(_exclusion_rows(stack.sync_factory, BINARY_DOC)) == 1

    accounting = builder.build_generation(
        [_eligible_doc(BINARY_DOC)], source_id=SRC, force_rebuild=True
    )
    assert accounting.new_docs == [BINARY_DOC], "内容变安全后必须可正常入库"
    assert _exclusion_rows(stack.sync_factory, BINARY_DOC) == [], (
        "激活后陈旧排除登记必须清除(政策放宽自愈,不再压制 missing)"
    )


# --------------------------------------------------------------------------- #
# #92 AC10 联动:长身份(>200)全链投影不失真
# --------------------------------------------------------------------------- #


def test_long_identity_end_to_end_projection(stack):
    """production-class Docusaurus i18n 长路径:账本/版本/向量 props 全程精确。"""
    long_rel = (
        "i18n/en/docusaurus-plugin-content-docs/current/1-neoedge-ng4500-series/"
        "2-ng4500-cb01-development-board/2-software-guide/"
        "1-driver-installation-and-updates/0-interface-and-modules-configure.md"
    )
    long_id = f"{PREFIX}main/{long_rel}"
    assert len(long_id) > 200, "fixture 必须是 production-class 长身份"
    builder = stack.builder
    accounting = builder.build_generation([_eligible_doc(long_id)], source_id=SRC)
    assert accounting.new_docs == [long_id], (
        "长身份必须无损入库(基线:StringDataRightTruncation)"
    )
    with stack.sync_factory() as s:
        row = s.execute(
            select(Document).where(Document.source_id == long_id)
        ).scalar_one()
        assert row.source_id == long_id
    # 向量投影保留精确身份(props.source_id)
    from weaviate.classes.query import Filter

    col = stack.pipeline._collection
    resp = col.query.fetch_objects(
        filters=Filter.by_property("source_id").equal(long_id), limit=10
    )
    assert len(resp.objects) >= 1
    for obj in resp.objects:
        assert obj.properties["source_id"] == long_id
