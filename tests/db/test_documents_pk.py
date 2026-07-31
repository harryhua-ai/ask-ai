"""Document 复合 PK (content_hash, branch) 测试:多分支同内容各留一行。

回归 2026-07-31 端到端验证发现的 bug:单 content_hash PK 导致跨分支
同内容文件互相覆盖。修复后复合 PK (content_hash, branch) 使各分支独立。
"""
import pytest
from sqlalchemy import select

from backend.db.models import Document


@pytest.mark.asyncio
async def test_same_content_diff_branch_coexist(db_session):
    """同 content_hash、不同 branch 应各留一行(核心回归点)。"""
    s1 = Document(
        content_hash="hash1", source_id="r/main/f.py", source_type="local_git",
        product="p", title="f", url="u", branch="main", chunk_count=2,
    )
    s2 = Document(
        content_hash="hash1", source_id="r/feat/f.py", source_type="local_git",
        product="p", title="f", url="u", branch="feat-a", chunk_count=2,
    )
    db_session.add(s1)
    await db_session.commit()
    db_session.add(s2)
    await db_session.commit()  # 复合 PK (hash1, feat-a) 与 (hash1, main) 不冲突
    rows = (await db_session.execute(
        select(Document).where(Document.content_hash == "hash1")
    )).scalars().all()
    assert len(rows) == 2
    assert {r.branch for r in rows} == {"main", "feat-a"}


@pytest.mark.asyncio
async def test_same_branch_same_content_integrity(db_session):
    """同 (content_hash, branch) 重复插入应触发 PK 冲突(不产生双行)。"""
    s1 = Document(
        content_hash="hash2", source_id="r/main/g.py", source_type="local_git",
        product="p", title="g", url="u", branch="main", chunk_count=1,
    )
    db_session.add(s1)
    await db_session.commit()
    s2 = Document(
        content_hash="hash2", source_id="r/main/g.py", source_type="local_git",
        product="p", title="g", url="u", branch="main", chunk_count=3,
    )
    db_session.add(s2)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()
    rows = (await db_session.execute(
        select(Document).where(Document.content_hash == "hash2")
    )).scalars().all()
    assert len(rows) == 1
