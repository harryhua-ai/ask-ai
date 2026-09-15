"""#71 权威成员对账矫正 CLI(授权生产矫正机制;dry-run 计划为默认)。

为 #71 确认的陈旧语料提供**可审、可计划、幂等**的矫正入口,与 sync 侧
成员对账共享同一权威语义(backend/services/membership_currency.py):

- 陈旧总体**在执行时从权威真值重算**(连接器权威枚举 vs 账本在服成员),
  绝不硬编码任何历史数字(#71 授权契约第 16 条);
- dry-run(默认)产出精确计划(逐条 path + chunk_count,JSON 可序列化
  可持久化审计),零写副作用;
- ``--apply`` 显式执行:仅 ``tombstone_document`` 逻辑退休(无物理删行/
  删向量;物理清除仍只归 GC),单事务原子提交,重复执行幂等收敛;
- apply 成功后持久化数据源货币真值(kill-safety:先完成 retire 事务,
  后写真值)。

授权边界:生产执行属生产写操作,必须持独立授权
(PROD_MUTATION_AUTHORIZATION_REQUIRED),与在线同步窗口互斥(同
scripts/repair_corpus.py 纪律)。

用法(dry-run,默认):
    python scripts/reconcile_membership.py --source wiki-documents-local
    python scripts/reconcile_membership.py --source wiki-documents-local \
        --output /tmp/membership-plan.json

显式执行:
    python scripts/reconcile_membership.py --source wiki-documents-local --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select

from backend.config import load_settings
from backend.connectors.db_adapter import to_source_config
from backend.connectors.registry import ConnectorRegistry
from backend.db.models import Document
from backend.db.session import get_engine, get_session_factory
from backend.services.membership_currency import (
    MEMBERSHIP_STATUS_CURRENT,
    MEMBERSHIP_STATUS_STALE,
    MembershipTruthPersistenceError,
    ledger_active_membership,
    persist_membership_truth,
    reconcile_membership,
    truth_detail_of,
)

logger = logging.getLogger(__name__)


async def build_plan(
    sync_session_factory: Any,
    connector: Any,
    source_id: str,
) -> dict[str, Any]:
    """权威对账计划(dry-run;零写副作用)。

    权威枚举在计划时执行一次;陈旧总体即时重算,产出逐条精确计划。
    ``sync_session_factory`` = 同步账本面(与 pipeline._session_factory 同语义)。
    """
    enumeration = set(connector.membership_source_ids())
    with sync_session_factory() as session:
        active = ledger_active_membership(session, source_id)
        chunk_counts = {
            sid: int(cc)
            for sid, cc in session.execute(
                select(Document.source_id, Document.chunk_count).where(
                    Document.source_id.like(f"{source_id}/%")
                )
            ).all()
        }
    stale = sorted(active - enumeration)
    entries = [
        {
            "path": sid,
            "action": "RETIRE_STALE_DOCUMENT",
            "reason": "source_confirmed_absence",
            "chunk_count": int(chunk_counts.get(sid, 0)),
            "detail": "logical tombstone via document_lifecycle (no physical delete)",
        }
        for sid in stale
    ]
    return {
        "tool": "reconcile_membership",
        "source_prefix": source_id,
        "mode": "dry_run",
        "created_at": datetime.now(UTC).isoformat(),
        "authoritative_membership_count": len(enumeration),
        "ledger_serving_count": len(active),
        "total_documents": len(entries),
        "total_chunks": sum(e["chunk_count"] for e in entries),
        "entries": entries,
    }


async def apply_plan(
    session_factory: Any,
    sync_session_factory: Any,
    connector: Any,
    source_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """执行矫正(权威成员对账;幂等;成功后持久化货币真值)。

    返回可审计结果(本次 detected/retired + 复核残余)。执行时重算总体,
    不依赖任何历史计划数字。retire 走同步账本面单事务原子提交;真值持久化
    在其后(异步面)—— kill-safety 排序。

    失败语义(R2 BLOCKER 2):真值持久化失败以
    :class:`MembershipTruthPersistenceError` 显式上抛 —— 已提交墓碑不回滚,
    CLI 必须如实报告失败(退出码非 0),绝不伪造成功。
    """
    result = reconcile_membership(sync_session_factory, connector, source_id, reason=reason)
    status = MEMBERSHIP_STATUS_CURRENT if not result.unresolved else MEMBERSHIP_STATUS_STALE
    await persist_membership_truth(
        session_factory,
        source_id,
        status=status,
        stale_detected=len(result.stale_ids),
        stale_retired=result.retired,
        detail=truth_detail_of(result),
    )
    return {
        "source_prefix": source_id,
        "mode": "apply",
        "status": result.status,
        "currency_status": status,
        "authoritative_membership_count": result.enumerated_count,
        "ledger_serving_count": result.ledger_active_count,
        "stale_detected": len(result.stale_ids),
        "stale_retired": result.retired,
        "residual": list(result.residual_ids),
    }


async def main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reconcile_membership")
    parser.add_argument("--source", required=True, help="数据源 ID(严格前缀圈定)")
    parser.add_argument("--apply", action="store_true", help="显式执行(缺省=dry-run 计划)")
    parser.add_argument("--output", type=Path, default=None, help="计划 JSON 落盘路径")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    session_factory = get_session_factory(engine)
    # 同步账本面(墓碑原语/成员读取,与 sync pipeline._session_factory 同语义)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine(settings.postgres_dsn.replace("+asyncpg", "+psycopg2"))
    sync_session_factory = sessionmaker(bind=sync_engine)
    try:
        async with session_factory() as session:
            from backend.db.models import DataSource

            row = (
                await session.execute(
                    select(DataSource).where(DataSource.id == args.source)
                )
            ).scalar_one_or_none()
        if row is None:
            print(f"ERROR: data source not found: {args.source}", file=sys.stderr)
            return 2
        connector = ConnectorRegistry.create(to_source_config(row))
        if not hasattr(connector, "membership_source_ids"):
            print(
                f"ERROR: connector type '{row.type}' 无权威成员枚举能力"
                "(membership_source_ids);#71 矫正机制仅适用具备该能力的源",
                file=sys.stderr,
            )
            return 2

        if not args.apply:
            plan = await build_plan(sync_session_factory, connector, args.source)
            rendered = json.dumps(plan, ensure_ascii=False, indent=2)
            print(rendered)
            if args.output:
                args.output.write_text(rendered, encoding="utf-8")
                print(f"plan written: {args.output}", file=sys.stderr)
            print(
                f"\nDRY-RUN 计划:{plan['total_documents']} 篇陈旧 / "
                f"{plan['total_chunks']} chunks(逻辑退休;零副作用已保持)",
                file=sys.stderr,
            )
            return 0

        try:
            result = await apply_plan(
                session_factory,
                sync_session_factory,
                connector,
                args.source,
                reason=f"authorized-correction:{args.source}",
            )
        except MembershipTruthPersistenceError as exc:
            print(
                "ERROR: 矫正退休已提交,但货币真值持久化失败(绝不伪造成功;"
                "下一轮/重试将重新建立真值):\n"
                f"  {exc}",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "completed" or result["residual"]:
            print("ERROR: reconciliation 未完全收敛(见 residual)", file=sys.stderr)
            return 1
        print(
            f"\nAPPLY 完成:retired={result['stale_retired']} / "
            f"detected={result['stale_detected']}(幂等;重复执行将收敛为 0)",
            file=sys.stderr,
        )
        return 0
    finally:
        await engine.dispose()
        sync_engine.dispose()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
