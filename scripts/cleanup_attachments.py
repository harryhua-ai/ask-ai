"""清理 30 天前的附件物理文件(保留 DB 元数据 + extracted_text)。

cron: 每日 03:00 跑一次。部署侧 cron 不在本 plan。
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import Attachment
from backend.db.session import get_engine, get_session_factory

RETENTION_DAYS = 30


async def main() -> int:
    engine = get_engine(load_settings().postgres_dsn)
    sf = get_session_factory(engine)
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    cleaned = 0
    async with sf() as s:
        rows = (
            await s.execute(
                select(Attachment).where(
                    Attachment.created_at < cutoff,
                    Attachment.storage_path.isnot(None),
                )
            )
        ).scalars().all()
        for att in rows:
            if att.storage_path:
                p = Path(att.storage_path)
                if p.exists():
                    p.unlink()
                att.storage_path = None
                cleaned += 1
        await s.commit()
    print(f"cleaned {cleaned} attachments")
    return cleaned


if __name__ == "__main__":
    asyncio.run(main())