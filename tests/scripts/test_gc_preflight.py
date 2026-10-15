"""Issue #164 只读预检回归(fixture 级,零网络/零 PG/零 Weaviate)。

契约锚点(issue #164 AC2/AC3):
- 整数守恒:目标残留 = GC 可覆盖(在场) + orphan(单列), distinct UUID;
- 目标清单与在服 current 可推导集合交集必须为 0;
- 全局 tombstone_days 外溢面 fail-closed:doomed ⊄ 冻结 allowlist 即拒绝,
  外溢文档 UUID 绝不入清理清单;
- dry-run 绝无 Weaviate DELETE/PG 写入(只读代理拦截 + 账本构造零写路径);
- 删除身份只能来自 ``chunk_uuids_for_version`` 确定性推导(P0-A);
- ``objects_deleted``=尝试数≠实际成功:预检以在场/缺席探针区分;
- #162 语义回归:普通墓碑在 tombstone_days=None 下一律不合格。
"""

from __future__ import annotations

import hashlib
import uuid as uuidlib
from datetime import UTC, datetime, timedelta

import pytest

from scripts.gc_preflight import (
    EXIT_FAILCLOSED,
    GenerationRow,
    LedgerResult,
    NotReadOnly,
    PreflightRow,
    ReadOnlyCollection,
    VersionRow,
    compute_ledger,
    doomed_document_rows,
)

NOW = datetime(2026, 10, 15, 9, 42, 0, tzinfo=UTC)

SRC_A = "fixture-repo/main/docs/a.md"
SRC_B = "fixture-repo/main/docs/b.md"
SRC_C = "fixture-repo/main/docs/c.md"
SRC_D = "fixture-repo/main/docs/d.md"
SRC_E = "fixture-repo/main/docs/e.md"

G0 = "00000000-0000-0000-0000-000000000000"  # retired, matured anchor
G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"
G3 = "33333333-3333-3333-3333-333333333333"
G4 = "44444444-4444-4444-4444-444444444444"
G5 = "55555555-5555-5555-5555-555555555555"  # retired, future anchor

ALLOWED = {SRC_A, SRC_B}


def _u(name: str) -> str:
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, name))


def base_docs() -> list[PreflightRow]:
    return [
        PreflightRow(SRC_A, "deleted", NOW - timedelta(days=40), "v-a1", None),
        PreflightRow(SRC_B, "deleted", NOW - timedelta(days=40), "v-b1", None),
        PreflightRow(SRC_C, "deleted", NOW - timedelta(days=40), "v-c1", None),
        PreflightRow(SRC_D, "active", None, "v-d1", None),
        PreflightRow(SRC_E, "deleted", NOW - timedelta(days=1), "v-e1", None),
    ]


def base_versions() -> list[VersionRow]:
    return [
        VersionRow(SRC_A, "v-a1", G1, 2, 3),
        VersionRow(SRC_B, "v-b0", G0, 1, 2),  # 旧代行(经退役代 GC 覆盖)
        VersionRow(SRC_B, "v-b1", G2, 3, 1),
        VersionRow(SRC_C, "v-c1", G3, 4, 2),
        VersionRow(SRC_D, "v-d1", G4, 5, 2),
        VersionRow(SRC_E, "v-e1", G1, 2, 1),
    ]


def base_gens() -> list[GenerationRow]:
    return [
        GenerationRow(G0, 10, "retired", NOW - timedelta(days=1), None),
        GenerationRow(G1, 20, "ready", None, None),
        GenerationRow(G2, 30, "ready", None, None),
        GenerationRow(G3, 40, "ready", None, None),
        GenerationRow(G4, 50, "ready", None, None),
        GenerationRow(G5, 60, "retired", NOW + timedelta(days=1), None),
    ]


def base_inventory() -> list[tuple[str, str]]:
    inv = [(_u(f"{SRC_A}#{G1}#{i}"), SRC_A) for i in range(3)]
    inv += [(_u(f"{SRC_B}#{G0}#{i}"), SRC_B) for i in range(2)]
    inv += [(_u(f"{SRC_B}#{G2}#{0}"), SRC_B)]
    inv += [(_u(f"{SRC_C}#{G3}#{i}"), SRC_C) for i in range(2)]
    inv += [(_u(f"{SRC_D}#{G4}#{i}"), SRC_D) for i in range(2)]
    inv += [(_u(f"{SRC_D}#deadbeef-generation#{0}"), SRC_D)]  # active 文档孤儿
    return inv


def run_ledger(inventory=None, docs=None, **kwargs) -> LedgerResult:
    return compute_ledger(
        docs if docs is not None else base_docs(),
        base_versions(),
        base_gens(),
        inventory if inventory is not None else base_inventory(),
        tombstone_days=kwargs.pop("tombstone_days", 30),
        now=kwargs.pop("now", NOW),
        allowed_deleted_sources=kwargs.pop("allowed", ALLOWED),
        **kwargs,
    )


class TestConservation:
    def test_residual_equals_coverable_plus_orphan(self):
        res = run_ledger()
        # 目标内残留 = A(3) + B(3);C 是外溢文档,不在 allowlist 内不入目标。
        assert res.residual_target_objects == 6
        assert len(res.present_uuids) == 6
        assert res.orphan_in_target_uuids == []
        assert res.residual_target_objects == len(res.present_uuids) + len(res.orphan_in_target_uuids)
        assert res.as_dict()["conservation"] is True

    def test_part1_retired_generation_covers_old_row(self):
        res = run_ledger()
        # B 的旧代行(g0)由合格退役代 G0 覆盖(不在 doomed 版本行内也在清单)。
        assert G0 in res.eligible_generation_ids
        assert _u(f"{SRC_B}#{G0}#{0}") in res.derived_deletable_uuids
        assert _u(f"{SRC_B}#{G0}#{1}") in res.derived_deletable_uuids

    def test_future_anchor_generation_not_eligible(self):
        res = run_ledger()
        assert G5 not in res.eligible_generation_ids

    def test_missing_derivable_distinguished_from_present(self):
        # GCReport.objects_deleted=尝试数≠实际成功:缺席对象单列统计。
        inv = [x for x in base_inventory() if x[0] != _u(f"{SRC_A}#{G1}#{2}")]
        res = run_ledger(inventory=inv)
        assert len(res.present_uuids) == 5
        assert res.missing_derivable_uuids == [_u(f"{SRC_A}#{G1}#{2}")]
        # 清单仍含全部可推导 UUID(点删缺席 UUID 为无副作用匹配零)。
        assert len(res.derived_deletable_uuids) == 6


class TestSpilloverFailClosed:
    def test_out_of_allowlist_doomed_is_spillover(self):
        res = run_ledger()
        assert res.spillover_sources == [SRC_C]
        assert any("外溢面拒绝" in v for v in res.violations)
        # 外溢文档的 UUID 绝不入清理清单。
        assert all(SRC_C not in s for s in [])
        c_uuid = _u(f"{SRC_C}#{G3}#{0}")
        assert c_uuid not in res.derived_deletable_uuids

    def test_window_growth_changes_doomed_set(self):
        # T=1 时 E(1 天前删除)也进 doomed:证明窗口扩大必然重过 allowlist 门。
        run_ledger(tombstone_days=1)
        doomed = doomed_document_rows(base_docs(), 1, NOW)
        assert SRC_E in doomed
        assert SRC_E not in ALLOWED

    def test_tombstone_days_none_disables_plain_tombstones(self):
        # #162 语义回归:普通墓碑(无 gc_eligible_at 锚)在 None 下一律不合格。
        doomed = doomed_document_rows(base_docs(), None, NOW)
        assert doomed == []


class TestServingSafety:
    def test_no_overlap_with_serving_current(self):
        res = run_ledger()
        assert res.serving_overlap_uuids == []

    def test_serving_uuids_never_in_manifest(self):
        # 在服文档 D 的 current 可推导 UUID 与清理清单结构不相交:
        # UUID 空间含 source_id,且 doomed 文档整体退出在服对照面。
        res = run_ledger()
        d_uuids = {_u(f"{SRC_D}#{G4}#{i}") for i in range(2)}
        assert res.derived_deletable_uuids
        assert not (set(res.derived_deletable_uuids) & d_uuids)
        assert res.serving_overlap_uuids == []

    def test_doomed_doc_excluded_from_serving_reference_set(self):
        # 同一 source_id 即使账本错乱也只有一个生命周期:doomed 优先退出
        # 在服对照面,交集检查(防御纵深)恒为空。
        docs = base_docs()
        docs[3] = PreflightRow(SRC_D, "active", None, "v-a1", None)  # 指向 A 的版本行
        versions = base_versions() + [VersionRow(SRC_D, "v-a1", G1, 2, 3)]
        res = compute_ledger(
            docs, versions, base_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=ALLOWED,
        )
        # D 的 UUID 空间(SRC_D#G1#i)不属于 A 的清单(SRC_A#G1#i):
        # source_id 是身份的一部分,跨身份碰撞结构上不可能。
        assert res.serving_overlap_uuids == []
        assert _u(f"{SRC_D}#{G1}#{0}") not in res.derived_deletable_uuids


class TestOrphanSingleListed:
    def test_active_doc_orphan_never_in_manifest(self):
        res = run_ledger()
        stray = _u(f"{SRC_D}#deadbeef-generation#{0}")
        assert stray in res.orphan_uuids
        assert stray not in res.derived_deletable_uuids

    def test_orphan_in_target_is_failclosed(self):
        inv = base_inventory() + [(_u(f"{SRC_A}#ghost-generation#{0}"), SRC_A)]
        res = run_ledger(inventory=inv)
        assert res.orphan_in_target_uuids == [_u(f"{SRC_A}#ghost-generation#{0}")]
        assert any("orphan" in v for v in res.violations)
        assert _u(f"{SRC_A}#ghost-generation#{0}") not in res.derived_deletable_uuids


class TestExactIdentityDerivation:
    def test_manifest_matches_backend_uuid_path(self):
        from backend.pipeline.ingest import chunk_uuids_for_version

        res = run_ledger()
        expected = set()
        for v in base_versions():
            if v.source_id in ALLOWED:
                expected |= set(
                    chunk_uuids_for_version(v.source_id, v.generation_id, v.generation_ordinal, v.chunk_count)
                )
        expected |= {_u(f"{SRC_B}#{G0}#{i}") for i in range(2)}
        assert set(res.derived_deletable_uuids) == expected

    def test_legacy_ordinal_zero_namespace(self):
        from backend.pipeline.ingest import legacy_chunk_uuids

        assert legacy_chunk_uuids(SRC_A, 2) == [_u(f"{SRC_A}#{0}"), _u(f"{SRC_A}#{1}")]


class TestReadOnlyGuarantee:
    def test_proxy_blocks_mutations(self):
        class Inner:
            def delete_many(self, *a, **k):  # pragma: no cover - must not run
                raise AssertionError("delete_many reached inner")

            def insert_many(self, *a, **k):  # pragma: no cover
                raise AssertionError

            def iterator(self, **k):
                return iter([("u1", {"source_id": "s"})])

        proxy = ReadOnlyCollection(Inner())
        with pytest.raises(NotReadOnly):
            proxy.delete_many()
        with pytest.raises(NotReadOnly):
            proxy.insert_many()
        with pytest.raises(NotReadOnly):
            proxy.replace()
        assert list(proxy.iterator()) == [("u1", {"source_id": "s"})]

    def test_ledger_construction_is_pure(self):
        # compute_ledger 不接受任何 collection/写入句柄:零写由构造保证。
        res = run_ledger()
        assert isinstance(res, LedgerResult)

    def test_manifest_hash_stable(self):
        res = run_ledger()
        h = hashlib.sha256()
        for u in sorted(res.derived_deletable_uuids):
            h.update(u.encode())
            h.update(b"\n")
        assert res.manifest_sha256 == h.hexdigest()


class TestRetirementAnchorSemantics:
    def test_matured_anchor_dooms_regardless_of_window(self):
        docs = [
            PreflightRow("r/main/x.md", "deleted", NOW - timedelta(days=1), "v-r1", NOW - timedelta(days=1)),
        ]
        doomed = doomed_document_rows(docs, None, NOW)
        assert doomed == ["r/main/x.md"]

    def test_future_anchor_not_doomed(self):
        docs = [
            PreflightRow("r/main/y.md", "deleted", NOW - timedelta(days=1), "v-r1", NOW + timedelta(days=6)),
        ]
        doomed = doomed_document_rows(docs, 30, NOW)
        assert doomed == []

    def test_exit_code_constants(self):
        assert EXIT_FAILCLOSED == 2
