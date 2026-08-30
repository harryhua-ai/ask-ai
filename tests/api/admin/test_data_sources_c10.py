"""C10:github 源可诊断性与表单缺陷修复的后端契约测试。

覆盖:
- preview-branches 返回 default_branch(供表单默认分支,消除 "main" 硬编码)
- 创建/同步前校验 branches ⊆ 远端分支(不合法拦截)
- 同仓库已有源时 clone_path 冲突拦截(显式配置不同路径方可创建)
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

REMOTE_BRANCHES = ["master", "dev"]
REMOTE_DEFAULT = "master"


class _FakeResp:
    """httpx.Response 最小桩。"""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeGitHubClient:
    """模拟 GitHub API:仓库信息(默认分支)+ 分支列表。"""

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if url.endswith("/branches?per_page=100"):
            return _FakeResp([{"name": b} for b in REMOTE_BRANCHES])
        return _FakeResp({"default_branch": REMOTE_DEFAULT})


@pytest.fixture
def fake_github(monkeypatch):
    """把数据源端点的 httpx.AsyncClient 替换为 GitHub API 桩。"""
    import backend.api.admin.data_sources as ds_mod

    monkeypatch.setattr(ds_mod.httpx, "AsyncClient", _FakeGitHubClient)


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建临时管理员并返回 Authorization 头,结束后清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="c10-admin@test.com",
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


def _github_payload(source_id: str, branches: list[str], clone_path: str | None = None) -> dict:
    config: dict = {"repo_url": "https://github.com/camthink-ai/demo-repo.git"}
    if branches:
        config["branches"] = branches
    if clone_path:
        config["clone_path"] = clone_path
    return {
        "id": source_id,
        "type": "github",
        "product": "demo",
        "enabled": True,
        "sync_interval": "24h",
        "config": config,
    }


async def test_preview_branches_returns_default_branch(fake_github, auth_headers):
    """preview-branches 应附 default_branch(表单默认分支数据源)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/data-sources/preview-branches?owner=camthink-ai&repo=demo-repo",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["branches"] == ["master", "dev"]
    assert body["default_branch"] == "master"


async def test_create_github_source_rejects_unknown_branch(fake_github, auth_headers):
    """branches 含远端不存在的分支 → 400 拦截(不再静默带入坏分支)。"""
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/data-sources",
                json=_github_payload("c10-bad-branch", ["master", "ghost-branch"]),
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "ghost-branch" in resp.json()["detail"]
    finally:
        await _cleanup_source("c10-bad-branch")


async def test_create_duplicate_repo_conflict_requires_distinct_clone_path(fake_github, auth_headers):
    """同仓库已有源:未显式配置 clone_path → 409;显式配置 → 放行。"""
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/admin/data-sources",
                json=_github_payload("c10-repo-a", ["master"]),
                headers=auth_headers,
            )
            assert first.status_code == 201

            dup = await client.post(
                "/api/admin/data-sources",
                json=_github_payload("c10-repo-b", ["master"]),
                headers=auth_headers,
            )
            assert dup.status_code == 409
            assert "clone_path" in dup.json()["detail"]

            distinct = await client.post(
                "/api/admin/data-sources",
                json=_github_payload(
                    "c10-repo-c", ["master"], clone_path="~/ask-ai-corpus/demo-repo-c10"
                ),
                headers=auth_headers,
            )
            assert distinct.status_code == 201
    finally:
        await _cleanup_source("c10-repo-a")
        await _cleanup_source("c10-repo-b")
        await _cleanup_source("c10-repo-c")


async def test_sync_rejects_invalid_branches(fake_github, auth_headers):
    """同步前校验:branches 含远端不存在分支 → 400,不派发后台任务。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id="c10-stale-branch",
                type="github",
                product="demo",
                enabled=True,
                config={
                    "repo_url": "https://github.com/camthink-ai/demo-repo.git",
                    "branches": ["ghost-branch"],
                },
                sync_interval="24h",
            )
        )
        await session.commit()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/data-sources/c10-stale-branch/sync",
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "ghost-branch" in resp.json()["detail"]
    finally:
        await _cleanup_source("c10-stale-branch")
