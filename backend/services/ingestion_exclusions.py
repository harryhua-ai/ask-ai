"""永久性灌入排除登记服务(#91;单一实现,membership 与 builder 共享)。

Role A REVIEW_2/REVIEW_3 修正后的完整语义 —— **即时失效 + 有界兜底**:

1. builder 对任何到达它的内容**永远重跑现行政策** ``check_content``,
   本表只是记账(写面),绝不是判定门 —— 增量路径把内容变更送到 builder
   即刻重判(安全=激活+清登记;不安全=原位换判定)。
2. **即时失效(REVIEW_3)**:连接器若能提供权威内容指纹
   (``membership_content_fingerprints``,github 经 git 对象库窄面读取),
   对账逐身份比对登记的 ``content_hash``:指纹漂移 ⇒ **立即**不再压制
   missing ⇒ 补灌重取 ⇒ 重判。
3. **有界兜底(Tier 2)**:无指纹能力或指纹不可得时,压制仅在窗口内生效
   (:data:`INGESTION_EXCLUSION_REEVALUATION_DAYS`,自 ``last_confirmed_at``);
   过期身份重回 missing ⇒ 补灌重取 ⇒ 重判 —— 同内容不安全=刷新确认
   (压制重启,零嵌入,不复活 GPU 循环),内容变更=按事实处置。
   政策/安全规则演进经窗口过期获得确定性重评估路径。
4. 每身份恰一行(PK = source_id):行 = 对该身份**当前权威内容**的判定;
   ``content_hash`` 记录判定针对的内容指纹,判定换内容即原位更新。
5. 卫生:对账事务内清除「窗口过期 ∘ 已不在权威枚举」的行(不再有任何
   压制或审计用途;身份重回权威时经补灌重评估重建,无复活风险)。

被排除物:不入账、不入向量、永不成为服务真值(不假收敛)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from backend.db.models import IngestionExclusion

logger = logging.getLogger(__name__)

# 压制窗口(天;自 last_confirmed_at 起)。与 RETIRED_RETENTION_DAYS 同为
# 冻结工程默认(7 天):重评估成本 = 一次内容抓取 + 安全扫描(零嵌入),
# 窗口内陈旧压制的最长存活 = 7 天,过期必有确定性重评估。
INGESTION_EXCLUSION_REEVALUATION_DAYS = 7


def suppression_cutoff(now: datetime) -> datetime:
    """压制窗口起点:``last_confirmed_at < cutoff`` 的登记不再压制 missing。"""
    return now - timedelta(days=INGESTION_EXCLUSION_REEVALUATION_DAYS)


def record_permanent_exclusion(
    session_factory: Any,
    *,
    source_id: str,
    content_hash: str,
    reason: str,
    detail: str,
    stage: str,
    actor: str = "sync",
    now: datetime | None = None,
) -> None:
    """登记/确认一次确定性永久排除(upsert,每身份恰一行)。

    - 新身份:建行(times_confirmed=1,first_seen_at=now);
    - 同身份同内容:确认计数 +1,last_confirmed_at 前移(压制窗口重启);
    - 同身份内容变更(指纹不同):原位换判定(content_hash/reason/detail/
      stage 更新,last_confirmed_at 前移;first_seen_at 保留首见审计)。

    写失败向上抛出,由调用方按瞬态失败处置(fail-closed,绝不静默丢单)。
    """
    ts = now or datetime.now(UTC)
    with session_factory() as session:
        row = session.get(IngestionExclusion, source_id)
        if row is None:
            session.add(
                IngestionExclusion(
                    source_id=source_id,
                    content_hash=content_hash,
                    reason=reason,
                    detail=detail,
                    stage=stage,
                    actor=actor,
                    times_confirmed=1,
                    first_seen_at=ts,
                    last_confirmed_at=ts,
                )
            )
        else:
            if row.content_hash != content_hash:
                logger.info(
                    "排除登记换判定 %s:content_hash %s → %s(内容变更,重判)",
                    source_id,
                    str(row.content_hash)[:12],
                    content_hash[:12],
                )
                row.content_hash = content_hash
                row.reason = reason
                row.detail = detail
                row.stage = stage
            row.times_confirmed += 1
            row.last_confirmed_at = ts
            row.actor = actor
        session.commit()


def purge_expired_out_of_authority(
    session: Any, source_id: str, enumeration: set[str], *, cutoff: datetime
) -> int:
    """清除「窗口过期 ∘ 已不在权威枚举」的登记(对账事务内卫生;幂等)。

    身份仍在权威枚举内的过期行**必须保留** —— 它正是「重评估请求」:
    过期 ⇒ 身份重回 missing ⇒ 补灌重判 ⇒ builder 刷新或清除本行。
    """
    rows = session.execute(
        select(IngestionExclusion).where(
            IngestionExclusion.source_id.like(f"{source_id}/%"),
            IngestionExclusion.last_confirmed_at < cutoff,
        )
    ).scalars().all()
    purged = 0
    for row in rows:
        if row.source_id in enumeration:
            continue
        session.delete(row)
        purged += 1
    if purged:
        logger.info(
            "清除越权过期排除登记 %d 行(源 %s,窗口 %d 天)",
            purged,
            source_id,
            INGESTION_EXCLUSION_REEVALUATION_DAYS,
        )
    return purged


def delete_for_identities(session: Any, source_ids: list[str]) -> None:
    """按身份清除登记(激活事务内调用:内容重判通过 ⇒ 登记作废)。"""
    if not source_ids:
        return
    session.execute(delete(IngestionExclusion).where(IngestionExclusion.source_id.in_(source_ids)))
