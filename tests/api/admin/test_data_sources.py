"""数据源管理端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户并返回 Authorization 头；测试结束后清理测试数据源与用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="ds-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理：仅删除本测试创建的数据源和用户，避免破坏 Task 9 迁移的共享 dev 数据
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == "test-source"))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == "test-source"))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_create_and_list_data_source(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/data-sources",
            json={
                "id": "test-source",
                "type": "github",
                "product": "test",
                "config": {"owner": "camthink-ai", "repo": "test"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        resp = await client.get("/api/admin/data-sources", headers=auth_headers)
        assert resp.status_code == 200
        assert any(s["id"] == "test-source" for s in resp.json())


async def test_list_data_sources_includes_latest_sync(auth_headers):
    """list 端点聚合 sync_log 最新一条,返回 last_sync(同步时间并入数据源页面)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/data-sources",
            json={
                "id": "test-source",
                "type": "github",
                "product": "test",
                "config": {"repo_url": "https://github.com/camthink-ai/test.git"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            SyncLog(
                source_id="test-source",
                source_type="github",
                status="success",
                triggered_by="cron",
            )
        )
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/data-sources", headers=auth_headers)
        assert resp.status_code == 200
        entry = next(s for s in resp.json() if s["id"] == "test-source")
        assert entry["last_sync"] is not None, "最新同步时间应从 sync_log 聚合返回"
        assert "T" in entry["last_sync"] or " " in entry["last_sync"]


async def test_preview_dirs_lists_subdirs(tmp_path, auth_headers):
    """preview-dirs 返回 root_path 下的子目录(不列文件/系统目录/隐藏目录)。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "en").mkdir()
    (root / "src").mkdir()
    (root / "node_modules").mkdir()  # 系统目录,应过滤
    (root / ".hidden").mkdir()  # 隐藏目录,应过滤
    (root / "README.md").write_text("x", encoding="utf-8")  # 文件,不列
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/data-sources/preview-dirs",
            params={"root_path": str(root)},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    names = {d["name"] for d in data["dirs"]}
    assert "docs" in names and "src" in names
    assert "node_modules" not in names  # 系统目录过滤
    assert ".hidden" not in names  # 隐藏目录过滤
    # 子层递归:docs 下应有 en
    docs_entry = next(d for d in data["dirs"] if d["name"] == "docs")
    assert docs_entry["children_count"] >= 1
    child_names = {c["name"] for c in docs_entry["children"]}
    assert "en" in child_names
    # 子层路径为相对 root 的相对路径
    en_child = next(c for c in docs_entry["children"] if c["name"] == "en")
    assert en_child["path"] == "docs/en"


async def test_preview_dirs_nonexistent_root_404(auth_headers):
    """root_path 不存在时返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/data-sources/preview-dirs",
            params={"root_path": "/nonexistent/xxx_abc_123_zzz"},
            headers=auth_headers,
        )
    assert resp.status_code == 404


async def test_preview_branches(auth_headers, monkeypatch):
    """preview-branches 应调 GitHub API 返回分支列表与默认分支(mock httpx)。"""
    from unittest.mock import AsyncMock, MagicMock

    import backend.api.admin.data_sources as mod

    def _resp(payload):
        fake = MagicMock()
        fake.raise_for_status.return_value = None
        fake.json.return_value = payload
        return fake

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(
        side_effect=lambda url: (
            _resp([{"name": "main"}, {"name": "hw-v1.2"}])
            if url.endswith("/branches?per_page=100")
            else _resp({"default_branch": "main"})
        )
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/data-sources/preview-branches?owner=o&repo=r",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["branches"] == ["main", "hw-v1.2"]
    assert data["default_branch"] == "main"


async def test_sync_all_returns_enabled_source_ids_skips_disabled(auth_headers, monkeypatch):
    """sync-all 返回启用源 id+count、跳过禁用源;整批一次派生独立执行面子进程。

    P4(阶段9):端点只提交任务,绝不 in-process 执行 ingest —— 以
    scripts.sync._sync_one 置雷(误入进程内执行即 AssertionError)防线证明。
    """
    import sys

    import scripts.sync as sync_mod
    from backend.main import app
    from backend.services import sync_executor

    spawned: list[tuple[list[str], dict]] = []

    class _FakeProc:
        pid = 4242
        returncode = None  # None = 存活

    async def _fake_spawn(*argv, **kwargs):
        spawned.append((list(argv), kwargs))
        return _FakeProc()

    monkeypatch.setattr(sync_executor, "_spawn", _fake_spawn)
    monkeypatch.setattr(sync_executor, "_inflight", {})

    def _boom(*a, **k):
        raise AssertionError("sync-all 不得在 backend 进程内执行同步业务逻辑")

    monkeypatch.setattr(sync_mod, "_sync_one", _boom)

    factory = app.state.session_factory
    # 前置清理:防历史失败残留(上次 finally 未跑导致主键冲突)
    async with factory() as session:
        await session.execute(
            DataSource.__table__.delete().where(
                DataSource.id.in_(["test-sync-enabled", "test-sync-disabled"])
            )
        )
        await session.commit()
    async with factory() as session:
        session.add(
            DataSource(
                id="test-sync-enabled",
                type="filesystem",
                product="test",
                enabled=True,
                config={"root_path": "/tmp"},
                sync_interval="24h",
            )
        )
        session.add(
            DataSource(
                id="test-sync-disabled",
                type="filesystem",
                product="test",
                enabled=False,
                config={"root_path": "/tmp"},
                sync_interval="24h",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert "test-sync-enabled" in data["source_ids"]
        assert "test-sync-disabled" not in data["source_ids"]  # 跳过禁用
        assert data["count"] == len(data["source_ids"])
        assert data["count"] >= 1
        # 整批一个子进程(脚本内顺序跑源,单 pipeline 防 GPU OOM),argv 逐元素无 shell
        assert len(spawned) == 1
        argv, kwargs = spawned[0]
        assert argv[0] == sys.executable
        assert argv[1].endswith("scripts/sync.py")
        assert "--source" not in argv  # 不带 --source → 脚本内部遍历全部启用源
        assert "--triggered-by" in argv and argv[argv.index("--triggered-by") + 1] == "manual"
        assert kwargs.get("start_new_session") is True  # 脱离 backend 进程组(AC6)
    finally:
        async with factory() as session:
            await session.execute(
                DataSource.__table__.delete().where(
                    DataSource.id.in_(["test-sync-enabled", "test-sync-disabled"])
                )
            )
            await session.commit()
