"""源可见性纵深守卫(PC-01 / P0_KNOWLEDGE_TRUST_BOUNDARY;rework:fail-closed)。

主防线是 chunk 级 ``channel_visibility``(HybridSearcher 三路检索均已过滤);
本模块提供**第二道防线**:在候选进入 rerank / LLM 上下文之前,按源的最新
``channel_visibility`` 配置复核一次,拦截 chunk 元数据滞后/缺失导致的泄漏
(如迁移未跑完、幽灵 chunk)。

冻结契约(Part 4):AUTHORIZATION FAILURE MUST NOT BECOME AUTHORIZATION BYPASS。

- Known source + explicitly allowed                  → ALLOW
- Known source + explicitly not allowed              → DENY
- Unknown / ghost source(前缀不在权威配置)          → DENY(不得进入生成上下文)
- No authoritative snapshot available                → DENY(不得放行未证实候选)
- Stale valid snapshot exists + refresh failure      → MAY use stale snapshot

语义说明(与 Phase 2A 既有元数据一致,不引入新信任体系):
- 权威数据 = ``data_sources.config.channel_visibility`` 渠道白名单;
- 已知源缺省该键 → 默认公开(``DEFAULT_VISIBILITY``,产品既有语义,保公开知识可用);
- 请求渠道经 admin→widget 访客等价别名映射;``channel=None`` 属未知请求上下文 → DENY;
- 授权失败的总代价 = 该候选被丢弃(下游拒答门兜底):可用性损失,绝不变为授权旁路。
"""

import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from backend.retrieval.search import _visibility_probe_channel

logger = logging.getLogger(__name__)

# 与 connectors/registry.SourceConfig 默认一致:**已知源**未显式配置视为公开。
# 注意只作用于已知源;未知/幽灵前缀一律 DENY(fail-closed)。
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
    """按源配置复核候选可见性的纵深守卫(fail-closed,授权失败 ≠ 授权旁路)。"""

    def __init__(self, loader: VisibilityLoader, ttl: float = 30.0) -> None:
        self._loader = loader
        self._ttl = ttl
        self._snapshot: dict[str, tuple[str, ...]] | None = None
        self._loaded_at = -float("inf")

    async def allows(self, source_id: str, channel: str | None) -> bool:
        """候选 ``source_id`` 是否对该请求渠道可见(授权语义见模块 docstring)。

        Args:
            source_id: 候选 chunk 的 source_id(前缀 = data_sources.id)。
            channel: 原始请求渠道(admin 由别名映射为 widget)。

        Returns:
            True 仅当:已知源 + 渠道在白名单内。其余一律 False。
        """
        probe = _visibility_probe_channel(channel)
        if probe is None:
            # 未知请求上下文:不确定性不得放行。
            return False
        mapping = await self._snapshot_or_stale()
        if mapping is None:
            # Case A:无权威快照可用 → 不得放行未证实候选。
            return False
        visibility = mapping.get(source_id.split("/")[0])
        if visibility is None:
            # Case B:unknown / ghost source → 不得进入生成上下文。
            return False
        return probe in visibility

    async def _snapshot_or_stale(self) -> dict[str, tuple[str, ...]] | None:
        """返回权威快照;刷新失败时沿用陈旧有效快照;从未成功过 → None。"""
        now = time.monotonic()
        if self._snapshot is not None and now - self._loaded_at < self._ttl:
            return self._snapshot
        try:
            self._snapshot = await self._loader()
            self._loaded_at = now
        except Exception as exc:  # noqa: BLE001
            if self._snapshot is None:
                # Case A:从未有权威快照。调用方按 DENY 处理。
                logger.error("visibility 快照加载失败且无陈旧快照,fail-closed:%s", str(exc)[:200])
                return None
            # Stale valid snapshot + refresh failure → MAY use stale snapshot。
            logger.warning("visibility 快照刷新失败,沿用陈旧快照:%s", str(exc)[:200])
        return self._snapshot


def make_db_loader(session_factory: Callable[[], Awaitable[object]]) -> VisibilityLoader:
    """构造从 ``data_sources`` 读全量源可见性配置的 loader。"""

    async def _load() -> dict[str, tuple[str, ...]]:
        from backend.db.models import DataSource

        async with session_factory() as session:  # type: ignore[operator]
            rows = (await session.execute(select(DataSource.id, DataSource.config))).all()
        return {rid: _as_visibility((cfg or {}).get("channel_visibility")) for rid, cfg in rows}

    return _load
