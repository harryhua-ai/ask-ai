"""Authoritative membership reconciliation + persisted currency truth(#71)。

生产缺陷 #71 的根因是「成员资格对账」结构性缺失:删除/重命名上游文档后,
账本中的陈旧文档永远保持 active 并继续被检索引用,而同步健康只看
PG↔Weaviate 一致性,对上游漂移结构性失明。

本服务把「权威成员对账」落成唯一实现,供多条路径共享同一语义:

- scripts/sync.py 每轮同步(含无变更/SHA 短路轮);
- scripts/reconcile_membership.py 授权生产矫正(先 dry-run 计划后 apply);
- 未来 connector 扩展(web_crawl 已有等价快照语义,filesystem/woocommerce
  无能力面,如实标记 unsupported,见 #71 授权范围第 18 条)。

语义冻结(Issue #71 授权契约):

1. stale_set = 账本在服成员(serving=active/missing_candidate)− 权威成员;
2. stale_set 一律经 ``tombstone_document`` 逻辑退休(绝不物理删行/删向量;
   物理清除仍只归 GC);
3. 正确性不依赖 git 事件窗口或 ``fetch_deleted`` 历史;
4. 幂等收敛:重复执行 stale_set 收敛为空;
5. 原子退休:单事务提交,中断即整体回滚,不存在半退休态;
6. 货币真值持久化(DataSource 加性列)必须且只能在退休事务成功完成后写入
   (kill-safety:先真值后完成 = 禁止)。

会话面契约(与 scripts/sync.py 既有语义一致):账本退休走**同步**
session_factory(``pipeline._session_factory``,墓碑原语是同步 Session
API);货币真值持久化走异步 session_factory(SyncLog/调度真值同面)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.db.models import DataSource, Document
from backend.services.document_lifecycle import DocLifecycle, tombstone_document

logger = logging.getLogger(__name__)

# 持久货币真值词表(Admin/UI 契约;冻结,扩词需走评审)
MEMBERSHIP_STATUS_CURRENT = "current"
MEMBERSHIP_STATUS_STALE = "stale"
MEMBERSHIP_STATUS_FAILED = "failed"
MEMBERSHIP_STATUS_UNSUPPORTED = "unsupported"

# 单条 detail 采样上限(真值列仅存样例,全量清单在 SyncLog/delta_counts/报告)
_DETAIL_SAMPLE = 20


class MembershipTruthPersistenceError(RuntimeError):
    """成员货币真值持久化失败(#71 R2 BLOCKER 2)。

    语义冻结:真值持久化**绝不 best-effort** —— 任何失败(写库故障/源行
    缺失)都以本错误显式上抛,由调用方裁决轮次状态(partial)与错误呈现;
    已提交的退休墓碑不受影响(不回滚),下一轮重试对账与真值建立。绝不允许
    「对账成功但真值写失败仍宣称 current/健康」。
    """


@dataclass(frozen=True)
class MembershipReconciliation:
    """一次成员对账的完整事实(调用方据此持久化真值)。"""

    source_id: str
    enumerated_count: int
    ledger_active_count: int
    stale_ids: tuple[str, ...] = field(default_factory=tuple)
    retired: int = 0
    residual_ids: tuple[str, ...] = field(default_factory=tuple)
    # #82:authority−ledger 方向(权威成员 − 账本在服成员)。非空 ⇒ 存在
    # 配置范围内却从未入账(或已退休但重回权威)的成员,由调用方经既有
    # ingest 路径补灌;本服务只负责对账事实,不做灌入。
    missing_ids: tuple[str, ...] = field(default_factory=tuple)
    status: str = "completed"  # completed / failed
    error: str | None = None

    @property
    def unresolved(self) -> bool:
        """对账完成后仍存在未解决的漂移。"""
        return bool(self.residual_ids)


def ledger_active_membership(session: Any, source_id: str) -> set[str]:
    """账本当前在服成员(source_id 前缀圈定;lifecycle ∈ SERVING)。

    同步 Session API(墓碑原语同面)。
    """
    result = session.execute(
        select(Document.source_id).where(
            Document.source_id.like(f"{source_id}/%"),
            Document.lifecycle.in_(DocLifecycle.SERVING),
        )
    )
    return {str(sid) for sid in result.scalars().all()}


def reconcile_membership(
    session_factory: Any,
    connector: Any,
    source_id: str,
    *,
    reason: str = "",
) -> MembershipReconciliation:
    """执行一次权威成员对账(计算 → 原子退休 → 复核)。

    权威成员由 connector 的 ``membership_source_ids()`` 提供(当前树状态,
    与灌入同过滤面)。任一步失败向上抛出(账本事务整体回滚,零半退休态),
    由调用方决定货币真值与轮次状态 —— 本函数绝不写 DataSource 真值列
    (kill-safety 归调用方排序)。

    Args:
        session_factory: **同步**账本会话工厂(``pipeline._session_factory``)。
        connector: 暴露 ``membership_source_ids()`` 的数据源连接器。
        source_id: 数据源 ID(前缀圈定)。
        reason: 墓碑 reason 审计串。

    Returns:
        MembershipReconciliation(含 stale/retired/residual 完整事实)。

    Raises:
        Exception: 权威枚举或退休事务失败(账本零改动)。
    """
    enumeration = set(connector.membership_source_ids())
    with session_factory() as session:
        active = ledger_active_membership(session, source_id)
        stale = sorted(active - enumeration)
        # #82:补灌方向 —— 权威成员 − 账本在服成员。覆盖两类缺口:从未灌入
        # (分支 scope 扩大后新纳入的既有内容)与墓碑后重回权威(上游删除后
        # 重新出现); retirement 语义不变,缺失成员的灌入归调用方既有路径。
        missing = sorted(enumeration - active)
        retired = 0
        for sid in stale:
            if tombstone_document(session, sid, reason=reason or "membership_reconcile"):
                retired += 1
        session.commit()
        # 退休事务提交后复核:提交成功 ⇒ 原子性成立 ⇒ residual 恒应为空;
        # 非空仅可能来自并发写入(极少),如实上报为未解决漂移。
        residual = ledger_active_membership(session, source_id)
    residual_ids = tuple(sorted(residual - enumeration))
    logger.info(
        "成员对账完成 %s: authoritative=%d ledger_serving=%d stale=%d retired=%d"
        " missing=%d residual=%d",
        source_id,
        len(enumeration),
        len(active),
        len(stale),
        retired,
        len(missing),
        len(residual_ids),
    )
    return MembershipReconciliation(
        source_id=source_id,
        enumerated_count=len(enumeration),
        ledger_active_count=len(active),
        stale_ids=tuple(stale),
        retired=retired,
        residual_ids=residual_ids,
        missing_ids=tuple(missing),
        status="completed",
    )


async def persist_membership_truth(
    session_factory: Any,
    source_id: str,
    *,
    status: str,
    stale_detected: int = 0,
    stale_retired: int = 0,
    detail: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
) -> None:
    """持久化数据源货币真值(加性列;Admin 只读本真值,不做实时枚举)。

    调用方排序契约:必须在对账事务成功完成后调用(kill-safety,#71 授权
    契约第 8 条)。

    失败语义(R2 BLOCKER 2 冻结):**绝不静默** —— 写库故障或源行缺失一律
    抛出 :class:`MembershipTruthPersistenceError`,由调用方把本轮降级为
    未解决(partial)并如实呈现;已提交的墓碑不回滚,下一轮重试真值建立。

    Raises:
        MembershipTruthPersistenceError: 真值未能持久化(任何原因)。
    """
    ts = checked_at or datetime.now(UTC)
    try:
        async with session_factory() as session:
            ds = (
                await session.execute(
                    select(DataSource).where(DataSource.id == source_id)
                )
            ).scalar_one_or_none()
            if ds is None:
                raise MembershipTruthPersistenceError(
                    f"membership truth not persisted: source row missing: {source_id}"
                )
            ds.membership_status = status
            ds.membership_checked_at = ts
            ds.membership_stale_detected = int(stale_detected)
            ds.membership_stale_retired = int(stale_retired)
            ds.membership_detail = detail
            await session.commit()
    except MembershipTruthPersistenceError:
        raise
    except Exception as exc:
        raise MembershipTruthPersistenceError(
            f"membership truth not persisted for {source_id}: {str(exc)[:200]}"
        ) from exc


def truth_detail_of(result: MembershipReconciliation) -> dict[str, Any]:
    """由对账事实构造真值 detail 列载荷(采样陈旧清单,审计用)。"""
    return {
        "enumerated": result.enumerated_count,
        "ledger_serving": result.ledger_active_count,
        "stale_sample": list(result.stale_ids[:_DETAIL_SAMPLE]),
        "residual_sample": list(result.residual_ids[:_DETAIL_SAMPLE]),
        # #82 加性审计键:缺失成员样例(补灌方向的可见性;Admin 契约词表不变)
        "missing_sample": list(result.missing_ids[:_DETAIL_SAMPLE]),
    }
