"""Source Lifecycle Contract 测试(S0 / 验收 F、G、H)。

- 词汇表与判定原语纯真值表(含 deny-by-default);
- sync_eligible_condition SQL 编译(NULL 行不被误过滤);
- 真实 DB roundtrip:生命周期状态跨会话持久;既有行(NULL)迁移等价 ACTIVE。
"""

import pytest
from sqlalchemy import select

from backend.db.models import DataSource
from backend.services.source_lifecycle import (
    ACTIVE,
    DELETING,
    DELETE_FAILED,
    DELETE_REQUESTED,
    is_active,
    is_deletion_in_flight,
    is_delete_failed,
    is_sync_eligible,
    normalize,
    sync_eligible_condition,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ACTIVE),
        ("", ACTIVE),
        (ACTIVE, ACTIVE),
        (DELETING, DELETING),
        (DELETE_FAILED, DELETE_FAILED),
        (DELETE_REQUESTED, DELETE_REQUESTED),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_active_predicates():
    assert is_active(None) and is_active(ACTIVE)
    assert not is_active(DELETING)


def test_deletion_in_flight():
    assert is_deletion_in_flight(DELETE_REQUESTED)
    assert is_deletion_in_flight(DELETING)
    assert not is_deletion_in_flight(DELETE_FAILED)  # 终态失败≠在途
    assert not is_deletion_in_flight(None)


def test_delete_failed_predicate():
    assert is_delete_failed(DELETE_FAILED)
    assert not is_delete_failed(DELETING)


@pytest.mark.parametrize(
    "state,eligible",
    [
        (None, True),  # 既有行默认态
        (ACTIVE, True),
        (DELETE_REQUESTED, False),
        (DELETING, False),
        (DELETE_FAILED, False),  # 部分清理态,同步不安全
        ("some_future_state", False),  # deny-by-default:未知状态不可同步
    ],
)
def test_sync_eligibility_truth_table(state, eligible):
    assert is_sync_eligible(state) is eligible


def test_sync_eligible_condition_compiles_and_allows_null():
    """条件可编译且为 allow-list(NULL ∪ active);deleting 行被过滤。"""
    stmt = select(DataSource.id).where(sync_eligible_condition())
    sql = str(stmt.compile())
    assert "lifecycle_state" in sql
    assert "deleting" not in sql  # 条件里不出现任何删除态字面量(allow-list 形态)
    assert DELETE_REQUESTED not in sql and DELETE_FAILED not in sql


@pytest.mark.asyncio
async def test_lifecycle_state_persists_across_sessions(db_engine):
    """验收 F/H:状态跨会话持久;既有行(NULL)≡ ACTIVE 且可被同步条件选中。"""
    from backend.db.session import get_session_factory

    factory = get_session_factory(db_engine)
    async with factory() as session:
        # 既有行等价形态:不写 lifecycle 列(NULL)
        session.add(
            DataSource(
                id="s0-legacy",
                type="web_crawl",
                product="t",
                enabled=True,
                config={"base_url": "https://x.example"},
            )
        )
        # 删除中行
        session.add(
            DataSource(
                id="s0-deleting",
                type="web_crawl",
                product="t",
                enabled=True,
                config={"base_url": "https://y.example"},
                lifecycle_state=DELETING,
                lifecycle_error=None,
            )
        )
        await session.commit()

    # 新会话(模拟 refresh / 进程重启后的读取)
    from backend.services.source_lifecycle import normalize as _norm

    async with factory() as session:
        rows = (await session.execute(select(DataSource).order_by(DataSource.id))).scalars().all()
        by_id = {r.id: r for r in rows}
        assert _norm(by_id["s0-legacy"].lifecycle_state) == ACTIVE  # H:NULL ≡ ACTIVE
        assert by_id["s0-deleting"].lifecycle_state == DELETING  # F:状态持久
        assert is_deletion_in_flight(by_id["s0-deleting"].lifecycle_state)

        eligible_ids = set(
            (await session.execute(select(DataSource.id).where(sync_eligible_condition())))
            .scalars()
            .all()
        )
        assert eligible_ids == {"s0-legacy"}  # G:deleting 机器可读地被排除


@pytest.mark.asyncio
async def test_delete_failed_state_roundtrip(db_engine):
    """失败态 + 摘要持久,重试前的机器可读真相。"""
    from backend.db.session import get_session_factory

    factory = get_session_factory(db_engine)
    async with factory() as session:
        session.add(
            DataSource(
                id="s0-failed",
                type="github",
                product="t",
                enabled=True,
                config={"repo_url": "https://github.com/x/y.git"},
                lifecycle_state=DELETE_FAILED,
                lifecycle_error="purge residue 12",
            )
        )
        await session.commit()
    async with factory() as session:
        row = (
            await session.execute(select(DataSource).where(DataSource.id == "s0-failed"))
        ).scalar_one()
        assert row.lifecycle_state == DELETE_FAILED
        assert row.lifecycle_error == "purge residue 12"
        assert is_delete_failed(row.lifecycle_state)
        assert not is_sync_eligible(row.lifecycle_state)
