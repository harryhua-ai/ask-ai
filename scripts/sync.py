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

import backend.connectors.filesystem  # 触发 @register 装饰器
import backend.connectors.github
import backend.connectors.local_git  # noqa: F401 - 触发 @register 装饰器
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
            select(DataSource).where(DataSource.enabled.is_(True)).order_by(DataSource.id)
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


async def _sync_one(
    cfg: SourceConfig,
    pipeline: IngestionPipeline,
    session_factory: Any,
    *,
    triggered_by: str = "cron",
    dry_run: bool = False,
) -> None:
    """同步单个数据源:fetch → ingest → delete → 写 SyncLog。

    - 异常被捕获并记录到 SyncLog(status="failed"),**不向上传播**,
      避免一个数据源失败中断整个批次。
    - ``dry_run=True`` 时只列举文档数,不灌入向量库、不写 SyncLog。
    - ``finally`` 块确保无论成功 / 失败 / 异常都会写 SyncLog(除非 dry_run)。

    Args:
        cfg: 数据源配置(SourceConfig)。
        pipeline: 已初始化的 IngestionPipeline 实例。
        session_factory: 异步 SQLAlchemy 会话工厂(``async_sessionmaker``)。
        triggered_by: SyncLog.triggered_by 字段值,``"cron"`` 或 ``"manual"``。
        dry_run: True 时只列举文档数,不灌入 / 不写 SyncLog。
    """
    start = time.monotonic()
    log_entry = SyncLog(
        source_id=cfg.id,
        source_type=cfg.type,
        status="success",
        triggered_by=triggered_by,
    )

    try:
        connector = ConnectorRegistry.create(cfg)
        since = datetime.now(UTC) - timedelta(hours=24)

        docs = list(connector.fetch_changes(since))
        if not docs:
            # 区分首次(无 documents 记录)vs 无变更(已有记录)
            existing = await _count_documents(session_factory, cfg.id)
            if existing > 0:
                # 无变更跳过:不回退全量,不灌入,直接记 SyncLog 返回
                logger.info(
                    "数据源 %s 无变更,跳过(documents 已有 %d)", cfg.id, existing
                )
                log_entry.items_new = 0
                log_entry.items_unchanged = existing
                log_entry.finished_at = datetime.now(UTC)
                log_entry.duration_ms = int((time.monotonic() - start) * 1000)
                return
            # 首次同步:documents 表无记录,回退到全量拉取
            logger.info("数据源 %s 首次同步,回退到全量拉取", cfg.id)
            docs = list(connector.fetch_all())

        logger.info("数据源 %s 抓取到 %d 篇文档", cfg.id, len(docs))

        if dry_run:
            # dry-run 模式:不灌入向量库,只统计文档数后返回
            log_entry.items_new = len(docs)
            log_entry.finished_at = datetime.now(UTC)
            log_entry.duration_ms = int((time.monotonic() - start) * 1000)
            return

        results = pipeline.ingest_all(docs)
        deleted = connector.fetch_deleted(since)
        for doc_id in deleted:
            pipeline.delete_document(doc_id)

        log_entry.items_new = sum(1 for v in results.values() if v > 0)
        log_entry.items_updated = sum(results.values())
        log_entry.items_deleted = len(deleted)
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


async def run_sync(
    settings: Settings,
    source_id: str | None = None,
    *,
    dry_run: bool = False,
    reindex: bool = False,
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

        # 显式指定 source_id 视为"手动触发";无参数 cron 调度为"自动"
        triggered_by = "manual" if source_id else "cron"
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
                triggered_by=triggered_by,
                dry_run=dry_run,
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
        )
    )


if __name__ == "__main__":
    main()
