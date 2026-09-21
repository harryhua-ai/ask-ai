"""Issue #102 AC1/AC2:repair-all 批级协调不得长持业务表锁;与外部 DDL 重叠有界完成。

生产实证(v1.6.3-r8,#100 验证):repair-all 的批级 ``lock_session`` 在**同一个
长开事务**里先 ``FOR UPDATE`` data_sources、再跑 documents 资格 SELECT —— 该
事务整批存活(生产实证 idle in transaction 56min+)并持有 documents ACCESS
SHARE;sync-cron ``init_db`` 的 no-op ``ALTER TABLE documents`` 排队等
ACCESS EXCLUSIVE;repair 后续 per-doc 查询按 PG 公平序排在 ALTER 之后 ⇒
三方互等、零前进,直至人工 ``pg_terminate_backend``。

契约(#102):

- AC1 RED:真实 PG 上复现该锁序(长读事务 → ALTER 排队 → 后续读饿死);
  GREEN:同一重叠形态在新实现下有界完成;
- AC2:guard 会话整批只允许触碰 data_sources 行锁(跨 worker 批互斥契约
  不变);documents 资格快照必须在独立短事务中读取(读完即释放);
- AC5:#100 语义不变 —— 幂等键/逐文档隔离/聚合守恒/open-task lineage。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from backend.auth.jwt import create_access_token, hash_password
from backend.config import load_settings
from backend.db.models import (
    DataSource,
    Document,
    DocumentRepairTask,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    SyncLog,
    SyncRequest,
    User,
)

SRC = f"lock102-{uuid.uuid4().hex[:10]}"
BULK_URL = f"/api/admin/data-sources/{SRC}/documents/repair-all"
DOCS = [f"{SRC}/main/a.md", f"{SRC}/main/b.md", f"{SRC}/main/c.md"]

PROBE_TIMEOUT = 5  # 外部 DDL 在旧锁序下应排队超时的判定窗
BATCH_DEADLINE = 60  # repair-all 整批完成判定上限


def _sync_dsn() -> str:
    dsn = load_settings(
        config_dir=Path(__file__).parents[2] / "config"
    ).postgres_dsn
    return dsn.replace("+asyncpg", "+psycopg2").replace("+psycopg2", "")


def _raw_conn():
    import psycopg2

    conn = psycopg2.connect(_sync_dsn())
    conn.autocommit = False
    return conn


class _FakeCollection:
    def __init__(self) -> None:
        self.objects: list[dict] = []

    def iterator(self, return_properties=None, **kw):
        def _gen():
            for o in self.objects:
                props = dict(o)
                if return_properties:
                    props = {k: props.get(k) for k in return_properties}
                yield SimpleNamespace(properties=props)

        return _gen()

    @property
    def data(self):
        coll = self

        class _Data:
            def insert(self, *, properties, vector, uuid):
                coll.objects.append(dict(properties))
                return uuid

        return _Data()


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest_asyncio.fixture(loop_scope="session")
async def lock102_seed():
    from backend.main import app

    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=SRC,
                type="filesystem",
                product="probe",
                config={"root_path": f"data/uploads/data-sources/{SRC}"},
                sync_interval="24h",
                enabled=True,
            )
        )
        for doc_id in DOCS:
            # active 且无可解析现行版本 ⇒ attention 资格;执行走 rebuild 交接
            session.add(
                Document(
                    source_id=doc_id,
                    content_hash="c" * 64,
                    source_type="filesystem",
                    product="probe",
                    title=doc_id.rsplit("/", 1)[-1],
                    url=f"file:///{doc_id}",
                    branch="",
                    chunk_count=0,
                    lifecycle="active",
                )
            )
        user_id = uuid.uuid4()
        session.add(
            User(
                id=user_id,
                email=f"{SRC}-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(
        str(user_id), "admin", app.state.settings.jwt_secret
    )
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    collection = _FakeCollection()
    client = SimpleNamespace(collections=SimpleNamespace(get=lambda _name: collection))
    app.state.weaviate_client = client
    app.state.embedder = _FakeEmbedder()
    app.state.weaviate_class_name = "Document"
    yield {"headers": {"Authorization": f"Bearer {token}"}, "factory": factory}
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)
    async with factory() as session:
        await session.execute(
            DocumentRepairTask.__table__.delete().where(
                DocumentRepairTask.source_id == SRC
            )
        )
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == SRC))
        await session.execute(
            SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC)
        )
        await session.execute(
            DocumentVersionChunk.__table__.delete().where(
                DocumentVersionChunk.version_id.in_(
                    select(DocumentVersion.id).where(
                        DocumentVersion.source_id.like(f"{SRC}/%")
                    )
                )
            )
        )
        await session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.like(f"{SRC}/%")
            )
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%"))
        )
        await session.execute(
            IndexGeneration.__table__.delete().where(IndexGeneration.source_id == SRC)
        )
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id == SRC)
        )
        await session.execute(
            User.__table__.delete().where(User.email.like(f"{SRC}%"))
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# AC1:生产锁序在真实 PG 上的确定性复现 + 新实现下的有界完成
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ac1_production_lock_ordering_reproduced_then_bounded():
    """AC1:长读事务持 documents 锁 ⇒ ALTER 排队 ⇒ 后续读饿死(生产锁序)。

    前半段是**锁序本体**的 RED 复现(与实现无关的 PostgreSQL 事实,即生产
    三方停摆的机制):排队者作为后台线程启动,断言其在判定窗内零前进;
    释放长读后全部前进。后半段证明同一重叠形态下,新 ensure_*(存在性
    探测跳过稳态 DDL)与普通读不再排队 —— 同形态有界完成。

    线程纪律:psycopg2 阻塞调用一律走 ``asyncio.to_thread`` 后台任务,
    绝不在事件循环上同步等待排队中的语句(否则测试进程自死锁)。
    """
    conn1 = await asyncio.to_thread(_raw_conn)  # 模拟 repair-all 批级事务:documents 长读

    def _hold(cur):
        cur.execute("SELECT count(*) FROM documents")
        cur.fetchall()

    try:
        await asyncio.to_thread(_hold, conn1.cursor())

        def _alter():
            conn2 = _raw_conn()
            try:
                conn2.cursor().execute(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type VARCHAR(30)"
                )
                conn2.commit()
            finally:
                conn2.close()

        def _read():
            conn3 = _raw_conn()
            try:
                conn3.cursor().execute("SELECT count(*) FROM documents")
            finally:
                conn3.rollback()
                conn3.close()

        alter_task = asyncio.create_task(asyncio.to_thread(_alter))  # sync-cron init_db 形态
        await asyncio.sleep(0.5)
        read_task = asyncio.create_task(asyncio.to_thread(_read))  # repair per-doc 形态
        await asyncio.sleep(0.5)
        assert not alter_task.done(), "ALTER 必须排在长读事务之后(生产锁序复现)"
        assert not read_task.done(), "后续普通读必须排在等待中的 ALTER 之后(饿死复现)"

        # 释放长读 ⇒ 排队者全部前进(证明是队列而非死锁,且 bounded)
        conn1.rollback()
        await asyncio.wait_for(alter_task, timeout=PROBE_TIMEOUT)
        await asyncio.wait_for(read_task, timeout=PROBE_TIMEOUT)
    finally:
        try:
            conn1.rollback()
        except Exception:
            pass
        conn1.close()

    # GREEN 面:同一重叠(长读仍持有)下,新 ensure_* 稳态零 DDL ⇒ 即时完成,
    # 且随后的普通读不被任何排队者阻塞
    from backend.db.session import ensure_track_c_columns, get_engine

    conn_hold = await asyncio.to_thread(_raw_conn)
    try:
        await asyncio.to_thread(_hold, conn_hold.cursor())
        dsn = load_settings(
            config_dir=Path(__file__).parents[2] / "config"
        ).postgres_dsn
        engine = get_engine(dsn)
        start = time.monotonic()
        await asyncio.wait_for(ensure_track_c_columns(engine), timeout=PROBE_TIMEOUT)
        elapsed = time.monotonic() - start

        probe_task = asyncio.create_task(asyncio.to_thread(_read))
        await asyncio.wait_for(probe_task, timeout=PROBE_TIMEOUT)
        await engine.dispose()
        conn_hold.rollback()
        assert elapsed < PROBE_TIMEOUT
    finally:
        try:
            conn_hold.rollback()
        except Exception:
            pass
        conn_hold.close()


# --------------------------------------------------------------------------- #
# AC2:guard 会话整批只碰 data_sources;资格快照独立短事务
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_all_guard_session_only_touches_data_sources(
    lock102_seed, monkeypatch
):
    """AC2:长开的 guard 事务只允许一条语句(data_sources FOR UPDATE);
    documents 资格 SELECT 必须发生在另一个会话且该会话不再有后续语句。"""
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.main import app

    factory = app.state.session_factory

    # 慢化执行:每文档 1.5s,保证批窗口稳定可观测
    import backend.api.admin.data_sources as ds_mod

    real_execute = ds_mod.execute_repair_task

    async def slow_execute(*args, **kwargs):
        await asyncio.sleep(1.5)
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(ds_mod, "execute_repair_task", slow_execute)

    sessions: dict[int, dict] = {}
    orig_execute = AsyncSession.execute

    async def traced_execute(self, statement, *args, **kwargs):
        sid = id(self)
        sql = str(statement)
        entry = sessions.setdefault(sid, {"statements": [], "closed": False})
        # 强引用防 GC:id() 在对象回收后会被复用,弱引用会把新会话的语句
        # 误记到旧会话名下(全量套件下 GC 时机不同,曾致误报)。
        entry["ref"] = self
        entry["statements"].append(" ".join(sql.split()))
        return await orig_execute(self, statement, *args, **kwargs)

    async def traced_close(self):
        entry = sessions.setdefault(id(self), {"statements": [], "closed": False})
        entry["ref"] = self
        entry["closed"] = True
        return await orig_close(self)

    orig_close = AsyncSession.close
    monkeypatch.setattr(AsyncSession, "execute", traced_execute)
    monkeypatch.setattr(AsyncSession, "close", traced_close)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.post(BULK_URL, headers=lock102_seed["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible"] == 3
    assert body["succeeded"] + body["rebuild_requested"] + body["failed"] == body["eligible"]

    monkeypatch.setattr(AsyncSession, "execute", orig_execute)
    monkeypatch.setattr(AsyncSession, "close", orig_close)

    guard = [
        e
        for e in sessions.values()
        if any("FOR UPDATE" in s.upper() for s in e["statements"])
    ]
    assert len(guard) == 1, f"恰一个 guard 会话持有行锁(实际 {len(guard)})"
    guard_stmts = guard[0]["statements"]
    non_guard_stmts = [s for s in guard_stmts if "data_sources" not in s]
    assert not non_guard_stmts, (
        "guard 长事务不得触碰 data_sources 以外的任何表 —— "
        f"违规语句: {non_guard_stmts[:3]}(#102 生产死锁源)"
    )
    eligibility_sessions = [
        e
        for e in sessions.values()
        if e is not guard[0]
        and any(s.startswith("SELECT documents") for s in e["statements"])
    ]
    assert eligibility_sessions, "资格快照必须存在"
    for e in eligibility_sessions:
        docs_reads = [s for s in e["statements"] if s.startswith("SELECT documents")]
        assert len(docs_reads) == 1, (
            "资格快照会话恰读一次 documents(独立短事务,读完即释放)"
        )


# --------------------------------------------------------------------------- #
# AC1 端到端:repair-all 与外部 documents DDL 重叠 ⇒ 有界完成
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_all_completes_while_foreign_documents_ddl_arrives(
    lock102_seed, monkeypatch
):
    """AC1/AC4:批进行中外部 ALTER documents 到达 ⇒ 不再排队/停摆;
    repair-all 与 DDL 都有界完成;#100 聚合守恒不变(AC5)。"""
    import backend.api.admin.data_sources as ds_mod
    from backend.main import app

    factory = app.state.session_factory
    real_execute = ds_mod.execute_repair_task

    async def slow_execute(*args, **kwargs):
        await asyncio.sleep(1.5)
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(ds_mod, "execute_repair_task", slow_execute)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        repair_task = asyncio.create_task(
            client.post(BULK_URL, headers=lock102_seed["headers"])
        )
        # 等批进入 per-doc 阶段(首个任务行落库)再注入外部 DDL —— 生产时序
        deadline = time.monotonic() + 15
        first_task_seen = False
        while time.monotonic() < deadline:
            async with factory() as session:
                n = (
                    (
                        await session.execute(
                            select(DocumentRepairTask.id).where(
                                DocumentRepairTask.source_id == SRC
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            if n:
                first_task_seen = True
                break
            await asyncio.sleep(0.1)
        assert first_task_seen, "批必须在判定窗内进入 per-doc 阶段"

        # 外部 DDL 到达(sync-cron init_db 的稳态形态)
        def _foreign_ddl():
            conn = _raw_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type VARCHAR(30)"
                )
                conn.commit()
            finally:
                conn.close()

        start = time.monotonic()
        await asyncio.wait_for(asyncio.to_thread(_foreign_ddl), timeout=PROBE_TIMEOUT)
        ddl_elapsed = time.monotonic() - start

        resp = await asyncio.wait_for(repair_task, timeout=BATCH_DEADLINE)
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible"] == 3
    assert body["succeeded"] + body["rebuild_requested"] + body["failed"] == body["eligible"], (
        f"#100 聚合守恒必须保持: {body}"
    )
    assert ddl_elapsed < PROBE_TIMEOUT, (
        f"外部 DDL 必须有界完成(实际 {ddl_elapsed:.1f}s;旧锁序下排在批事务之后停摆)"
    )
