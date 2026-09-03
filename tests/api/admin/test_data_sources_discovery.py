"""#16 discover-repo 端点契约测试(Simple Mode preview)。

覆盖:
- Repo URL(+可选分支)→ S0 DiscoveryResultOut envelope + 推荐编译 config;
- branch 缺省时远端默认分支解析;
- 非法 repo_url / 远端不可达 → 400(脱敏,不含内部堆栈);
- viewer 无权(发现属 editor+ 操作,与既有 preview 端点同权限位)。

全部 GitHub IO 经 monkeypatch 注入,零真实网络。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
from backend.main import app
from backend.services import repo_discovery as rd_mod

pytestmark = pytest.mark.asyncio(loop_scope="session")

TREE = {
    "tree": [
        {"path": "README.md", "type": "blob", "size": 200},
        {"path": "src/main.py", "type": "blob", "size": 1000},
        {"path": "tests/test_main.py", "type": "blob", "size": 300},
        {"path": "assets/logo.png", "type": "blob", "size": 4096},
        {"path": "deploy/id_rsa", "type": "blob", "size": 50},
    ],
    "truncated": False,
}


@pytest.fixture
def fake_github_api(monkeypatch):
    """替换 default_api_get:记录请求 path,返回桩数据。"""
    calls: list[str] = []

    def api_get(path: str) -> dict:
        calls.append(path)
        if path == "/repos/o/r":
            return {"default_branch": "main"}
        if path == "/repos/o/r/git/trees/main?recursive=1":
            return dict(TREE)
        raise rd_mod.RepoDiscoveryError("仓库或分支不存在(或无权访问)")

    monkeypatch.setattr(rd_mod, "default_api_get", api_get)
    return calls


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="i16-admin@test.com",
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


async def _post(client: AsyncClient, headers: dict, payload: dict):
    return await client.post(
        "/api/admin/data-sources/discover-repo", json=payload, headers=headers
    )


async def test_discover_returns_s0_envelope_and_recommended_config(fake_github_api, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(
            client,
            auth_headers,
            {"repo_url": "https://github.com/o/r.git", "branch": "main"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "github"
    assert body["target"] == {"owner": "o", "repo": "r", "branch": "main"}
    assert body["totals"]["files"] == 5
    assert body["totals"]["unsafe_files"] == 1
    # 推荐编译产物 = 既有 config 词表;review(png)/unsafe(id_rsa)不进白名单
    assert body["recommended_config"]["file_types"] == [".md", ".py"]
    assert "tests" in body["recommended_config"]["exclude_dirs"]
    # 每个候选都带人读理由;分组保持
    assert all(c["reason"] for c in body["candidates"])
    assert {g["key"] for g in body["groups"]} == {"(根目录)", "src", "tests", "assets", "deploy"}


async def test_discover_resolves_default_branch_when_branch_omitted(fake_github_api, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, auth_headers, {"repo_url": "https://github.com/o/r"})
    assert resp.status_code == 200
    assert resp.json()["target"]["branch"] == "main"
    assert "/repos/o/r" in fake_github_api


async def test_discover_invalid_repo_url_returns_400(fake_github_api, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, auth_headers, {"repo_url": "https://gitlab.com/o/r"})
    assert resp.status_code == 400
    assert "repo_url" in resp.json()["detail"]


async def test_discover_remote_error_maps_to_400_sanitized(fake_github_api, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(
            client,
            auth_headers,
            {"repo_url": "https://github.com/o/r", "branch": "ghost"},
        )
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]


async def test_discover_requires_editor_role(fake_github_api):
    """viewer 只读角色不能触发发现(与既有 preview 端点同权限位)。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="i16-viewer@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(
                client,
                {"Authorization": f"Bearer {token}"},
                {"repo_url": "https://github.com/o/r", "branch": "main"},
            )
        assert resp.status_code == 403
    finally:
        async with factory() as session:
            await session.execute(User.__table__.delete().where(User.id == user_id))
            await session.commit()
