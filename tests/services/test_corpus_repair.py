"""Corpus Repair 工具测试(Issue #13 Stage A;F/G/H/I/J 契约)。

F  历史 .hef → 判定 unsafe(reason=model_artifact_ext,复用 Technical Safety)
G  管理员 file_types 含 .hef/.bin → Technical Safety 仍胜(connector 准入)
H  dry-run → 零 DB/向量变更;计划可序列化审计、确定性
I  apply → 仅计划内对象受影响(账本行 + 确定性 UUID 点删)
J  repair retry → 幂等(重放无新增变更、无失败)

全程零 embed(账本 + fake collection),不依赖 CUDA。
"""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.db.models import Document
from backend.pipeline.ingest import _deterministic_uuid
from backend.services.corpus_repair import (
    ACTION_RETIRE_UNSAFE_ARTIFACT,
    CorpusRepairTool,
)

SRC = "src"

pytestmark = pytest.mark.asyncio


class _FakeByIdFilter:
    """monkeypatch 替身:捕获 contains_any 收到的 uuid(版本无关)。"""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def by_id(self):  # Filter.by_id()
        return self

    def contains_any(self, ids):
        self._sink.extend(ids)
        return f"contains_any({len(ids)})"


@pytest.fixture
def deleted_uuids(monkeypatch) -> list[str]:
    """捕获工具发出的全部点删 uuid(按调用顺序)。"""
    sink: list[str] = []
    monkeypatch.setattr("weaviate.classes.query.Filter", _FakeByIdFilter(sink))
    return sink


def _seed_kwargs(path: str, content_hash: str, chunk_count: int = 3) -> dict:
    return dict(
        content_hash=content_hash,
        source_id=path,
        source_type="github",
        product="p",
        title=path.rsplit("/", 1)[-1],
        url="u",
        branch="main",
        chunk_count=chunk_count,
    )


@pytest.fixture
def async_factory(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(db_engine)


@pytest.fixture
def sync_factory(db_engine):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import os

    engine = create_engine(os.environ["TEST_DATABASE_URL"].replace("+asyncpg", ""))
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _tool(async_factory, sync_factory):
    pipeline = MagicMock()
    pipeline._session_factory = sync_factory
    pipeline._ensure_collection.return_value = None
    collection = MagicMock()
    pipeline._collection = collection
    tool = CorpusRepairTool(async_session_factory=async_factory, pipeline=pipeline)
    return tool, pipeline, collection


async def _seed_rows(async_factory, *kwargs_list):
    async with async_factory() as session:
        for kw in kwargs_list:
            session.add(Document(**kw))
        await session.commit()


async def _count(async_factory) -> int:
    async with async_factory() as session:
        return len((await session.execute(select(Document.source_id))).scalars().all())


async def test_f_historical_hef_detected_unsafe(async_factory, sync_factory):
    """F:账本中的历史 .hef → RETIRE_UNSAFE_ARTIFACT(reason=model_artifact_ext)。

    检测复用 TechnicalSafetyPolicy(非硬编码清单)。
    """
    await _seed_rows(
        async_factory,
        _seed_kwargs(f"{SRC}/main/models/person_v1.hef", "h1"),
        _seed_kwargs(f"{SRC}/main/docs/ok.md", "h2"),
    )
    tool, _pipeline, _collection = _tool(async_factory, sync_factory)
    plan = await tool.plan(SRC, orphan_chunks={})

    artifact_entries = [e for e in plan.entries if e.action == ACTION_RETIRE_UNSAFE_ARTIFACT]
    assert [e.path for e in artifact_entries] == [f"{SRC}/main/models/person_v1.hef"]
    assert artifact_entries[0].reason == "model_artifact_ext"
    assert artifact_entries[0].chunk_count == 3
    # 计划可序列化(dry-run 审计契约)
    assert json.dumps(plan.to_dict(), ensure_ascii=False)


async def test_f2_detection_shares_technical_safety_vocabulary(async_factory, sync_factory):
    """F2:检测词表 = Technical Safety 本尊 —— .so/.bin/.onnx/.pt 全数命中,合法文本不误伤。"""
    from backend.connectors.safety import historical_artifact_verdict

    for suffix in (".so", ".bin", ".onnx", ".pt"):
        verdict = historical_artifact_verdict(f"{SRC}/main/lib/thing{suffix}")
        assert not verdict.safe, suffix
        assert verdict.reason == "model_artifact_ext"
    assert historical_artifact_verdict(f"{SRC}/main/docs/readme.md").safe


async def test_g_safety_wins_over_admin_file_types(tmp_path):
    """G:管理员 file_types 显式含 .hef/.bin → Technical Safety 仍然拦截。"""
    import os

    from backend.connectors.filesystem import FilesystemConnector
    from backend.connectors.registry import SourceConfig

    root = tmp_path / "repo"
    root.mkdir()
    (root / "model.hef").write_bytes(b"\x01HEF binary")
    (root / "fw.bin").write_bytes(b"\x00\x01binary")
    (root / "keep.md").write_text("ok", encoding="utf-8")

    cfg = SourceConfig(
        id="fs-src",
        type="filesystem",
        product="p",
        enabled=True,
        config={"root_path": str(root), "file_types": [".hef", ".bin", ".md"]},
        sync_interval="24h",
    )
    connector = FilesystemConnector(cfg)
    docs = list(connector.fetch_all())
    paths = {d.metadata["path"] for d in docs}
    assert paths == {"keep.md"}  # .hef/.bin 虽在白名单,仍被 Technical Safety 排除
    assert connector.safety_stats["excluded"] == 2
    assert set(connector.safety_stats["reasons"]) == {"model_artifact_ext"}
    assert os.path.exists(root / "model.hef")  # 源文件未被触碰(仅准入排除)


async def test_h_dry_run_zero_mutation(async_factory, sync_factory, deleted_uuids):
    """H:dry-run(plan)零 DB/向量变更;计划确定性(两次生成逐条一致)。"""
    await _seed_rows(
        async_factory,
        _seed_kwargs(f"{SRC}/main/a.md", "h1"),
        _seed_kwargs(f"{SRC}/main/bad.so", "h2", chunk_count=7),
    )
    tool, _pipeline, _collection = _tool(async_factory, sync_factory)

    plan1 = await tool.plan(SRC, orphan_chunks={})
    plan2 = await tool.plan(SRC, orphan_chunks={})
    before = await _count(async_factory)

    assert before == 2
    assert not deleted_uuids  # 零向量删除
    assert [e.to_dict() for e in plan1.entries] == [e.to_dict() for e in plan2.entries]
    actions = {e.action for e in plan1.entries}
    assert ACTION_RETIRE_UNSAFE_ARTIFACT in actions
    assert all(e.action != "RETIRE_DELETED_DOCUMENT" for e in plan1.entries)  # 无成员证据不生成


async def test_i_apply_touches_only_planned_objects(async_factory, sync_factory, deleted_uuids):
    """I:apply 仅影响计划内对象 —— .hef 账本行删除 + 该文档 uuid 点删;.md 零触碰。"""
    hef_path = f"{SRC}/main/models/person_v1.hef"
    await _seed_rows(
        async_factory,
        _seed_kwargs(hef_path, "h1", chunk_count=3),
        _seed_kwargs(f"{SRC}/main/ok.md", "h2", chunk_count=2),
    )
    tool, _pipeline, _collection = _tool(async_factory, sync_factory)
    plan = await tool.plan(SRC, orphan_chunks={})

    result = await tool.apply(plan)

    assert not result.failed
    assert any("ledger-row" in a and hef_path in a for a in result.applied)
    async with async_factory() as session:
        remaining = set((await session.execute(select(Document.source_id))).scalars())
    assert remaining == {f"{SRC}/main/ok.md"}  # 兄弟合法文档零触碰
    # 向量:按确定性 UUID 精确点删该文档 0..2
    assert sorted(deleted_uuids) == sorted(_deterministic_uuid(hef_path, i) for i in range(3))


async def test_i2_apply_orphan_rebuild_and_orphan_artifact(
    async_factory, sync_factory, deleted_uuids
):
    """I2:安全路径孤儿 → 零 embed 重建;.hef 孤儿 → 仅向量退休(绝不建行)。"""
    tool, pipeline, _collection = _tool(async_factory, sync_factory)
    safe_orphan = f"{SRC}/main/new.md"
    artifact_orphan = f"{SRC}/main/legacy.onnx"

    def _fake_fetch(filters=None, limit=None):
        return MagicMock(
            objects=[
                MagicMock(
                    properties={
                        "source_id": safe_orphan,
                        "content_hash": "hash-new",
                        "source_type": "github",
                        "product": "p",
                        "title": "new.md",
                        "url": "u",
                        "branch": "main",
                    }
                )
            ]
            * limit
        )

    pipeline._collection.query.fetch_objects.side_effect = _fake_fetch
    plan = await tool.plan(SRC, orphan_chunks={safe_orphan: {0, 1}, artifact_orphan: {0}})

    result = await tool.apply(plan)
    assert not result.failed

    async with async_factory() as session:
        rows = {r.source_id: r for r in (await session.execute(select(Document))).scalars()}
    assert set(rows) == {safe_orphan}  # 重建安全路径;artifact 孤儿绝不建行
    assert rows[safe_orphan].content_hash == "hash-new"
    assert rows[safe_orphan].chunk_count == 2

    # 重建分支不动向量:其 fetch 过滤器(2 uuid)也会经过替身,但仅读不删;
    # artifact 孤儿按实际存量 index 精确点删(1 uuid)
    assert len(deleted_uuids) == 3
    assert set(deleted_uuids[:2]) == {
        _deterministic_uuid(safe_orphan, 0),
        _deterministic_uuid(safe_orphan, 1),
    }
    assert deleted_uuids[2] == _deterministic_uuid(artifact_orphan, 0)


async def test_j_apply_retry_idempotent(async_factory, sync_factory, deleted_uuids):
    """J:重试幂等 —— 第二次 apply 零新增账本变更、零失败;fresh 计划无退休条目。"""
    hef_path = f"{SRC}/main/models/x.hef"
    await _seed_rows(async_factory, _seed_kwargs(hef_path, "h1", chunk_count=2))
    tool, _pipeline, _collection = _tool(async_factory, sync_factory)

    plan = await tool.plan(SRC, orphan_chunks={})
    result1 = await tool.apply(plan)
    assert not result1.failed
    count_after_first = await _count(async_factory)

    # 重放同一计划:账本行已不存在 → skipped(而非再次 applied),零失败
    result2 = await tool.apply(plan)
    assert not result2.failed
    assert not [a for a in result2.applied if a.endswith("ledger-row")]
    assert any("already absent" in s for s in result2.skipped)
    assert await _count(async_factory) == count_after_first

    # 全新扫描:artifact 行已退休 → 无 RETIRE 条目(幂等收敛)
    fresh = await tool.plan(SRC, orphan_chunks={})
    assert all(e.action != ACTION_RETIRE_UNSAFE_ARTIFACT for e in fresh.entries)
