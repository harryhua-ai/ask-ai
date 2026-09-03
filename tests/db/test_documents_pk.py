"""documents 身份契约测试(Issue #13 Stage A,D1/D2 冻结)。

回归 Issue #13 根因 RC-1:旧 PK (content_hash, branch) 为内容寻址 —— 同内容
同分支多路径只允许一行且行归属被"最后灌入者"抢占。新契约:PK = (source_id)
路径身份,同内容不同路径(同分支/同源/跨源)必须各自成行;content_hash 降级
为内容指纹索引,不再承担唯一性。

历史注:本文件旧版断言「同 (content_hash, branch) 重复插入触发 PK 冲突」——
那正是 Issue #13 的根因契约,已随 D1/D2 冻结被本新契约取代。
"""

import pytest
from sqlalchemy import exc as sa_exc, select

from backend.db.models import Document


def _row(path: str, branch: str, content_hash: str = "same-hash") -> Document:
    return Document(
        content_hash=content_hash,
        source_id=path,
        source_type="github",
        product="p",
        title="t",
        url="u",
        branch=branch,
        chunk_count=2,
    )


@pytest.mark.asyncio
async def test_a_same_hash_same_branch_diff_paths_coexist(db_session):
    """A:同 hash + 同 branch + 不同路径 → 两行并存(D2 核心契约)。

    旧 PK (content_hash, branch) 下第二行必然主键冲突(Issue #13 根因)。
    """
    db_session.add(_row("repo/main/dir_a/util.py", "main"))
    await db_session.commit()
    db_session.add(_row("repo/main/dir_b/util.py", "main"))
    await db_session.commit()  # 新 PK (source_id):不冲突

    rows = (
        (await db_session.execute(select(Document).where(Document.content_hash == "same-hash")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.source_id for r in rows} == {"repo/main/dir_a/util.py", "repo/main/dir_b/util.py"}


@pytest.mark.asyncio
async def test_b_same_hash_across_sources_coexist(db_session):
    """B:同 hash 跨数据源 → 各自成行(生产实锤:cJSON.c 跨 ne301/apic)。"""
    db_session.add(_row("ne301-local/main/Lib/cJSON.c", "main"))
    await db_session.commit()
    db_session.add(_row("ne503-apic-69d3594b/main/mcu/Lib/cJSON.c", "main"))
    await db_session.commit()

    rows = (
        (await db_session.execute(select(Document).where(Document.content_hash == "same-hash")))
        .scalars()
        .all()
    )
    assert {r.source_id.split("/")[0] for r in rows} == {"ne301-local", "ne503-apic-69d3594b"}


@pytest.mark.asyncio
async def test_a2_same_content_diff_branch_still_coexist(db_session):
    """旧契约中仍然正确的部分保留:同内容跨分支各留一行(路径本就不同)。"""
    db_session.add(_row("r/main/f.py", "main"))
    await db_session.commit()
    db_session.add(_row("r/feat/f.py", "feat"))
    await db_session.commit()
    rows = (
        (await db_session.execute(select(Document).where(Document.content_hash == "same-hash")))
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_pk_is_path_duplicate_path_rejected(db_session):
    """唯一性权威 = source_id(路径):同路径重复行被 PK 拒绝(幂等灌入由
    upsert 承担,而非放行双行)。"""
    db_session.add(_row("repo/main/g.py", "main", content_hash="h1"))
    await db_session.commit()
    db_session.add(_row("repo/main/g.py", "main", content_hash="h2"))
    with pytest.raises(sa_exc.IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    rows = (
        (await db_session.execute(select(Document).where(Document.source_id == "repo/main/g.py")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
