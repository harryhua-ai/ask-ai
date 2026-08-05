"""POST /api/upload 集成测试(widget 端点)。"""
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.db.models import Attachment
from backend.main import app


@pytest.fixture
async def _upload_session_factory(db_engine):
    """把测试 DB session_factory 注入 app.state,供上传端点 + BackgroundTask 使用。"""
    from backend.db.session import get_session_factory

    factory = get_session_factory(db_engine)
    app.state.session_factory = factory
    yield factory


@pytest.mark.integration
async def test_upload_single_log(_upload_session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/upload",
            data={"session_id": "s1"},
            files=[("files", ("err.log", io.BytesIO(b"ERROR crash\n"), "text/x-log"))],
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["attachments"][0]["ok"] is True
    assert data["attachments"][0]["kind"] == "log"
    assert data["attachments"][0]["status"] in ("ready", "processing")


@pytest.mark.integration
async def test_upload_rejects_exe_disguised(_upload_session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    pe_header = b"MZ\x90\x00\x03\x00"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/upload",
            data={"session_id": "s1"},
            files=[("files", ("fake.txt", io.BytesIO(pe_header), "text/plain"))],
        )
    # 单文件且被拒 → 422(全拒);body 无 attachments 键
    assert resp.status_code == 422


@pytest.mark.integration
async def test_upload_masks_pii_in_log(_upload_session_factory, tmp_path, monkeypatch):
    """日志含邮箱 → 入库 extracted_text 已脱敏(BackgroundTask 完成后)。"""
    import asyncio

    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/upload",
            data={"session_id": "s1"},
            files=[
                (
                    "files",
                    ("p.log", io.BytesIO(b"contact john@example.com\n"), "text/x-log"),
                )
            ],
        )
    assert resp.status_code == 200, resp.text
    att_id = resp.json()["attachments"][0]["id"]

    # 轮询 DB 等 BackgroundTask 完成(最多 5s)
    sf = _upload_session_factory
    att = None
    for _ in range(20):
        await asyncio.sleep(0.25)
        async with sf() as s:
            att = await s.get(Attachment, uuid.UUID(att_id))
            if att and att.extracted_text is not None:
                break
    assert att is not None and att.extracted_text is not None, "BackgroundTask 未完成"
    assert "john@example.com" not in att.extracted_text  # 邮箱已脱敏
