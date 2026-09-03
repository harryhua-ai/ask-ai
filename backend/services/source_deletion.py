"""#18 非阻塞数据源删除:durable 异步删除编排。

职责(S0 冻结边界内,#18 落地):
- 受理:ACTIVE / DELETE_FAILED → DELETE_REQUESTED(行锁下校验 + 碰撞检查,
  持久化提交后才返回——受理即持久,刷新页面状态可恢复);
- 执行:DELETE_REQUESTED → DELETING(CAS 认领)→ purge → 配置行 + 账本行
  同事务删除(成功后无 tombstone);
- 失败:purge/收尾任何异常 → DELETE_FAILED + ``lifecycle_error``,行保留可重试;
- 恢复:sweep 同时重驱 DELETE_REQUESTED 与孤儿 DELETING(进程重启后首轮
  sweep 即崩溃恢复;purge 幂等,重复执行安全);
- 碰撞防线(双向):
  * 删除受理时该源有在途同步(pending/running 交接请求,含 sync-all 批量,
    或 running SyncRun)→ 409 拒绝受理;
  * DELETING / DELETE_FAILED 源启动新 sync 由
    :func:`backend.services.source_lifecycle.is_sync_eligible`
    deny-by-default 拒绝(含未来未知状态)。

安全边界:purge 的安全/一致性验证**原样保留**(账本确定性 UUID 点删 +
孤儿边界兜底 + 残留验证段;G2/P0-A 冻结禁令:删侧只点名对象 UUID,不做
TEXT 属性过滤删除)。顺序 = 先 purge 后删行,全程不产生「配置行已删但
vector purge 未知」的静默半态:purge 未收敛则行保留(DELETE_FAILED)。

并发模型:单 backend 容器单 worker;跨进程重复认领由 CAS(rowcount)
裁决胜者,V1 不做跨进程互斥(孤儿 DELETING 双执行者均收敛于同一幂等
purge,验证段保证不假报成功)。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import weaviate
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from weaviate.classes.query import Filter

from backend.db.models import DataSource, Document, SyncRequest, SyncRun
from backend.services import source_lifecycle
from backend.services.source_lifecycle import (
    DELETE_FAILED,
    DELETE_REQUESTED,
    DELETING,
    IN_FLIGHT_STATES,
)

logger = logging.getLogger(__name__)

# sweep 周期兜底:事件唤醒丢失 / 进程外状态变化都能在该窗口内被重驱。
SWEEP_INTERVAL_SECONDS = 30.0

# sync_requests 视为"在途"的状态(与 services/sync_requests._ACTIVE_STATES 同义,
# 独立定义避免依赖私有常量)。
_IN_FLIGHT_REQUEST_STATES = ("pending", "running")


class DeletionRequestError(Exception):
    """删除受理被拒(参数校验 / 状态不允许 / 同步碰撞),HTTP 层映射 status_code。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class DeletionRequest:
    """受理结果。``accepted=False`` 表示已在途的幂等返回(非错误)。"""

    source_id: str
    accepted: bool
    state: str


async def _assert_no_in_flight_sync(session: AsyncSession, source_id: str) -> None:
    """该源存在在途同步(pending/running 请求或 running run)→ 409 拒绝删除。

    sync-all 批量请求 ``source_id IS NULL`` 同样视为碰撞:执行面领用后会
    覆盖该源(second line of defense 是 sync.py WHERE 的 deny-by-default,
    但受理侧显式阻止优先,避免删除与批量同步交错)。
    """
    req = (
        await session.execute(
            select(SyncRequest.id)
            .where(
                SyncRequest.status.in_(_IN_FLIGHT_REQUEST_STATES),
                (SyncRequest.source_id == source_id) | SyncRequest.source_id.is_(None),
            )
            .limit(1)
        )
    ).first()
    if req is not None:
        raise DeletionRequestError(
            409, "该数据源有在途同步请求,请等待同步完成后再删除"
        )
    run = (
        await session.execute(
            select(SyncRun.id)
            .where(SyncRun.source_id == source_id, SyncRun.status == "running")
            .limit(1)
        )
    ).first()
    if run is not None:
        raise DeletionRequestError(409, "该数据源正在同步中,请等待同步完成后再删除")


async def request_deletion(
    session: AsyncSession, source_id: str, *, allowed_from: frozenset[str]
) -> DeletionRequest:
    """受理删除请求:行锁下校验 + 转入 DELETE_REQUESTED(持久化提交)。

    - 行不存在 → 404;
    - 已在途(DELETE_REQUESTED/DELETING)→ 幂等返回 ``accepted=False``;
    - 当前状态不在 ``allowed_from`` → 409(如 retry 端点只接受 DELETE_FAILED);
    - 在途同步碰撞 → 409(不改变任何状态)。

    提交成功即持久:进程随即崩溃也不丢受理(重启 sweep 兜底)。
    """
    result = await session.execute(
        select(DataSource).where(DataSource.id == source_id).with_for_update()
    )
    ds = result.scalar_one_or_none()
    if ds is None:
        raise DeletionRequestError(404, "数据源不存在")
    state = source_lifecycle.normalize(ds.lifecycle_state)
    if source_lifecycle.is_deletion_in_flight(state):
        return DeletionRequest(source_id=source_id, accepted=False, state=state)
    if state not in allowed_from:
        raise DeletionRequestError(409, f"当前状态 {state} 不允许发起该操作")
    await _assert_no_in_flight_sync(session, source_id)
    ds.lifecycle_state = DELETE_REQUESTED
    ds.lifecycle_since = datetime.now(UTC)
    ds.lifecycle_error = None
    await session.commit()
    logger.warning("数据源删除已受理: source=%s", source_id)
    return DeletionRequest(source_id=source_id, accepted=True, state=DELETE_REQUESTED)


async def _mark_delete_failed(
    factory: async_sessionmaker[AsyncSession], source_id: str, exc: Exception
) -> None:
    """DELETING → DELETE_FAILED(CAS;状态已被并发改变时静默让位)。"""
    async with factory() as session:
        await session.execute(
            update(DataSource)
            .where(DataSource.id == source_id, DataSource.lifecycle_state == DELETING)
            .values(
                lifecycle_state=DELETE_FAILED,
                lifecycle_error=f"{type(exc).__name__}: {exc}"[:2000],
            )
        )
        await session.commit()
    logger.error("数据源 %s 删除失败(可重试): %s: %s", source_id, type(exc).__name__, exc)


async def _claim_and_delete_one(
    factory: async_sessionmaker[AsyncSession],
    weaviate_url: str,
    class_name: str,
    source_id: str,
) -> bool:
    """认领并执行单个源的删除。返回 False = 认领失败(状态已被并发改变)。

    顺序(失败安全,沿用既有删除契约):purge 全部收敛 → 同一事务删配置行
    与账本行。purge 异常向上抛,由调用方转 DELETE_FAILED——绝不先删行。
    """
    async with factory() as session:
        result = await session.execute(
            update(DataSource)
            .where(
                DataSource.id == source_id,
                DataSource.lifecycle_state.in_(IN_FLIGHT_STATES),
            )
            .values(
                lifecycle_state=DELETING,
                lifecycle_since=datetime.now(UTC),
                lifecycle_error=None,
            )
        )
        await session.commit()
        if result.rowcount != 1:
            return False
        ledger = (
            await session.execute(
                select(Document.source_id, Document.chunk_count).where(
                    # 源 ID 是字面标识符:startswith(autoescape=True) 防
                    # %/_ 通配符越界(AC-FIX-01)
                    Document.source_id.startswith(f"{source_id}/", autoescape=True)
                )
            )
        ).all()

    # 同步 weaviate 客户端必须进线程池:大语料 purge 耗时,阻塞事件循环
    # 会复刻 2026-09-02 生产 504 事故模式。
    await run_in_threadpool(
        purge_source_corpus_sync,
        weaviate_url,
        class_name,
        source_id,
        [(sid, int(cc or 0)) for sid, cc in ledger],
    )

    async with factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == source_id))
        ).scalar_one_or_none()
        if ds is not None:
            await session.delete(ds)
        await session.execute(
            delete(Document).where(
                Document.source_id.startswith(f"{source_id}/", autoescape=True)
            )
        )
        await session.commit()
    logger.warning("数据源 %s 删除完成(配置行+账本行已移除,无 tombstone)", source_id)
    return True


async def _process_one_safely(
    factory: async_sessionmaker[AsyncSession],
    weaviate_url: str,
    class_name: str,
    source_id: str,
) -> bool:
    """认领执行 + 异常转 DELETE_FAILED。返回是否认领成功。"""
    try:
        return await _claim_and_delete_one(factory, weaviate_url, class_name, source_id)
    except Exception as exc:  # noqa: BLE001 - 删除失败必须落为可观察终态,不吞
        await _mark_delete_failed(factory, source_id, exc)
        return True


async def process_pending_deletions(
    factory: async_sessionmaker[AsyncSession],
    weaviate_url: str,
    class_name: str,
    *,
    source_ids: list[str] | None = None,
) -> list[str]:
    """sweep:处理全部在途删除行,返回本轮认领处理的源 ID 列表。

    DELETE_REQUESTED(已受理未启动)与 DELETING(执行中崩溃的孤儿)都在
    重驱范围——这就是重启恢复语义:worker 首轮 sweep 即完成崩溃恢复。
    """
    async with factory() as session:
        q = (
            select(DataSource.id)
            .where(DataSource.lifecycle_state.in_(IN_FLIGHT_STATES))
            .order_by(DataSource.id)
        )
        if source_ids:
            q = q.where(DataSource.id.in_(source_ids))
        ids = list((await session.execute(q)).scalars())
    processed: list[str] = []
    for sid in ids:
        if await _process_one_safely(factory, weaviate_url, class_name, sid):
            processed.append(sid)
    return processed


class SourceDeletionWorker:
    """进程内删除 worker:事件驱动即时处理 + 周期 sweep 兜底。

    - ``kick()``:受理端点提交后即时唤醒(低延迟);
    - 周期 sweep(默认 30s):兜住唤醒丢失 / 直写 DB 的状态变化 / 进程重启
      (lifespan 启动 worker 后的首轮 sweep 即崩溃恢复);
    - ``_active`` 防同进程对同一源重复认领(sweep 重入)。
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        weaviate_url: str,
        class_name: str,
        *,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
    ) -> None:
        self._factory = factory
        self._weaviate_url = weaviate_url
        self._class_name = class_name
        self._sweep_interval = sweep_interval
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._active: set[str] = set()

    def kick(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def start(self) -> None:
        if self._task is not None:
            return
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="source-deletion-worker")
        logger.warning("删除 worker 已启动(sweep=%.0fs)", self._sweep_interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._wake = None
        logger.warning("删除 worker 已停止")

    async def _run(self) -> None:
        while True:
            try:
                await self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("删除 sweep 失败(下一轮重试)")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._sweep_interval)
            except TimeoutError:
                pass
            self._wake.clear()

    async def _sweep(self) -> None:
        async with self._factory() as session:
            rows = (
                await session.execute(
                    select(DataSource.id)
                    .where(DataSource.lifecycle_state.in_(IN_FLIGHT_STATES))
                    .order_by(DataSource.id)
                )
            ).scalars()
            pending = [sid for sid in rows if sid not in self._active]
        for sid in pending:
            self._active.add(sid)
            try:
                await _process_one_safely(
                    self._factory, self._weaviate_url, self._class_name, sid
                )
            finally:
                self._active.discard(sid)


# ---------------------------------------------------------------------------
# Weaviate 语料 purge(自 api/admin/data_sources.py 原样迁移,逻辑零改动;
# 安全/一致性验证是冻结契约,详见函数 docstring 与 G2/P0-A 冻结禁令)
# ---------------------------------------------------------------------------


def purge_source_corpus_sync(
    weaviate_url: str, class_name: str, prefix: str, ledger: list[tuple[str, int]]
) -> dict:
    """清除某数据源名下的全部向量语料(G2 重写:PRUNE IS DOCUMENT-LOCAL)。

    三段式,前缀边界严格为 ``prefix + "/"``,**全路径无任何 TEXT 属性过滤
    删除原语**(P0-A/G2 冻结禁令:Weaviate 对 TEXT 的 equal/like 是分词
    语义,``equal("a/b")`` 会命中共享 token 的兄弟文档,生产实证可跨源
    误删):

        1. 账本段:对 PG documents 已知的每个 source_id,按该文档自己的
           确定性 UUID(uuid5(source_id, 0..chunk_count-1))批量点删——
           与 ingest._prune_stale_chunks/delete_document 同一文档局部保证;
        2. 孤儿段:迭代器全扫 + 客户端前缀边界过滤,收集**实际存量对象
           UUID** 后逐个删除(读侧允许 TEXT 前缀判断,删侧只点名对象 UUID);
        3. 验证段:再次边界扫描,残留 > 0 则 raise——调用方转
           DELETE_FAILED,配置与账本原样保留可重试(不假报成功)。

    Returns:
        ``{"ledger_docs": N, "orphans": M, "residue": 0}`` 供日志观察。

    Raises:
        RuntimeError: 验证段发现残留(删除未收敛)。
    """
    from backend.pipeline.ingest import _deterministic_uuid

    parsed = urlparse(weaviate_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        collection = client.collections.get(class_name)

        # 1) 账本段:文档局部确定性 UUID 点删
        purge_uuids: list[str] = []
        for sid, cc in ledger:
            purge_uuids.extend(_deterministic_uuid(sid, i) for i in range(int(cc or 0)))
        for start in range(0, len(purge_uuids), 500):
            collection.data.delete_many(
                where=Filter.by_id().contains_any(purge_uuids[start : start + 500])
            )

        # 2) 孤儿段:实际存量扫描 → 对象 UUID 点删
        stale_uuids: list[str] = []
        for item in collection.iterator(return_properties=["source_id"]):
            sid = item.properties.get("source_id")
            if isinstance(sid, str) and sid.startswith(prefix + "/"):
                stale_uuids.append(str(item.uuid))
        for u in stale_uuids:
            collection.data.delete_by_id(u)

        # 3) 验证段:残留必须为 0
        residue = 0
        for item in collection.iterator(return_properties=["source_id"]):
            sid = item.properties.get("source_id")
            if isinstance(sid, str) and sid.startswith(prefix + "/"):
                residue += 1
        if residue:
            raise RuntimeError(
                f"purge 后仍有 {residue} 个残留向量对象(source={prefix}),保留状态可重试"
            )

        logger.info(
            "语料清理完成: 账本 %d 篇(UUID 点删 %d), 孤儿 %d chunks, 残留 0",
            len(ledger),
            len(purge_uuids),
            len(stale_uuids),
        )
        return {"ledger_docs": len(ledger), "orphans": len(stale_uuids), "residue": 0}
    finally:
        client.close()
