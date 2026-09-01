"""源可见性纵深守卫(PC-01 / P0_KNOWLEDGE_TRUST_BOUNDARY)。

主防线是 chunk 级 ``channel_visibility``(HybridSearcher 三路检索均已过滤);
本模块提供**第二道防线**:在候选进入 rerank / LLM 上下文之前,按源的最新
``channel_visibility`` 配置复核一次,拦截 chunk 元数据滞后/缺失导致的泄漏
(如迁移未跑完、幽灵 chunk)。

语义(与 Phase 2A 既有元数据一致,不引入新信任体系):
- 权威数据 = ``data_sources.config.channel_visibility`` 渠道白名单;
- 请求渠道(经 admin→widget 访客等价别名)在白名单内 → 可见;
- 白名单为空或不含探测渠道(如 ``["internal"]``)→ 该源对访客等价请求不可见;
- 前缀不在配置中的源(未知/幽灵 chunk)→ 放行(chunk 级过滤仍是主防线,守卫只做纵深);
- loader 故障 → 沿用最近一次成功快照;从未成功 → 全部放行(fail-open,不拖垮检索)。
"""

import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from backend.retrieval.search import _visibility_probe_channel

logger = logging.getLogger(__name__)

# 与 connectors/registry.SourceConfig 默认一致:未显式配置视为公开。
DEFAULT_VISIBILITY: tuple[str, ...] = ("widget", "api")

VisibilityLoader = Callable[[], Awaitable[dict[str, tuple[str, ...]]]]


def _as_visibility(value: object) -> tuple[str, ...]:
    """config 中的 channel_visibility 值 → 元组;None/非法回退默认公开。"""
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    if isinstance(value, str) and value:
        return (value,)
    return DEFAULT_VISIBILITY


class SourceVisibilityGuard:
    """按源配置复核候选可见性的纵深守卫(TTL 缓存,永不让检索不可用)。"""

    def __init__(self, loader: VisibilityLoader, ttl: float = 30.0) -> None:
        self._loader = loader
        self._ttl = ttl
        self._snapshot: dict[str, tuple[str, ...]] | None = None
        self._loaded_at = -float("inf")

    async def allows(self, source_id: str, channel: str | None) -> bool:
        """候选 ``source_id`` 是否对该请求渠道可见。

        Args:
            source_id: 候选 chunk 的 source_id(前缀 = data_sources.id)。
            channel: 原始请求渠道(admin 由别名映射为 widget)。

        Returns:
            True 表示放行(渠道可见 / 未知源 / 无探测渠道)。
        """
        probe = _visibility_probe_channel(channel)
        if probe is None:
            return True
        mapping = await self._snapshot_or_stale()
        visibility = mapping.get(source_id.split("/")[0])
        if visibility is None:
            return True
        return probe in visibility

    async def _snapshot_or_stale(self) -> dict[str, tuple[str, ...]]:
        now = time.monotonic()
        if self._snapshot is not None and now - self._loaded_at < self._ttl:
            return self._snapshot
        try:
            self._snapshot = await self._loader()
            self._loaded_at = now
        except Exception as exc:  # noqa: BLE001
            if self._snapshot is None:
                logger.warning("visibility 快照加载失败,fail-open:%s", str(exc)[:200])
                return {}
            logger.warning("visibility 快照刷新失败,沿用旧快照:%s", str(exc)[:200])
        return self._snapshot


def make_db_loader(session_factory: Callable[[], Awaitable[object]]) -> VisibilityLoader:
    """构造从 ``data_sources`` 读全量源可见性配置的 loader。"""

    async def _load() -> dict[str, tuple[str, ...]]:
        from backend.db.models import DataSource

        async with session_factory() as session:  # type: ignore[operator]
            rows = (await session.execute(select(DataSource.id, DataSource.config))).all()
        return {rid: _as_visibility((cfg or {}).get("channel_visibility")) for rid, cfg in rows}

    return _load
