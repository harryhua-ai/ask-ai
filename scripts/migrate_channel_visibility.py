"""channel_visibility 存量回填(P0 PC-01 / AC-07)。

背景:信任边界 = chunk 级 ``channel_visibility``(HybridSearcher 三路检索过滤)
+ SourceVisibilityGuard(源配置纵深)。Phase 2A 之前入库的 chunk 缺失该属性
(读取按默认公开解释),且内部源的 config 从未显式标记受限 → 存量索引把内部
内容当公开。本脚本把每个 chunk 的 ``channel_visibility`` 按**当前源配置**回填:

- target = ``data_sources.config.channel_visibility``,缺失该键 → 默认公开
  ``["widget", "api"]``(零回归);
- 语义等价(缺失属性 ≡ 默认公开)时跳过,不产生无谓写;
- 内部源标记方式:先给源 config 设 ``channel_visibility: ["internal"]``(管理端
  PATCH /api/admin/data-sources/{id} 的 config 字段即可),再跑本脚本 ``--apply``;
- 幽灵 chunk(前缀不在 data_sources 中)不动,单列 reported 供人工裁决;
- 幂等:重复运行安全;只写属性,不重嵌入。

用法(在 backend 容器/带 .env 的环境执行):
    python scripts/migrate_channel_visibility.py            # dry-run,只打印计划
    python scripts/migrate_channel_visibility.py --apply    # 执行写入
    python scripts/migrate_channel_visibility.py --source knowledge-support --apply
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_VISIBILITY = ["widget", "api"]


def _norm(value: object) -> list[str]:
    """任意形态(list/tuple/str/None)→ 规范 list,缺失按默认公开。"""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, str) and value:
        return [value]
    return list(DEFAULT_VISIBILITY)


def compute_changes(
    records: Iterable[tuple[str, object]],
    source_map: dict[str, object],
    only_sources: set[str] | None = None,
) -> tuple[list[tuple[str, list[str]]], list[str], list[str]]:
    """规划需要回填的对象。

    Args:
        records: ``(source_id, weaviate channel_visibility 属性或 None)`` 列表。
        source_map: ``{data_sources.id: config dict 或 channel_visibility list}``。
        only_sources: 仅规划这些源前缀(None = 全部)。

    Returns:
        ``(changes, skipped, unknown)``:
        changes = ``[(source_id, target_list)]``;skipped = 语义相等不写;
        unknown = 前缀不在 source_map(幽灵 chunk)。
    """
    changes: list[tuple[str, list[str]]] = []
    skipped: list[str] = []
    unknown: list[str] = []
    mismatch: set[str] = set()
    seen: dict[str, None] = {}  # 有序去重(py3.7+ dict 保序)
    for source_id, current in records:
        prefix = source_id.split("/")[0]
        if only_sources is not None and prefix not in only_sources:
            continue
        raw = source_map.get(prefix)
        if raw is None:
            if source_id not in seen:
                unknown.append(source_id)
                seen[source_id] = None
            continue
        cfg = raw.get("channel_visibility") if isinstance(raw, dict) else raw
        target = _norm(cfg)
        if _norm(current) != target:
            mismatch.add(source_id)  # 同一 source_id 多份对象:任一不匹配即需回填
        seen[source_id] = None
    for source_id in seen:
        prefix = source_id.split("/")[0]
        if only_sources is not None and prefix not in only_sources:
            continue
        raw = source_map.get(prefix)
        if raw is None:
            continue
        cfg = raw.get("channel_visibility") if isinstance(raw, dict) else raw
        target = _norm(cfg)
        if source_id in mismatch:
            changes.append((source_id, target))
        else:
            skipped.append(source_id)
    return changes, skipped, unknown


async def _load_source_map() -> dict[str, object]:
    """从 DB 读 {data_sources.id: config}。"""
    from sqlalchemy import select

    from backend.config import load_settings
    from backend.db.models import DataSource
    from backend.db.session import get_engine, get_session_factory

    settings = load_settings(config_dir=Path(__file__).resolve().parent.parent / "config")
    factory = get_session_factory(get_engine(settings.postgres_dsn))
    async with factory() as session:
        rows = (await session.execute(select(DataSource.id, DataSource.config))).all()
    return {rid: cfg or {} for rid, cfg in rows}


def _iter_objects(collection: Any):  # type: ignore[name-defined]
    """全量迭代 (source_id, channel_visibility, uuid)。"""
    for obj in collection.iterator(return_properties=["source_id", "channel_visibility"]):
        yield (
            obj.properties.get("source_id", ""),
            obj.properties.get("channel_visibility"),
            obj.uuid,
        )


async def main() -> int:  # pragma: no cover - IO 编排,核心逻辑已单测
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="执行写入(默认 dry-run)")
    ap.add_argument("--source", action="append", default=[], help="仅处理指定源前缀(可多次)")
    args = ap.parse_args()
    only = set(args.source) or None

    source_map = await _load_source_map()
    print(f"sources in DB: {len(source_map)} -> {sorted(source_map)}", flush=True)

    import weaviate as weaviate_mod

    from backend.config import load_settings
    from backend.main import _parse_weaviate_url

    settings = load_settings(config_dir=Path(__file__).resolve().parent.parent / "config")
    host, port = _parse_weaviate_url(settings.weaviate_url)
    client = weaviate_mod.connect_to_local(host=host, port=port)
    collection = client.collections.get(settings.weaviate_class_name)

    records = list(_iter_objects(collection))
    changes, skipped, unknown = compute_changes(
        [(sid, vis) for sid, vis, _ in records], source_map, only
    )
    # 同一 source_id 可能存在多份对象(重复入库的存量数据):全部 uuid 都要更新
    uuids_by_sid: dict[str, list[Any]] = {}
    for sid, _, uuid in records:
        uuids_by_sid.setdefault(sid, []).append(uuid)

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "scanned": len(records),
                "to_update": len(changes),
                "semantically_equal_skipped": len(skipped),
                "unknown_prefix": len(unknown),
                "unknown_sample": unknown[:10],
                "plan_sample": changes[:10],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    if args.apply:
        done = 0
        for sid, target in changes:
            for uuid in uuids_by_sid.get(sid, []):
                collection.data.update(uuid=uuid, properties={"channel_visibility": target})
                done += 1
            if done % 500 < len(uuids_by_sid.get(sid, [])):
                print(f"  updated ~{done}/{sum(len(v) for v in uuids_by_sid.values())}", flush=True)
        print(f"APPLIED: {done} object updates", flush=True)
    else:
        print("DRY-RUN: 未写入。确认后加 --apply。", flush=True)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
