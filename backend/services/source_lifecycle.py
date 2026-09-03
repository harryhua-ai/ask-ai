"""数据源生命周期契约(S0 Foundation;#18 非阻塞删除的前置)。

职责边界(S0 冻结):
- 本模块只提供 **词汇表 + 纯判定原语 + 查询条件**;
- 删除 worker / purge 编排 / API 端点**不在**本模块(#18 实现);
- 不与 sync_requests / sync_runs 的 operation truth 竞争——生命周期状态
  持久化在 ``data_sources`` 行自身(3 个 NULLABLE 列,见 models.DataSource)。

状态机(列 ``lifecycle_state``):

    ACTIVE(NULL / "active",既有行零回填的默认态)
      └─ DELETE 请求 ──▶ DELETE_REQUESTED ──▶ DELETING ──成功──▶ (整行删除,无 tombstone)
                                             └─失败──▶ DELETE_FAILED ──重试──▶ DELETING

- DELETE_REQUESTED → DELETING 是请求处理器内的瞬时转移(置状态即受理),
  两者都持久化以便崩溃后对账可区分「已受理未启动」与「清理进行中」;
- DELETE_FAILED 保留行 + ``lifecycle_error``,可重试(purge 幂等);
- **sync 资格默认拒绝(deny-by-default)**:任何非 ACTIVE 持久化状态
  (含未来新增状态)一律不得启动新 sync——deleting 源被同步会复活
  已清理语料(delete→sync→ghost race),delete_failed 源的语料处于
  部分清理态,同步同样不安全。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_

ACTIVE = "active"
DELETE_REQUESTED = "delete_requested"
DELETING = "deleting"
DELETE_FAILED = "delete_failed"

# 持久化词表(ACTIVE 以 NULL 表达,不写入;词表冻结,新增值须先过
# sync 资格评审——deny-by-default 语义保证漏配安全)
PERSISTED_STATES: frozenset[str] = frozenset({DELETE_REQUESTED, DELETING, DELETE_FAILED})
# 删除在途:受理后、终态前
IN_FLIGHT_STATES: frozenset[str] = frozenset({DELETE_REQUESTED, DELETING})


def normalize(state: str | None) -> str:
    """列值 → 规范状态名(NULL/空 = ACTIVE,既有行零迁移回填)。"""
    if state is None or state == "":
        return ACTIVE
    return state


def is_active(state: str | None) -> bool:
    return normalize(state) == ACTIVE


def is_deletion_in_flight(state: str | None) -> bool:
    """删除已受理且未到终态(重复 DELETE / 手动 sync 应被 409 拒绝)。"""
    return normalize(state) in IN_FLIGHT_STATES


def is_delete_failed(state: str | None) -> bool:
    return normalize(state) == DELETE_FAILED


def is_sync_eligible(state: str | None) -> bool:
    """单一可复用判定:该生命周期状态能否启动新 sync(验收 G)。

    deny-by-default:仅 ACTIVE 可同步;deleting / delete_failed /
    delete_requested 及任何未来新状态一律 False。
    """
    return normalize(state) == ACTIVE


def sync_eligible_condition() -> Any:
    """SQLAlchemy 条件:``data_sources`` 行是否允许被同步调度消费。

    供 #18 接线进 ``scripts/sync.py::_load_configs_from_db`` 的 WHERE
    (S0 不改 sync.py,避免与并行波冲突)。与 :func:`is_sync_eligible`
    同为 allow-list 语义(NULL ∪ active):未来新增的任何持久化状态
    默认不可同步。NULL 必须显式 or 进来,否则既有行全部被过滤。
    """
    from backend.db.models import DataSource

    return or_(
        DataSource.lifecycle_state.is_(None),
        DataSource.lifecycle_state == ACTIVE,
    )
