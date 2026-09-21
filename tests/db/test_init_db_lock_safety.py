"""Issue #102 AC3:启动期兼容性 DDL 不得在稳态发出阻塞 DDL;真缺列时有界且 truthful。

生产实证(#100 验证,v1.6.3-r8):sync-cron 每轮 ``init_db`` 重跑
``ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type`` —— 列已存在
时 PostgreSQL 仍先取 ACCESS EXCLUSIVE 再判 no-op,排在长事务(如 repair-all
批级事务)之后无限等待,形成 #102 三方锁队列。

契约(#102 AC3):

- 稳态(schema 已兼容):ensure_* 只做 catalog 存在性探测,**零 DDL 语句**
  —— catalog 读不申请目标表锁,不可能排在任何长事务之后;
- 真缺列:仍必须执行真实兼容性 DDL,但在有界 ``lock_timeout`` 下运行 ——
  与长事务重叠时以可执行错误有界失败(下一轮重试),绝不无限排队、
  绝不静默跳过。

真实 PostgreSQL;多连接锁序用独立 psycopg2 连接构造。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from sqlalchemy import event, text

from backend.config import load_settings
from backend.db.session import (
    ensure_sync_delta_columns,
    ensure_sync_request_kind_column,
    ensure_track_c_columns,
    get_engine,
    init_db,
)

LOCK_TIMEOUT_SECONDS = 5
PROBE_TIMEOUT = 20  # 有界失败判定上限(≫ lock_timeout,≪ 生产 56min 停滞)


def _sync_dsn() -> str:
    dsn = load_settings(config_dir=Path(__file__).parents[2] / "config").postgres_dsn
    return dsn.replace("+asyncpg", "+psycopg2").replace("+psycopg2", "")


def _foreign_lock(table: str, mode: str = "ACCESS EXCLUSIVE"):
    """打开一个持有目标表锁的独立连接(模拟长事务占用;调用方负责释放)。"""
    import psycopg2

    conn = psycopg2.connect(_sync_dsn())
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(f"LOCK TABLE {table} IN {mode} MODE")
    return conn


@pytest.fixture()
def ddl_counter():
    """DDL 语句计数器(dict 形态,AsyncEngine 不可挂属性)。"""
    return {"count": 0}


@pytest.fixture()
def ddl_counting_engine(ddl_counter):
    """带 DDL 语句计数器的引擎(独立于共享 db_engine,控制自己的生命周期)。"""
    dsn = load_settings(config_dir=Path(__file__).parents[2] / "config").postgres_dsn
    engine = get_engine(dsn)

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        up = statement.upper()
        if "ALTER TABLE" in up or "CREATE INDEX" in up:
            ddl_counter["count"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    yield engine
    event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    ddl_counter["count"] = 0
    engine.sync_engine.dispose()


# --------------------------------------------------------------------------- #
# AC3 GREEN 面:稳态零 DDL
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ensure_track_c_columns_issues_no_ddl_when_schema_present(
    ddl_counting_engine, ddl_counter,
):
    """schema 已兼容 ⇒ ensure_track_c_columns 零 DDL 语句(连长事务占锁都无感)。"""
    foreign = _foreign_lock("documents")  # 长事务持有 documents ACCESS EXCLUSIVE
    try:
        start = time.monotonic()
        await asyncio.wait_for(
            ensure_track_c_columns(ddl_counting_engine), timeout=PROBE_TIMEOUT
        )
        elapsed = time.monotonic() - start
    finally:
        foreign.rollback()
        foreign.close()
    assert ddl_counter["count"] == 0, (
        "稳态必须零阻塞 DDL —— 存在性探测通过时不得发出任何 ALTER/CREATE INDEX"
        "(生产死锁源:每轮 no-op ADD COLUMN 仍取 ACCESS EXCLUSIVE)"
    )
    assert elapsed < PROBE_TIMEOUT


@pytest.mark.asyncio
async def test_init_db_steady_state_emits_no_ddl(ddl_counting_engine, ddl_counter):
    """init_db 第二轮(已初始化库)= 零 ALTER/CREATE INDEX 语句。"""
    await init_db(ddl_counting_engine)  # 第一轮:建立/确认 schema
    ddl_counter["count"] = 0
    await init_db(ddl_counting_engine)  # 稳态轮(sync-cron 每小时的真实形态)
    assert ddl_counter["count"] == 0, (
        "稳态 init_db 不得发出任何阻塞 DDL(#102 AC3)"
    )


@pytest.mark.asyncio
async def test_other_ensure_helpers_steady_state_issue_no_ddl(
    ddl_counting_engine, ddl_counter,
):
    """ensure_sync_delta_columns / ensure_sync_request_kind_column 同契约。"""
    await ensure_sync_delta_columns(ddl_counting_engine)
    await ensure_sync_request_kind_column(ddl_counting_engine)
    assert ddl_counter["count"] == 0


# --------------------------------------------------------------------------- #
# AC3 truthful 面:真缺列 ⇒ 有界且可执行(完成或有界 actionable 失败)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_missing_column_completes_safely_without_conflict(
    ddl_counting_engine, ddl_counter, monkeypatch,
):
    """真缺列 + 无锁冲突 ⇒ 真实 DDL 安全完成(不静默跳过)。"""
    import backend.db.session as session_mod

    real = session_mod._table_column_exists

    async def missing_content_type(conn, table, column):
        if table == "documents" and column == "content_type":
            return False
        return await real(conn, table, column)

    monkeypatch.setattr(session_mod, "_table_column_exists", missing_content_type)
    ddl_counter["count"] = 0
    await asyncio.wait_for(ensure_track_c_columns(ddl_counting_engine), timeout=PROBE_TIMEOUT)
    assert ddl_counter["count"] >= 1, (
        "真缺列必须执行真实兼容性 DDL(绝不静默假装兼容)"
    )


@pytest.mark.asyncio
async def test_missing_column_with_conflicting_lock_fails_bounded_and_actionable(
    ddl_counting_engine, monkeypatch
):
    """真缺列 + 长事务占锁 ⇒ lock_timeout 内有界失败,错误可执行(绝不无限排队)。"""
    import backend.db.session as session_mod

    real = session_mod._table_column_exists

    async def missing_content_type(conn, table, column):
        if table == "documents" and column == "content_type":
            return False
        return await real(conn, table, column)

    monkeypatch.setattr(session_mod, "_table_column_exists", missing_content_type)

    foreign = _foreign_lock("documents")  # ACCESS EXCLUSIVE:DDL 必等
    try:
        start = time.monotonic()
        with pytest.raises(Exception) as excinfo:
            await asyncio.wait_for(
                ensure_track_c_columns(ddl_counting_engine),
                timeout=LOCK_TIMEOUT_SECONDS * 4,
            )
        elapsed = time.monotonic() - start
    finally:
        foreign.rollback()
        foreign.close()
    assert elapsed < LOCK_TIMEOUT_SECONDS * 4, (
        f"真缺列且锁被长事务占用时必须在有界时间内失败(实际 {elapsed:.1f}s;"
        "生产形态 = 无限排队 56min+)"
    )
    msg = str(excinfo.value)
    assert "lock" in msg.lower() or "锁" in msg, (
        f"失败必须可执行:指明锁竞争语境(实际: {msg[:200]})"
    )
