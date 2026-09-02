"""site_experiences 表补 i18n 文案列 + 从 YAML 回填(多语言闭环 G-L5,幂等)。

既有库必须显式执行(``init_db``/create_all 不给已存在的表加列);
新库由 create_all 直接带列并通过 lifespan seed 回填,本脚本执行时为 no-op。
列定义:``welcome_i18n`` / ``starters_i18n``(JSONB,按语言键的体验文案变体)。
回填:与 ``seed_default_sites`` 同源(YAML 为权威),只补 NULL 行,不覆盖已回填值。

⚠️ 本脚本仅本地验证;生产执行属 Production Gate 授权范围。

用法:
    python scripts/migrate_site_experiences_i18n.py [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import get_engine
from backend.services.site_experiences import DEFAULT_SITES_CONFIG, load_sites_config

_COLUMNS = ("welcome_i18n", "starters_i18n")


async def main() -> int:
    ap = argparse.ArgumentParser(description="site_experiences 补 i18n 列 + YAML 回填(幂等)")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写入")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    try:
        async with engine.begin() as conn:
            for col in _COLUMNS:
                col_exists = await conn.scalar(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.columns"
                        "  WHERE table_schema='public' AND table_name='site_experiences'"
                        f"        AND column_name='{col}'"
                        ")"
                    )
                )
                if col_exists:
                    print(f"[skip] site_experiences.{col} 已存在")
                elif args.dry_run:
                    print(f"[dry-run] site_experiences.{col} 不存在,将在非 dry-run 模式添加")
                else:
                    await conn.execute(text(f"ALTER TABLE site_experiences ADD COLUMN {col} JSONB"))
                    print(f"[ok] site_experiences.{col} 已创建")
            if args.dry_run:
                return 0

        # 回填:按 site_id 逐行补 NULL 的 i18n 变体(YAML 权威;不覆盖已有值)
        sites = {str(item["site_id"]): item for item in load_sites_config(DEFAULT_SITES_CONFIG)}
        backfilled = 0
        async with engine.begin() as conn:
            for site_id, item in sites.items():
                welcome_i18n = (
                    json.dumps(item["welcome_i18n"], ensure_ascii=False)
                    if item.get("welcome_i18n")
                    else None
                )
                starters_i18n = (
                    json.dumps(item["starters_i18n"], ensure_ascii=False)
                    if item.get("starters_i18n")
                    else None
                )
                if welcome_i18n is None and starters_i18n is None:
                    continue
                result = await conn.execute(
                    text(
                        "UPDATE site_experiences SET welcome_i18n = COALESCE(:w, welcome_i18n),"
                        " starters_i18n = COALESCE(:s, starters_i18n)"
                        " WHERE site_id = :sid"
                        "   AND (welcome_i18n IS NULL OR starters_i18n IS NULL)"
                    ),
                    {"w": welcome_i18n, "s": starters_i18n, "sid": site_id},
                )
                backfilled += result.rowcount
        print(f"[ok] 回填完成,更新 {backfilled} 行")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
