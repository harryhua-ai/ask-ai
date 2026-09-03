"""数据源同步脚本(cron 入口)。

串联所有 RAG 组件,完成一次完整的数据源 → 向量库同步流程:
    配置加载 → Connector 实例化 → fetch_changes/fetch_all →
    IngestionPipeline.ingest_all → fetch_deleted → delete_document →
    SyncLog 写入 Postgres。

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
    --reindex           删除并重建 collection 后全量重灌
    --triggered-by      sync_log 触发方标记(auto/manual/cron;
                        独立执行面的 Admin 手动触发显式传 manual)
    --help              显示帮助

- **URL 解析**:用 ``urllib.parse.urlparse`` 替代 brief 中 ``split("//")``
  的脆弱写法,统一处理带/不带 scheme 的 URL。
"""

import argparse
import asyncio
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
from backend.connectors.db_adapter import to_source_config
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.db.models import DataSource, Document, SyncLog
from backend.db.session import (
    get_engine,
    get_session_factory,
    get_sync_session_factory,
    init_db,
)
from backend.embedder.bge import BGEEmbedder
from backend.pipeline.ingest import IngestionPipeline
from backend.services.source_lifecycle import sync_eligible_condition
from backend.services.sync_runs import (
    STAGE_CHUNK,
    STAGE_CONSISTENCY,
    STAGE_DONE,
    STAGE_EMBED,
    STAGE_FETCH,
    STAGE_INDEX,
    STAGE_PARSE,
    STAGE_SAFETY_FILTER,
)
from backend.services.vector_consistency import verify_source_vectors

logger = logging.getLogger(__name__)


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


async def _load_configs_from_db(session_factory: Any) -> list[SourceConfig]:
    """从 ``data_sources`` 表读 enabled 配置,转 SourceConfig。

    替代 Task 7 之前从 YAML 加载的逻辑:数据源配置现在持久化在 Postgres
    ``data_sources`` 表(由管理界面 / API 维护),同步脚本直接读 DB。

    Args:
        session_factory: 异步 SQLAlchemy 会话工厂(``async_sessionmaker``)。

    Returns:
        按 ``id`` 升序排列的 :class:`SourceConfig` 列表(仅含 enabled=True)。
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
    return [to_source_config(ds) for ds in rows]


async def _count_documents(session_factory: Any, source_id_prefix: str) -> int:
    """统计 documents 表中某数据源的已有记录数(判断首次 vs 无变更)。

    用 ``source_id LIKE '<id>/%'`` 前缀匹配(source_id 格式为
    ``{cfg.id}/{branch}/{rel}``)。

    Args:
        session_factory: 异步 SQLAlchemy 会话工厂。
        source_id_prefix: 数据源 ID(如 ``"ne301-local"``)。

    Returns:
        该数据源在 documents 表的行数。
    """
    async with session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.source_id.like(f"{source_id_prefix}/%"))
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
    if dry_run:
        # dry-run 原语义:无变更时也只列举,不做任何校验/写库副作用
        log_entry.items_new = 0
        log_entry.items_unchanged = existing
        log_entry.finished_at = datetime.now(UTC)
        log_entry.duration_ms = int((time.monotonic() - start) * 1000)
        return
    report = await verify_source_vectors(session_factory, pipeline, source_id)
    if telemetry is not None:
        await telemetry.progress(session_factory, STAGE_CONSISTENCY, None, None)
        await telemetry.consistency(session_factory, _consistency_facts(report))
    if report.is_healthy:
        logger.info("数据源 %s 无变更,跳过(documents 已有 %d)", source_id, existing)
        log_entry.items_new = 0
        log_entry.items_updated = 0
        log_entry.items_unchanged = existing
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
        if report.refill_source_ids:
            refill_set = set(report.refill_source_ids)
            docs = [d for d in connector.fetch_all() if d.source_id in refill_set]
            results = pipeline.ingest_all(docs)  # 写失败仍 raise → 走外层 except 记 failed
            items_updated = sum(results.values())
            gap_parts.append(
                f"需重灌 {refill_n} 篇(整篇缺失 {missing_n} + chunk 不一致 {mismatch_n});"
                f"多余 chunk {report.stale_chunk_count} 个(已由 ingest 清理)"
            )
        retired = repaired = unresolved = 0
        chunk_totals = {"retired_chunks": 0, "repaired_chunks": 0}
        if report.orphan_chunks:
            try:
                retired, repaired, unresolved = _reconcile_orphan_vectors(
                    source_id, connector, pipeline, report, chunk_totals=chunk_totals
                )
            except Exception as exc:  # noqa: BLE001 - reconciliation 失败绝不删除
                logger.error(
                    "数据源 %s 孤儿 reconciliation 失败(全部保留): %s",
                    source_id,
                    str(exc)[:200],
                )
                unresolved = report.orphan_count
        if report.orphan_chunks or retired or repaired or unresolved:
            gap_parts.append(
                f"孤儿处置:EXTRA_CONFIRMED_RETIRED={retired}(精确删除),"
                f"账本重建={repaired}(零 embedding),"
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
                    repaired_ledger_rows=repaired,
                ),
            )
        if report2.is_healthy:
            log_entry.status = "success"
            log_entry.items_unchanged = existing
        else:
            log_entry.status = "partial"
        log_entry.items_new = repaired
        log_entry.items_deleted = retired
        log_entry.items_updated = items_updated
        gap_parts.append(
            f"复验:{report2.actual_chunks}/{report2.expected_chunks} chunks,"
            f"MISSING_LEGITIMATE={len(report2.refill_source_ids)},"
            f"EXTRA_UNRESOLVED_ORPHAN={report2.orphan_count}"
        )
        log_entry.error_detail = (
            f"一致性校验发现缺口 {report.actual_chunks}/{report.expected_chunks} chunks;"
            f"{';'.join(gap_parts)}"
        )
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
                    session.add(
                        Document(
                            content_hash=str(content_hash),
                            source_id=sid,
                            source_type=str(props.get("source_type") or ""),
                            product=str(props.get("product") or ""),
                            title=str(props.get("title") or ""),
                            url=str(props.get("url") or ""),
                            branch=str(props.get("branch") or ""),
                            chunk_count=max(indices) + 1,
                        )
                    )
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
) -> None:
    """同步单个数据源:fetch → ingest → delete → 写 SyncLog。

    - 异常被捕获并记录到 SyncLog(status="failed"),**不向上传播**,
      避免一个数据源失败中断整个批次。
    - ``dry_run=True`` 时只列举文档数,不灌入向量库、不写 SyncLog。
    - ``reindex=True`` 时绕过增量 skip 逻辑,强制 ``fetch_all()`` 全量重灌。
      用于 schema 变更 / 符号字段回填等需要重分块的场景。配合 ``run_sync``
      的 collection 删除,所有对象全新 insert(insert_many 批量写,不走
      replace 回退,远程 tunnel 下性能可接受)。
    - ``finally`` 块确保无论成功 / 失败 / 异常都会写 SyncLog(除非 dry_run)。

    Args:
        cfg: 数据源配置(SourceConfig)。
        pipeline: 已初始化的 IngestionPipeline 实例。
        session_factory: 异步 SQLAlchemy 会话工厂(``async_sessionmaker``)。
        triggered_by: SyncLog.triggered_by 字段值,``"cron"`` 或 ``"manual"``。
        dry_run: True 时只列举文档数,不灌入 / 不写 SyncLog。
        reindex: True 时强制全量重灌(绕过增量 skip)。
    """
    start = time.monotonic()
    log_entry = SyncLog(
        source_id=cfg.id,
        source_type=cfg.type,
        status="success",
        triggered_by=triggered_by,
    )
    # Wave-0:attempt 启动即落 SyncRun 运行事实(不等同步结束);dry_run 不落。
    tel = _RunTelemetry()
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
            # reindex 模式:绕过增量 skip,强制全量重灌(符号字段回填 /
            # schema 变更)。collection 已由 run_sync 删除,此处 fetch_all
            # 后全部走 insert_many 批量写,UUID 不冲突。
            logger.info("reindex 模式:数据源 %s 强制全量重灌", cfg.id)
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
                    )
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
        _ingest_seen: dict[str, int] = {}

        def _ingest_progress(stage: str, done: int) -> None:
            # 同步回调(ingest 阻塞事件循环期间无法 await DB):仅缓冲,
            # 批界之后由 _sync_one 统一落笔——语义等价,行为零改变
            _ingest_seen[stage] = done

        results = pipeline.ingest_all(docs, progress=_ingest_progress)
        for _st in (STAGE_SAFETY_FILTER, STAGE_CHUNK, STAGE_EMBED, STAGE_INDEX):
            if _st in _ingest_seen:
                await tel.progress(session_factory, _st, _ingest_seen[_st], _docs_total)
        await tel.counters(session_factory, docs_total=_docs_total, docs_done=len(results))
        deleted = connector.fetch_deleted(since)
        for doc_id in deleted:
            pipeline.delete_document(doc_id)
        # 阶段⑩ W6:retirement 效应安全完成后才推进 crawl 成员快照。
        # 删除循环中途被 kill → 本调用不执行 → 旧快照保留 → 下轮重报同一
        # 差集(重复删除幂等),ghost 不再永久化。无此能力的 connector no-op。
        committer = getattr(connector, "commit_membership_snapshot", None)
        if callable(committer):
            committer()

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

        log_entry.items_new = sum(1 for v in results.values() if v > 0)
        log_entry.items_updated = sum(results.values())
        log_entry.items_deleted = len(deleted)

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

    except Exception as exc:  # noqa: BLE001 - 单源失败不中断批次
        log_entry.status = "failed"
        log_entry.error_detail = str(exc)
        # 失败路径同样尽力留 coverage 痕迹(异常中断时的已抓部分不消失)
        connector_for_stats = locals().get("connector")
        stats = getattr(connector_for_stats, "run_stats", None)
        if isinstance(stats, dict) and stats.get("full"):
            log_entry.error_detail = f"{log_entry.error_detail};{_coverage_line(stats)}"
        log_entry.finished_at = datetime.now(UTC)
        log_entry.duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("同步失败 %s: %s", cfg.id, exc)

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
) -> None:
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
        reindex: 删除并重建 Weaviate collection 后全量同步所有数据源。
            Weaviate v4 不允许修改已有 collection 的 property 类型,故
            schema 变更(如 Task 4 新增的 channel_visibility / doc_section /
            chunk_type)必须通过 ``--reindex`` 触发 collection 重建才能生效。
            ⚠️ 期间服务不可用(零停机迁移为后续工作)。
    """
    engine = get_engine(settings.postgres_dsn)
    weaviate_client: Any | None = None
    try:
        host, port = _parse_weaviate_endpoint(settings.weaviate_url)
        weaviate_client = weaviate.connect_to_local(host=host, port=port)

        if reindex and not dry_run:
            logger.info("reindex 模式:删除 collection %s", settings.weaviate_class_name)
            try:
                weaviate_client.collections.delete(
                    name=settings.weaviate_class_name,
                )
                logger.info(
                    "collection %s 已删除,将由 IngestionPipeline 重建",
                    settings.weaviate_class_name,
                )
            except Exception as exc:  # noqa: BLE001 - collection 不存在时不中断
                logger.warning("删除 collection 失败(可能不存在):%s", exc)
        elif reindex and dry_run:
            logger.warning("reindex 在 dry_run 模式下跳过 collection 删除(避免删后不重灌)")

        if not dry_run:
            await init_db(engine)

        session_factory = get_session_factory(engine)
        configs = await _load_configs_from_db(session_factory)
        sync_session_factory = get_sync_session_factory(settings.postgres_dsn)
        embedder = BGEEmbedder(
            device=settings.embedder_device,
            batch_size=settings.embedder_batch_size,
            max_length=settings.embedder_max_length,
        )
        pipeline = IngestionPipeline(
            embedder,
            weaviate_client,
            class_name=settings.weaviate_class_name,
            session_factory=sync_session_factory,
        )

        marker = _resolve_triggered_by(source_id, triggered_by)
        if force_replay:
            _inject_recovery_replay(configs)
        for cfg in configs:
            if not cfg.enabled:
                logger.info("跳过禁用的数据源 %s", cfg.id)
                continue
            if source_id and cfg.id != source_id:
                continue
            await _sync_one(
                cfg,
                pipeline,
                session_factory,
                triggered_by=marker,
                dry_run=dry_run,
                reindex=reindex,
                request_id=request_id,
                attempt=attempt,
                recovery_replay=force_replay,
            )
    finally:
        # 无论成功 / 失败,都释放 Weaviate client 与 Postgres engine
        if weaviate_client is not None:
            weaviate_client.close()
        await engine.dispose()


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
        help="删除并重建 Weaviate collection 后全量同步所有数据源",
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
    """CLI 入口:配置日志 → 解析参数 → 加载 Settings → 运行 run_sync。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    settings = load_settings()
    asyncio.run(
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


if __name__ == "__main__":
    main()
