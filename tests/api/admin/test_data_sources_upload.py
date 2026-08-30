"""C9:filesystem 数据源上传端点契约测试。

覆盖:
- 落盘保留相对路径嵌套结构;响应计数
- 路径穿越拒绝(绝对路径 / .. 段 / 混合)
- 单文件超 20MB 拒收
- 源配置 file_types 白名单外拒收
- files/paths 数量不一致拒收;非 filesystem 源拒收
"""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

MB = 1024 * 1024


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建临时管理员并返回 Authorization 头,结束后清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="c9-admin@test.com",
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


async def _seed_fs_source(source_id: str, file_types: list[str] | None = None) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        config: dict = {}
        if file_types is not None:
            config["file_types"] = file_types
        session.add(
            DataSource(
                id=source_id,
                type="filesystem",
                product="demo",
                enabled=True,
                config=config,
                sync_interval="24h",
            )
        )
        await session.commit()


async def _cleanup_source(source_id: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == source_id))
        await session.commit()


@pytest.fixture
def upload_cwd(tmp_path, monkeypatch):
    """把 CWD 切到临时目录:上传落盘 data/uploads/... 落在 tmp,自动清理。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def _upload(client, headers, source_id, items: list[tuple[str, bytes]]):
    files = [(f"files", (name, content, "application/octet-stream")) for name, content in items]
    return await client.post(
        f"/api/admin/data-sources/{source_id}/upload",
        files=files,
        data={"paths": [name for name, _ in items]},
        headers=headers,
    )


async def test_upload_saves_nested_paths(upload_cwd, auth_headers):
    """上传落盘保留嵌套目录结构;响应 saved 计数;内容与文件名一致。"""
    sid = "c9-upload-nested"
    await _seed_fs_source(sid, file_types=[".md"])
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _upload(
                client,
                auth_headers,
                sid,
                [("docs/guide/a.md", b"# Guide"), ("b.md", b"# B"), ("deep/nested/c.md", b"C")],
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["saved"] == 3
        assert body["root"] == f"data/uploads/data-sources/{sid}"
        base = upload_cwd / "data" / "uploads" / "data-sources" / sid
        assert (base / "docs" / "guide" / "a.md").read_bytes() == b"# Guide"
        assert (base / "b.md").read_bytes() == b"# B"
        assert (base / "deep" / "nested" / "c.md").read_bytes() == b"C"
    finally:
        await _cleanup_source(sid)


async def test_upload_rejects_path_traversal(upload_cwd, auth_headers):
    """路径穿越防护:绝对路径 / .. 段 / 混合穿越一律 400,且不落盘。"""
    sid = "c9-upload-traversal"
    await _seed_fs_source(sid, file_types=[".md"])
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for bad in ["/etc/x.md", "../escape.md", "a/../../x.md", "docs/../../out.md"]:
                resp = await _upload(client, auth_headers, sid, [(bad, b"x")])
                assert resp.status_code == 400, bad
                assert "路径" in resp.json()["detail"]
        assert not (upload_cwd / "escape.md").exists()
        assert not (upload_cwd / "x.md").exists()
    finally:
        await _cleanup_source(sid)


async def test_upload_rejects_oversize_file(upload_cwd, auth_headers):
    """单文件超过 20MB → 400 拒收。"""
    sid = "c9-upload-oversize"
    await _seed_fs_source(sid, file_types=[".md"])
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _upload(
                client, auth_headers, sid, [("big.md", b"x" * (20 * MB + 1))]
            )
        assert resp.status_code == 400
        assert "20MB" in resp.json()["detail"]
    finally:
        await _cleanup_source(sid)


async def test_upload_rejects_outside_whitelist(upload_cwd, auth_headers):
    """源配置了 file_types 白名单 → 白名单外后缀 400 拒收。"""
    sid = "c9-upload-whitelist"
    await _seed_fs_source(sid, file_types=[".md"])
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _upload(client, auth_headers, sid, [("script.py", b"print(1)")])
        assert resp.status_code == 400
        assert "白名单" in resp.json()["detail"]
    finally:
        await _cleanup_source(sid)


async def test_upload_rejects_count_mismatch_and_non_fs(upload_cwd, auth_headers):
    """files/paths 数量不一致 → 400;非 filesystem 源 → 400。"""
    sid = "c9-upload-misc"
    await _seed_fs_source(sid, file_types=[])
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = [("files", ("a.md", b"x", "text/plain"))]
            resp = await client.post(
                f"/api/admin/data-sources/{sid}/upload",
                files=files,
                data={"paths": ["a.md", "b.md"]},
                headers=auth_headers,
            )
            assert resp.status_code == 400

            # github 源不支持上传
            factory = app.state.session_factory
            async with factory() as session:
                session.add(
                    DataSource(
                        id="c9-github-src",
                        type="github",
                        product="demo",
                        enabled=True,
                        config={"repo_url": "https://github.com/camthink-ai/demo.git"},
                        sync_interval="24h",
                    )
                )
                await session.commit()
            resp = await _upload(client, auth_headers, "c9-github-src", [("a.md", b"x")])
            assert resp.status_code == 400
            assert "filesystem" in resp.json()["detail"]
    finally:
        await _cleanup_source(sid)
        await _cleanup_source("c9-github-src")
