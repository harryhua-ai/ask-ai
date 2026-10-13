"""#124 错误联系方式可审计作废:sales_leads 补作废审计列(幂等加性迁移)。

为授权管理员提供「标记无效/作废」能力的持久化地基:
- contact_voided BOOLEAN NOT NULL DEFAULT false(存量行 = 未作废,零回填);
- contact_voided_at / contact_voided_by / contact_voided_reason(作废审计:
  时间 / 操作人 / 理由,NULL = 未作废)。

语义边界(Contract):作废绝不删除/改写 contact_value / contact_masked /
contact_captured_at 原文(必要历史审计不可恢复擦除被禁止);作废记录不再
计入有效 contact_captured/有效联系数,漏斗单独统计作废数量。

本脚本供 Production Gate 显式执行/校验,不依赖应用启动;幂等
(列已存在时 catalog 探测 no-op),生产执行窗口任意(纯加列)。

用法:
    python scripts/migrate_add_sales_lead_contact_void.py [--dry-run]
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import ensure_sales_lead_contact_void_columns, get_engine

_VOID_COLUMNS = (
    "contact_voided",
    "contact_voided_at",
    "contact_voided_by",
    "contact_voided_reason",
)


async def migrate(engine) -> None:
    await ensure_sales_lead_contact_void_columns(engine)
    print("OK: sales_leads 作废审计列就绪(幂等迁移完成)")


async def _main() -> None:
    ap = argparse.ArgumentParser(description="sales_leads 作废审计列加性迁移(幂等)")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写入")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    try:
        if args.dry_run:
            async with engine.begin() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'sales_leads'"
                    )
                )
                cols = {r[0] for r in rows}
            missing = [c for c in _VOID_COLUMNS if c not in cols]
            if missing:
                print(f"[dry-run] sales_leads 缺列 {missing},非 dry-run 模式将补齐")
            else:
                print("[skip] sales_leads 作废审计列已存在,无需迁移")
            return
        await migrate(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
