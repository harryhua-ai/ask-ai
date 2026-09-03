"""#10 Admin release 端点契约测试(GET /api/admin/system/release)。

- auth required(未认证 401;viewer/editor/admin 均可读——与 Admin 只读页一致);
- 返回值 = 进程级 release authority(backend.release 单例),非前端/环境可变值;
- 只读、无环境 dump:响应键精确锁定。
"""

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
from backend.main import app
from backend.release import reset_release_identity_cache

pytestmark = pytest.mark.asyncio(loop_scope="session")

MANIFEST = {
    "version": "1.2.3",
    "git_sha": "b" * 40,
    "built_at": "2026-09-03T08:30:00Z",
    "image": "ghcr.io/harryhua-ai/ask-ai:v1.2.3",
    "ci_run_id": "98765",
}


@pytest.fixture
def pinned_release(tmp_path: Path, monkeypatch):
    """把进程 release authority 钉到已知 manifest,校验 API 直呈同一权威。"""
    f = tmp_path / "RELEASE.json"
    f.write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setattr("backend.release._RELEASE_FILE", f)
    monkeypatch.setenv("APP_MODE", "prod")
    reset_release_identity_cache()
    yield
    reset_release_identity_cache()


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="i10-admin@test.com",
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


async def test_release_requires_auth(pinned_release):
    """未认证请求 → 401(Admin 端点既有 auth 约定)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/system/release")
    assert resp.status_code == 401


async def test_release_returns_runtime_authority(pinned_release, auth_headers):
    """返回值 = 运行时 release authority(RELEASE.json 单例),逐字段相等。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/system/release", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == MANIFEST["version"]
    assert body["git_sha"] == MANIFEST["git_sha"]
    assert body["built_at"] == MANIFEST["built_at"]
    assert body["image"] == MANIFEST["image"]
    assert body["ci_run_id"] == MANIFEST["ci_run_id"]
    assert body["app_mode"] == "production"
    assert body["source"] == "manifest"


async def test_release_response_keys_locked(pinned_release, auth_headers):
    """响应键精确锁定:只读身份,无环境 dump、无密钥面。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/system/release", headers=auth_headers)
    assert set(resp.json().keys()) == {
        "version", "git_sha", "built_at", "app_mode", "image", "ci_run_id", "source",
    }


async def test_health_matches_release_authority(pinned_release):
    """/health 与 Admin 端点同源:同一 release authority。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = (await client.get("/health")).json()
        release = (
            await client.get("/api/admin/system/release")
        )
    assert health["version"] == MANIFEST["version"]
    assert health["git_sha"] == MANIFEST["git_sha"]
    assert health["status"] == "ok"
    # release 端点仍需认证(此处仅断言 health 不受影响)
    assert release.status_code == 401
