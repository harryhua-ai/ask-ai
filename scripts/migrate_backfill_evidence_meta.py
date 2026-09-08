"""INC-2a 证据语义元数据确定性回填(只写属性,不重嵌入,向量零触碰)。

冻结契约(§8/§9/§12/§16):
- 确定性:每个 chunk 的新语义只由其**自身持久化的** ``source_type`` 与
  ``channel_visibility`` 经 ``backend.evidence_meta.derive_evidence_meta``
  推导——与摄取路径同一纯函数,零漂移;相同存储输入恒等输出。
- 幂等:第二次运行 changes=0(dry-run/apply 均可重复)。
- 有界:只写 5 个 evidence_* 属性;绝不改 text、绝不传 vector、绝不删对象。
- 幽灵/孤儿(source 前缀不在 data_sources)**只上报,不写**(与
  migrate_channel_visibility 幽灵处置一致)。
- 可度量:total/eligible/changed/unchanged/unknown_unclassifiable/orphans/
  failures 全量计数,并按源前缀与语义值分布输出。

用法(非生产环境;生产回填需单独授权):
    python scripts/migrate_backfill_evidence_meta.py            # dry-run
    python scripts/migrate_backfill_evidence_meta.py --apply    # 执行写入
    python scripts/migrate_backfill_evidence_meta.py --source knowledge-support --apply

环境变量(与 scripts/sync.py 一致):
    WEAVIATE_URL / WEAVIATE_CLASS_NAME;PG DSN 走 backend config,
    用于加载 data_sources.id 权威集合判孤儿(DB 不可用时降级跳过孤儿判定)。
"""

import argparse
import asyncio
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.evidence_meta import (  # noqa: E402
    EVIDENCE_PROPERTIES,
    PROP_AUTHORITY,
    PROP_CITATION,
    PROP_ORIGIN,
    PROP_SENSITIVITY,
    PROP_TEMPORALITY,
    derive_evidence_meta,
)
from scripts.migrate_add_evidence_meta_props import (  # noqa: E402
    _parse_weaviate_endpoint,
    ensure_evidence_props,
)

logger = logging.getLogger(__name__)


@dataclass
class BackfillCounters:
    """契约 §8 要求的最小可度量集合 + 语义值分布。"""

    total_inspected: int = 0
    eligible: int = 0
    changed: int = 0
    unchanged: int = 0
    unknown_unclassifiable: int = 0
    orphans: int = 0
    failures: int = 0
    authority_hist: Counter = field(default_factory=Counter)
    sensitivity_hist: Counter = field(default_factory=Counter)
    citation_hist: Counter = field(default_factory=Counter)
    changed_by_source: Counter = field(default_factory=Counter)


def plan_object(record: dict[str, Any]) -> dict[str, str]:
    """单对象确定性规划:存量持久化事实 → 目标 evidence 属性集。

    与摄取路径 ``_build_props`` 的 ``_evidence_props`` 使用同一纯函数
    :func:`backend.evidence_meta.derive_evidence_meta`,输入同为对象自身
    持久化的 source_type/channel_visibility——两条写路径构造上零漂移。
    """
    meta = derive_evidence_meta(record.get("source_type", ""), record.get("channel_visibility"))
    return {
        PROP_AUTHORITY: meta.authority_class,
        PROP_TEMPORALITY: meta.temporality,
        PROP_SENSITIVITY: meta.sensitivity,
        PROP_CITATION: meta.citation_eligibility,
        PROP_ORIGIN: meta.origin,
    }


def plan_backfill(
    records: Iterator[dict[str, Any]],
    known_source_ids: "set[str] | frozenset[str] | None",
) -> "tuple[BackfillCounters, list[tuple[str, dict[str, str]]]]":
    """纯核心:全量规划回填变更(IO 无关,可直接单测)。

    Args:
        records: 对象属性快照序列(含 uuid/source_id/source_type/
            channel_visibility 及现有 evidence_* 值,可缺)。
        known_source_ids: 权威 ``data_sources.id`` 集合;None 表示跳过孤儿
            判定(DB 不可用降级,孤儿计 0)。

    Returns:
        (计数器, 变更列表 ``[(uuid, 目标属性)]``)。语义已相等的对象不产生
        变更(幂等);孤儿只计数不进变更。
    """
    counters = BackfillCounters()
    changes: list[tuple[str, dict[str, str]]] = []
    for rec in records:
        counters.total_inspected += 1
        source_id = rec.get("source_id", "")
        prefix = source_id.split("/")[0] if source_id else ""
        if known_source_ids is not None and prefix not in known_source_ids:
            counters.orphans += 1
            continue
        counters.eligible += 1
        try:
            target = plan_object(rec)
        except Exception:  # noqa: BLE001 - 单对象规划失败不中断整体
            counters.failures += 1
            continue
        counters.authority_hist[target[PROP_AUTHORITY]] += 1
        counters.sensitivity_hist[target[PROP_SENSITIVITY]] += 1
        counters.citation_hist[target[PROP_CITATION]] += 1
        # 修订 SAFETY-01:citation 严格镜像组合语义恒有值,
        # "不可分类"判据 = 两个安全维度(authority+sensitivity)双 unknown
        if target[PROP_AUTHORITY] == "unknown" and target[PROP_SENSITIVITY] == "unknown":
            counters.unknown_unclassifiable += 1
        current = {k: rec.get(k) for k in EVIDENCE_PROPERTIES}
        if current != target:
            counters.changed += 1
            counters.changed_by_source[prefix] += 1
            changes.append((rec["uuid"], target))
        else:
            counters.unchanged += 1
    return counters, changes


def _iter_records(collection: Any, only_sources: set[str] | None) -> Iterator[dict[str, Any]]:
    """全量迭代对象属性快照(只读;含 evidence_* 现值以判 unchanged)。"""
    props = ["source_id", "source_type", "channel_visibility", *EVIDENCE_PROPERTIES]
    for obj in collection.iterator(return_properties=props):
        properties = obj.properties or {}
        source_id = properties.get("source_id", "")
        if only_sources and source_id.split("/")[0] not in only_sources:
            continue
        yield {"uuid": str(obj.uuid), **properties}


def _load_known_source_ids() -> frozenset[str] | None:
    """从 PG 加载权威 data_sources.id 集合;DB 不可用 → None(降级跳过孤儿判定)。"""
    try:
        from sqlalchemy import select

        from backend.config import load_settings
        from backend.db.models import DataSource
        from backend.db.session import get_engine, get_session_factory

        settings = load_settings(config_dir=Path(__file__).resolve().parent.parent / "config")
        factory = get_session_factory(get_engine(settings.postgres_dsn))

        async def _load() -> frozenset[str]:
            async with factory() as session:
                rows = (await session.execute(select(DataSource.id))).all()
            return frozenset(r[0] for r in rows)

        return asyncio.run(_load())
    except Exception as exc:  # noqa: BLE001 - DB 不可用降级,不阻塞回填
        logger.warning("data_sources 加载失败,孤儿判定降级跳过:%s", str(exc)[:200])
        return None


def _report(counters: BackfillCounters, apply_mode: bool) -> None:
    logger.info("total_inspected=%d", counters.total_inspected)
    logger.info(
        "eligible=%d  orphan(前缀不在 data_sources,只上报不写)=%d",
        counters.eligible,
        counters.orphans,
    )
    logger.info(
        "changed=%d  unchanged=%d  failures=%d",
        counters.changed,
        counters.unchanged,
        counters.failures,
    )
    logger.info("unknown_unclassifiable(三维度全 unknown)=%d", counters.unknown_unclassifiable)
    logger.info("authority 分布: %s", dict(counters.authority_hist))
    logger.info("sensitivity 分布: %s", dict(counters.sensitivity_hist))
    logger.info("citation 分布: %s", dict(counters.citation_hist))
    logger.info("changed by source(top10): %s", counters.changed_by_source.most_common(10))
    if not apply_mode:
        logger.info("DRY-RUN:未写入任何对象。加 --apply 执行写入。")


def apply_changes(
    collection: Any,
    changes: "list[tuple[str, dict[str, str]]]",
    counters: BackfillCounters,
    progress_every: int = 2000,
) -> int:
    """执行写集:逐对象 update 式属性写(可测;main 在 --apply 下唯一调用)。

    只写 evidence_* 属性;不传 vector / 不改 text → 向量与正文零触碰(§8)。
    单对象失败计数不中断;返回成功写入数。
    """
    written = 0
    for uuid, target in changes:
        try:
            collection.data.update(uuid=uuid, properties=target)
            written += 1
            if progress_every and written % progress_every == 0:
                logger.info("已写入 %d/%d", written, len(changes))
        except Exception as exc:  # noqa: BLE001 - 单对象写失败计数不中断
            counters.failures += 1
            logger.warning("update 失败 uuid=%s: %s", uuid, str(exc)[:160])
    logger.info("APPLY 完成:写入 %d/%d(幂等,可重复运行)", written, len(changes))
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="INC-2a 证据语义确定性回填")
    parser.add_argument("--apply", action="store_true", help="执行写入(默认 dry-run)")
    parser.add_argument("--source", action="append", default=[], help="仅回填这些源前缀(可多次)")
    args = parser.parse_args()

    weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
    class_name = os.environ.get("WEAVIATE_CLASS_NAME", "Document")
    host, port = _parse_weaviate_endpoint(weaviate_url)

    import weaviate

    client = weaviate.connect_to_local(host=host, port=port)
    try:
        if not client.collections.exists(class_name):
            logger.error("collection %s 不存在,先运行 sync.py 创建", class_name)
            return 1
        col = client.collections.get(class_name)
        added = ensure_evidence_props(col)
        if added:
            logger.info("补齐缺失 property:%s", added)

        known = _load_known_source_ids()
        only_sources = set(args.source) or None
        counters, changes = plan_backfill(_iter_records(col, only_sources), known)
        _report(counters, args.apply)
        if not args.apply:
            return 0
        apply_changes(col, changes, counters)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
