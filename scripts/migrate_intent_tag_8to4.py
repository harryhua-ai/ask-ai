"""历史 intent_tag 8 类 → 4 类一次性迁移(幂等)。

用法:
    python scripts/migrate_intent_tag_8to4.py [--dry-run]
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
from backend.db.session import get_engine  # noqa: E402

# 历史 8 类 → 新 4 类映射(语义对齐)
MAPPING = {
    "product_spec": "product",
    "getting_started": "product",
    "comparison": "product",
    "documentation": "product",
    "tech_support": "support",
    "api_reference": "support",
    "pricing": "commercial",
    "other": "off_topic",
}


async def main() -> int:
    ap = argparse.ArgumentParser(description="历史 intent_tag 8→4 迁移(幂等)")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    total = 0
    async with engine.begin() as conn:
        for old, new in MAPPING.items():
            if args.dry_run:
                result = await conn.execute(
                    text("SELECT count(*) FROM conversations WHERE intent_tag = :t"),
                    {"t": old},
                )
                n = result.scalar() or 0
                print(f"[dry-run] {old} -> {new}: {n} rows")
            else:
                result = await conn.execute(
                    text(
                        "UPDATE conversations SET intent_tag = :new "
                        "WHERE intent_tag = :old"
                    ),
                    {"new": new, "old": old},
                )
                n = result.rowcount or 0
                print(f"{old} -> {new}: {n} rows updated")
            total += n
    await engine.dispose()
    suffix = " (dry-run)" if args.dry_run else " 迁移完成"
    print(f"\n总计: {total} 行{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
