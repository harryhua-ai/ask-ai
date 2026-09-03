"""产品元数据迁移(CamThink V1 Answer Correctness,Issue #5 契约 §4)。

把存量 Weaviate chunk 的 ``product`` 元数据迁移到 taxonomy canonical 值:

- **source-scoped**:只触及 ``source_ids`` 指定的源;候选按 source_id 首段
  **客户端精确匹配**(不做 TEXT 属性分词过滤——P0-A 事故教训);
- **deterministic**:推导走与 ingest 完全相同的
  :meth:`Taxonomy.derive_product` 代码路径,重跑幂等;
- **dry-run first**::func:`plan_migration` 零写入;
- **in-place update**::func:`apply_migration` 只对发生变化的 chunk 调
  ``data.update(properties={"product": new})`` —— 属性级 patch,
  **不触向量、不 re-embed、不重建 collection**(契约 §4 优先方案);
- **无静默丢文档**:报告逐源 old→new 计数,unknown 明确列出并给样本。

生产执行不在本任务授权内(脚本默认 dry-run,见
``scripts/migrate_product_metadata.py``;Gate 顺序见实现报告 §生产验收)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.product_taxonomy import Taxonomy, get_taxonomy

#: unknown 样本列出的 source_id 条数上限(全量计数始终入账)
UNKNOWN_SAMPLE_CAP = 20


@dataclass
class SourceMigrationReport:
    """单源迁移报告(old→new 映射与计数,含 unknown 明细)。"""

    source_id: str
    scanned: int = 0
    changed: int = 0
    unchanged: int = 0
    # old label → {new slug: count}(unknown 也计数)
    mapping: dict[str, dict[str, int]] = field(default_factory=dict)
    unknown_count: int = 0
    unknown_samples: list[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    """迁移总报告。"""

    sources: list[SourceMigrationReport] = field(default_factory=list)
    total_scanned: int = 0
    total_changed: int = 0
    total_unchanged: int = 0
    total_unknown: int = 0


def _matches_scope(source_id: str, source_ids: set[str]) -> bool:
    """source_id 首段(= data_sources.id,连接器 ``{id}/...`` 格式)精确匹配。"""
    return source_id.split("/", 1)[0] in source_ids


def _scan(
    client: Any,
    *,
    class_name: str,
    source_ids: set[str],
    taxonomy: Taxonomy,
) -> tuple[MigrationReport, list[tuple[str, str]]]:
    """遍历候选 chunk,计算 (报告, 待更新列表)。

    迭代用 ``collection.iterator(include_vector=False)``:迁移决策只需
    source_id/product/url 属性,不取向量(与零 re-embed 的写侧语义一致)。
    """
    collection = client.collections.get(class_name)
    per_source: dict[str, SourceMigrationReport] = {
        sid: SourceMigrationReport(source_id=sid) for sid in source_ids
    }
    updates: list[tuple[str, str]] = []

    for obj in collection.iterator(
        include_vector=False,
        return_properties=["source_id", "product", "url"],
    ):
        props = obj.properties or {}
        source_id = str(props.get("source_id", ""))
        if not _matches_scope(source_id, source_ids):
            continue
        old_label = str(props.get("product", ""))
        first = source_id.split("/", 1)[0]
        report = per_source[first]
        report.scanned += 1
        derived = taxonomy.derive_product(old_label, source_id, str(props.get("url", "")))
        new_slug = derived.slug
        bucket = report.mapping.setdefault(old_label, {})
        bucket[new_slug] = bucket.get(new_slug, 0) + 1
        if new_slug == "unknown":
            report.unknown_count += 1
            if len(report.unknown_samples) < UNKNOWN_SAMPLE_CAP:
                report.unknown_samples.append(source_id)
        if new_slug != old_label:
            report.changed += 1
            updates.append((str(obj.uuid), new_slug))
        else:
            report.unchanged += 1

    report = MigrationReport(
        sources=[per_source[sid] for sid in sorted(per_source)],
        total_scanned=sum(r.scanned for r in per_source.values()),
        total_changed=sum(r.changed for r in per_source.values()),
        total_unchanged=sum(r.unchanged for r in per_source.values()),
        total_unknown=sum(r.unknown_count for r in per_source.values()),
    )
    return report, updates


def plan_migration(
    client: Any,
    *,
    class_name: str,
    source_ids: list[str],
    taxonomy: Taxonomy | None = None,
) -> MigrationReport:
    """dry-run:计算迁移计划与报告,零写入。"""
    if taxonomy is None:
        taxonomy = get_taxonomy()
    report, _ = _scan(
        client, class_name=class_name, source_ids=set(source_ids), taxonomy=taxonomy
    )
    return report


def apply_migration(
    client: Any,
    *,
    class_name: str,
    source_ids: list[str],
    taxonomy: Taxonomy | None = None,
    batch_size: int = 200,
) -> MigrationReport:
    """原位迁移:仅更新变化的 ``product`` 属性(不触向量,零 re-embed)。

    幂等:已是 canonical 值的 chunk 不产生写入。
    """
    if taxonomy is None:
        taxonomy = get_taxonomy()
    report, updates = _scan(
        client, class_name=class_name, source_ids=set(source_ids), taxonomy=taxonomy
    )
    collection = client.collections.get(class_name)
    for start in range(0, len(updates), batch_size):
        for uuid, new_slug in updates[start : start + batch_size]:
            collection.data.update(uuid=uuid, properties={"product": new_slug})
    return report


def format_report(report: MigrationReport) -> str:
    """报告 → 人类可读文本(脚本输出用)。"""
    lines = [
        (
            f"scanned={report.total_scanned} changed={report.total_changed} "
            f"unchanged={report.total_unchanged} unknown={report.total_unknown}"
        ),
    ]
    for src in report.sources:
        lines.append(f"[{src.source_id}] scanned={src.scanned} changed={src.changed} "
                     f"unchanged={src.unchanged} unknown={src.unknown_count}")
        for old, dist in sorted(src.mapping.items()):
            dist_text = ", ".join(f"{new}:{count}" for new, count in sorted(dist.items()))
            lines.append(f"  {old} → {dist_text}")
        if src.unknown_samples:
            lines.append("  unknown samples:")
            for sample in src.unknown_samples:
                lines.append(f"    - {sample}")
    return "\n".join(lines)
