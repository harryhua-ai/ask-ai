"""创建 sales_leads 表(CAMTHINK V1 Sales Lead Capture,幂等)。

新表由后端启动时 ``init_db``(Base.metadata.create_all)自动创建;
本脚本供 Production Gate 显式执行/校验,不依赖应用启动:
- 表已存在 → no-op 并报告行数;
- 表不存在 → 按当前模型 DDL 创建。

用法:
    python scripts/migrate_sales_leads.py [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402

from backend.config import load_settings  # noqa: E402
from backend.db.models import Base, SalesLead  # noqa: E402
from backend.db.session import get_engine  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="创建 sales_leads 表(幂等)")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写入")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    try:
        async with engine.begin() as conn:
            exists = await conn.scalar(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_schema = 'public' AND table_name = 'sales_leads'"
                    ")"
                )
            )
            if exists:
                count = await conn.scalar(text("SELECT COUNT(*) FROM sales_leads"))
                print(f"[skip] sales_leads 已存在,当前 {count} 行,无需迁移")
                return 0
            if args.dry_run:
                print("[dry-run] sales_leads 不存在,将在非 dry-run 模式创建")
                return 0
            # 只创建 metadata 中缺的表(checkfirst=True),不触碰任何已有表
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=[SalesLead.__table__], checkfirst=True
                )
            )
        print("[ok] sales_leads 表已创建")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
