"""为 sales_leads 添加资格来源列,保留无法证明来源的历史 NULL 值。

本迁移仅加一列,不回填、不改写任何 raw status 或历史记录。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import ensure_sales_lead_qualification_provenance_column, get_engine


async def main() -> None:
    parser = argparse.ArgumentParser(description="sales_leads 资格来源列加性迁移")
    parser.add_argument("--dry-run", action="store_true", help="只检查是否缺列")
    args = parser.parse_args()
    engine = get_engine(load_settings().postgres_dsn)
    try:
        if args.dry_run:
            async with engine.begin() as conn:
                exists = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema=current_schema() AND table_name='sales_leads' "
                        "AND column_name='qualification_provenance'"
                    )
                )
            print("[skip] qualification_provenance 已存在" if exists.scalar() else "[dry-run] 缺 qualification_provenance")
        else:
            await ensure_sales_lead_qualification_provenance_column(engine)
            print("OK: qualification_provenance 就绪;历史值保持 NULL")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
