"""Attachment 模型 CRUD + 归属校验测试。"""
import uuid
import pytest
from sqlalchemy import select

from backend.db.models import Attachment, Conversation


@pytest.mark.unit
async def test_attachment_create_minimal(db_session):
    """最小字段创建(vision_done 默认 False,kind=log)。"""
    att = Attachment(
        id=uuid.uuid4(),
        owner_type="widget_anon",
        owner_id="sess-abc",
        filename="error.log",
        mime_type="text/x-log",
        kind="log",
        size_bytes=1024,
    )
    db_session.add(att)
    await db_session.commit()
    fetched = (await db_session.execute(select(Attachment).where(Attachment.id == att.id))).scalar_one()
    assert fetched.vision_done is False
    assert fetched.kind == "log"
    assert fetched.extracted_text is None
    assert fetched.storage_path is None  # 清理后为 null


@pytest.mark.unit
async def test_attachment_owner_isolation(db_session):
    """不同 owner_id 的附件隔离(widget session 防误用)。"""
    a1 = Attachment(id=uuid.uuid4(), owner_type="widget_anon", owner_id="sess-A",
                   filename="a.log", mime_type="text/x-log", kind="log", size_bytes=10)
    a2 = Attachment(id=uuid.uuid4(), owner_type="widget_anon", owner_id="sess-B",
                   filename="b.log", mime_type="text/x-log", kind="log", size_bytes=10)
    db_session.add_all([a1, a2])
    await db_session.commit()
    mine = (await db_session.execute(
        select(Attachment).where(Attachment.owner_id == "sess-A"))).scalars().all()
    assert len(mine) == 1
    assert mine[0].filename == "a.log"
