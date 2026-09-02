"""W6 web_crawl 成员快照提交序 golden 回归(阶段⑩)。

危险窗口(Discovery W6):全量轮 ``fetch_deleted`` 在返回删除清单的**同时**
覆写 crawl-state 快照 → 删除循环中途被 kill → 快照已推进 → 未完成 retirement
永久丢失(ghost)。

冻结不变式(Contract §11):MEMBERSHIP STATE MUST NOT ADVANCE UNTIL RETIREMENT
EFFECTS ARE SAFELY COMPLETED。即:fetch_deleted 只计算差集、不落盘;删除循环
安全完成后由 ``commit_membership_snapshot()`` 推进;kill 于删除中途 → 旧快照
保留 → 下轮重新发现同一差集(重复删除幂等)。
"""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from backend.config import load_settings
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.connectors.web_crawl import WebCrawlConnector, _url_to_source_path

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_connector(tmp_path, monkeypatch, membership):
    """构造不触网的 web_crawl connector:membership = 当前权威成员 URL 列表。"""
    cfg = SourceConfig(
        id="w6",
        type="web_crawl",
        product="web",
        config={"base_url": "https://w6.local"},
        enabled=True,
        sync_interval="24h",
    )
    monkeypatch.chdir(tmp_path)  # 状态文件落 tmp
    conn = WebCrawlConnector(cfg)
    urls = [f"https://w6.local/{u}" for u in membership]
    conn._entries_cache = {u: None for u in urls}
    conn._seen_urls = set(urls)
    conn._last_run_full = True
    conn._accepted_urls = list(urls)
    conn.run_stats = {
        "full": True,
        "discovered": len(urls),
        "accepted": len(urls),
        "extracted": len(urls),
        "failed": 0,
        "rejected": {},
        "failed_urls": [],
        "rejected_urls": {},
    }
    return conn


def _snapshot_ids(membership):
    return sorted(f"w6/{_url_to_source_path(f'https://w6.local/{u}')}" for u in membership)


def _read_state(tmp_path):
    return json.loads((tmp_path / "data" / "crawl-state" / "w6.json").read_text())


def test_fetch_deleted_does_not_advance_snapshot(tmp_path, monkeypatch):
    """fetch_deleted 只报差集;快照必须保持旧值(kill 安全前提)。"""
    conn = _make_connector(tmp_path, monkeypatch, ["a", "b", "c"])
    conn._save_state(_snapshot_ids(["a", "b", "c"]))  # 种入上一轮已提交快照
    assert _read_state(tmp_path) == _snapshot_ids(["a", "b", "c"])
    # 远端收缩为 {a}:发现 b/c 退休候选
    conn2 = _make_connector(tmp_path, monkeypatch, ["a"])
    deleted = list(conn2.fetch_deleted(datetime.now(UTC)))
    assert deleted == _snapshot_ids(["b", "c"])
    # 快照必须未推进(W6 核心)
    assert _read_state(tmp_path) == _snapshot_ids(["a", "b", "c"])


def test_uncommitted_snapshot_survives_restart_and_rediscovery(tmp_path, monkeypatch):
    """kill 于删除中途 → 新实例(旧快照)仍能重新发现同一差集 → 重删幂等收敛。"""
    conn = _make_connector(tmp_path, monkeypatch, ["a", "b", "c"])
    conn._save_state(_snapshot_ids(["a", "b", "c"]))
    conn2 = _make_connector(tmp_path, monkeypatch, ["a"])
    first = list(conn2.fetch_deleted(datetime.now(UTC)))
    assert first == _snapshot_ids(["b", "c"])
    # 模拟删除 b 后进程被 kill:未 commit
    # 重启后的新实例:必须再次发现 c(旧快照仍在)
    conn3 = _make_connector(tmp_path, monkeypatch, ["a"])
    second = list(conn3.fetch_deleted(datetime.now(UTC)))
    assert second == _snapshot_ids(["b", "c"])  # 重复报告 = 幂等重删的依据
    # 删除全部完成后才提交快照
    conn3.commit_membership_snapshot()
    assert _read_state(tmp_path) == _snapshot_ids(["a"])


def test_commit_is_noop_without_pending_snapshot(tmp_path, monkeypatch):
    conn = _make_connector(tmp_path, monkeypatch, ["a"])
    conn.commit_membership_snapshot()  # 无 pending → 不写文件
    assert not (tmp_path / "data" / "crawl-state" / "w6.json").exists()


def test_incremental_round_never_touches_snapshot(tmp_path, monkeypatch):
    """增量轮(_last_run_full=False)fetch_deleted 恒 [] 且不推进/不排队快照。"""
    conn = _make_connector(tmp_path, monkeypatch, ["a", "b"])
    conn._save_state(_snapshot_ids(["a", "b"]))
    conn._last_run_full = False
    conn._accepted_urls = None
    assert list(conn.fetch_deleted(datetime.now(UTC))) == []
    assert conn._pending_snapshot is None
    assert _read_state(tmp_path) == _snapshot_ids(["a", "b"])


# --------------------------------------------------------------------------- #
# _sync_one 集成:commit 必须发生在删除循环**之后**;删除阶段失败不推进快照
# --------------------------------------------------------------------------- #


class _Embed:
    dimension = 8

    def embed(self, texts):
        return [[0.1] * self.dimension for _ in texts]


@ConnectorRegistry.register("w6stub")
class _W6StubConnector:
    """最小 stub:可编程 fetch_deleted/delete 行为 + 快照提交记账。"""

    def __init__(self, config: SourceConfig):
        self.id = config.id
        self.deleted = ["w6stub/d1", "w6stub/d2"]
        self.fail_on = None  # 第 N 次 delete_document 时抛错(1-based);None 不抛
        self.events: list[tuple] = []
        self._committed = False

    @property
    def product(self):
        return "w6"

    def fetch_changes(self, since):
        import hashlib

        from backend.connectors.base import RawDocument

        yield RawDocument(
            source_id="w6stub/keep.md",
            source_type="w6stub",
            product="w6",
            title="keep",
            content="content",
            url="https://w6.local/keep",
            metadata={"path": "keep.md"},
            content_hash=hashlib.sha256(b"keep").hexdigest(),
            branch="default",
        )

    def fetch_deleted(self, since):
        self.events.append(("fetch_deleted", tuple(self.deleted)))
        return list(self.deleted)

    def commit_membership_snapshot(self):
        self.events.append(("commit",))
        self._committed = True


@pytest_asyncio.fixture(loop_scope="session")
async def _sync_env():
    from unittest.mock import MagicMock

    from backend.db.session import get_engine, get_session_factory, init_db
    from backend.pipeline.ingest import IngestionPipeline

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    client = MagicMock()
    client.collections.exists.return_value = True
    collection = MagicMock()
    collection.name = "RecoveryW6"
    insert_result = MagicMock()
    insert_result.errors = {}
    collection.data.insert_many.return_value = insert_result
    client.collections.get.return_value = collection
    pipeline = IngestionPipeline(_Embed(), client, class_name="RecoveryW6", session_factory=None)
    return factory, pipeline


@contextmanager
def _fake_weaviate_for(pipeline):
    """最小 fake:delete_document 的账本路径由 None session 跳过;Weaviate 侧容错。"""
    yield


async def test_sync_one_commits_snapshot_after_delete_loop(_sync_env, monkeypatch):
    from scripts.sync import _sync_one

    factory, pipeline = _sync_env
    cfg = SourceConfig(
        id="w6stub", type="w6stub", product="w6", config={}, enabled=True, sync_interval="24h"
    )
    conn = ConnectorRegistry.create(cfg)
    monkeypatch.setattr(ConnectorRegistry, "create", lambda c: conn)  # _sync_one 内部用它
    real_delete = pipeline.delete_document
    order: list = []

    def spy_delete(sid):
        order.append(("delete", sid))
        real_delete(sid)

    pipeline.delete_document = spy_delete
    orig_commit = conn.commit_membership_snapshot

    def spy_commit():
        order.append(("commit",))
        orig_commit()

    conn.commit_membership_snapshot = spy_commit
    await _sync_one(cfg, pipeline, factory, triggered_by="manual")
    assert ("delete", "w6stub/d1") in order and ("delete", "w6stub/d2") in order
    assert order.index(("commit",)) > order.index(("delete", "w6stub/d2"))
    assert conn._committed is True


async def test_sync_one_delete_failure_does_not_advance_snapshot(_sync_env, monkeypatch):
    """删除阶段失败 → sync_log failed,快照不推进(下次重报,幂等重删)。"""
    from sqlalchemy import delete, select

    from backend.db.models import SyncLog
    from scripts.sync import _sync_one

    factory, pipeline = _sync_env
    # SyncLog.id 是 uuid4:清理上一用例残留,“取最新行”断言才可靠
    async with factory() as session:
        await session.execute(delete(SyncLog).where(SyncLog.source_id == "w6stub"))
        await session.commit()
    cfg = SourceConfig(
        id="w6stub", type="w6stub", product="w6", config={}, enabled=True, sync_interval="24h"
    )
    conn = ConnectorRegistry.create(cfg)
    conn.fail_on = 2
    monkeypatch.setattr(ConnectorRegistry, "create", lambda c: conn)
    calls = {"n": 0}

    def flaky_delete(sid):
        calls["n"] += 1
        if calls["n"] == conn.fail_on:
            raise RuntimeError("weaviate delete exploded")

    pipeline.delete_document = flaky_delete
    await _sync_one(cfg, pipeline, factory, triggered_by="manual")
    assert conn._committed is False  # 删除阶段失败 → 快照不推进
    async with factory() as session:
        row = (
            (
                await session.execute(
                    select(SyncLog).where(SyncLog.source_id == "w6stub").order_by(SyncLog.id.desc())
                )
            )
            .scalars()
            .first()
        )
    assert row is not None and row.status == "failed"
