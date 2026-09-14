"""v1.6.3 Track C(U-12/U-13):知识设置政策层(CURRENT/HISTORICAL + 新鲜度)。

冻结语义(track-c-contract U-12):
- **CURRENT = 有资格支撑当前事实型回答**,受新鲜度政策约束;过期 CURRENT
  证据必须诚实浮现(超期态 Admin 可见);
- **HISTORICAL = 保留用于历史问题/溯源/证据链**,不得支撑「当前价格/当前
  规格/当前可用性/当前运行状态」类断言;
- 新鲜度政策按 source 可配置、**后端权威**;**检索资格必须消费政策真值**
  (``excluded_source_prefixes`` → 检索服务过滤);
- **政策层叠加于现行 lifecycle 真值之上**,不重设计 lifecycle 模型
  (零改写 lifecycle 列语义,只加列 + 消费)。

U-13(预览/确认一致性):影响计数由后端按当前账本权威计算并快照
(``compute_policy_impact`` + ledger fingerprint);确认必须携带 preview
token 且指纹一致,drift → 失效(409 重算);确认施加的 mutation 与预览
请求的策略完全一致(pending_policy 快照)。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    KnowledgeSettingsPreview,
)
from backend.services.document_lifecycle import DocLifecycle

ROLE_CURRENT = "current"
ROLE_HISTORICAL = "historical"
KNOWLEDGE_ROLES = (ROLE_CURRENT, ROLE_HISTORICAL)

# 新鲜度要求词表(小时;参考语义「超过该时间没有成功更新时,系统将提醒
# 知识更新服务」)。默认 24h(NULL = 默认)。冻结词表,写入侧必须校验
# (INT-C-03:非法值 reject/fail-loud,禁静默回落 24)。
FRESHNESS_CHOICES_HOURS = (6, 12, 24, 72, 168)
DEFAULT_FRESHNESS_HOURS = 24

ROLE_LABELS = {ROLE_CURRENT: "CURRENT", ROLE_HISTORICAL: "HISTORICAL"}


def effective_role(ds: DataSource) -> str:
    """源证据资格角色(NULL = 默认 CURRENT)。"""
    return ds.knowledge_role if ds.knowledge_role in KNOWLEDGE_ROLES else ROLE_CURRENT


def effective_freshness_hours(ds: DataSource) -> int:
    """源新鲜度阈值(NULL = 默认 24h)。

    INT-C-03:显式配置必须 ∈ 冻结词表(写入侧 schemas 已 reject);非空
    非法值 = 数据损坏,fail-loud(禁静默回落 24 掩盖真值)。"""
    value = ds.freshness_hours
    if value is None:
        return DEFAULT_FRESHNESS_HOURS
    if value not in FRESHNESS_CHOICES_HOURS:
        raise ValueError(
            f"freshness_hours={value} 不在冻结词表 {FRESHNESS_CHOICES_HOURS} 内"
            "(数据损坏;修复数据而非静默回落)"
        )
    return value


def freshness_truth(
    ds: DataSource, last_success_at: datetime | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """新鲜度真值(后端权威;超期态 Admin 可见/检索语义按角色消费)。"""
    now = now or datetime.now(UTC)
    hours = effective_freshness_hours(ds)
    if last_success_at is None:
        return {
            "freshness_hours": hours,
            "last_success_at": None,
            "overdue": True,
            "overdue_since": None,
            "basis": "never_synced",
        }
    age_hours = (now - last_success_at).total_seconds() / 3600
    overdue = age_hours > hours
    return {
        "freshness_hours": hours,
        "last_success_at": last_success_at.isoformat(),
        "overdue": overdue,
        "overdue_hours_ago": round(age_hours - hours, 2) if overdue else 0.0,
        "basis": "last_success",
    }


async def last_success_at(session: AsyncSession, source_id: str) -> datetime | None:
    """最近一次成功同步时点(sync_log status='success' 权威)。"""
    from backend.db.models import SyncLog

    row = await session.execute(
        select(SyncLog.finished_at)
        .where(SyncLog.source_id == source_id, SyncLog.status == "success")
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


def _escape_like(value: str) -> str:
    """LIKE 通配符转义(INT-C-04:%/_/\\;配合 ``escape="\\")`` 使用)。

    source_id 含 ``%``/``_`` 时未转义会扩查询(前缀域越过本源边界),
    影响计数/指纹必须精确圈定本源文档。与 data_sources._document_scope
    同一转义语义。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def policy_impact_counts(session: AsyncSession, source_id: str) -> dict[str, int]:
    """影响计数基础量(后端按当前账本权威计算;U-13 预览/确认同源)。"""
    scope = Document.source_id.like(f"{_escape_like(source_id)}/%", escape="\\")
    ledger_total = int(
        (
            await session.execute(select(func.count()).select_from(Document).where(scope))
        ).scalar()
        or 0
    )
    resolvable = Document.current_version_id.is_not(None) & select(
        DocumentVersion.id
    ).where(DocumentVersion.id == Document.current_version_id).exists()
    current_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Document)
                .where(scope, Document.lifecycle == DocLifecycle.ACTIVE, resolvable)
            )
        ).scalar()
        or 0
    )
    return {
        "affected_documents": ledger_total,
        "current_count": current_count,
        "historical_count": max(0, ledger_total - current_count),
    }


def compute_policy_impact(
    *,
    from_role: str,
    to_role: str,
    counts: dict[str, int],
) -> dict[str, int]:
    """变更影响计数(U-13 服务端权威;预览与确认同一函数,零口径漂移)。

    语义(与角色定义一一对应):
    - affected_documents:政策域内全部账本知识(角色是源级政策,作用于全域);
    - current_eligibility_change:当前事实型回答资格将变化的知识数
      (CURRENT→HISTORICAL = 失去资格的当前证据数,即 current_count;
      HISTORICAL→CURRENT = 重获资格数,同 current_count 口径);
    - historical_eligibility_change:历史/溯源资格将变化的知识数
      (即非当前证据存量 historical_count 口径)。
    """
    if from_role == to_role:
        return {
            "affected_documents": counts["affected_documents"],
            "current_eligibility_change": 0,
            "historical_eligibility_change": 0,
        }
    return {
        "affected_documents": counts["affected_documents"],
        "current_eligibility_change": counts["current_count"],
        "historical_eligibility_change": counts["historical_count"],
    }


async def ledger_fingerprint(session: AsyncSession, source_id: str) -> str:
    """账本指纹(U-13 drift 判定):文档身份+lifecycle+现行版本的确定性摘要。"""
    scope = Document.source_id.like(f"{_escape_like(source_id)}/%", escape="\\")
    rows = (
        await session.execute(
            select(Document.source_id, Document.lifecycle, Document.current_version_id)
            .where(scope)
            .order_by(Document.source_id)
        )
    ).all()
    digest = hashlib.sha256()
    for sid, lc, vid in rows:
        digest.update(str(sid).encode())
        digest.update(str(lc).encode())
        digest.update(str(vid).encode())
    return digest.hexdigest()


async def create_preview(
    session: AsyncSession,
    source_id: str,
    *,
    pending_policy: dict[str, Any],
    impact: dict[str, int],
    fingerprint: str,
    ttl_minutes: int = 30,
) -> KnowledgeSettingsPreview:
    """持久化预览快照(计数权威 + 确认一致性锚)。"""
    preview = KnowledgeSettingsPreview(
        source_id=source_id,
        pending_policy=pending_policy,
        impact=impact,
        ledger_fingerprint=fingerprint,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    session.add(preview)
    await session.commit()
    await session.refresh(preview)
    return preview


async def validate_confirm_token(
    session: AsyncSession, source_id: str, token: str, pending_policy: dict[str, Any]
) -> KnowledgeSettingsPreview:
    """确认一致性校验(U-13;失败抛 409,要求重算/重新预览)。

    - token 不存在/不属于本源/已消费/已过期 → 409(预览已失效,需重算);
    - pending_policy 与本次确认请求不一致 → 409(施加 mutation 必须 =
      预览 mutation);
    - 账本指纹与预览时不一致 → 409 drift(计数已不可信,需重新预览)。
    """
    from fastapi import HTTPException
    from uuid import UUID

    try:
        token_uuid = UUID(token)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=409,
            detail="预览已失效,请重新预览(影响计数必须与当前账本一致)",
        ) from exc
    preview = (
        await session.execute(
            select(KnowledgeSettingsPreview)
            .where(
                KnowledgeSettingsPreview.id == token_uuid,
                KnowledgeSettingsPreview.source_id == source_id,
            )
            .order_by(KnowledgeSettingsPreview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if preview is None or preview.status != "pending" or (
        preview.expires_at is not None and preview.expires_at < datetime.now(UTC)
    ):
        raise HTTPException(
            status_code=409,
            detail="预览已失效,请重新预览(影响计数必须与当前账本一致)",
        )
    if json.dumps(preview.pending_policy, sort_keys=True) != json.dumps(
        pending_policy, sort_keys=True
    ):
        raise HTTPException(
            status_code=409,
            detail="确认的策略与预览不一致,已拒绝(预览 mutation 才可施加)",
        )
    current_fp = await ledger_fingerprint(session, source_id)
    if current_fp != preview.ledger_fingerprint:
        preview.status = "stale"
        await session.commit()
        raise HTTPException(
            status_code=409,
            detail="账本已变化(影响计数 drift),预览失效;请重新预览后确认",
        )
    return preview


async def excluded_source_prefixes(session: AsyncSession) -> list[str]:
    """检索资格消费(U-12 硬性挂钩):HISTORICAL 源前缀集合(后端真值)。

    检索服务据此过滤候选:HISTORICAL 源知识保留于溯源/证据链,不支撑
    当前事实型断言 → 不进入当前事实型回答检索候选。
    """
    rows = await session.execute(
        select(DataSource.id).where(DataSource.knowledge_role == ROLE_HISTORICAL)
    )
    return sorted({row[0] for row in rows.all()})


def excluded_source_prefixes_sync(session_factory: Any) -> list[str]:
    """同步版政策真值读取(检索调用栈为同步;与在服代 provider 同模式)。"""
    from backend.db.models import DataSource as _DS

    with session_factory() as session:
        rows = session.execute(
            select(_DS.id).where(_DS.knowledge_role == ROLE_HISTORICAL)
        ).all()
        return sorted({str(row[0]) for row in rows})


class CachedSourceExclusions:
    """政策真值短 TTL 缓存(检索路径每查询零建连;TTL 与可见性守卫同量级)。

    失败语义:缓存有效时返回缓存;缓存空且读取失败 → 异常向上传播
    (fail-closed,调用方绝不无限制检索)。
    """

    def __init__(self, loader: Any, ttl: float = 30.0) -> None:
        self._loader = loader
        self._ttl = ttl
        self._value: list[str] | None = None
        self._loaded_at: float = 0.0

    def get(self) -> list[str]:
        import time

        now = time.monotonic()
        if self._value is not None and (now - self._loaded_at) < self._ttl:
            return self._value
        value = list(self._loader())
        self._value = value
        self._loaded_at = now
        return value
