"""数据源同步脚本(cron 入口)。

串联所有 RAG 组件,完成一次完整的数据源 → 向量库同步流程:
    配置加载 → Connector 实例化 → fetch_changes/fetch_all →
    变更判定 → GenerationBuilder 生成构建/验证/原子激活(持久内容副本
    入 Postgres)→ fetch_deleted → 墓碑(逻辑删除)→ SyncLog 写入 Postgres。

设计要点
--------
- **同步/异步桥接** (重要):
  ``run_sync`` 为 ``async`` 函数,但 Connector 与 ``IngestionPipeline`` 内部
  均为同步实现(Weaviate-client v4 是同步 SDK,Postgres ``documents`` 表
  写入用的是同步 ``sessionmaker``)。本脚本只在以下三处使用 async:
      1. ``init_db(engine)`` 异步建表(DDL)
      2. ``session_factory()`` 异步会话,写 ``SyncLog``
      3. ``engine.dispose()`` 异步关闭连接池
  其余步骤(fetch / ingest / delete / weaviate_client.close)均为同步调用,
  在事件循环中"阻塞式"执行。对一个 cron 任务来说没有问题(无并发需求),
  但**不应**放在高并发 web 请求路径中。

- **资源释放**:Weaviate client 与 Postgres engine 在 ``finally`` 块中关闭,
  确保异常时也释放连接(init_db 失败 / connect_to_local 失败均能正确清理)。

- **CLI 参数**(argparse,比 ``sys.argv`` 更标准):
    --source SOURCE_ID  仅同步指定数据源(默认同步全部启用源)
    --dry-run           仅列举抓取的文档数,不写向量库 / 不写 SyncLog
    --reindex           全量生成重建(新代构建→验证→原子激活,零服务损失)
    --triggered-by      sync_log 触发方标记(auto/manual/cron;
                        独立执行面的 Admin 手动触发显式传 manual)
    --help              显示帮助

- **URL 解析**:用 ``urllib.parse.urlparse`` 替代 brief 中 ``split("//")``
  的脆弱写法,统一处理带/不带 scheme 的 URL。
"""

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

# 让 ``python scripts/sync.py`` 直接执行时也能导入 backend 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

import weaviate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import backend.connectors.filesystem  # 触发 @register 装饰器
import backend.connectors.github
import backend.connectors.local_git  # 触发 @register 装饰器
import backend.connectors.web_crawl  # 触发 @register 装饰器
import backend.connectors.woocommerce  # noqa: F401 - 触发 @register 装饰器
from backend.config import Settings, load_settings
from backend.connectors.base import SourceRootUnavailable
from backend.connectors.db_adapter import to_source_config
from backend.connectors.github import GitTransportError  # #34:传输失败证据化分类
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.db.models import DataSource, Document, SyncLog
from backend.db.session import (
    get_engine,
    get_session_factory,
    get_sync_session_factory,
    init_db,
)
from backend.embedder.bge import BGEEmbedder
from backend.embedder.fallback import (
    CpuFallbackError,
    SyncEmbedderHandle,
    _build_sync_embedder,
    _terminal_sync_embedder,
)
from backend.embedder.remote import build_remote_sync_embedder
from backend.pipeline.generation_builder import BuildAccounting, GenerationBuilder
from backend.pipeline.ingest import IngestionPipeline
from backend.services import document_lifecycle as lifecycle
from backend.services import schedule_truth
from backend.services.membership_currency import (
    MEMBERSHIP_STATUS_CURRENT,
    MEMBERSHIP_STATUS_FAILED,
    MEMBERSHIP_STATUS_STALE,
    MEMBERSHIP_STATUS_UNSUPPORTED,
    MembershipTruthPersistenceError,
    persist_membership_truth,
    reconcile_membership,
    truth_detail_of,
)
from backend.services.source_lifecycle import sync_eligible_condition
from backend.services.sync_delta import build_document_delta
from backend.services.sync_runs import (
    STAGE_CHUNK,
    STAGE_CONSISTENCY,
    STAGE_DONE,
    STAGE_EMBED,
    STAGE_FETCH,
    STAGE_INDEX,
    STAGE_PARSE,
    STAGE_SAFETY_FILTER,
    record_device,
)
from backend.services.vector_consistency import verify_source_vectors

logger = logging.getLogger(__name__)


def build_sync_embedder(settings) -> SyncEmbedderHandle:
    """构造 sync 嵌入句柄(Hardware-Aware Runtime)。

    默认 = 共享运行时客户端:sync 不再自载模型,经内部嵌入端点消费 backend
    的单一驻留实例(同模型+同 GPU → 至多一个活跃运行时;GPU→CPU 单向回退
    由服务端完成并如实镜像进遥测)。

    ``ASKAI_SYNC_EMBEDDER=local`` 保留既有进程内 GPU-first 工厂(离线测试 /
    本地联调逃生口);生产 compose 不设置该变量。
    """
    import os

    mode = os.environ.get("ASKAI_SYNC_EMBEDDER", "remote").strip().lower()
    if mode == "local":
        # Keep the existing scripts.sync.BGEEmbedder seam for offline tests while
        # the public factory and lifecycle implementation live in backend/embedder.
        return _build_sync_embedder(settings, BGEEmbedder)
    return build_remote_sync_embedder(settings)


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    """从 ``weaviate_url`` 解析 (host, port)。

    相比 brief 中 ``url.split("//")[1].split(":")[0]`` 的脆弱写法,
    ``urlparse`` 能正确处理多种格式。

    支持的输入:
        - ``http://localhost:8080``   → ("localhost", 8080)
        - ``http://weaviate.svc``     → ("weaviate.svc", 8080)  # 缺省端口
        - ``localhost:8080``          → ("localhost", 8080)     # 自动补 scheme
        - ``https://host:443``        → ("host", 443)

    Args:
        weaviate_url: Weaviate URL 字符串。

    Returns:
        ``(host, port)`` 元组,port 缺省时取 8080(Weaviate 默认)。
    """
    if "://" not in weaviate_url:
        # urlparse 不带 scheme 会把 host 解析到 path,补一个 http:// 前缀修复
        weaviate_url = f"http://{weaviate_url}"
    parsed = urlparse(weaviate_url)
    return parsed.hostname or "localhost", parsed.port or 8080


async def _load_configs_from_db(
    session_factory: Any,
    *,
    due_only: bool = False,
    now: datetime | None = None,
) -> list[SourceConfig]:
    """从 ``data_sources`` 表读 enabled 配置,转 SourceConfig。

    替代 Task 7 之前从 YAML 加载的逻辑:数据源配置现在持久化在 Postgres
    ``data_sources`` 表(由管理界面 / API 维护),同步脚本直接读 DB。

    Args:
        session_factory: 异步 SQLAlchemy 会话工厂(``async_sessionmaker``)。

    Args:
        due_only: 自动调度时只返回 ``next_run_at`` 已到期或等待首次调度的源。
            手动触发不得使用此过滤；调用方负责选择该模式。
        now: 测试可注入当前时间；缺省使用 UTC 当前时间。

    Returns:
        按 ``id`` 升序排列的 :class:`SourceConfig` 列表(仅含 enabled=True，
        可选再经过 due gate)。
    """
    async with session_factory() as session:
        result = await session.execute(
            select(DataSource)
            .where(
                DataSource.enabled.is_(True),
                # #18 lifecycle deny-by-default:删除在途/失败源(含未来
                # 未知状态)一律不进同步宇宙,防止同步复活已清理语料
                sync_eligible_condition(),
            )
            .order_by(DataSource.id)
        )
        rows = result.scalars().all()
    if due_only:
        clock = now or datetime.now(UTC)
        rows = [
            ds
            for ds in rows
            if schedule_truth.should_run_source(
                next_run_at=ds.next_run_at,
                now=clock,
                triggered_by="cron",
            )
        ]
    return [to_source_config(ds) for ds in rows]


async def _reconcile_source_schedule(session_factory: Any, source_id: str) -> None:
    """同步日志落库后刷新该源的持久化 next_run_at；不可证明则不写。"""
    try:
        async with session_factory() as session:
            row = await session.execute(select(DataSource).where(DataSource.id == source_id))
            source = row.scalar_one_or_none()
            # Unit tests and degraded callers may use a lightweight session
            # double; only a real ORM row is allowed to alter schedule truth.
            if isinstance(source, DataSource):
                await schedule_truth.reconcile_next_run_at(session, source)
    except Exception as exc:  # noqa: BLE001 - schedule read/write cannot falsify sync result
        logger.warning("数据源 %s 调度真值刷新失败: %s", source_id, str(exc)[:160])


async def _count_documents(session_factory: Any, source_id_prefix: str) -> int:
    """统计 documents 表中某数据源的**在服**记录数(判断首次 vs 无变更)。

    用 ``source_id LIKE '<id>/%'`` 前缀匹配(source_id 格式为
    ``{cfg.id}/{branch}/{rel}``),且只统计 lifecycle ∈ SERVING 的行
    (#82:墓碑(superseded/deleted)是已退出服务的逻辑删除行,不计入
    「未变更 N 篇」等现役口径 —— 否则生产会出现「5534 未变更」实为
    5379 在服 + 155 已退休的假真值)。

    Args:
        session_factory: 异步 SQLAlchemy 会话工厂。
        source_id_prefix: 数据源 ID(如 ``"ne301-local"``)。

    Returns:
        该数据源在 documents 表的**在服**行数。
    """
    async with session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Document)
            .where(
                Document.source_id.like(f"{source_id_prefix}/%"),
                Document.lifecycle.in_(lifecycle.DocLifecycle.SERVING),
            )
        )
        return int(result.scalar() or 0)


# --------------------------------------------------------------------------- #
# 增量窗口(2026-08-17 改造):since 取"上次成功同步时间",而非固定 now-24h
# --------------------------------------------------------------------------- #

# 无成功记录时(首次运行 / 历史日志被清)的保守回看窗口,保持旧行为
DEFAULT_INCREMENTAL_WINDOW = timedelta(hours=24)

# 上次成功时间过旧(源长期停摆 / 同步长期失败)时的窗口上限,
# 防止单次拉取无界膨胀;超出部分需手动全量补(如 --reindex)
MAX_INCREMENTAL_LOOKBACK = timedelta(days=30)

# WEB 合同#6/#7:全量抓取覆盖完整性低于该比例时记 partial(确定性、可解释)。
# ≥80% 候选页成功抽取 → success(coverage 行仍记录失败明细);
# <80% → partial(窗口不推进,下轮重试);0 抽取 → failed。
COVERAGE_PARTIAL_RATIO = 0.8

# ⑫ 实时进度落笔防抖间隔(秒):ingest 在工作线程执行,批界回调只更新内存
# 最新值;事件循环侧 flush 任务以该间隔摊销写 DB——批界粒度真实、又不做
# 每 chunk DB storm。进程中断时,已持久化的最后一条批界事实保留。
SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS = 1.0


def _consistency_facts(
    report: Any,
    *,
    identity_facts: dict | None = None,
    retired_chunks: int | None = None,
    repaired_ledger_rows: int | None = None,
) -> dict:
    """VectorGapReport → 结构化一致性事实(SyncRun.consistency 用)。

    Wave-0 既有六键不变(共享契约,消费方兼容);Issue #13 增量五键
    (PROPOSED_SHARED_INTERFACE,与 Sync Truth worktree 共享同一 jsonb,
    不建第二套 observability model):
      - duplicate_doc_count / polluted_artifact_chunks:账本身份面事实,
        由 ``_ledger_identity_facts`` 查得,调用方经 ``identity_facts`` 注入;
      - retired_chunks / repaired_ledger_rows:本轮 reconciliation 实际
        退休/重建量(无 reconciliation 的调用点不伪造 0,键省略);
      - repair_required:恒推导 = 非健康 ∨ 存在污染 artifact,供 #11/#15
        消费。
    """
    polluted = int((identity_facts or {}).get("polluted_artifact_chunks") or 0)
    facts = {
        "expected_chunks": report.expected_chunks,
        "actual_chunks": report.actual_chunks,
        "missing": len(report.missing_source_ids),
        "refill": len(report.refill_source_ids),
        "stale_chunk_count": report.stale_chunk_count,
        "orphan_count": report.orphan_count,
        "repair_required": (not report.is_healthy) or polluted > 0,
    }
    if identity_facts is not None:
        facts["duplicate_doc_count"] = int(identity_facts.get("duplicate_doc_count") or 0)
        facts["polluted_artifact_chunks"] = polluted
    if retired_chunks is not None:
        facts["retired_chunks"] = int(retired_chunks)
    if repaired_ledger_rows is not None:
        facts["repaired_ledger_rows"] = int(repaired_ledger_rows)
    return facts


async def _ledger_identity_facts(session_factory: Any, source_prefix: str) -> dict:
    """账本身份面事实(Issue #13 共享一致性遥测,只读)。

    - duplicate_doc_count:同 content_hash 多路径涉及的账本行数(D2 下为
      合法共存,仅作事实呈现;恒等于"多余身份行"的观察口径);
    - polluted_artifact_chunks:路径被当前 Technical Safety 判为禁止
      artifact 的账本行 chunk 总数(historical invalid pollution,D3)。

    Args:
        session_factory: 异步会话工厂。
        source_prefix: 数据源 ID(内部拼 ``'{prefix}/%'`` 前缀匹配)。
    """
    from backend.connectors.safety import historical_artifact_verdict

    async with session_factory() as session:
        dup_rows = (
            await session.execute(
                select(Document.content_hash, func.count(Document.source_id))
                .where(Document.source_id.like(f"{source_prefix}/%"))
                .group_by(Document.content_hash)
                .having(func.count(Document.source_id) > 1)
            )
        ).all()
        rows = (
            await session.execute(
                select(Document.source_id, Document.chunk_count).where(
                    Document.source_id.like(f"{source_prefix}/%")
                )
            )
        ).all()
    duplicate_doc_count = int(sum(n for _, n in dup_rows))
    polluted_artifact_chunks = sum(
        int(cc) for sid, cc in rows if not historical_artifact_verdict(str(sid)).safe
    )
    return {
        "duplicate_doc_count": duplicate_doc_count,
        "polluted_artifact_chunks": polluted_artifact_chunks,
    }


class _RunTelemetry:
    """单源 SyncRun 遥测句柄(⑪+⑫ Wave-0):尽力而为,绝不影响业务同步。

    SyncRun 是运行期事实(attempt 启动即落行),DB 抖动时静默降级为
    无遥测(与 SyncLog 写失败不中断批次的既有语义一致)。
    """

    def __init__(self) -> None:
        self.run_id: int | None = None

    async def start(
        self,
        session_factory: Any,
        *,
        source_id: str,
        request_id: int | None,
        attempt: int,
        recovery: bool,
        triggered_by: str,
    ) -> None:
        if self.run_id is not None:
            return
        try:
            from backend.services.sync_runs import start_run

            row = await start_run(
                session_factory,
                source_id=source_id,
                attempt=attempt,
                request_id=request_id,
                recovery=recovery,
                triggered_by=triggered_by,
            )
            self.run_id = row.id
        except Exception as exc:  # noqa: BLE001 - 遥测失败不阻断业务
            logger.warning("SyncRun 创建失败(降级无遥测): %s", str(exc)[:200])

    async def _do(self, coro) -> None:
        if self.run_id is None:
            # Service calls are coroutine objects created by the thin methods
            # below.  Close them when start telemetry did not obtain a run id,
            # otherwise best-effort telemetry degrades into RuntimeWarnings.
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            return
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            logger.warning("SyncRun 更新失败(忽略): %s", str(exc)[:200])

    async def progress(
        self, session_factory: Any, stage: str, current: int | None, total: int | None
    ) -> None:
        from backend.services.sync_runs import update_progress

        await self._do(
            update_progress(
                session_factory, self.run_id, stage=stage, stage_current=current, stage_total=total
            )
        )

    async def counters(self, session_factory: Any, **kv: object) -> None:
        from backend.services.sync_runs import update_counters

        await self._do(update_counters(session_factory, self.run_id, **kv))

    async def consistency(self, session_factory: Any, report: dict) -> None:
        from backend.services.sync_runs import record_consistency

        await self._do(record_consistency(session_factory, self.run_id, report))

    async def device(
        self,
        session_factory: Any,
        *,
        execution_device: str,
        fallback_reason: str | None = None,
        fallback_detail: str | None = None,
    ) -> None:
        """W2 冻结写入通道:execution_device/fallback 遥测(W1 消费)。

        execution_device ∈ {gpu, cpu, gpu_to_cpu}(受控词表,越界由
        record_device 拒绝);fallback_reason 为机器可读原因码;
        fallback_detail 为人类可读补充。best-effort,失败不阻断业务。

        集成注:经模块级 ``record_device`` 绑定调用——W2 已合入,适配器
        降级分支退役;模块级名保留 #14 测试对 ``scripts.sync.record_device``
        的 monkeypatch 接缝(调用期全局解析,不绕过)。
        """
        await self._do(
            record_device(
                session_factory,
                self.run_id,
                execution_device=execution_device,
                fallback_reason=fallback_reason,
                fallback_detail=fallback_detail,
            )
        )

    async def finish(
        self, session_factory: Any, *, status: str, error: str | None, sync_log_id: Any
    ) -> None:
        from backend.services.sync_runs import finish_run

        await self._do(
            finish_run(
                session_factory,
                self.run_id,
                status=status,
                error_summary=error,
                sync_log_id=sync_log_id,
            )
        )


def _coverage_line(stats: dict) -> str:
    """run_stats → 紧凑覆盖行(写入 SyncLog.error_detail,真实呈现抓取覆盖)。"""
    rej = stats.get("rejected") or {}
    rej_desc = ",".join(f"{k}:{v}" for k, v in rej.items() if v)
    failed_urls = stats.get("failed_urls") or []
    preview = ";failed_urls=" + ",".join(failed_urls[:5]) if failed_urls else ""
    return (
        f"coverage: discovered={stats.get('discovered', 0)}"
        f" accepted={stats.get('accepted', 0)}"
        f" extracted={stats.get('extracted', 0)}"
        f" failed={stats.get('failed', 0)}"
        + (f" rejected[{rej_desc}]" if rej_desc else "")
        + preview
    )


def _compute_since(last_success: datetime | None, now: datetime) -> datetime:
    """计算本次增量窗口起点。

    Args:
        last_success: 该源最近一次 status=success 的完成时间;None 表示
            无成功记录。
        now: 当前时间(调用方传入便于测试)。

    Returns:
        窗口起点。规则:无记录 → ``now - DEFAULT_INCREMENTAL_WINDOW``;
        过旧 → ``now - MAX_INCREMENTAL_LOOKBACK``(上限夹紧);
        未来时间(时钟漂移)→ ``now``(夹紧,避免空区间永久跳过)。
    """
    if last_success is None:
        return now - DEFAULT_INCREMENTAL_WINDOW
    since = max(last_success, now - MAX_INCREMENTAL_LOOKBACK)
    return min(since, now)


async def _last_success_at(session_factory: Any, source_id: str) -> datetime | None:
    """查 sync_log 中该源最近一次成功同步的完成时间。

    取 finished_at(缺省时回退 started_at,如异常中断的行);failed 行
    被跳过——失败不推进窗口,下次同步仍覆盖缺口。

    Args:
        session_factory: 异步 SQLAlchemy 会话工厂。
        source_id: 数据源 ID。

    Returns:
        最近一次成功同步的时间;无成功记录时返回 None。
    """
    async with session_factory() as session:
        result = await session.execute(
            select(SyncLog.finished_at, SyncLog.started_at)
            .where(SyncLog.source_id == source_id, SyncLog.status == "success")
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        )
        row = result.one_or_none()
    if row is None:
        return None
    finished_at, started_at = row
    return finished_at or started_at


def _membership_truth_persist_failed(
    log_entry: SyncLog, exc: MembershipTruthPersistenceError
) -> tuple[bool, dict[str, Any], tuple[str, ...]]:
    """真值持久化失败的统一处置(R2 BLOCKER 2 冻结语义)。

    本轮降级 partial(绝不 success)、error_detail 确定性指明真值持久化
    失败、delta 不携带 membership_status 声明(不伪造已持久真值);
    已提交墓碑不回滚,下一轮重试。missing 恒为空:真值未建立 ⇒ 补灌
    事实同样不可证明,下一轮对账重报。
    """
    logger.error("数据源 %s 成员真值持久化失败: %s", log_entry.source_id, str(exc)[:200])
    if log_entry.status == "success":
        log_entry.status = "partial"
    log_entry.error_detail = (
        f"{log_entry.error_detail or ''};"
        f"membership truth persistence failed: {str(exc)[:200]}"
    ).lstrip(";")
    return False, {}, ()


async def _reconcile_membership_for_source(
    cfg: SourceConfig,
    connector: Any,
    pipeline: IngestionPipeline,
    session_factory: Any,
    log_entry: SyncLog,
    *,
    dry_run: bool = False,
) -> tuple[bool, dict[str, Any], tuple[str, ...]]:
    """#71 权威成员对账:每轮必跑(含无变更 / SHA 短路轮)。

    stale_set = 账本在服成员 − 权威成员(connector.membership_source_ids),
    退休走既有 ``tombstone_document`` 逻辑删除语义(同步账本面,与 fetch_deleted
    墓碑块同一 session factory 语义)。正确性不依赖 git 事件窗口 /
    ``fetch_deleted`` 历史 / 删除事件是否被观测(Issue #71 授权契约第 1-8 条)。

    #82 补灌方向:missing = 权威成员 − 账本在服成员(分支 scope 扩大后
    新纳入的既有内容 / 墓碑后重回权威的文档)。本函数只上报缺失事实,
    灌入由调用方经既有 ingest 路径定向补灌(:func:`_backfill_missing_members`);
    退休语义与 lifecycle 词表分毫不变。

    货币真值(DataSource.membership_*)只在对账事务成功完成后持久化;
    对账失败如实记 failed 并把本轮 SyncLog 降级 partial —— 绝不在已知名义
    漂移未解决时宣称 success。

    真值持久化失败(R2 BLOCKER 2 冻结语义):**绝不 best-effort** ——
    :class:`MembershipTruthPersistenceError` 由本函数显式处置:本轮降级
    partial、error_detail 指明真值持久化失败、delta 不携带任何
    membership_status 声明(不伪造已持久真值);已提交墓碑不回滚,
    下一轮重试对账与真值建立。

    Returns:
        (resolved, delta_merge, missing_ids):resolved=False 表示漂移未解决
        或真值未建立(调用方不得记 success);delta_merge 需并入本轮
        delta_counts(键:membership_status / stale_detected / stale_retired
        / membership_missing,文档单位;仅在真值确已持久化时携带
        membership_status);missing_ids 非空 ⇒ 调用方应定向补灌。
    """
    if dry_run:
        # dry-run 原语义:零写副作用,不枚举权威真值、不持久化
        return True, {}, ()
    ledger_factory = getattr(pipeline, "_session_factory", None)
    if ledger_factory is None:
        # 账本工厂缺省(无 Postgres 部署/纯投影运行)时墓碑不可能成立(与
        # fetch_deleted 墓碑块同一纪律):如实跳过,绝不伪造对账事实。
        return True, {}, ()
    if getattr(connector, "membership_source_ids", None) is None:
        # 无成员枚举能力的 connector(filesystem/woocommerce/web_crawl 等):
        # 如实持久化 unsupported(中性,不降级健康);#71 授权范围第 18 条。
        # 真值写失败 ⇒ 不支持态也绝不静默(R2 BLOCKER 2/D)。
        try:
            await persist_membership_truth(
                session_factory, cfg.id, status=MEMBERSHIP_STATUS_UNSUPPORTED
            )
        except MembershipTruthPersistenceError as exc:
            return _membership_truth_persist_failed(log_entry, exc)
        return True, {"membership_status": MEMBERSHIP_STATUS_UNSUPPORTED}, ()
    try:
        result = reconcile_membership(
            ledger_factory, connector, cfg.id, reason=f"membership:{cfg.id}"
        )
    except Exception as exc:  # noqa: BLE001 - 对账失败不中断轮次业务,如实降级
        logger.error(
            "数据源 %s 成员对账失败(账本零改动,真值记 failed): %s",
            cfg.id,
            str(exc)[:200],
        )
        truth_delta: dict[str, Any] = {}
        detail_note = ""
        try:
            await persist_membership_truth(
                session_factory,
                cfg.id,
                status=MEMBERSHIP_STATUS_FAILED,
                detail={"error": str(exc)[:300]},
            )
            truth_delta = {"membership_status": MEMBERSHIP_STATUS_FAILED}
        except MembershipTruthPersistenceError as pexc:
            # 对账已失败、真值又写不进:两段事实都如实呈现,绝不掩盖
            detail_note = f";membership truth persistence failed: {pexc}"
            logger.error(
                "数据源 %s 真值持久化亦失败(failed 态未落库): %s",
                cfg.id,
                str(pexc)[:200],
            )
        if log_entry.status == "success":
            log_entry.status = "partial"
        log_entry.error_detail = (
            f"{log_entry.error_detail or ''};"
            f"membership reconciliation failed: {str(exc)[:200]}{detail_note}"
        ).lstrip(";")
        return False, truth_delta, ()
    status = MEMBERSHIP_STATUS_CURRENT if not result.unresolved else MEMBERSHIP_STATUS_STALE
    try:
        await persist_membership_truth(
            session_factory,
            cfg.id,
            status=status,
            stale_detected=len(result.stale_ids),
            stale_retired=result.retired,
            detail=truth_detail_of(result),
        )
    except MembershipTruthPersistenceError as exc:
        # B:退休墓碑已提交(不回滚);但真值未建立 ⇒ 本轮绝不记 success,
        # 也绝不携带 current/stale 声明;下一轮重试对账与真值建立。
        return _membership_truth_persist_failed(log_entry, exc)
    delta = {
        "membership_status": status,
        "stale_detected": len(result.stale_ids),
        "stale_detected_unit": "document",
        "stale_retired": result.retired,
        "stale_retired_unit": "document",
        # #82 加性计数:缺失权威成员(补灌方向的可见性,灌入在调用方)
        "membership_missing": len(result.missing_ids),
        "membership_missing_unit": "document",
        # #91 加性计数:确定性永久排除(不可灌入,已分区登记,非 actionable)
        "membership_excluded": len(result.excluded_ids),
        "membership_excluded_unit": "document",
    }
    if result.unresolved:
        if log_entry.status == "success":
            log_entry.status = "partial"
        log_entry.error_detail = (
            f"{log_entry.error_detail or ''};"
            f"membership drift unresolved: {len(result.residual_ids)} document(s)"
        ).lstrip(";")
        logger.error(
            "数据源 %s 成员对账后仍有未解决漂移 %d 篇(真值记 stale,轮次 partial)",
            cfg.id,
            len(result.residual_ids),
        )
        return False, delta, tuple(result.missing_ids)
    if result.stale_ids:
        logger.info(
            "数据源 %s 成员对账退休陈旧文档 %d 篇(逻辑删除,物理清除仅经 GC)",
            cfg.id,
            result.retired,
        )
    if result.missing_ids:
        logger.info(
            "数据源 %s 成员对账发现权威缺失成员 %d 篇(定向补灌,#82)",
            cfg.id,
            len(result.missing_ids),
        )
    return True, delta, tuple(result.missing_ids)


def _exclusion_delta(accounting: Any) -> dict[str, Any]:
    """#91:由 BuildAccounting 构造 eligible/永久排除加性记账键(AC10/AC12)。

    eligible = 进入本轮构建判定的文档中未被分区排除的部分(有资格参与
    原子生成的候选);permanent_excluded = 确定性安全排除分区数。零排除
    时返回空 dict(不制造无信息键)。
    """
    excluded_n = len(getattr(accounting, "excluded_docs", []) or [])
    zero_chunk_n = len(getattr(accounting, "zero_chunk_docs", []) or [])
    total_n = (
        len(accounting.new_docs)
        + len(accounting.updated_docs)
        + len(accounting.unchanged_docs)
        + len(accounting.metadata_docs)
        + excluded_n
    )
    if not excluded_n and not total_n:
        return {}
    delta = {
        "eligible_count": total_n - excluded_n,
        "eligible_count_unit": "document",
        "permanent_excluded": excluded_n,
        "permanent_excluded_unit": "document",
    }
    if zero_chunk_n:
        # #94:零语义分块单独分列(是 excluded 的子集;如实分账,不假收敛)
        delta["zero_semantic_chunk"] = zero_chunk_n
        delta["zero_semantic_chunk_unit"] = "document"
    return delta


async def _backfill_missing_members(
    cfg: SourceConfig,
    connector: Any,
    builder: GenerationBuilder,
    missing_ids: tuple[str, ...],
) -> BuildAccounting | None:
    """#82:authority−ledger 缺失成员定向补灌(既有 ingest 路径)。

    分支 scope 扩大后新纳入配置的既有内容(以及墓碑后重回权威的文档)
    由本函数经 ``connector.fetch_all()`` 过滤 + ``builder.build_generation``
    补灌 —— 与无变更路径向量缺口「不可重放回退源重建」同一机制。走
    ``force_rebuild=True``:墓碑行同哈希会被 classify 判 UNCHANGED 而跳过,
    强制新版本才能触发 ``activate_document_version`` 内置的墓碑撤销语义
    (恢复回 active),不发明任何新 lifecycle 状态。``missing_ids`` 为空
    (常态)时零开销:不抓取、不构建、不返回。

    Returns:
        BuildAccounting(补灌批次的构建事实)或 None(无缺失/零命中)。
        任一文档构建失败按既有契约 raise IngestFailures(本轮零激活)。
    """
    if not missing_ids:
        return None
    missing_set = set(missing_ids)
    docs = [d for d in connector.fetch_all() if d.source_id in missing_set]
    if not docs:
        logger.warning(
            "数据源 %s 权威缺失 %d 篇但全量枚举零命中(下轮对账重报)",
            cfg.id,
            len(missing_set),
        )
        return None
    logger.info(
        "数据源 %s 成员对账定向补灌缺失权威成员 %d/%d 篇(#82)",
        cfg.id,
        len(docs),
        len(missing_set),
    )
    return await asyncio.to_thread(
        builder.build_generation, docs, source_id=cfg.id, force_rebuild=True
    )


async def _handle_no_change(
    source_id: str,
    existing: int,
    connector: Any,
    pipeline: IngestionPipeline,
    session_factory: Any,
    log_entry: SyncLog,
    start: float,
    dry_run: bool = False,
    telemetry: "_RunTelemetry | None" = None,
    builder: GenerationBuilder | None = None,
) -> None:
    """无变更路径:先做向量一致性校验,缺口则 fetch_all 过滤补灌并记 partial。

    背景(2026-08 Weaviate 只读事故):Postgres documents 表有记录但
    Weaviate 无向量的缺口文档,增量同步永远判"无变更跳过"而不自愈。
    本函数在跳过前核对该源的向量完整性:
      - dry_run → 维持原语义:仅统计不校验不灌入(SyncLog 由 finally 的
        not dry_run 守卫,同样不写);
      - 健康(汇总级总数相等) → 记 success + unchanged;
        `_last_success_at` 认 success → 窗口照常推进。
      - 有缺口 → fetch_all 拉全源后按 refill_source_ids(整篇缺失 ∪
        chunk 集合不一致)过滤,只对缺口文档重灌(embed 幂等 upsert,
        多余 chunk 由 ingest 的 _prune_stale_chunks 清理);记 status="partial"
        + error_detail。partial 不被 `_last_success_at` 采纳 → 窗口不
        推进,下一轮同步重新校验自确认。

    Args:
        source_id: 数据源 ID(不带斜杠;校验器内部拼 `{prefix}/%` 与 `{prefix}/*`)。
        existing: documents 表该源已有记录数。
        connector: 已实例化的 connector(fetch_all 用)。
        pipeline: 灌入管道(校验与补灌共用)。
        session_factory: 异步会话工厂。
        log_entry: 待写 SyncLog(就地改 status/items/error_detail/finished_at)。
        start: time.monotonic() 起点(算 duration_ms)。
        dry_run: True 时维持旧语义仅统计,绝不触发校验/灌入副作用。
    """
    if builder is None:
        builder = GenerationBuilder(pipeline, pipeline._session_factory)
    if dry_run:
        # dry-run 原语义:无变更时也只列举,不做任何校验/写库副作用
        log_entry.items_new = 0
        log_entry.items_unchanged = existing
        log_entry.delta_counts = build_document_delta(
            unchanged_count=existing,
            reason="dry_run",
        )
        log_entry.finished_at = datetime.now(UTC)
        log_entry.duration_ms = int((time.monotonic() - start) * 1000)
        return
    # v1.6.4 Track A(Issue #25):账本侧缺席确认(仅不能自证删除的连接器,
    # fs/woo;A-1/A-2/A-3)。必须在一致性校验**之前**执行:fs 文件删除后
    # 向量仍在,verify 恒 healthy(正是 founding defect 的隐蔽形态)——缺席
    # 确认先完成退休/宽限标记,verify 才能反映真实服务口径(退休行退出
    # SERVING/期望计数)。不完整发现本轮 no-op,绝不推进计数(A-2)。
    absence: dict = {
        "complete": False,
        "confirmed": [],
        "candidates": [],
        "policy_absent": [],
        "restored": [],
    }
    if pipeline._session_factory is not None and not getattr(
        connector, "DECLARES_DELETIONS", True
    ):
        try:
            absence = _reconcile_source_absence(
                source_id,
                connector,
                pipeline,
                sync_run_id=getattr(telemetry, "run_id", None),
            )
        except SourceRootUnavailable:
            # Issue #100 AC2:根不可用必须向上穿透(最终 SyncLog failed)。
            # 并入下方通用 no-op 会让「根不可见」伪装成无变更成功。
            raise
        except Exception as exc:  # noqa: BLE001 - 缺席确认失败不阻断同步业务
            logger.warning(
                "数据源 %s 缺席确认失败(本轮 no-op): %s", source_id, str(exc)[:160]
            )
    report = await verify_source_vectors(session_factory, pipeline, source_id)
    if telemetry is not None:
        await telemetry.progress(session_factory, STAGE_CONSISTENCY, None, None)
        await telemetry.consistency(session_factory, _consistency_facts(report))
    if report.is_healthy:
        logger.info("数据源 %s 无变更,跳过(documents 已有 %d)", source_id, existing)
        log_entry.items_new = 0
        log_entry.items_updated = 0
        log_entry.items_unchanged = existing
        log_entry.delta_counts = build_document_delta(
            unchanged_count=existing,
            reason="no_change",
        )
        if telemetry is not None:
            # ⑫ short-circuit 机器事实(run-local 可证明):本轮无上游变更、
            # 零灌入——UI 据此呈现「无上游变更,跳过灌入」,绝不暗示完整
            # ingestion;与 refill/孤儿处置等真实灌入路径严格区分。
            await telemetry.counters(session_factory, ingestion_skipped=1)
    else:
        # 有缺口:先按 refill(整篇缺失 ∪ chunk 集合不一致)定向补灌(embed 仅
        # 缺口文档);孤儿向量走独立 reconciliation(§P1 生命周期):
        #   EXTRA_CONFIRMED_RETIRED(完整发现中确认源已无此文档)→ 按确定性
        #   UUID 精确删除残留;账本行丢失但源仍在 → 零 embedding 重建账本行;
        #   发现失败/不完整 → EXTRA_UNRESOLVED_ORPHAN,一律保留并上报,绝不删除。
        # 旧实现「refill 为空即 fetch_all+ingest_all 全量重灌自愈」已移除:
        # 无害 ghost 会令该分支每轮全量重灌(embed)+永久 partial(P1 合同)。
        # 处置后复验:收敛 → success(窗口推进);仍有缺口 → partial。
        missing_n = len(report.missing_source_ids)
        refill_n = len(report.refill_source_ids)
        mismatch_n = refill_n - missing_n  # chunk 集合不一致篇数(refill ⊇ missing)
        logger.info(
            "数据源 %s 一致性校验发现缺口:%d/%d chunks(actual/expected),"
            "需重灌 %d 篇(整篇缺失 %d + chunk 不一致 %d),多余 chunk %d 个,"
            "孤儿 %d 篇",
            source_id,
            report.actual_chunks,
            report.expected_chunks,
            refill_n,
            missing_n,
            mismatch_n,
            report.stale_chunk_count,
            report.orphan_count,
        )
        gap_parts: list[str] = []
        items_updated = 0
        gap_repaired_ids: set[str] = set()
        if report.refill_source_ids:
            refill_set = set(report.refill_source_ids)
            # v1.6.4 Track A(A-7,#25):refill 绝不复活已退休(withdrawn)
            # 身份。verify_source_vectors 口径已把 WITHDRAWN 排除在期望外,
            # 理论上不会出现在 refill 清单;此处显式再守卫,防上游口径漂移
            # (source-confirmed-removed 的内容不得经 repair 复活)。
            if pipeline._session_factory is not None:
                with pipeline._session_factory() as _wd_session:
                    withdrawn_ids = set(
                        _wd_session.execute(
                            select(Document.source_id).where(
                                Document.source_id.in_(refill_set),
                                Document.lifecycle.in_(lifecycle.DocLifecycle.WITHDRAWN),
                            )
                        ).scalars()
                    )
                refill_set -= withdrawn_ids
                if withdrawn_ids:
                    logger.warning(
                        "refill 守卫(A-7):%d 个已退休身份被排除,绝不复活:%s",
                        len(withdrawn_ids),
                        sorted(withdrawn_ids)[:3],
                    )
                    gap_parts.append(
                        f"A-7 守卫:排除已退休身份 {len(withdrawn_ids)} 篇(不复活)"
                    )
            # 空集时 repair_documents 返回零计划(无害空转);不修改 frozen
            # report,下游 refill 记账按实际修复量归零。
            # P1 gap-heal:优先从 PG 持久 chunk 副本重建(零源抓取;真值驱动);
            # 无持久副本的迁移缺口文档回退源抓取 + 强制重建(新代激活,非原位覆写)。
            repaired, unrepairable, chunks_repaired = builder.repair_documents(
                sorted(refill_set), source_id_scope=source_id
            )
            # U-10 记账别名(函数后段统一消费;与上行同值)
            repaired_fb, unrepairable_fb = list(repaired), list(unrepairable)
            gap_repaired_ids.update(repaired_fb)
            items_updated = chunks_repaired
            gap_parts.append(
                f"需重灌 {refill_n} 篇(整篇缺失 {missing_n} + chunk 不一致 {mismatch_n});"
                f"真值修复 {len(repaired)} 篇/{chunks_repaired} chunks"
            )
            if report.stale_chunk_count:
                gap_parts.append(
                    f"多余 chunk {report.stale_chunk_count} 个"
                    "(退出在服投影;物理清除仅经 retire/GC)"
                )
            if unrepairable:
                docs = [d for d in connector.fetch_all() if d.source_id in set(unrepairable)]
                _fb = builder.build_generation(docs, source_id=source_id, force_rebuild=True)
                items_updated += _fb.chunks_written
                gap_repaired_ids.update((*_fb.updated_docs, *_fb.new_docs))
                gap_parts.append(
                    f"不可重放(无持久副本/权威集不完整/超嵌入契约)"
                    f"回退源重建 {len(_fb.updated_docs) + len(_fb.new_docs)} 篇"
                    f"/{_fb.chunks_written} chunks"
                )
        # v1.6.3 Track C(U-10):逐文档自动恢复事件持久化(权威账本,恢复
        # 注记计数的数据源)。零行为变更:仅把本次一致性缺口自愈(refill)
        # 的逐文档结果(succeeded/failed)写入 document_recovery_events;
        # 尽力而为,记账失败不影响同步业务(与遥测同语义)。
        if report.refill_source_ids and not dry_run:
            try:
                from backend.services.recovery_events import record_recovery_events

                _fb_fixed: set[str] = set()
                if report.refill_source_ids and unrepairable_fb:
                    _fb_fixed = {
                        d
                        for d in (*_fb.updated_docs, *_fb.new_docs)
                        if d in unrepairable_fb
                    }
                _recover_failed = (
                    set(unrepairable_fb) - _fb_fixed if unrepairable_fb else set()
                )
                _recover_ok = (set(repaired_fb) | _fb_fixed) if repaired_fb else set(_fb_fixed)
                await record_recovery_events(
                    session_factory,
                    source_id,
                    repaired=sorted(_recover_ok),
                    unrepairable=sorted(_recover_failed),
                    sync_run_id=getattr(telemetry, "run_id", None),
                    detail={"mode": "gap_heal_refill"},
                )
            except Exception as _rev_exc:  # noqa: BLE001 - 记账失败不阻断同步
                logger.warning(
                    "数据源 %s 恢复事件记账失败(尽力而为): %s",
                    source_id,
                    str(_rev_exc)[:160],
                )
        retired = orphan_repaired = unresolved = 0
        chunk_totals = {"retired_chunks": 0, "repaired_chunks": 0}
        if report.orphan_chunks:
            try:
                retired, orphan_repaired, unresolved = _reconcile_orphan_vectors(
                    source_id, connector, pipeline, report, chunk_totals=chunk_totals
                )
            except Exception as exc:  # noqa: BLE001 - reconciliation 失败绝不删除
                logger.error(
                    "数据源 %s 孤儿 reconciliation 失败(全部保留): %s",
                    source_id,
                    str(exc)[:200],
                )
                unresolved = report.orphan_count
        if report.orphan_chunks or retired or orphan_repaired or unresolved:
            gap_parts.append(
                f"孤儿处置:EXTRA_CONFIRMED_RETIRED={retired}(精确删除),"
                f"账本重建={orphan_repaired}(零 embedding),"
                f"EXTRA_UNRESOLVED_ORPHAN={unresolved}(保留待人工裁决)"
            )
        # 处置后复验:以真实账本↔向量状态判定 success / partial
        report2 = await verify_source_vectors(session_factory, pipeline, source_id)
        if telemetry is not None:
            try:
                identity_facts = await _ledger_identity_facts(session_factory, source_id)
            except Exception as exc:  # noqa: BLE001 - 遥测尽力而为:身份事实不可得则增量键省略
                logger.warning(
                    "数据源 %s 账本身份事实查询失败(增量键省略): %s",
                    source_id,
                    str(exc)[:160],
                )
                identity_facts = None
            await telemetry.consistency(
                session_factory,
                _consistency_facts(
                    report2,
                    identity_facts=identity_facts,
                    retired_chunks=chunk_totals["retired_chunks"],
                    repaired_ledger_rows=orphan_repaired,
                ),
            )
        if report2.is_healthy:
            log_entry.status = "success"
            log_entry.items_unchanged = existing
        else:
            log_entry.status = "partial"
        # #71 授权契约第 13 条:items_* 只承载文档增量语义;孤儿向量退休与
        # 账本重建走 delta_counts 独立键,不再混入 items_new/items_deleted。
        log_entry.items_new = 0
        log_entry.items_deleted = 0
        log_entry.items_updated = items_updated
        log_entry.delta_counts = build_document_delta(
            # Repaired documents already existed; they are updates to the
            # serving projection, never new documents.  The fallback set is
            # included once, avoiding chunk/document double counting.
            updated_count=len(gap_repaired_ids),
            retired_count=0,
            unchanged_count=max(existing - len(gap_repaired_ids), 0),
            reason="consistency_repair",
            ledger_rebuilt_count=orphan_repaired,
            orphan_vectors_retired=retired,
        )
        gap_parts.append(
            f"复验:{report2.actual_chunks}/{report2.expected_chunks} chunks,"
            f"MISSING_LEGITIMATE={len(report2.refill_source_ids)},"
            f"EXTRA_UNRESOLVED_ORPHAN={report2.orphan_count}"
        )
        log_entry.error_detail = (
            f"一致性校验发现缺口 {report.actual_chunks}/{report.expected_chunks} chunks;"
            f"{';'.join(gap_parts)}"
        )
    # v1.6.4 Track A:缺席确认事实记账(两分支共有;文档退休计数与 #71 的
    # items_deleted 文档语义一致 —— 缺席确认退休是文档级退休,非孤儿向量)。
    if any(absence.get(k) for k in ("confirmed", "candidates", "policy_absent", "restored")):
        absence_note = (
            f"缺席确认:RETIRED={len(absence['confirmed'])}(两次连续完整发现),"
            f"missing_candidate={len(absence['candidates'])}(第一次,宽限中),"
            f"policy_absent={len(absence['policy_absent'])}(不计数),"
            f"restored={len(absence['restored'])}(重新出现)"
        )
        log_entry.error_detail = (
            f"{log_entry.error_detail or ''};{absence_note}"
            if log_entry.error_detail
            else absence_note
        )
    if absence.get("confirmed"):
        log_entry.items_deleted = (log_entry.items_deleted or 0) + len(absence["confirmed"])
        delta = log_entry.delta_counts or {}
        log_entry.delta_counts = {
            **delta,
            "retired_count": int(delta.get("retired_count") or 0) + len(absence["confirmed"]),
        }
    log_entry.finished_at = datetime.now(UTC)
    log_entry.duration_ms = int((time.monotonic() - start) * 1000)


def _discover_source_docs(connector: Any) -> tuple[list[Any], bool, set[str] | None]:
    """拉取当前权威全集,并评估「发现完整性」(RETIREMENT MUST BE SOURCE-CONFIRMED)。

    完整 = fetch_all 成功,且(若 connector 暴露 run_stats.full,如 web_crawl)
    覆盖率达到 COVERAGE_PARTIAL_RATIO。任何失败/不完整都使调用方不得执行
    退休删除(瞬时爬取失败 ≠ 文档退休)。

    P1 修正(Planner FINAL REVIEW):**权威源成员资格 ≠ 抽取成功**。
    web_crawl 的 accepted 先于单页抓取记账,覆盖率 ≥80% 仍可能存在「源里
    在、本轮抓取/抽取失败」的页面。若 connector 提供
    ``authoritative_source_ids()``(权威枚举成员集),退休判定必须以它为准;
    抽取成功集合仅用于「源仍在的账本行丢失」修复分支。无该原语的连接器
    (git/fs/woo:抽取即枚举)回退抽取集合。

    Returns:
        (docs, complete, membership):complete=False 时调用方只允许保留 + 上报;
        membership=None 表示 connector 无权威成员集原语(回退抽取集合)。
    """
    try:
        docs = list(connector.fetch_all())
    except SourceRootUnavailable:
        # Issue #100 AC2:根不可用 = 拓扑级失败,必须向上穿透(最终 SyncLog
        # failed + 可执行错误)。绝不并入「不完整发现」no-op —— 那会让
        # 「根不可见」伪装成合法空源/无变更成功,并把账本行送进缺席分类。
        raise
    except Exception as exc:  # noqa: BLE001 - 发现失败 → 不完整
        logger.warning(
            "源发现失败(%s),孤儿向量一律保留不删除",
            str(exc)[:160],
        )
        return [], False, None
    complete = True
    stats = getattr(connector, "run_stats", None)
    if isinstance(stats, dict) and stats.get("full"):
        extracted = int(stats.get("extracted", 0))
        # G3 发现完整性守卫:「discovered = 0」本身不能证明「源权威成员集
        # 为空」——合法空源与畸形 sitemap(200 + 坏 XML,解析静默返回空)
        # 在此不可区分。仅当 connector **显式报告** discovered == 0(run_stats
        # 含该键;真实 web_crawl 全量轮恒写入)时视为不完整发现,禁止破坏性
        # 退休(UNKNOWN/INCOMPLETE DISCOVERY ≠ AUTHORITATIVE EMPTY SOURCE),
        # 孤儿一律保留并上报。键缺失的 primitive connector(git/fs/woo:抽取
        # 即权威枚举)语义不变。
        accepted = int(stats.get("accepted", 0))
        if stats.get("discovered") == 0:
            logger.warning(
                "源发现完整性无法证明(discovered=0 accepted=%s extracted=%d)"
                "→ 视为不完整发现,孤儿一律保留不删除",
                stats.get("accepted"),
                extracted,
            )
            complete = False
        elif (
            accepted > 0 and extracted < accepted and extracted / accepted < COVERAGE_PARTIAL_RATIO
        ):
            logger.warning(
                "源发现覆盖率不足(%d/%d < %.0f%%)→ 视为不完整发现,孤儿一律保留",
                extracted,
                accepted,
                COVERAGE_PARTIAL_RATIO * 100,
            )
            complete = False
    membership: set[str] | None = None
    getter = getattr(connector, "authoritative_source_ids", None)
    if callable(getter):
        ids = getter()
        if isinstance(ids, (set, frozenset)):
            membership = set(ids)
    return docs, complete, membership


def _reconcile_orphan_vectors(
    source_id: str,
    connector: Any,
    pipeline: IngestionPipeline,
    report: Any,
    *,
    chunk_totals: dict | None = None,
) -> tuple[int, int, int]:
    """孤儿向量 reconciliation(零 embedding;分类见下,从不动兄弟文档)。

    对账本无行的孤儿文档逐篇分类(P1 冻结语义 + Planner 修正):
      - **权威源成员资格 ≠ 抽取成功**:退休判定以权威枚举成员集
        (``authoritative_source_ids``,web_crawl 含抓取失败/被拒页)为准;
        成员集中的孤儿(本轮抽取失败的存量页)一律保留并上报;
      - 完整发现中成员集确认源已无此文档 → EXTRA_CONFIRMED_RETIRED:按该文档
        自己的确定性 UUID(uuid5(source_id#i),来自校验器扫描的实际存量)
        精确删除;
      - 源中仍存在(抽取成功、账本行丢失)→ 以存量对象属性零 embedding 重建
        账本行。Issue #13(D1/D2)后账本按 ``source_id`` 路径身份 upsert,
        **同内容不同路径的兄弟孤儿不再触发 (content_hash, branch) 主键冲突**
        —— 即 Issue #13 的 UniqueViolation 根因在此根除;若插入仍因身份
        约束失败(如并发灌入竞态),显式记 EXTRA_UNRESOLVED_ORPHAN 上报,
        绝不吞错假装成功;
      - 发现失败 / 不完整 / 属性缺失 → EXTRA_UNRESOLVED_ORPHAN:保留 + 上报。

    删除/修复范围均由「本文档自己的 source_id + 实际 chunk_index」决定,
    结构上不可能触及兄弟文档(PRUNE IS DOCUMENT-LOCAL 同源不变量)。

    Args:
        source_id: 数据源 ID。
        connector: 已实例化 connector(权威发现)。
        pipeline: IngestionPipeline(Weaviate 访问 + 账本会话工厂)。
        report: VectorGapReport(orphan_chunks 为孤儿明细)。
        chunk_totals: 可选出参 dict;调用方传入时写入
            ``retired_chunks`` / ``repaired_chunks``(共享一致性遥测消费)。

    Returns:
        (retired, repaired, unresolved) — 三分类篇数。
    """
    from weaviate.classes.query import Filter

    from backend.db.models import Document
    from backend.pipeline.ingest import _deterministic_uuid

    docs, complete, membership = _discover_source_docs(connector)
    extracted_ids = {d.source_id for d in docs}
    # 退休证据 = 权威成员集;无原语的连接器(git/fs/woo:抽取即枚举)回退抽取集
    membership_ids = membership if membership is not None else extracted_ids
    pipeline._ensure_collection()
    collection = pipeline._collection

    retired = repaired = unresolved = 0
    if chunk_totals is not None:
        chunk_totals.setdefault("retired_chunks", 0)
        chunk_totals.setdefault("repaired_chunks", 0)
    for sid, indices in sorted(report.orphan_chunks.items()):
        uuids = [_deterministic_uuid(sid, i) for i in sorted(indices)]
        try:
            fetched = collection.query.fetch_objects(
                filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
            )
        except Exception as exc:  # noqa: BLE001 - 读失败 → 保留
            logger.warning("孤儿 %s 对象读取失败,保留:%s", sid, str(exc)[:120])
            unresolved += 1
            continue
        if len(fetched.objects) != len(indices):
            logger.warning(
                "孤儿 %s 存量与扫描不一致(%d/%d),保留待人工核查",
                sid,
                len(fetched.objects),
                len(indices),
            )
            unresolved += 1
            continue
        if sid in membership_ids:
            # 权威源成员仍在:若本轮抽取成功 → 账本行丢失,零 embedding 重建;
            # 若仅成员(抓取/抽取临时失败,如 G004-C/D)→ 保留上报,绝不退休。
            if sid not in extracted_ids:
                logger.warning(
                    "EXTRA_UNRESOLVED_ORPHAN: %s 仍在权威源成员集但本轮抽取失败"
                    "(瞬时),保留不删除",
                    sid,
                )
                unresolved += 1
                continue
            props = fetched.objects[0].properties
            content_hash = props.get("content_hash")
            if not content_hash:
                logger.warning("孤儿 %s 缺 content_hash 属性,保留待人工核查", sid)
                unresolved += 1
                continue
            session_factory = pipeline._session_factory
            if session_factory is None:
                logger.warning("孤儿 %s 无账本会话工厂,保留", sid)
                unresolved += 1
                continue
            try:
                with session_factory() as session:
                    doc_row = Document(
                        content_hash=str(content_hash),
                        source_id=sid,
                        source_type=str(props.get("source_type") or ""),
                        product=str(props.get("product") or ""),
                        title=str(props.get("title") or ""),
                        url=str(props.get("url") or ""),
                        branch=str(props.get("branch") or ""),
                        chunk_count=max(indices) + 1,
                    )
                    session.add(doc_row)
                    # P1 不变量:每文档恒有 current 版本(账本修复同样落初始版本,
                    # 归迁移初始代;chunk 副本暂缺属迁移缺口,由 repair/refill 演进)
                    lifecycle.ensure_initial_version(session, doc_row)
                    session.commit()
                repaired += 1
                if chunk_totals is not None:
                    chunk_totals["repaired_chunks"] += len(indices)
                logger.info(
                    "EXTRA_ORPHAN_LEDGER_REPAIRED: %s 账本行已按存量重建"
                    "(chunk_count=%d,零 embedding)",
                    sid,
                    max(indices) + 1,
                )
            except IntegrityError as exc:
                # Issue #13:身份约束冲突(如同路径并发灌入竞态)→ 显式保留并
                # 上报,绝不吞错假装 reconciliation 成功
                logger.warning(
                    "EXTRA_UNRESOLVED_ORPHAN: %s 账本重建触发身份约束冲突"
                    "(并发竞态或账本漂移),保留待人工核查:%s",
                    sid,
                    str(exc)[:160],
                )
                unresolved += 1
            except Exception as exc:  # noqa: BLE001 - 修复失败 → 保留
                logger.warning("孤儿 %s 账本重建失败,保留:%s", sid, str(exc)[:160])
                unresolved += 1
        elif complete and sid not in membership_ids:
            # EXTRA_CONFIRMED_RETIRED:完整权威枚举确认源已无此文档 → 精确退休删除
            for start in range(0, len(uuids), 500):
                collection.data.delete_many(
                    where=Filter.by_id().contains_any(uuids[start : start + 500])
                )
            retired += 1
            if chunk_totals is not None:
                chunk_totals["retired_chunks"] += len(indices)
            logger.info(
                "EXTRA_CONFIRMED_RETIRED: %s 已不在权威源(完整发现),"
                "按确定性 UUID 精确删除 %d 个残留 chunk",
                sid,
                len(uuids),
            )
        else:
            # 发现失败/不完整 → KEEP DATA + REPORT
            unresolved += 1
            logger.warning("EXTRA_UNRESOLVED_ORPHAN: %s 保留(发现不完整,不删除)", sid)
    return retired, repaired, unresolved


# ---------------------------------------------------------------------------
# 账本侧缺席确认(v1.6.4 Track A,Issue #25;A-1/A-2/A-3/A-6/A-7)
# ---------------------------------------------------------------------------


def _reconcile_source_absence(
    source_id: str,
    connector: Any,
    pipeline: IngestionPipeline,
    *,
    sync_run_id: int | None = None,
) -> dict:
    """完整权威发现差集 → 账本缺席确认状态机(向量侧 EXTRA_CONFIRMED_RETIRED
    的账本侧镜像;A-1/A-2 冻结语义)。

    仅对**不能自证删除**的连接器(``DECLARES_DELETIONS = False``:fs/woo)
    生效 —— git/web 连接器已经由 ``fetch_deleted``/membership 快照证明删除,
    维持既有路径(A-1)。逐账本行分类:

      - 行在权威清单中(重新出现):missing_candidate 宽限行 → 恢复 active
        并清除缺席状态(A-2/A-3 恢复语义);
      - 行缺席 + 政策范围外(``policy_absence_reason``):入宽限态呈现
        Needs Attention,连续计数**冻结清零**(A-3:政策缺席绝不确认为删除);
      - 行缺席 + 范围内:计数 +1;两次**连续**完整发现 → RETIRED
        (lifecycle=DELETED + A-6 审计记录持久化,即时撤出服务投影,
        GC 资格 = retired_at + 7d)。

    完整性守卫复用 :func:`_discover_source_docs`(发现失败/不完整/低覆盖 →
    本轮整体 no-op,不推进任何计数);幂等:重复确认扫描对已退休行零变更。

    Returns:
        ``{"complete": bool, "confirmed": [sid], "candidates": [sid],
        "policy_absent": [sid], "restored": [sid]}``(供 SyncLog 记账)。
    """

    def _empty(complete: bool) -> dict:
        return {
            "complete": complete,
            "confirmed": [],
            "candidates": [],
            "policy_absent": [],
            "restored": [],
        }

    if getattr(connector, "DECLARES_DELETIONS", True):
        # git/web:连接器自证删除,本机制不介入(A-1 边界)。
        return _empty(False)
    sync_factory = pipeline._session_factory
    if sync_factory is None:
        # 无账本(纯投影运行):缺席确认不可能成立,如实跳过。
        logger.warning("数据源 %s 无账本会话工厂,缺席确认跳过", source_id)
        return _empty(False)

    docs, complete, membership = _discover_source_docs(connector)
    extracted_ids = {d.source_id for d in docs}
    # 退休证据 = 权威成员集;无原语的连接器(fs/woo:抽取即枚举)回退抽取集。
    membership_ids = membership if membership is not None else extracted_ids
    if not complete:
        logger.warning(
            "数据源 %s 发现不完整,缺席确认本轮 no-op(不推进计数,A-2)", source_id
        )
        return _empty(False)

    reason_fn = getattr(connector, "policy_absence_reason", None)
    now = lifecycle.utcnow()
    result = _empty(True)
    with sync_factory() as session:
        rows = (
            session.execute(
                select(Document).where(
                    Document.source_id.startswith(f"{source_id}/", autoescape=True)
                )
            )
            .scalars()
            .all()
        )
        for doc in rows:
            sid = doc.source_id
            if doc.lifecycle in lifecycle.DocLifecycle.WITHDRAWN:
                continue  # 已退休/被接替:幂等跳过,零变更
            if sid in membership_ids:
                # 在权威清单中:宽限行恢复(A-2/A-3);健康行零变更。
                if lifecycle.restore_from_absence(doc):
                    result["restored"].append(sid)
                    logger.info("缺席恢复: %s 重新出现于权威发现,恢复 active", sid)
                continue
            # 缺席:先做 A-3 政策分类(范围外绝不推进确认计数)。
            policy_reason = reason_fn(sid) if callable(reason_fn) else None
            outcome = lifecycle.record_absence_observation(
                doc,
                policy_reason=policy_reason,
                observed_at=now,
                evidence={"sync_run_id": sync_run_id, "listing_size": len(membership_ids)},
            )
            if outcome == "confirmed":
                result["confirmed"].append(sid)
                logger.warning(
                    "缺席确认退休 %s(两次连续完整发现;即时撤出服务,7 天后 GC 资格)",
                    sid,
                )
            elif outcome == "observed":
                result["candidates"].append(sid)
                logger.info("缺席候选: %s 第一次完整发现缺席,入宽限态(仍在服务)", sid)
            else:  # "policy"
                result["policy_absent"].append(sid)
                logger.info(
                    "政策缺席: %s 因策略范围外不可见(%s),不推进退休确认",
                    sid,
                    policy_reason,
                )
        session.commit()
    return result


async def _sync_one(
    cfg: SourceConfig,
    pipeline: IngestionPipeline,
    session_factory: Any,
    *,
    triggered_by: str = "cron",
    dry_run: bool = False,
    reindex: bool = False,
    request_id: int | None = None,
    attempt: int = 1,
    recovery_replay: bool = False,
    builder: GenerationBuilder | None = None,
) -> bool:
    """同步单个数据源:fetch → 变更判定/生成构建/原子激活 → 墓碑 → 写 SyncLog。

    - 异常被捕获并记录到 SyncLog(status="failed"),**不向上传播**,
      避免一个数据源失败中断整个批次。
    - ``dry_run=True`` 时只列举文档数,不灌入向量库、不写 SyncLog。
    - ``reindex=True`` 时绕过增量 skip 逻辑,强制 ``fetch_all()`` 全量重建:
      **P1 语义 = 生成重建 + 原子激活**(旧"先删整个 collection 再重灌"已
      废除——重建期间在服投影分毫不动,验证通过才切换,Gate P1-E)。
    - ``finally`` 块确保无论成功 / 失败 / 异常都会写 SyncLog(除非 dry_run)。
    - 返回值(#34):本次是否发生**传输类**失败(GitTransportError)。
      业务失败仍恒以 0 退出(契约 §14 不变);run_sync 聚合后决定 runner
      退出码 → 传输失败落入 executor 既有 runner_failed 有界重试。

    Args:
        cfg: 数据源配置(SourceConfig)。
        pipeline: 已初始化的 IngestionPipeline 实例。
        session_factory: 异步 SQLAlchemy 会话工厂(``async_sessionmaker``)。
        triggered_by: SyncLog.triggered_by 字段值,``"cron"`` 或 ``"manual"``。
        dry_run: True 时只列举文档数,不灌入 / 不写 SyncLog。
        reindex: True 时强制全量重灌(绕过增量 skip)。
    """
    start = time.monotonic()
    if builder is None:
        builder = GenerationBuilder(pipeline, pipeline._session_factory)
    log_entry = SyncLog(
        source_id=cfg.id,
        source_type=cfg.type,
        status="success",
        triggered_by=triggered_by,
    )
    # Wave-0:attempt 启动即落 SyncRun 运行事实(不等同步结束);dry_run 不落。
    tel = _RunTelemetry()
    runtime_handle = getattr(pipeline, "_embedder", None)
    if not isinstance(runtime_handle, SyncEmbedderHandle):
        runtime_handle = None
    runtime_snapshot = runtime_handle.activity_snapshot() if runtime_handle is not None else None

    async def _record_runtime_facts() -> None:
        """Write facts produced by this source's real embedding activity.

        The model is constructed before source discovery.  Therefore a
        healthy GPU model plus a SHA short-circuit is not evidence of healthy
        GPU embedding; a real encode or a real fallback event is required.
        """
        if runtime_handle is None or runtime_snapshot is None:
            return
        has_activity = runtime_handle.has_activity_since(runtime_snapshot)
        if not has_activity and runtime_handle.fallback_reason is None:
            return
        await tel.device(
            session_factory,
            execution_device=runtime_handle.telemetry_execution_device,
            fallback_reason=runtime_handle.fallback_reason,
            fallback_detail=runtime_handle.fallback_detail,
        )
        cpu_counts = runtime_handle.cpu_counters_since(runtime_snapshot)
        if cpu_counts["cpu_batches"] or cpu_counts["cpu_docs"]:
            await tel.counters(session_factory, **cpu_counts)

    if not dry_run:
        await tel.start(
            session_factory,
            source_id=cfg.id,
            request_id=request_id,
            attempt=attempt,
            recovery=recovery_replay,
            triggered_by=triggered_by,
        )

    try:
        connector = ConnectorRegistry.create(cfg)
        # 增量窗口:上次成功时间(失败不推进窗口,防缺口被推过)
        last_success = await _last_success_at(session_factory, cfg.id)
        since = _compute_since(last_success, datetime.now(UTC))
        logger.info("数据源 %s 增量窗口: %s", cfg.id, since.isoformat())

        if reindex:
            # reindex 模式(P1 语义):绕过增量 skip,强制 fetch_all 全量重建。
            # 构建走新生成代(旧代持续服务),验证通过才原子激活——先删后灌已废除。
            logger.info("reindex 模式:数据源 %s 全量生成重建(零服务损失)", cfg.id)
            docs = list(connector.fetch_all())
            await tel.progress(session_factory, STAGE_FETCH, len(docs), len(docs))
        else:
            docs = list(connector.fetch_changes(since))
            # materialize 后总数可信才写 total;此前分母未知(stage=DISCOVER)
            await tel.progress(session_factory, STAGE_FETCH, len(docs), len(docs))
            if not docs:
                # 区分首次(无 documents 记录)vs 无变更(已有记录)
                existing = await _count_documents(session_factory, cfg.id)
                if existing > 0:
                    # #71:权威成员对账每轮必跑 —— 「远端看似无变更」(SHA
                    # 短路)绝不豁免成员资格对账;漂移未解决不记 success。
                    membership_resolved, membership_delta, missing_ids = (
                        await _reconcile_membership_for_source(
                            cfg,
                            connector,
                            pipeline,
                            session_factory,
                            log_entry,
                            dry_run=dry_run,
                        )
                    )
                    # #82:缺失权威成员(分支 scope 扩大等)先定向补灌,再走
                    # 无变更校验 —— 复验即可覆盖补灌文档的账本↔向量一致性。
                    backfill = await _backfill_missing_members(
                        cfg, connector, builder, missing_ids
                    )
                    await _handle_no_change(
                        cfg.id,
                        existing,
                        connector,
                        pipeline,
                        session_factory,
                        log_entry,
                        start,
                        dry_run=dry_run,
                        telemetry=tel if not dry_run else None,
                        builder=builder,
                    )
                    if membership_delta:
                        log_entry.delta_counts = {
                            **(log_entry.delta_counts or {}),
                            **membership_delta,
                        }
                    if backfill is not None:
                        # #82:补灌是真实新增,绝不伪装「无变更」—— new 桶与
                        # 加性溯源键如实呈现(_handle_no_change 记 0 new 之上
                        # 叠加;existing 本就不含补灌前不在服的成员)。
                        backfill_new_n = len(backfill.new_docs)
                        log_entry.items_new = backfill_new_n
                        delta_merge = dict(log_entry.delta_counts or {})
                        delta_merge["new_count"] = (
                            int(delta_merge.get("new_count", 0) or 0) + backfill_new_n
                        )
                        delta_merge["membership_backfilled"] = (
                            backfill_new_n + len(backfill.updated_docs)
                        )
                        delta_merge["membership_backfilled_unit"] = "document"
                        # #91 加性记账:eligible / 永久排除分区事实(AC10/AC12)
                        delta_merge.update(_exclusion_delta(backfill))
                        log_entry.delta_counts = delta_merge
                    if not membership_resolved and log_entry.status == "success":
                        log_entry.status = "partial"
                    return
                # 首次同步:documents 表无记录,回退到全量拉取
                logger.info("数据源 %s 首次同步,回退到全量拉取", cfg.id)
                docs = list(connector.fetch_all())

        logger.info("数据源 %s 抓取到 %d 篇文档", cfg.id, len(docs))
        # Wave-0:解析/覆盖计数(web_crawl 等 connector 提供多少记多少)
        _rs = getattr(connector, "run_stats", None)
        if isinstance(_rs, dict):
            await tel.counters(
                session_factory,
                discovered=_rs.get("discovered"),
                accepted=_rs.get("accepted"),
                extracted=_rs.get("extracted"),
                failed=_rs.get("failed"),
                rejected=_rs.get("rejected"),
            )
            _acc = _rs.get("accepted")
            await tel.progress(
                session_factory,
                STAGE_PARSE,
                _rs.get("extracted"),
                _acc if _rs.get("full") else None,  # 非全量轮分母未知
            )

        if dry_run:
            # dry-run 模式:不灌入向量库,只统计文档数后返回
            log_entry.items_new = len(docs)
            log_entry.finished_at = datetime.now(UTC)
            log_entry.duration_ms = int((time.monotonic() - start) * 1000)
            return

        _docs_total = len(docs)
        # CORRECTION A:SAFETY_FILTER 边界可观测(真实过滤发生在 ingest 内部;
        # 批界计数由回调如实提供,无分母时不伪造 total)
        await tel.progress(session_factory, STAGE_SAFETY_FILTER, None, None)
        # ⑫ 实时进度(W2):ingest 全程在工作线程执行(asyncio.to_thread),
        # 不再阻塞事件循环——同进程内 API/健康检查照常响应,批界进度可被
        # 并发读者(refresh/轮询)从 sync_runs 真实读取。回调(线程侧)只
        # 更新内存最新值(单生产者,赋值原子);DB 落笔由事件循环侧 flush
        # 任务按 SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS 防抖摊销,进程中断时
        # 已持久化的最后一条批界事实保留。
        _ingest_live: dict[str, int] = {}
        _ingest_seq: list[str] = []

        def _ingest_progress(stage: str, done: int) -> None:
            if stage not in _ingest_live:
                _ingest_seq.append(stage)  # 记录 stage 首现顺序(取当前相位用)
            _ingest_live[stage] = done

        async def _flush_ingest_progress() -> None:
            last_write = 0.0
            while True:
                await asyncio.sleep(0.2)
                if not _ingest_seq or time.monotonic() - last_write < (
                    SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS
                ):
                    continue
                stage = _ingest_seq[-1]
                await tel.progress(session_factory, stage, _ingest_live[stage], _docs_total)
                last_write = time.monotonic()

        flusher = asyncio.create_task(_flush_ingest_progress())
        try:
            # P1:生成构建 + 原子激活(替代旧 ingest_all 原位覆写)。
            # 任一文档失败 → IngestFailures raise → 本轮零激活,旧真相持续服务
            # (既有"失败不推窗口"纪律不变);reindex → force_rebuild 全量重建。
            accounting = await asyncio.to_thread(
                builder.build_generation,
                docs,
                source_id=cfg.id,
                force_rebuild=reindex,
                progress=_ingest_progress,
            )
        finally:
            flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await flusher
        # 终笔与既有语义一致:四 stage 批界终值按序落笔(结束态=INDEX);
        # 实时 flush 只是中途快照,终值以此为准。
        for _st in (STAGE_SAFETY_FILTER, STAGE_CHUNK, STAGE_EMBED, STAGE_INDEX):
            if _st in _ingest_live:
                await tel.progress(session_factory, _st, _ingest_live[_st], _docs_total)
        await tel.counters(session_factory, docs_total=_docs_total, docs_done=len(docs))
        # P1 删除安全:fetch_deleted → 墓碑(逻辑删除,非物理;I-6/FC-4)。
        # 墓碑文档即时退出服务集(active 集不再含其对象),物理清除仅经 GC。
        deleted = connector.fetch_deleted(since)
        tombstoned = 0
        # 账本工厂缺省(无 Postgres 部署/纯投影运行)时墓碑不可能成立:
        # 逻辑删除原语依赖账本;此处如实跳过(物理清除本就仅经 GC),
        # 绝不以删除向量对象伪造墓碑语义。
        if deleted and pipeline._session_factory is not None:
            with pipeline._session_factory() as sync_session:
                for doc_id in deleted:
                    if lifecycle.tombstone_document(
                        sync_session,
                        doc_id,
                        reason=f"fetch_deleted:{cfg.id}",
                        actor=lifecycle.ACTOR_SYNC_FETCH_DELETED,
                        evidence={"mechanism": "fetch_deleted", "source": cfg.id},
                    ):
                        tombstoned += 1
                sync_session.commit()
        # v1.6.4 Track A(Issue #25):账本侧缺席确认(仅 fs/woo 类连接器;
        # A-1/A-2 两次连续完整发现退休;A-3 政策缺席不计数)。紧跟墓碑块之后:
        # git provenance 先行,发现差集补位;幂等,与 #71 成员对账天然共存
        # (#71 仅覆盖提供 membership_source_ids 的连接器)。
        absence_change: dict = {}
        if pipeline._session_factory is not None and not getattr(
            connector, "DECLARES_DELETIONS", True
        ):
            try:
                absence_change = _reconcile_source_absence(
                    cfg.id,
                    connector,
                    pipeline,
                    sync_run_id=getattr(tel, "run_id", None) if not dry_run else None,
                )
                if absence_change.get("confirmed"):
                    tombstoned += len(absence_change["confirmed"])
            except Exception as exc:  # noqa: BLE001 - 缺席确认失败不阻断同步
                logger.warning(
                    "数据源 %s 缺席确认失败(本轮 no-op): %s", cfg.id, str(exc)[:160]
                )
                absence_change = {}
        # 阶段⑩ W6:retirement 效应安全完成后才推进 crawl 成员快照。
        # 删除循环中途被 kill → 本调用不执行 → 旧快照保留 → 下轮重报同一
        # 差集(重复墓碑幂等),ghost 不再永久化。无此能力的 connector no-op。
        committer = getattr(connector, "commit_membership_snapshot", None)
        if callable(committer):
            committer()

        # #71 权威成员对账(每轮必跑,与 delta 是否为空无关):正确性独立于
        # git 事件窗口与 fetch_deleted 历史;退休走同一墓碑语义,货币真值仅在
        # 退休事务成功后持久化(kill-safety)。
        membership_resolved, membership_delta, missing_ids = (
            await _reconcile_membership_for_source(
                cfg, connector, pipeline, session_factory, log_entry, dry_run=dry_run
            )
        )
        membership_deleted = membership_delta.get("stale_retired", 0)
        # #82:缺失权威成员(分支 scope 扩大等)在终局一致性校验前定向补灌,
        # 使复验覆盖补灌文档的账本↔向量一致性。
        backfill = await _backfill_missing_members(cfg, connector, builder, missing_ids)
        backfill_new_n = len(backfill.new_docs) if backfill is not None else 0
        backfill_updated_n = (
            len(backfill.updated_docs) + len(backfill.metadata_docs)
            if backfill is not None
            else 0
        )
        backfill_chunks_n = backfill.chunks_written if backfill is not None else 0
        # 补灌批次与主批次的重叠成员(墓碑行被主批次判 unchanged、又被补灌
        # 强制重建):从 unchanged 桶剔除,避免一篇文档进两个变更桶。
        backfill_ids = set(missing_ids) if backfill is not None else set()

        # CORRECTION B:终局一致性事实(INDEX → CONSISTENCY → DONE)。
        # 复用权威 verify_source_vectors(与无变更路径同一实现,不造第二套);
        # 凭 ingest 成功推断健康被禁止——校验失败如实记录,不伪造健康载荷,
        # 业务结局仍归 sync_log(既有 sync business rules 不变)。
        await tel.progress(session_factory, STAGE_CONSISTENCY, None, None)
        try:
            _final = await verify_source_vectors(session_factory, pipeline, cfg.id)
            try:
                _identity = await _ledger_identity_facts(session_factory, cfg.id)
            except Exception as exc:  # noqa: BLE001 - 身份事实不可得≠业务失败
                logger.warning(
                    "数据源 %s 账本身份事实查询失败(增量键省略): %s",
                    cfg.id,
                    str(exc)[:160],
                )
                _identity = None
            await tel.consistency(
                session_factory, _consistency_facts(_final, identity_facts=_identity)
            )
        except Exception as exc:  # noqa: BLE001 - 校验不可用≠业务失败,证据面如实降级
            logger.warning(
                "数据源 %s 终局一致性校验失败(如实记录,不伪造健康): %s",
                cfg.id,
                str(exc)[:200],
            )
            await tel.consistency(session_factory, {"verification_failed": str(exc)[:300]})

        log_entry.items_new = len(accounting.new_docs) + backfill_new_n
        # 既有 SyncLog 口径:items_updated 按 chunk 数记账;metadata-only 变更
        # (零重嵌)按篇计入,保持"本轮发生变更的量"可观测。
        log_entry.items_updated = (
            accounting.chunks_written
            + len(accounting.metadata_docs)
            + backfill_chunks_n
            + backfill_updated_n
        )
        # #71:items_deleted = 本轮文档墓碑总数(窗口检测 + 权威成员对账);
        # 成员对账的 stale_detected/stale_retired 另有独立 delta_counts 键,
        # 两者不混淆(授权契约第 13 条)。
        log_entry.items_deleted = tombstoned + membership_deleted
        # #82:unchanged 口径排除被补灌重建的成员(它们已进入 new/updated 桶)
        unchanged_n = len(set(accounting.unchanged_docs) - backfill_ids)
        log_entry.items_unchanged = unchanged_n
        # #65 additive truth:all administrator deltas are document counts.
        # ``items_updated`` above intentionally remains the historical mixed
        # chunk/document field for old consumers and is never reinterpreted.
        log_entry.delta_counts = build_document_delta(
            new_count=len(accounting.new_docs) + backfill_new_n,
            updated_count=len(accounting.updated_docs)
            + len(accounting.metadata_docs)
            + backfill_updated_n,
            retired_count=tombstoned + membership_deleted,
            unchanged_count=unchanged_n,
            reason="source_changes",
        )
        if membership_delta:
            log_entry.delta_counts = {**log_entry.delta_counts, **membership_delta}
        if backfill is not None:
            log_entry.delta_counts = {
                **log_entry.delta_counts,
                "membership_backfilled": backfill_new_n + backfill_updated_n,
                "membership_backfilled_unit": "document",
            }
        # #91 加性记账:主构建 + 补灌批次的 eligible/永久排除分区事实
        main_exclusion_delta = _exclusion_delta(accounting)
        if main_exclusion_delta or backfill is not None:
            merge = dict(main_exclusion_delta)
            if backfill is not None:
                for key, value in _exclusion_delta(backfill).items():
                    if key.endswith("_unit"):
                        continue
                    merge[key] = merge.get(key, 0) + value
            log_entry.delta_counts = {**log_entry.delta_counts, **merge}
        # Track A:缺席确认事实进 error_detail(宽限/政策缺席/恢复均留痕;
        # 退休篇数已并入 items_deleted/retired_count)。
        if any(
            absence_change.get(k)
            for k in ("confirmed", "candidates", "policy_absent", "restored")
        ):
            log_entry.error_detail = (
                f"{log_entry.error_detail or ''};缺席确认:"
                f"RETIRED={len(absence_change['confirmed'])}(两次连续完整发现),"
                f"missing_candidate={len(absence_change['candidates'])}(第一次,宽限中),"
                f"policy_absent={len(absence_change['policy_absent'])}(不计数),"
                f"restored={len(absence_change['restored'])}(重新出现)"
            ).lstrip(";")

        # WEB 合同#6/#7:全量抓取覆盖记账 —— coverage 行始终写入 error_detail
        # (成功也留痕),完整性不足时降级 status,绝不让「85 页只活 2 页」
        # 伪装成健康成功。仅对提供 run_stats 且声明全量轮的 connector 生效,
        # git/filesystem/woocommerce 等连接器语义不变。
        stats = getattr(connector, "run_stats", None)
        if isinstance(stats, dict) and stats.get("full"):
            log_entry.error_detail = (
                f"{log_entry.error_detail or ''};{_coverage_line(stats)}".lstrip(";")
            )
            extracted = int(stats.get("extracted", 0))
            accepted = int(stats.get("accepted", 0))
            if accepted > 0 and extracted < accepted:
                if extracted == 0:
                    log_entry.status = "failed"
                    log_entry.error_detail += (
                        f";全部候选页抽取失败(accepted={accepted}),判定同步失败"
                    )
                elif extracted / accepted < COVERAGE_PARTIAL_RATIO:
                    log_entry.status = "partial"
                    log_entry.error_detail += (
                        f";覆盖率不足({extracted}/{accepted}="
                        f"{extracted / accepted:.0%} < {COVERAGE_PARTIAL_RATIO:.0%}),记 partial"
                    )

        await tel.progress(session_factory, STAGE_DONE, len(docs), len(docs))
        log_entry.finished_at = datetime.now(UTC)
        log_entry.duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "同步完成 %s: %d 新, %d 更新, %d 删除",
            cfg.id,
            log_entry.items_new,
            log_entry.items_updated,
            log_entry.items_deleted,
        )
        return False

    except Exception as exc:  # noqa: BLE001 - 单源失败不中断批次
        log_entry.status = "failed"
        log_entry.error_detail = str(exc)
        if isinstance(exc, SourceRootUnavailable):
            # Issue #100 AC2:源根不可用 = 可执行拓扑错误,操作员按详情
            # 修复共享挂载/路径配置;绝非业务空源,绝不推进成功窗口。
            log_entry.error_detail = f"[source-unavailable] {log_entry.error_detail}"
        # #45:IngestFailures 携带结构化逐文档失败(.failures)—— 计入
        # SyncRun.counters.docs_failed(零迁移),error_detail 已含逐文档
        # 明细行(stage/分类/可重试性),操作员无需再翻日志定位。
        ingest_failures = getattr(exc, "failures", None)
        if ingest_failures:
            await tel.counters(
                session_factory,
                docs_failed=len(ingest_failures),
                docs_failed_retryable=sum(1 for f in ingest_failures if f.retryable),
            )
        # #91:失败轮的永久排除分区事实照常暴露 —— 排除不是失败,也不是
        # 健康假象的遮掩(AC10/I9:绝不靠「少报错误」制造假健康)。
        excluded_failures = getattr(exc, "excluded", None) or []
        if excluded_failures:
            await tel.counters(
                session_factory,
                docs_permanent_excluded=len(excluded_failures),
            )
            log_entry.error_detail = (
                f"{log_entry.error_detail};"
                f"永久排除分区 {len(excluded_failures)} 篇"
                f"(已登记 ingestion_exclusions,不再重复补灌)"
            )
        # #34:传输类失败证据化 —— 计入 SyncRun.counters.transport_failures,
        # 并向 run_sync 上抛信号(经返回值),落入 executor 既有有界重试;
        # 非传输类(业务/契约)失败保持旧语义:仅记 SyncLog,不触发重试。
        transport_failure = isinstance(exc, GitTransportError)
        if transport_failure:
            await tel.counters(session_factory, transport_failures=1)
            log_entry.error_detail = f"[transport][retryable] {log_entry.error_detail}"
        # 失败路径同样尽力留 coverage 痕迹(异常中断时的已抓部分不消失)
        connector_for_stats = locals().get("connector")
        stats = getattr(connector_for_stats, "run_stats", None)
        if isinstance(stats, dict) and stats.get("full"):
            log_entry.error_detail = f"{log_entry.error_detail};{_coverage_line(stats)}"
        log_entry.finished_at = datetime.now(UTC)
        log_entry.duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("同步失败 %s: %s", cfg.id, exc)
        return transport_failure

    finally:
        if not dry_run:
            # 内嵌 try/except 防止 commit 失败冲破外层 except 的错误隔离
            # (例如连接断开 / 死锁),保证后续数据源仍可继续同步
            try:
                async with session_factory() as session:
                    session.add(log_entry)
                    await session.commit()
            except Exception as exc:  # noqa: BLE001 - SyncLog 写入失败不中断批次
                logger.error("SyncLog 写入失败 %s: %s", cfg.id, exc)
            # #62:the persisted schedule advances from the latest successful
            # SyncLog only; failures therefore leave the previous due point.
            await _reconcile_source_schedule(session_factory, cfg.id)
            await _record_runtime_facts()
            # Wave-0:SyncRun 终局(业务成败归 sync_log;completed=attempt 跑完)
            _run_status = "failed" if log_entry.status == "failed" else "completed"
            await tel.finish(
                session_factory,
                status=_run_status,
                error=log_entry.error_detail if _run_status == "failed" else None,
                sync_log_id=getattr(log_entry, "id", None),
            )


def _resolve_triggered_by(source_id: str | None, triggered_by: str | None) -> str:
    """解析 sync_log.triggered_by 标记。

    显式指定优先(独立执行面的 Admin 手动触发经 CLI 传入,见
    backend/services/sync_executor.py);否则按旧规则 —— 显式 source_id
    视为"手动触发",无参数 cron 调度为"自动"。
    """
    if triggered_by in ("manual", "cron"):
        return triggered_by
    return "manual" if source_id else "cron"


def _inject_recovery_replay(configs: list[SourceConfig]) -> None:
    """阶段⑩ F16:为恢复重放轮注入 connector 上下文标记。

    ``recovery_replay`` 由 GitHubConnector 消费(增量关闭 remote-SHA 短路,
    按 last-success 边界重读 git 历史);其余 connector 忽略。SourceConfig 为
    frozen dataclass → 以 ``dataclasses.replace`` 生成不可变替换;只改本次
    执行的内存配置,不触碰 DB 中的 source config。
    """
    import dataclasses

    for i, cfg in enumerate(configs):
        configs[i] = dataclasses.replace(cfg, config={**cfg.config, "recovery_replay": True})


async def run_sync(
    settings: Settings,
    source_id: str | None = None,
    *,
    dry_run: bool = False,
    reindex: bool = False,
    triggered_by: str | None = None,
    force_replay: bool = False,
    request_id: int | None = None,
    attempt: int = 1,
) -> bool:
    """执行一次完整的同步流程。

    流程:
        1. 创建 Postgres 引擎与异步会话工厂,从 ``data_sources`` 表读 enabled
           配置(Task 7:替代 YAML,配置由管理界面维护)。
        2. 初始化 Weaviate client、BGE Embedder、IngestionPipeline(传入同步
           session_factory 供 ``documents`` 表写入)。
        3. 遍历启用的数据源,调 ``_sync_one`` 逐个同步。
        4. ``finally`` 块释放 Weaviate client 与 Postgres engine。

    同步 / 异步说明(详见模块 docstring):
        Connector 与 IngestionPipeline 均为同步实现,直接在 async 函数中调用。
        仅 ``init_db`` / ``session_factory()`` / ``engine.dispose()`` 使用 await。

    Args:
        settings: 全局配置实例(包含 postgres_dsn / weaviate_url 等)。
        source_id: 仅同步指定数据源 ID;``None`` 同步全部启用源。
        triggered_by: 显式触发方标记("manual"/"cron");``None`` 按旧规则
            由 source_id 推导(独立执行面的手动触发经 CLI 显式传 manual)。
        dry_run: 仅列举抓取的文档数,不灌入向量库 / 不写 SyncLog。
        reindex: 全量**生成重建**(逐源 fetch_all → 新代构建 → 验证 →
            原子激活)。P1 语义:旧"先删 collection 再重灌"已废除,
            重建全程服务不中断(零停机,契约 Gate P1-E)。

    Returns:
        #34:本次运行是否发生传输类失败(GitTransportError)。main 据此以
        退出码 2 结束 runner → 落入 executor 既有 runner_failed 有界重试;
        纯业务失败恒返回 False(退出码 0,契约 §14 不变)。
    """
    engine = get_engine(settings.postgres_dsn)
    weaviate_client: Any | None = None
    had_transport_failure = False
    try:
        host, port = _parse_weaviate_endpoint(settings.weaviate_url)
        weaviate_client = weaviate.connect_to_local(host=host, port=port)

        if reindex and dry_run:
            logger.warning("reindex 在 dry_run 模式下仅列举,不构建(P1:零服务损失重建)")
        elif reindex:
            # P1:--reindex 语义 = 生成重建 + 原子激活(逐源,见 _sync_one)。
            # 旧"先删整个 collection 再重灌"已废除(先删后灌不再是任何权威
            # 重建路径,Gate P1-E);重建全程在服投影分毫不动。
            logger.info(
                "reindex 模式:全量生成重建(旧'先删 collection'已废除;"
                "重建期间服务不中断)"
            )

        if not dry_run:
            await init_db(engine)

        session_factory = get_session_factory(engine)
        marker = _resolve_triggered_by(source_id, triggered_by)
        # The cron executor may wake frequently, but only due sources are
        # eligible.  Manual runs intentionally bypass this source-level gate.
        configs = await _load_configs_from_db(
            session_factory,
            due_only=marker == "cron",
        )
        sync_session_factory = get_sync_session_factory(settings.postgres_dsn)
        try:
            embedder = build_sync_embedder(settings)
        except CpuFallbackError as exc:
            # Keep the failed setup inside the sync process boundary so every
            # source can receive normal failed-run accounting.  This does not
            # retry, restart, or touch the backend online model process.
            logger.error("同步 embedder GPU→CPU fallback 终止: %s", exc)
            embedder = _terminal_sync_embedder(exc)
        pipeline = IngestionPipeline(
            embedder,
            weaviate_client,
            class_name=settings.weaviate_class_name,
            session_factory=sync_session_factory,
            # #45:嵌入字符契约对齐 —— 与内部嵌入端点同源配置,灌入边界
            # 预切超限 chunk,杜绝「文本超长 → 413 → 整文档必败且重试无效」。
            max_chunk_chars=settings.embedder_max_length,
        )
        builder = GenerationBuilder(pipeline, sync_session_factory)

        if force_replay:
            _inject_recovery_replay(configs)
        for cfg in configs:
            if not cfg.enabled:
                logger.info("跳过禁用的数据源 %s", cfg.id)
                continue
            if source_id and cfg.id != source_id:
                continue
            if await _sync_one(
                cfg,
                pipeline,
                session_factory,
                triggered_by=marker,
                dry_run=dry_run,
                reindex=reindex,
                request_id=request_id,
                attempt=attempt,
                recovery_replay=force_replay,
                builder=builder,
            ):
                had_transport_failure = True
    finally:
        # 无论成功 / 失败,都释放 Weaviate client 与 Postgres engine
        if weaviate_client is not None:
            weaviate_client.close()
        await engine.dispose()
    return had_transport_failure


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。

    支持以下选项:
        --source SOURCE_ID  仅同步指定数据源 ID(默认同步全部启用源)
        --dry-run           仅列举抓取的文档数,不写库
        --reindex           删除并重建 Weaviate collection 后全量同步
        --help              显示帮助
    """
    parser = argparse.ArgumentParser(
        prog="sync",
        description="Ask AI 数据源同步脚本(cron 入口)",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="仅同步指定数据源 ID(默认同步全部启用源)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列举抓取的文档数,不灌入向量库,也不写 SyncLog",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="全量生成重建(逐源 fetch_all → 新代构建 → 验证 → 原子激活;"
        "零服务损失;P1 起不再先删 collection)",
    )
    parser.add_argument(
        "--triggered-by",
        choices=["auto", "manual", "cron"],
        default="auto",
        help="sync_log.triggered_by 标记;auto=按旧规则(带 --source 记 manual,"
        "否则 cron)。独立执行面的 Admin 手动触发经此显式标记为 manual。",
    )
    parser.add_argument(
        "--request-id",
        type=int,
        default=None,
        help="⑪+⑫ Wave-0:关联 sync_requests.id(SyncRun.request_id);"
        "cron/CLI 直跑不传 → NULL(合法,非错误)。",
    )
    parser.add_argument(
        "--attempt",
        type=int,
        default=1,
        help="⑪+⑫ Wave-0:本次 runner 启动是第几次 attempt(执行面传入;"
        "首启=1)。仅用于 SyncRun 遥测归属,不影响恢复语义。",
    )
    parser.add_argument(
        "--force-incremental-replay",
        action="store_true",
        help="阶段⑩ 恢复重放:GitHub 增量关闭 remote-SHA 短路,按 last-success"
        " 边界重读 git 历史(仅执行面恢复重试路径使用)。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI 入口:配置日志 → 解析参数 → 加载 Settings → 运行 run_sync。

    #34:退出码契约 —— 传输类失败(GitTransportError)→ 退出码 2,落入
    executor 既有 runner_failed 有界重试(4 次/30/120/600s);纯业务失败
    与完全成功 → 退出码 0(冻结契约 §14:业务失败不进入恢复调度)。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    settings = load_settings()
    transport_failure = asyncio.run(
        run_sync(
            settings,
            source_id=args.source,
            dry_run=args.dry_run,
            reindex=args.reindex,
            triggered_by=None if args.triggered_by == "auto" else args.triggered_by,
            force_replay=args.force_incremental_replay,
            request_id=args.request_id,
            attempt=args.attempt,
        )
    )
    if transport_failure:
        sys.exit(2)


if __name__ == "__main__":
    main()
