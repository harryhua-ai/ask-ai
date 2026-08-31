"""C9 编辑流:upload_mode 数据源的后端契约测试。

覆盖:
- 创建 upload_mode 源时服务端强制 root_path=上传落盘目录(用户不可填,回归护栏)
- PATCH 更新后 root_path 不被前端提交的空值抹掉(编辑保存不得破坏同步根路径)
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建临时管理员并返回 Authorization 头,结束后清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="c9-edit-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def _cleanup_source(source_id: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == source_id))
        await session.commit()


def _upload_payload(source_id: str) -> dict:
    """模拟前端创建 upload_mode 源的提交:root_path 留空(由服务端补)。"""
    return {
        "id": source_id,
        "type": "filesystem",
        "product": "knowledge",
        "enabled": True,
        "sync_interval": "24h",
        "config": {"upload_mode": True, "file_types": [".md"], "root_path": ""},
    }


async def test_create_upload_source_forces_root_path(auth_headers):
    source_id = f"knowledge-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/data-sources", json=_upload_payload(source_id), headers=auth_headers
            )
        assert resp.status_code == 201, resp.text
        expected = f"data/uploads/data-sources/{source_id}"
        assert resp.json()["config"]["root_path"] == expected
    finally:
        await _cleanup_source(source_id)


async def test_update_upload_source_keeps_root_path(auth_headers):
    source_id = f"knowledge-{uuid.uuid4().hex[:8]}"
    expected = f"data/uploads/data-sources/{source_id}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/data-sources", json=_upload_payload(source_id), headers=auth_headers
            )
            assert resp.status_code == 201, resp.text

            # 模拟前端编辑保存:config 整体提交且 root_path 为空串(现状 buildConfig 行为)
            patch_payload = {
                "type": "filesystem",
                "product": "knowledge",
                "enabled": True,
                "sync_interval": "24h",
                "config": {
                    "upload_mode": True,
                    "file_types": [".md", ".txt"],
                    "include_dirs": ["sub"],
                    "root_path": "",
                },
            }
            patched = await client.patch(
                f"/api/admin/data-sources/{source_id}", json=patch_payload, headers=auth_headers
            )
        assert patched.status_code == 200, patched.text
        cfg = patched.json()["config"]
        assert cfg["root_path"] == expected, "编辑保存不得抹掉上传源的 root_path"
        assert cfg["include_dirs"] == ["sub"]
        assert cfg["file_types"] == [".md", ".txt"]
    finally:
        await _cleanup_source(source_id)
