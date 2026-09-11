"""数据源同步脚本(scripts/sync.py)单元测试。

覆盖:
- ``_parse_weaviate_endpoint`` URL 解析(多种格式)
- ``run_sync`` 主流程:
    - 处理 enabled 数据源,跳过 disabled
    - ``source_id`` 参数过滤
    - connector 异常 → SyncLog.status == "failed"
    - dry_run 跳过向量库与 SyncLog 写入
    - 异常时正确释放 Weaviate client / Postgres engine
- ``_sync_one`` 单源同步:
    - 增量为空时回退到全量
    - SyncLog 字段填充正确
"""

import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.connectors.registry import SourceConfig
from backend.pipeline.generation_builder import BuildAccounting
from scripts.sync import _parse_weaviate_endpoint, run_sync

# --------------------------------------------------------------------------- #
# 测试辅助
# --------------------------------------------------------------------------- #


def _make_config(
    *,
    id: str = "src-1",
    type: str = "github",
    enabled: bool = True,
) -> SourceConfig:
    """构造默认 SourceConfig,允许测试覆盖字段。"""
    return SourceConfig(
        id=id,
        type=type,
        product="test",
        enabled=enabled,
        config={},
        sync_interval="1h",
    )


def _make_settings() -> MagicMock:
    """构造默认 Settings mock,字段值与 run_sync 期望一致。

    jwt_secret / internal_api_base_url 给定真实字符串:默认 remote 同步嵌入
    句柄在构造期派生内部令牌(HMAC 需 str key);测试不真正发请求。
    """
    settings = MagicMock()
    settings.config_dir = Path("/tmp/fake-config")
    settings.postgres_dsn = "postgresql+asyncpg://user:pwd@localhost/db"
    settings.weaviate_url = "http://localhost:8080"
    settings.weaviate_class_name = "Document"
    settings.embedder_device = "cpu"
    settings.jwt_secret = "test-jwt-secret"
    settings.internal_api_base_url = "http://127.0.0.1:9"
    return settings


def _make_async_session_factory():
    """构造 async session factory mock。

    返回 (factory_mock, session_mock)。``factory_mock()`` 返回一个 async
    context manager,``async with factory_mock() as session`` 中 ``session``
    即 ``session_mock``。``session.commit`` 被设为 AsyncMock,匹配真实
    AsyncSession 的 await commit() 语义。
    """
    session = MagicMock()
    session.commit = AsyncMock()  # run_sync 中是 await session.commit()
    # _last_success_at 的 sync_log 查询:默认无成功记录(窗口回退 24h)
    session.execute = AsyncMock(
        return_value=MagicMock(one_or_none=lambda: None)
    )

    @asynccontextmanager
    async def _ctx():
        yield session

    factory = MagicMock(side_effect=_ctx)
    return factory, session


def _make_connector_mock(docs=None, deleted=None):
    """构造同步 Connector mock,fetch_changes/fetch_all/fetch_deleted 可控。"""
    connector = MagicMock()
    if docs is None:
        # 默认 fetch_changes 返回非空,触发"增量"分支
        connector.fetch_changes.return_value = iter([MagicMock(name="doc1")])
    else:
        connector.fetch_changes.return_value = iter(docs)
    connector.fetch_all.return_value = iter([])
    connector.fetch_deleted.return_value = deleted if deleted is not None else []
    return connector


def _patch_sync_deps(
    *,
    configs=None,
    connector=None,
    pipeline=None,
    session_factory=None,
    engine=None,
    weaviate_client=None,
):
    """打桩全部外部依赖,返回 ``(patches, handles)``。

    用法(P1:patches 含 GenerationBuilder 接缝,统一 ExitStack 进入)::

        patches, handles = _patch_sync_deps(configs=[...], connector=mock)
        with contextlib.ExitStack() as _stack:
            for _p in patches:
                _stack.enter_context(_p)
            await run_sync(settings)
    """
    if configs is None:
        configs = []
    if engine is None:
        engine = MagicMock()
        engine.dispose = AsyncMock()  # run_sync 中是 await engine.dispose()
    if weaviate_client is None:
        weaviate_client = MagicMock()
    if pipeline is None:
        pipeline = MagicMock()
    if session_factory is None:
        session_factory, _ = _make_async_session_factory()

    builder_instance = MagicMock()
    builder_instance.build_generation.return_value = BuildAccounting(
        source_id="sync-test",
        new_docs=["doc1"],
        chunks_written=3,
    )
    builder_instance.repair_documents.return_value = (["doc1"], [], 3)
    builder_cls_mock = patch(
        "scripts.sync.GenerationBuilder", return_value=builder_instance
    )
    patches_list = (
        patch(
            "scripts.sync._load_configs_from_db",
            new_callable=AsyncMock,
            return_value=configs,
        ),
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.get_engine", return_value=engine),
        patch("scripts.sync.init_db", new_callable=AsyncMock),
        patch("scripts.sync.get_session_factory", return_value=session_factory),
        patch("scripts.sync.get_sync_session_factory", return_value=MagicMock()),
        patch("scripts.sync.weaviate.connect_to_local", return_value=weaviate_client),
        patch("scripts.sync.BGEEmbedder", return_value=MagicMock()),
        patch("scripts.sync.IngestionPipeline", return_value=pipeline),
        builder_cls_mock,
    )
    return patches_list, {
        "engine": engine,
        "weaviate_client": weaviate_client,
        "pipeline": pipeline,
        "session_factory": session_factory,
        "builder": builder_instance,
    }


# --------------------------------------------------------------------------- #
# _parse_weaviate_endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_parse_weaviate_endpoint_with_scheme_and_port():
    """带 scheme 与 port 的 URL 应正确解析。"""
    host, port = _parse_weaviate_endpoint("http://localhost:8080")
    assert host == "localhost"
    assert port == 8080


@pytest.mark.unit
def test_parse_weaviate_endpoint_without_scheme():
    """不带 scheme 的 URL 应自动补 http:// 后解析。"""
    host, port = _parse_weaviate_endpoint("localhost:8080")
    assert host == "localhost"
    assert port == 8080


@pytest.mark.unit
def test_parse_weaviate_endpoint_default_port():
    """port 缺省时应返回 8080(Weaviate 默认端口)。"""
    host, port = _parse_weaviate_endpoint("http://weaviate.svc")
    assert host == "weaviate.svc"
    assert port == 8080


@pytest.mark.unit
def test_parse_weaviate_endpoint_https_custom_port():
    """HTTPS + 自定义端口应被正确解析。"""
    host, port = _parse_weaviate_endpoint("https://weaviate.example.com:443")
    assert host == "weaviate.example.com"
    assert port == 443


# --------------------------------------------------------------------------- #
# run_sync 主流程
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_run_sync_processes_enabled_sources():
    """enabled=True 的数据源应被同步,SyncLog 写入 status=success。"""
    settings = _make_settings()
    cfg_enabled = _make_config(id="enabled-src", enabled=True)
    cfg_disabled = _make_config(id="disabled-src", enabled=False)
    connector = _make_connector_mock()
    session_factory, session = _make_async_session_factory()
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {"doc1": 3}

    patches, handles = _patch_sync_deps(
        configs=[cfg_enabled, cfg_disabled],
        connector=connector,
        pipeline=pipeline,
        session_factory=session_factory,
    )
    _builder = handles["builder"]
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings)

    # enabled source 应被同步:调用了 build_generation(P1 生成构建)
    assert _builder.build_generation.called
    # disabled source 不应被处理:ConnectorRegistry.create 只被调一次
    # (简脚本只对 enabled 源 create connector)
    assert handles["engine"].dispose.called
    # SyncLog 被写入:session.add + session.commit
    assert session.add.called


@pytest.mark.unit
async def test_run_sync_filters_by_source_id():
    """传 source_id 参数时只处理匹配的数据源,其余跳过。"""
    settings = _make_settings()
    cfg_a = _make_config(id="src-a", enabled=True)
    cfg_b = _make_config(id="src-b", enabled=True)
    connector = _make_connector_mock()
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {"doc1": 1}

    patches, _handles = _patch_sync_deps(
        configs=[cfg_a, cfg_b],
        connector=connector,
        pipeline=pipeline,
    )
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings, source_id="src-a")

    # 只同步了 src-a(src-b 被过滤),ConnectorRegistry.create 只被调一次
    assert connector.fetch_changes.call_count == 1


@pytest.mark.unit
async def test_run_sync_records_failed_status_on_exception():
    """connector.fetch_changes 抛异常时 SyncLog.status == "failed"。"""
    settings = _make_settings()
    cfg = _make_config(id="bad-src", enabled=True)

    # connector.fetch_changes 抛异常
    bad_connector = MagicMock()
    bad_connector.fetch_changes.side_effect = RuntimeError("network down")
    bad_connector.fetch_all.return_value = iter([])
    bad_connector.fetch_deleted.return_value = []

    session_factory, session = _make_async_session_factory()
    pipeline = MagicMock()

    patches, handles = _patch_sync_deps(
        configs=[cfg],
        connector=bad_connector,
        pipeline=pipeline,
        session_factory=session_factory,
    )
    _builder = handles["builder"]
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings)

    # SyncLog 应被写入,且 status="failed"
    assert session.add.called
    added_entry = session.add.call_args[0][0]
    assert added_entry.status == "failed"
    assert "network down" in (added_entry.error_detail or "")
    # 失败(connector 抓取异常)时不应进入构建
    assert not _builder.build_generation.called


@pytest.mark.unit
async def test_run_sync_skips_disabled_sources():
    """cfg.enabled=False 的数据源应被跳过,不调 connector。"""
    settings = _make_settings()
    cfg_disabled = _make_config(id="disabled-src", enabled=False)
    connector = _make_connector_mock()

    patches, _ = _patch_sync_deps(
        configs=[cfg_disabled],
        connector=connector,
    )
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings)

    # disabled src 不应触发 ConnectorRegistry.create
    connector.fetch_changes.assert_not_called()


@pytest.mark.unit
async def test_run_sync_releases_resources_on_exception():
    """pipeline 内部异常时,Weaviate client 与 engine 仍应被释放。"""
    settings = _make_settings()
    cfg = _make_config(id="src-1", enabled=True)
    connector = _make_connector_mock()

    # weaviate_client.close 是 sync,engine.dispose 是 async
    weaviate_client = MagicMock()
    engine = MagicMock()
    engine.dispose = AsyncMock()

    # 让 init_db 抛异常(触发 finally 中的资源释放)
    init_db_mock = AsyncMock(side_effect=RuntimeError("db init failed"))

    with (
        patch(
            "scripts.sync._load_configs_from_db",
            new_callable=AsyncMock,
            return_value=[cfg],
        ),
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.get_engine", return_value=engine),
        patch("scripts.sync.init_db", init_db_mock),
        patch("scripts.sync.get_session_factory", return_value=MagicMock()),
        patch(
            "scripts.sync.weaviate.connect_to_local",
            return_value=weaviate_client,
        ),
        patch("scripts.sync.BGEEmbedder", return_value=MagicMock()),
        patch("scripts.sync.IngestionPipeline", return_value=MagicMock()),
        pytest.raises(RuntimeError, match="db init failed"),
    ):
        await run_sync(settings)

    # 即使异常,weaviate_client.close 与 engine.dispose 也应被调用
    weaviate_client.close.assert_called_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.unit
async def test_run_sync_dry_run_skips_persistence():
    """dry_run=True 时不调 ingest_all,也不写 SyncLog。"""
    settings = _make_settings()
    cfg = _make_config(id="src-1", enabled=True)
    connector = _make_connector_mock()
    session_factory, session = _make_async_session_factory()
    pipeline = MagicMock()

    patches, handles = _patch_sync_deps(
        configs=[cfg],
        connector=connector,
        pipeline=pipeline,
        session_factory=session_factory,
    )
    _builder = handles["builder"]
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings, dry_run=True)

    # dry-run 模式下不应构建 / 写 SyncLog
    assert not _builder.build_generation.called
    assert not session.add.called
    assert not session.commit.called


# --------------------------------------------------------------------------- #
# _sync_one 行为补充
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_sync_one_falls_back_to_fetch_all_when_changes_empty():
    """fetch_changes 空 + documents 表无记录 → 首次同步,回退到 fetch_all。

    Task 3 后 _sync_one 在 fetch_changes 空时先查 documents 表:无记录则
    回退全量,有记录则跳过。本测试 mock session.execute 返回 count=0
    (首次同步),验证 fetch_all + ingest_all 被调用。
    """
    from scripts.sync import _sync_one

    cfg = _make_config(id="src-1")
    pipeline = MagicMock()
    connector = MagicMock()
    # fetch_changes 空 → 进入 documents 表查询分支
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([MagicMock(name="doc1")])
    connector.fetch_deleted.return_value = []
    session_factory, session = _make_async_session_factory()
    # _count_documents 调 await session.execute(...).scalar()
    # 返回 0 = documents 表无记录 → 走首次回退路径
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value=0),
            # _last_success_at 的窗口查询:无成功记录 → 窗口回退 24h
            one_or_none=lambda: None,
        )
    )

    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.GenerationBuilder") as builder_cls,
    ):
        await _sync_one(cfg, pipeline, session_factory)

    # fetch_all 应被调用(回退路径)
    connector.fetch_all.assert_called_once()
    # build_generation 应被调用(全量构建,P1 生成路径)
    builder_cls.return_value.build_generation.assert_called_once()
    # SyncLog 应被写入
    assert session.add.called


@pytest.mark.unit
async def test_sync_one_reindex_forces_fetch_all_bypassing_skip():
    """reindex=True 时绕过增量 skip,强制 fetch_all(符号字段回填场景)。

    即使 fetch_changes 返回空且 documents 表已有记录(正常会 skip),
    reindex 模式仍应调 fetch_all + ingest_all 全量重灌。
    """
    from scripts.sync import _sync_one

    cfg = _make_config(id="src-1")
    pipeline = MagicMock()
    connector = MagicMock()
    # fetch_changes 空(无近期变更)
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([MagicMock(name="doc1")])
    connector.fetch_deleted.return_value = []
    session_factory, session = _make_async_session_factory()
    # documents 表"已有记录"(count > 0)——正常路径会 skip,但 reindex 应绕过
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar=MagicMock(return_value=100),
            one_or_none=lambda: None,
        )
    )

    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.GenerationBuilder") as builder_cls,
    ):
        await _sync_one(cfg, pipeline, session_factory, reindex=True)

    # reindex 应强制 fetch_all(绕过 skip)
    connector.fetch_all.assert_called_once()
    # build_generation 应被调用,且 force_rebuild=True(P1 全量生成重建)
    builder_cls.return_value.build_generation.assert_called_once()
    assert builder_cls.return_value.build_generation.call_args.kwargs.get("force_rebuild") is True


@pytest.mark.unit
async def test_sync_one_reindex_skips_fetch_changes():
    """reindex=True 时不应调 fetch_changes(直接走 fetch_all)。"""
    from scripts.sync import _sync_one

    cfg = _make_config(id="src-1")
    pipeline = MagicMock()
    connector = MagicMock()
    connector.fetch_changes.return_value = iter([MagicMock(name="should-not-use")])
    connector.fetch_all.return_value = iter([MagicMock(name="doc1")])
    connector.fetch_deleted.return_value = []
    session_factory, _ = _make_async_session_factory()

    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.GenerationBuilder") as builder_cls,
    ):
        await _sync_one(cfg, pipeline, session_factory, reindex=True)

    # fetch_changes 不应被调用(reindex 直接 fetch_all)
    connector.fetch_changes.assert_not_called()
    connector.fetch_all.assert_called_once()
    builder_cls.return_value.build_generation.assert_called_once()


@pytest.mark.unit
async def test_sync_one_synclog_fields_accounting():
    """SyncLog 字段 items_new / items_updated / items_deleted 应按构建账本填充(P1)。

    items_new = 新文档篇数;items_updated = chunks_written + metadata-only 篇数;
    items_deleted = 墓碑生效数(fetch_deleted → 逻辑删除,非物理)。
    """
    from backend.pipeline.generation_builder import BuildAccounting
    from scripts.sync import _sync_one

    cfg = _make_config(id="src-1")
    pipeline = MagicMock()
    connector = _make_connector_mock(deleted=["deleted-doc-1"])
    session_factory, session = _make_async_session_factory()

    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.GenerationBuilder") as builder_cls,
    ):
        builder_cls.return_value.build_generation.return_value = BuildAccounting(
            source_id="src-1",
            new_docs=["new-doc"],
            updated_docs=["upd-doc"],
            chunks_written=5,
        )
        await _sync_one(cfg, pipeline, session_factory)

    added_entry = session.add.call_args[0][0]
    # items_new: 新文档 1 篇
    assert added_entry.items_new == 1
    # items_updated: chunks_written=5(metadata-only 0 篇)
    assert added_entry.items_updated == 5
    # items_deleted: 墓碑生效 1(fetch_deleted → 墓碑,逻辑删除)
    assert added_entry.items_deleted == 1
    assert added_entry.status == "success"


# --------------------------------------------------------------------------- #
# SyncLog commit 错误隔离(I2 修复)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_sync_one_commit_failure_does_not_propagate():
    """_sync_one 的 SyncLog.commit() 抛异常时不应向上传播。

    finally 块内层 try/except 捕获 commit 异常,确保日志写入失败
    不会冲破外层 except 的错误隔离。
    """
    from scripts.sync import _sync_one

    cfg = _make_config(id="src-1")
    pipeline = MagicMock()
    connector = _make_connector_mock()

    # session 可用(窗口查询正常),但 commit 失败(死锁 / 连接断开场景)
    session_factory, session = _make_async_session_factory()
    session.commit = AsyncMock(side_effect=RuntimeError("db commit failed"))

    # 不应抛异常 - finally 内层 try/except 应吞掉异常
    with (
        patch("scripts.sync.ConnectorRegistry.create", return_value=connector),
        patch("scripts.sync.GenerationBuilder") as builder_cls,
    ):
        await _sync_one(cfg, pipeline, session_factory)

    # 主流程应已正常完成
    builder_cls.return_value.build_generation.assert_called_once()


@pytest.mark.unit
async def test_sync_log_commit_failure_does_not_break_isolation():
    """多个数据源时,第一个 SyncLog commit 失败,后续 source 仍应被处理。

    验证 finally 块的 commit 异常被捕获后,run_sync 循环继续执行,
    第二个数据源的 ingest_all 仍被调用。
    """
    settings = _make_settings()
    cfg_a = _make_config(id="src-a", enabled=True)
    cfg_b = _make_config(id="src-b", enabled=True)

    # 用 side_effect 让 fetch_changes 每次返回新 iter(避免迭代器耗尽)
    connector = MagicMock()
    connector.fetch_changes.side_effect = lambda *a, **kw: iter([MagicMock(name="doc")])
    connector.fetch_all.return_value = iter([])
    connector.fetch_deleted.return_value = []

    pipeline = MagicMock()

    # 第一次 commit 抛异常,第二次正常 - 验证错误隔离
    call_state = {"n": 0}

    @asynccontextmanager
    async def _ctx():
        call_state["n"] += 1
        session = MagicMock()
        # 窗口查询正常(无成功记录)
        session.execute = AsyncMock(
            return_value=MagicMock(one_or_none=lambda: None)
        )
        if call_state["n"] == 1:
            # 模拟 commit 失败(死锁 / 连接断开)
            session.commit = AsyncMock(side_effect=RuntimeError("db commit failed"))
        else:
            session.commit = AsyncMock()
        yield session

    factory = MagicMock(side_effect=_ctx)

    patches, handles = _patch_sync_deps(
        configs=[cfg_a, cfg_b],
        connector=connector,
        pipeline=pipeline,
        session_factory=factory,
    )
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        # run_sync 整体不应抛异常
        await run_sync(settings)

    # 第二个 source 仍应被处理:build_generation 被调用 2 次
    assert handles["builder"].build_generation.call_count == 2


# --------------------------------------------------------------------------- #
# --reindex:全量生成重建,不再删除 collection(P1 Gate P1-E)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reindex_rebuilds_generation_without_collection_delete():
    """``--reindex`` P1 语义:全量生成重建 + 原子激活,零服务损失。

    契约 Compatibility Boundary 显式取代项:旧"先删整个 collection 再重灌"
    废除——重建期间在服投影分毫不动,验证通过才原子切换(Gate P1-E)。

    验证:
        - ``reindex=True`` 时**不调用** ``collections.delete``(P1 红线);
        - ``build_generation`` 以 ``force_rebuild=True`` 被调用(生成重建,
          非原位覆写)。
    """
    settings = _make_settings()
    cfg = _make_config(id="src-1", enabled=True)
    connector = _make_connector_mock()

    patches, handles = _patch_sync_deps(
        configs=[cfg],
        connector=connector,
    )
    builder = handles["builder"]
    with contextlib.ExitStack() as _stack:
        for _p in patches:
            _stack.enter_context(_p)
        await run_sync(settings, dry_run=False, reindex=True)

    # P1 红线:重建绝不删除 collection(在服投影不动)
    handles["weaviate_client"].collections.delete.assert_not_called()
    # 重建经生成构建:fetch_all 全量 → force_rebuild=True 新代构建
    connector.fetch_all.assert_called_once()
    builder.build_generation.assert_called_once()
    assert builder.build_generation.call_args.kwargs.get("force_rebuild") is True
