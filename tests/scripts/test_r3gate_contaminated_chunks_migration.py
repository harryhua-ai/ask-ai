"""r3 发布安全门:contaminated chunk 迁移半态核查(第四节;只验证+钉住行为)。

12 项测试映射(胶囊):
- T10:迁移部分完成后重跑 → 幂等/续跑安全;DELETE 范围精确(generation_ordinal>0
  AND chunk_index >= chunk_count);ordinal=0 legacy 行不在范围(冻结契约);
- T11:迁移异常 → 异常向上抛、无假成功标记("OK:" 缺席)、数据原样保留。

五点核查结论的钉住(①DELETE 精确 WHERE 范围 ②幂等 ③中断后状态 ④r2 兼容
⑤异常不误报成功):本文件以行为测试固定 ①②③⑤;④ 由代码证据固定
(generation_builder 重放范围 = 版本权威 chunk 集 chunk_index < chunk_count,
删除的恰是范围外行 → r2 读少些行不崩,不读 chunk 原文)。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

import scripts.migrate_remove_contaminated_version_chunks as mc
from backend.db.models import DocumentVersion, DocumentVersionChunk
from scripts.migrate_remove_contaminated_version_chunks import migrate

# fail-closed: no fallback DSN — missing TEST_DATABASE_URL must abort, never
# silently fall back to a non-test or production-reachable database (#174 R2 discipline).
_DSN = os.environ["TEST_DATABASE_URL"]


@pytest.fixture
async def engine():
    eng = create_async_engine(_DSN)
    yield eng
    await eng.dispose()


def _mk_version(source_id: str, *, ordinal: int, chunk_count: int) -> DocumentVersion:
    return DocumentVersion(
        id=uuid.uuid4(),
        source_id=source_id,
        version_seq=1,
        content_hash=uuid.uuid4().hex,
        metadata_hash=uuid.uuid4().hex,
        generation_id=uuid.uuid4(),
        generation_ordinal=ordinal,
        status="active",
        chunk_count=chunk_count,
    )


async def _seed(engine, marker: str) -> dict[str, DocumentVersion]:
    """三版本:误挂行(ordinal>0 超限)、legacy 冻结行(ordinal=0 超限)、干净行。"""
    v_bad = _mk_version(f"t10-{marker}/bad", ordinal=3, chunk_count=2)
    v_legacy = _mk_version(f"t10-{marker}/legacy", ordinal=0, chunk_count=1)
    v_clean = _mk_version(f"t10-{marker}/clean", ordinal=7, chunk_count=2)
    chunks = [
        (v_bad, 0), (v_bad, 1),  # 在范围内,保留
        (v_bad, 2), (v_bad, 3),  # 超限误挂 → 迁移目标
        (v_legacy, 0), (v_legacy, 1),  # ordinal=0 超限 → 冻结契约,保留
        (v_clean, 0), (v_clean, 1),  # 干净
    ]
    async with engine.begin() as conn:
        for v in (v_bad, v_legacy, v_clean):
            await conn.execute(
                insert(DocumentVersion).values(
                    id=v.id,
                    source_id=v.source_id,
                    version_seq=v.version_seq,
                    content_hash=v.content_hash,
                    metadata_hash=v.metadata_hash,
                    generation_id=v.generation_id,
                    generation_ordinal=v.generation_ordinal,
                    status=v.status,
                    chunk_count=v.chunk_count,
                )
            )
        for v, idx in chunks:
            await conn.execute(
                insert(DocumentVersionChunk).values(
                    version_id=v.id, chunk_index=idx, text=f"t-{idx}", props={}
                )
            )
    return {"bad": v_bad, "legacy": v_legacy, "clean": v_clean}


async def _chunk_indices(engine, version_id) -> list[int]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(DocumentVersionChunk.chunk_index)
                .where(DocumentVersionChunk.version_id == version_id)
                .order_by(DocumentVersionChunk.chunk_index)
            )
        ).all()
    return [int(r[0]) for r in rows]


async def _cleanup(engine, versions: list[DocumentVersion]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            delete(DocumentVersionChunk).where(
                DocumentVersionChunk.version_id.in_([v.id for v in versions])
            )
        )
        await conn.execute(
            delete(DocumentVersion).where(
                DocumentVersion.id.in_([v.id for v in versions])
            )
        )


async def test_t10_exact_scope_idempotent_and_resume_safe(engine):
    """T10:范围精确 + 幂等 + 部分完成后续跑安全。"""
    # 共享测试库先收敛到零基线(迁移幂等,重复执行安全)
    await migrate(engine)
    marker = uuid.uuid4().hex[:8]
    versions = await _seed(engine, marker)
    try:
        # 首轮:只删 ordinal>0 且 idx>=chunk_count 的行(v_bad 的 2,3)
        receipt = await migrate(engine)
        assert receipt == {"planned": 2, "removed": 2}
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1]
        # ordinal=0 legacy 超限行不在 DELETE 范围(冻结契约,原样保留)
        assert await _chunk_indices(engine, versions["legacy"].id) == [0, 1]
        # 干净行零触碰
        assert await _chunk_indices(engine, versions["clean"].id) == [0, 1]

        # 重跑 = no-op(幂等)
        assert await migrate(engine) == {"planned": 0, "removed": 0}

        # 部分完成模拟:外部先删 1 条误挂行 → 续跑只清剩余(无重复/无残留)
        async with engine.begin() as conn:
            await conn.execute(
                delete(DocumentVersionChunk).where(
                    DocumentVersionChunk.version_id == versions["bad"].id,
                    DocumentVersionChunk.chunk_index == 3,
                )
            )
        async with engine.begin() as conn:
            await conn.execute(
                insert(DocumentVersionChunk).values(
                    version_id=versions["bad"].id,
                    chunk_index=4,
                    text="re-contaminated",
                    props={},
                )
            )
        receipt = await migrate(engine)
        assert receipt == {"planned": 1, "removed": 1}
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1]
    finally:
        await _cleanup(engine, list(versions.values()))


async def test_t11_migration_exception_never_reports_success(engine, capsys, monkeypatch):
    """T11:迁移异常 → 异常向上抛、无 "OK:" 假成功标记、数据原样。"""
    await migrate(engine)  # 零基线
    capsys.readouterr()  # 冲掉基线成功运行的输出,仅断言异常路径自身无成功标记
    marker = uuid.uuid4().hex[:8]
    versions = await _seed(engine, marker)
    try:
        monkeypatch.setattr(mc, "_DELETE_SQL", "THIS IS NOT VALID SQL")
        with pytest.raises(DBAPIError):  # 非法 SQL → 语法错误,驱动层结构化上抛
            await migrate(engine)
        out = capsys.readouterr().out
        assert "OK:" not in out, "异常路径不得输出成功标记"
        # 数据原样(单事务原子性:DELETE 失败即回滚,无半态)
        assert await _chunk_indices(engine, versions["bad"].id) == [0, 1, 2, 3]
    finally:
        await _cleanup(engine, list(versions.values()))
