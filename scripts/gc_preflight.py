"""GC 残留清理只读预检(Issue #164;AC3)。

对「已删文档残留向量」建立可复核的精确身份账本并裁决:
  - 当前 main(#162)GC 资格语义下, tombstone_days=T 能精确覆盖哪些 UUID;
  - 残留对象中哪些是任何 PG 行都推导不出的 orphan(单列,绝不入清理清单);
  - 目标集合与在服(active/missing_candidate)可推导 UUID 的交集必须为 0;
  - 全局墓碑窗外溢面 fail-closed:doomed 集合超出冻结 allowlist 即拒绝。

红线(本程序自身):
  - **零生产写入**:Weaviate 句柄经只读代理包裹(任何 delete/insert/replace
    调用即刻抛错),PG 仅 SELECT;绝不调用 GC apply。
  - **精确身份**:删除清单只能来自 ``chunk_uuids_for_version`` 确定性推导
    (uuid5),禁止 TEXT Like/prefix/token 命中入清单。
  - ``GCReport.objects_deleted`` 语义=尝试数≠实际删除成功(代码
    ``_delete_version_objects`` 返回 len(uuids) 且忽略 delete_many 结果);
    本预检以只读存在性探针区分「可推导/在场/缺席」,不把尝试数当事实。

用法:
    python scripts/gc_preflight.py --tombstone-days 30 \
        --allowlist-json allowlist.json [--inventory-jsonl inv.jsonl] \
        [--report-json out.json]

allowlist.json = 冻结的已删 source_id 清点(操作前 dry-run 集合冻结的审计
锚;文件含 sha256 自描述)。外溢面:doomed ⊄ allowlist → exit 2(fail-closed)。

离线复用当前 main 实际 GC 资格判断:liveness 模式另跑
``lifecycle_gc.sweep(apply=False)``(A-5 dry-run 默认)并与本地重算对账,
不一致 exit 3(资格语义漂移检测)。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.document_lifecycle import RETIRED_RETENTION_DAYS

logger = logging.getLogger("gc_preflight")

EXIT_OK = 0
EXIT_FAILCLOSED = 2
EXIT_ELIGIBILITY_DRIFT = 3


# --------------------------------------------------------------------------- #
# 只读代理(AC3:dry-run 绝无 Weaviate DELETE / PG 写入 / 重建索引)
# --------------------------------------------------------------------------- #
class NotReadOnly(RuntimeError):
    """只读代理拦截到变更调用(测试与运行期双重防线)。"""


class ReadOnlyCollection:
    """Weaviate collection 只读代理:变更属性一律拦截。"""

    _BLOCKED_PREFIXES = ("delete", "insert", "replace", "update", "purge")

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if any(name.startswith(p) for p in self._BLOCKED_PREFIXES):
            raise NotReadOnly(f"只读预检禁止变更调用: {name}")
        target = getattr(self._inner, name)

        if callable(target):
            def _wrapped(*args, **kwargs):
                return target(*args, **kwargs)

            return _wrapped
        return target


# --------------------------------------------------------------------------- #
# 账本数据结构
# --------------------------------------------------------------------------- #
@dataclass
class PreflightRow:
    """一行 PG 身份输入(与生产表列一一对应;不含任何正文/私有列)。"""

    source_id: str
    lifecycle: str
    deleted_at: datetime | None
    current_version_id: str | None
    retirement_gc_eligible_at: datetime | None


@dataclass
class VersionRow:
    source_id: str
    id: str
    generation_id: str
    generation_ordinal: int
    chunk_count: int


@dataclass
class GenerationRow:
    id: str
    ordinal: int
    status: str
    gc_eligible_at: datetime | None
    purged_at: datetime | None


@dataclass
class LedgerResult:
    tombstone_days: int | None
    now: datetime
    doomed_sources: list[str] = field(default_factory=list)
    spillover_sources: list[str] = field(default_factory=list)
    eligible_generation_ids: list[str] = field(default_factory=list)
    derived_deletable_uuids: list[str] = field(default_factory=list)
    present_uuids: list[str] = field(default_factory=list)
    present_in_target_uuids: list[str] = field(default_factory=list)
    missing_derivable_uuids: list[str] = field(default_factory=list)
    orphan_uuids: list[str] = field(default_factory=list)
    orphan_in_target_uuids: list[str] = field(default_factory=list)
    serving_overlap_uuids: list[str] = field(default_factory=list)
    residual_target_objects: int = 0
    inventory_total: int = 0
    violations: list[str] = field(default_factory=list)

    @property
    def manifest_sha256(self) -> str:
        h = hashlib.sha256()
        for u in sorted(self.derived_deletable_uuids):
            h.update(u.encode())
            h.update(b"\n")
        return h.hexdigest()

    def as_dict(self) -> dict:
        return {
            "tombstone_days": self.tombstone_days,
            "now": self.now.isoformat(),
            "doomed_docs": len(self.doomed_sources),
            "spillover_docs": len(self.spillover_sources),
            "eligible_generations": len(self.eligible_generation_ids),
            "derived_deletable_uuids": len(self.derived_deletable_uuids),
            "present_uuids": len(self.present_uuids),
            "present_in_target_uuids": len(self.present_in_target_uuids),
            "missing_derivable_uuids": len(self.missing_derivable_uuids),
            "orphan_uuids_total": len(self.orphan_uuids),
            "orphan_uuids_in_target": len(self.orphan_in_target_uuids),
            "serving_overlap_uuids": len(self.serving_overlap_uuids),
            "residual_target_objects": self.residual_target_objects,
            "inventory_total": self.inventory_total,
            "conservation": self.residual_target_objects
            == len(self.present_in_target_uuids) + len(self.orphan_in_target_uuids),
            "manifest_sha256": self.manifest_sha256,
            "violations": list(self.violations),
        }


def _parse_ts(raw):
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# 资格判定(镜像 backend/services/lifecycle_gc.sweep 的文档级规则)
# --------------------------------------------------------------------------- #
def doomed_document_rows(
    docs: list[PreflightRow],
    tombstone_days: int | None,
    now: datetime,
) -> tuple[list[str], list[str]]:
    """返回 (doomed_source_ids, spillover_happened_sources)。

    与 sweep 逐条对应:被接替(superseded_at+7d, 此处 deleted_at 兼容列缺省
    时不参与;生产当前无 superseded 行)+ 显式 gc_eligible_at 锚(发现确认
    退休)+ opt-in 墓碑窗(deleted_at+T, 锚行只走自动窗)。
    普通墓碑在 tombstone_days=None 下一律不合格(#162 语义)。
    """
    doomed: list[str] = []
    for d in docs:
        if d.retirement_gc_eligible_at is not None and d.retirement_gc_eligible_at <= now:
            if d.lifecycle in ("deleted", "superseded"):
                doomed.append(d.source_id)
            continue
        if d.lifecycle == "superseded" and d.deleted_at is not None:
            if d.deleted_at <= now - timedelta(days=RETIRED_RETENTION_DAYS):
                doomed.append(d.source_id)
            continue
        if tombstone_days is not None and d.lifecycle == "deleted" and d.deleted_at is not None:
            if d.retirement_gc_eligible_at is not None:
                continue  # 锚行只走自动窗,墓碑窗更短也不得提前
            if d.deleted_at <= now - timedelta(days=tombstone_days):
                doomed.append(d.source_id)
    return doomed


def eligible_generation_rows(gens: list[GenerationRow], now: datetime) -> list[str]:
    return [
        g.id
        for g in gens
        if g.status == "retired"
        and g.gc_eligible_at is not None
        and g.gc_eligible_at <= now
        and g.purged_at is None
    ]


# --------------------------------------------------------------------------- #
# 账本主体
# --------------------------------------------------------------------------- #
def compute_ledger(
    docs: list[PreflightRow],
    versions: list[VersionRow],
    generations: list[GenerationRow],
    inventory: list[tuple[str, str]],
    *,
    tombstone_days: int | None,
    now: datetime,
    allowed_deleted_sources: set[str] | None,
) -> LedgerResult:
    """构造精确差异账本(inventory = [(uuid, source_id), ...] 只读清单)。

    allowlist 语义:doomed 集合超出 allowlist 的部分=外溢面,单列并入
    violations(fail-closed),其 UUID 绝不入 deletable 清单。
    """
    from backend.pipeline.ingest import chunk_uuids_for_version

    res = LedgerResult(tombstone_days=tombstone_days, now=now)

    doomed = doomed_document_rows(docs, tombstone_days, now)
    doomed_set = set(doomed)
    if allowed_deleted_sources is not None:
        res.spillover_sources = sorted(doomed_set - allowed_deleted_sources)
        if res.spillover_sources:
            res.violations.append(
                f"fail-closed: doomed 集合超出冻结 allowlist {len(res.spillover_sources)} 篇(外溢面拒绝)"
            )
    # 外溢文档的 UUID 一律不入清单:清单只覆盖 allowlist 内的 doomed。
    in_scope = doomed_set & (allowed_deleted_sources or doomed_set)
    res.doomed_sources = sorted(in_scope)

    res.eligible_generation_ids = eligible_generation_rows(generations, now)
    gen_id_set = set(res.eligible_generation_ids)

    versions_by_source: dict[str, list[VersionRow]] = {}
    versions_by_gen: dict[str, list[VersionRow]] = {}
    for v in versions:
        versions_by_source.setdefault(v.source_id, []).append(v)
        versions_by_gen.setdefault(v.generation_id, []).append(v)

    # deletable = 范围内 doomed 文档全部版本行 + 合格退役代全部版本行
    # (P0-A:全部由 chunk_uuids_for_version 确定性推导,精确身份)。
    deletable: set[str] = set()
    for sid in res.doomed_sources:
        for v in versions_by_source.get(sid, []):
            deletable.update(
                chunk_uuids_for_version(sid, v.generation_id, v.generation_ordinal, v.chunk_count)
            )
    for gid in gen_id_set:
        for v in versions_by_gen.get(gid, []):
            deletable.update(
                chunk_uuids_for_version(
                    v.source_id, v.generation_id, v.generation_ordinal, v.chunk_count
                )
            )
    res.derived_deletable_uuids = sorted(deletable)

    # 全库可推导集合(交集安全证明与 orphan 判定的对照面)。
    all_derivable: set[str] = set()
    serving_current: set[str] = set()
    current_by_source = {d.source_id: d.current_version_id for d in docs}
    for v in versions:
        us = set(
            chunk_uuids_for_version(
                v.source_id, v.generation_id, v.generation_ordinal, v.chunk_count
            )
        )
        all_derivable |= us
        if current_by_source.get(v.source_id) == v.id and v.source_id not in doomed_set:
            serving_current |= us

    # 残留分类(inventory 只读清单)。present 对全部 deletable 探测(含
    # 退役代覆盖的非目标文档对象,如实披露 GC 触达面),target 内单列守恒。
    target_sources = set(res.doomed_sources)
    present: list[str] = []
    present_in_target: list[str] = []
    orphan_in_target: list[str] = []
    orphan_total: list[str] = []
    residual_target = 0
    for uid, sid in inventory:
        if sid in target_sources:
            residual_target += 1
            if uid in deletable:
                present.append(uid)
                present_in_target.append(uid)
            else:
                orphan_in_target.append(uid)
        elif uid in deletable:
            present.append(uid)
        if uid not in all_derivable:
            orphan_total.append(uid)
    res.residual_target_objects = residual_target
    res.inventory_total = len(inventory)
    res.present_uuids = sorted(present)
    res.present_in_target_uuids = sorted(present_in_target)
    res.missing_derivable_uuids = sorted(deletable - set(present))
    res.orphan_uuids = sorted(orphan_total)
    res.orphan_in_target_uuids = sorted(orphan_in_target)

    res.serving_overlap_uuids = sorted(deletable & serving_current)
    if res.serving_overlap_uuids:
        res.violations.append(
            f"fail-closed: 清单与在服 current 可推导集合相交 {len(res.serving_overlap_uuids)} 个 UUID"
        )
    if res.orphan_in_target_uuids:
        res.violations.append(
            f"fail-closed: 目标残留含 {len(res.orphan_in_target_uuids)} 个不可推导 orphan(单列,不入清单)"
        )
    return res


# --------------------------------------------------------------------------- #
# liveness 数据源(全部只读)
# --------------------------------------------------------------------------- #
def _weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    from scripts.gc_lifecycle import _parse_weaviate_endpoint

    return _parse_weaviate_endpoint(weaviate_url)


def _load_csv_rows(docs_csv: str, versions_csv: str, gens_csv: str):
    """冻结工件(生产只读导出的 CSV)→ 账本输入;全离线复算用。"""
    import csv

    docs: list[PreflightRow] = []
    with open(docs_csv) as f:
        for r in csv.DictReader(f):
            docs.append(
                PreflightRow(
                    source_id=r["source_id"],
                    lifecycle=r["lifecycle"],
                    deleted_at=_parse_ts(r.get("deleted_at")),
                    current_version_id=r.get("current_version_id") or None,
                    retirement_gc_eligible_at=_parse_ts(r.get("ret_gc_anchor")),
                )
            )
    versions: list[VersionRow] = []
    with open(versions_csv) as f:
        for r in csv.DictReader(f):
            versions.append(
                VersionRow(
                    source_id=r["source_id"],
                    id=r["id"],
                    generation_id=r["generation_id"],
                    generation_ordinal=int(r["generation_ordinal"]),
                    chunk_count=int(r["chunk_count"]),
                )
            )
    gens: list[GenerationRow] = []
    with open(gens_csv) as f:
        for r in csv.DictReader(f):
            gens.append(
                GenerationRow(
                    id=r["id"],
                    ordinal=int(r["ordinal"]),
                    status=r["status"],
                    gc_eligible_at=_parse_ts(r.get("gc_eligible_at")),
                    purged_at=_parse_ts(r.get("purged_at")),
                )
            )
    return docs, versions, gens


def _load_live_rows(session_factory):
    """生产 PG 只读身份行(SELECT only)。"""
    from sqlalchemy import select

    from backend.db.models import Document, DocumentVersion, IndexGeneration

    docs: list[PreflightRow] = []
    versions: list[VersionRow] = []
    gens: list[GenerationRow] = []
    with session_factory() as s:
        for sid, lc, deleted_at, cv, meta in s.execute(
            select(
                Document.source_id,
                Document.lifecycle,
                Document.deleted_at,
                Document.current_version_id,
                Document.metadata_,
            )
        ):
            record = meta.get("retirement") if isinstance(meta, dict) else None
            anchor = None
            if isinstance(record, dict):
                anchor = _parse_ts(record.get("gc_eligible_at"))
            docs.append(
                PreflightRow(
                    source_id=sid,
                    lifecycle=str(lc),
                    deleted_at=deleted_at,
                    current_version_id=str(cv) if cv else None,
                    retirement_gc_eligible_at=anchor,
                )
            )
        for sid, vid, gid, gord, cc in s.execute(
            select(
                DocumentVersion.source_id,
                DocumentVersion.id,
                DocumentVersion.generation_id,
                DocumentVersion.generation_ordinal,
                DocumentVersion.chunk_count,
            )
        ):
            versions.append(
                VersionRow(
                    source_id=sid,
                    id=str(vid),
                    generation_id=str(gid),
                    generation_ordinal=int(gord),
                    chunk_count=int(cc),
                )
            )
        for gid, gord, status, gea, pa in s.execute(
            select(
                IndexGeneration.id,
                IndexGeneration.ordinal,
                IndexGeneration.status,
                IndexGeneration.gc_eligible_at,
                IndexGeneration.purged_at,
            )
        ):
            gens.append(
                GenerationRow(
                    id=str(gid),
                    ordinal=int(gord),
                    status=str(status),
                    gc_eligible_at=gea,
                    purged_at=pa,
                )
            )
    return docs, versions, gens


def _load_live_inventory(collection) -> list[tuple[str, str]]:
    """生产 Weaviate 只读清单(cursor 迭代;仅 identity 字段)。"""
    out: list[tuple[str, str]] = []
    for obj in collection.iterator(
        include_metadata=True, return_properties=["source_id"], batch_size=500
    ):
        props = obj.properties or {}
        out.append((str(obj.uuid), props.get("source_id")))
    return out


async def _sweep_crosscheck(session_factory, tombstone_days, now) -> tuple[list[str], list[str]]:
    """复用 main 真实 sweep(dry-run)产出资格集合,供对账(apply=False)。"""
    from backend.services.lifecycle_gc import sweep

    report = await sweep(
        session_factory,
        None,  # apply=False 路径不触碰 pipeline
        tombstone_days=tombstone_days,
        now=now,
        apply=False,
    )
    return report.documents_eligible, report.generations_eligible


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="GC 残留清理只读预检(零写入)")
    parser.add_argument("--tombstone-days", type=int, default=None)
    parser.add_argument("--allowlist-json", type=str, required=True,
                        help="冻结的已删 source_id 清点 JSON({sources:[...], sha256})")
    parser.add_argument("--inventory-jsonl", type=str, default=None,
                        help="离线清单 JSONL(uuid,source_id);缺省=生产只读 cursor 扫描")
    parser.add_argument("--docs-csv", type=str, default=None,
                        help="离线 documents 身份 CSV(source_id,lifecycle,deleted_at,"
                        "current_version_id,ret_reason,ret_gc_anchor);与 versions/gens "
                        "CSV 同给=全离线复算(不连生产)")
    parser.add_argument("--versions-csv", type=str, default=None)
    parser.add_argument("--gens-csv", type=str, default=None)
    parser.add_argument("--now-iso", type=str, default=None,
                        help="离线复算的裁决时刻(ISO);缺省=当前 UTC")
    parser.add_argument("--report-json", type=str, default=None)
    parser.add_argument("--skip-sweep-crosscheck", action="store_true")
    args = parser.parse_args()

    with open(args.allowlist_json) as f:
        allow = json.load(f)
    allowed = set(allow["sources"])
    digest = hashlib.sha256(
        "".join(u + "\n" for u in sorted(allowed)).encode()
    ).hexdigest()
    if allow.get("sha256") and allow["sha256"] != digest:
        print("allowlist sha256 不匹配(fail-closed)", file=sys.stderr)
        return EXIT_FAILCLOSED

    offline_pg = bool(args.docs_csv and args.versions_csv and args.gens_csv)
    now = _parse_ts(args.now_iso) if args.now_iso else datetime.now(UTC)

    if args.inventory_jsonl:
        inventory = []
        with open(args.inventory_jsonl) as f:
            for line in f:
                r = json.loads(line)
                inventory.append((r["u"], r["s"]))
        if offline_pg:
            docs, versions, gens = _load_csv_rows(
                args.docs_csv, args.versions_csv, args.gens_csv
            )
        else:
            from backend.config import load_settings
            from backend.db.session import get_engine, get_session_factory

            settings = load_settings()
            sf = get_session_factory(get_engine(settings.postgres_dsn))
            docs, versions, gens = _load_live_rows(sf)
        drift = None
    elif offline_pg:
        # 全离线模式必须连冻结清单一起给(账本=PG × 清单 的交叉对账)。
        print("离线 PG 模式需要 --inventory-jsonl", file=sys.stderr)
        return EXIT_FAILCLOSED
    else:
        import weaviate

        from backend.config import load_settings
        from backend.db.session import get_engine, get_session_factory, get_sync_session_factory

        settings = load_settings()
        sf = get_session_factory(get_engine(settings.postgres_dsn))
        docs, versions, gens = _load_live_rows(sf)
        host, port = _weaviate_endpoint(settings.weaviate_url)
        client = weaviate.connect_to_local(host=host, port=port)
        try:
            raw = client.collections.get(settings.weaviate_class_name)
            inventory = _load_live_inventory(ReadOnlyCollection(raw))
        finally:
            client.close()
        drift = None
        if not args.skip_sweep_crosscheck:
            gc_docs, _gc_gens = asyncio.run(
                _sweep_crosscheck(
                    get_sync_session_factory(settings.postgres_dsn),
                    args.tombstone_days,
                    now,
                )
            )
            local_doomed = sorted(
                doomed_document_rows(docs, args.tombstone_days, now)
            )
            drift = None if sorted(gc_docs) == local_doomed else (sorted(gc_docs), local_doomed)

    result = compute_ledger(
        docs,
        versions,
        gens,
        inventory,
        tombstone_days=args.tombstone_days,
        now=now,
        allowed_deleted_sources=allowed,
    )
    out = result.as_dict()
    out["allowlist_size"] = len(allowed)
    out["allowlist_sha256"] = digest
    if drift is not None:
        out["eligibility_drift"] = {
            "sweep_documents_eligible": len(drift[0]),
            "local_recompute": len(drift[1]),
        }
        result.violations.append("fail-closed: sweep 与本地重算资格集合不一致(语义漂移)")

    if args.report_json:
        with open(args.report_json, "w") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))

    if drift is not None:
        return EXIT_ELIGIBILITY_DRIFT
    if result.violations:
        return EXIT_FAILCLOSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
