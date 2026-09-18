"""零语义分块确定性分类服务(#94;builder 记账面 + membership 压制面共享)。

Role A 冻结语义(#94 ght-contract;PR #98 模式的姊妹篇):

1. builder 对到达它的内容**每代永远重跑现行 chunker**,本表只是记账
   (写面),绝不是判定门 —— 策略演进因此天然获得重评估:新策略下产出
   有效分块 ⇒ 激活事务清除本行;仍为 [] ⇒ 原位换判定(刷新策略指纹)。
2. **指纹双轴失效(AC3)**:content_fingerprint 或 chunker_policy_fingerprint
   变化 ⇒ 原位换判定(压制永不凌驾于新观察之上)。
3. **有界压制(AC3 兜底)**:membership 对账只在窗口内
   (:data:`ZERO_CHUNK_REEVALUATION_DAYS`,自 last_confirmed_at)且内容指纹
   一致(连接器 ``membership_content_fingerprints`` 可得时)把身份移入
   zero_chunk_ids;过期/漂移 ⇒ 重回 actionable missing ⇒ 补灌重判。
4. 失败类(chunker/parser 异常、物化失败、超时、embed/index 失败、中断/
   未知)永远走 failed(fail-closed),绝不写本表(AC4)。
5. 与 #91 ``ingestion_exclusions`` 严格分表分列 —— 零分块不是安全排除,
   也不是退役/在服/失败;核算与真值面单独如实计数(AC5,不假收敛)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from backend.db.models import ZeroSemanticChunk

logger = logging.getLogger(__name__)

# 压制窗口(天;自 last_confirmed_at 起):重评估成本 = 一次内容抓取 +
# 纯 CPU 语义分块(零嵌入),窗口内陈旧压制的最长存活 = 7 天,过期必有
# 确定性重评估(有界兜底,与 #91 窗口语义同源)。
ZERO_CHUNK_REEVALUATION_DAYS = 7


def suppression_cutoff(now: datetime) -> datetime:
    """压制窗口起点:``last_confirmed_at < cutoff`` 的登记不再压制 missing。"""
    return now - timedelta(days=ZERO_CHUNK_REEVALUATION_DAYS)


def chunker_policy_fingerprint(kind: str, max_tokens: int, overlap: int, max_chunk_chars: int) -> str:
    """chunker 策略的确定性版本身份(AC2):分块器类别 + 全部形状参数。

    任何影响分块结果的参数变化都会改变本指纹 ⇒ 新策略下首代构建即原位
    换判定(仍为 [])或清除(产出分块),策略演进无需人工介入。
    """
    import hashlib

    return hashlib.sha256(
        f"chunk-policy:v1|kind={kind}|max_tokens={max_tokens}|overlap={overlap}|max_chars={max_chunk_chars}".encode()
    ).hexdigest()


def record_zero_semantic_chunk(
    session_factory: Any,
    *,
    source_id: str,
    content_fingerprint: str,
    chunker_policy_fingerprint: str,
    detail: str = "",
    now: datetime | None = None,
) -> None:
    """登记/确认一次确定性零分块结果(upsert,每身份恰一行)。

    - 新身份:建行(times_confirmed=1,first_seen_at=now);
    - 同身份同内容同策略:确认计数 +1,last_confirmed_at 前移(窗口重启);
    - 指纹任一变化(内容或策略):原位换判定(指纹列更新,last_confirmed_at
      前移;first_seen_at 保留首见审计)。

    写失败向上抛出,由调用方按瞬态失败处置(fail-closed,绝不静默丢单)。
    """
    ts = now or datetime.now(UTC)
    with session_factory() as session:
        row = session.get(ZeroSemanticChunk, source_id)
        if row is None:
            session.add(
                ZeroSemanticChunk(
                    source_id=source_id,
                    content_fingerprint=content_fingerprint,
                    chunker_policy_fingerprint=chunker_policy_fingerprint,
                    detail=detail,
                    times_confirmed=1,
                    first_seen_at=ts,
                    last_confirmed_at=ts,
                )
            )
        else:
            if (
                row.content_fingerprint != content_fingerprint
                or row.chunker_policy_fingerprint != chunker_policy_fingerprint
            ):
                logger.info(
                    "零分块登记换判定 %s:content %s→%s, policy %s→%s(指纹漂移,重评)",
                    source_id,
                    str(row.content_fingerprint)[:8],
                    content_fingerprint[:8],
                    str(row.chunker_policy_fingerprint)[:8],
                    chunker_policy_fingerprint[:8],
                )
                row.content_fingerprint = content_fingerprint
                row.chunker_policy_fingerprint = chunker_policy_fingerprint
                row.detail = detail
            row.times_confirmed += 1
            row.last_confirmed_at = ts
        session.commit()


def purge_expired_out_of_authority(
    session: Any, source_id: str, enumeration: set[str], *, cutoff: datetime
) -> int:
    """清除「窗口过期 ∘ 已不在权威枚举」的登记(对账事务内卫生;幂等)。

    身份仍在权威枚举内的过期行**必须保留** —— 它正是「重评估请求」:
    过期 ⇒ 身份重回 missing ⇒ 补灌重判 ⇒ builder 刷新或清除本行。
    """
    rows = session.execute(
        select(ZeroSemanticChunk).where(
            ZeroSemanticChunk.source_id.like(f"{source_id}/%"),
            ZeroSemanticChunk.last_confirmed_at < cutoff,
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
            "清除越权过期零分块登记 %d 行(源 %s,窗口 %d 天)",
            purged,
            source_id,
            ZERO_CHUNK_REEVALUATION_DAYS,
        )
    return purged


def delete_for_identities(session: Any, source_ids: list[str]) -> None:
    """按身份清除登记(激活事务内调用:内容重判产出有效分块 ⇒ 分类作废)。"""
    if not source_ids:
        return
    session.execute(
        delete(ZeroSemanticChunk).where(ZeroSemanticChunk.source_id.in_(source_ids))
    )
