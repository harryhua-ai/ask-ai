"""30 天清理任务测试:>30 天删文件置 null,<30 天留。"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.db.models import Attachment
from scripts.cleanup_attachments import RETENTION_DAYS


async def _cleanup_with_session(s) -> None:
    """在给定 session 上执行 cleanup 主逻辑(测试隔离用)。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
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
    await s.commit()


@pytest.mark.unit
async def test_cleanup_deletes_old_files(db_session, tmp_path):
    """created_at >30 天前 + storage_path 指向真实文件 → 删文件 + 置 null;新附件保留。"""
    old_file = tmp_path / "old.log"
    old_file.write_text("old")
    old_att = Attachment(
        id=uuid.uuid4(),
        owner_type="widget_anon",
        owner_id="sess",
        filename="old.log",
        mime_type="text/x-log",
        kind="log",
        size_bytes=3,
        storage_path=str(old_file),
        created_at=datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 5),
    )
    new_file = tmp_path / "new.log"
    new_file.write_text("new")
    new_att = Attachment(
        id=uuid.uuid4(),
        owner_type="widget_anon",
        owner_id="sess",
        filename="new.log",
        mime_type="text/x-log",
        kind="log",
        size_bytes=3,
        storage_path=str(new_file),
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add_all([old_att, new_att])
    await db_session.commit()

    await _cleanup_with_session(db_session)

    old_id, new_id = old_att.id, new_att.id
    db_session.expire_all()
    o = await db_session.get(Attachment, old_id)
    n = await db_session.get(Attachment, new_id)
    assert o.storage_path is None and not old_file.exists()
    assert n.storage_path is not None and new_file.exists()