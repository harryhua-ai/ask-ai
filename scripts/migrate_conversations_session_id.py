"""conversations 表补 session_id 列(Sales Lead 会话线程依赖,幂等)。

既有库必须显式执行(``init_db``/create_all 不给已存在的表加列);
新库由 create_all 直接带列,本脚本执行时为 no-op。

用法:
    python scripts/migrate_conversations_session_id.py [--dry-run]
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


async def main() -> int:
    ap = argparse.ArgumentParser(description="conversations 补 session_id 列(幂等)")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写入")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    try:
        async with engine.begin() as conn:
            col_exists = await conn.scalar(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.columns"
                    "  WHERE table_schema='public' AND table_name='conversations'"
                    "        AND column_name='session_id'"
                    ")"
                )
            )
            if col_exists:
                nulls = await conn.scalar(
                    text("SELECT COUNT(*) FROM conversations WHERE session_id IS NULL")
                )
                print(
                    f"[skip] conversations.session_id 已存在,{nulls} 行为 NULL(历史数据,无需回填)"
                )
                return 0
            if args.dry_run:
                print("[dry-run] conversations.session_id 不存在,将在非 dry-run 模式添加")
                return 0
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN session_id VARCHAR(64)"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_session_id"
                    " ON conversations (session_id)"
                )
            )
        print("[ok] conversations.session_id 列与索引已创建")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
