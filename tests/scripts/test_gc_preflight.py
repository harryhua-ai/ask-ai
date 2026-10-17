"""Issue #164 只读预检回归(fixture 级,零网络/零 PG/零 Weaviate)。

契约锚点(issue #164 AC2/AC3;R2 增补对应 A 复审五项阻塞):
- 整数守恒:目标残留 = GC 可覆盖(在场) + orphan(单列), distinct UUID;
- 目标清单与在服 current 可推导集合交集必须为 0;
- 全局 tombstone_days 外溢面 fail-closed:doomed ⊄ 冻结 allowlist 即拒绝,
  外溢文档 UUID 绝不入清理清单;
- dry-run 绝无 Weaviate DELETE/PG 写入(只读代理拦截 + 账本构造零写路径);
- 删除身份只能来自 ``chunk_uuids_for_version`` 确定性推导(P0-A);
- ``objects_deleted``=运行时确认删除数;预检仍以在场/缺席探针独立核对;
- #162 语义回归:普通墓碑在 tombstone_days=None 下一律不合格;
- GC apply 硬否决:历史修复前发现(#164, 2026-10-15)的删除回执与提交顺序
  问题现已在运行时修复;当前测试验证回执计数和精确 UUID 缺席后才提交 PG。
  现役 HARD NO-GO 只列仍开放的范围、live snapshot、User 授权与生产恢复门;
- R2(820-only 范围门):合格退役代触及的目标外文档 UUID 绝不入清单,
  单列「需另行授权」并 fail-closed;
- R2(allowlist sha256 强制):缺失/空/不匹配一律拒绝;
- R2(资格对账双面):sweep 对账必须同时覆盖文档与代资格面,漂移即 exit 3
  且报告 violations 不得为空;
- R2(清单守恒代码门):distinct UUID / 非空 source_id 绑定 / 源↔UUID 绑定
  一致性由 compute_ledger 强制;
- R2(SessionFactory 契约):``_load_live_rows`` 只接受同步会话工厂
  (sync 上下文 + 同步 execute),``_sweep_crosscheck`` 只接受异步会话工厂
  (async 上下文 + await execute),main() 两种输入路径不得错配;
- R3(空 allowlist 边界):空 allowlist=授权 0 篇(与 None=未提供显式区分),
  违规路径的清理清单恒为空集、manifest 对应空集 —— 绝不回退到全量 doomed;
- R3(空白 source_id):None/空串/纯空白 source_id 一律按无有效身份
  fail-closed,不再只认 None;
- R3(parity 不可静默旁路):可供授权判断的 live 预检强制 sweep 双面对账;
  ``--skip-sweep-crosscheck`` 或「冻结清单 JSONL × 当前 live PG」混合输入
  只能得到 unverified 标记 + 非零退出(exit 4),不可作为安全门 PASS。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
import uuid as uuidlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import scripts.gc_preflight as gc_preflight
from scripts.gc_preflight import (
    EXIT_ELIGIBILITY_DRIFT,
    EXIT_FAILCLOSED,
    EXIT_OK,
    EXIT_UNVERIFIED,
    AllowlistRejected,
    GenerationRow,
    HARD_NO_GO_REASONS,
    LedgerResult,
    NotReadOnly,
    PreflightRow,
    ReadOnlyCollection,
    VersionRow,
    compute_ledger,
    doomed_document_rows,
    load_allowlist,
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
        # 预检按只读库存区分缺席与在场对象,不混用运行时删除计数。
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


# --------------------------------------------------------------------------- #
# R2 增补(A 复审五项阻塞):负例、范围门、契约与端到端 main() fixture
# --------------------------------------------------------------------------- #
G6 = "66666666-6666-6666-6666-666666666666"  # retired 且已成熟,覆盖 active 文档旧代

LIVE_DOCS = [
    (SRC_A, "deleted", NOW - timedelta(days=40), "v-a1", {}),
    (SRC_B, "deleted", NOW - timedelta(days=40), "v-b1", {}),
]
LIVE_VERSIONS = [
    (SRC_A, "v-a1", G1, 2, 3),
    (SRC_B, "v-b1", G2, 3, 3),
    (SRC_B, "v-b0", G0, 1, 2),
]
LIVE_GENS = [(G0, 10, "retired", NOW - timedelta(days=1), None)]
LIVE_INVENTORY = (
    [(_u(f"{SRC_A}#{G1}#{i}"), SRC_A) for i in range(3)]
    + [(_u(f"{SRC_B}#{G2}#{i}"), SRC_B) for i in range(3)]
    + [(_u(f"{SRC_B}#{G0}#{i}"), SRC_B) for i in range(2)]
)


def _allowlist_digest(sources: list[str]) -> str:
    return hashlib.sha256("".join(u + "\n" for u in sorted(sources)).encode()).hexdigest()


def _write_allowlist(tmp_path, sources, sha256=True):
    payload = {"sources": sorted(sources)}
    digest = _allowlist_digest(sorted(sources))
    if sha256 is True:
        payload["sha256"] = digest
    elif isinstance(sha256, str):
        payload["sha256"] = sha256
    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps(payload))
    return p


class TestAllowlistSha256Enforced:
    """A 阻塞 3a:allowlist sha256 缺/空/不匹配一律 fail-closed。"""

    def test_missing_sha256_rejected(self, tmp_path):
        p = _write_allowlist(tmp_path, [SRC_A], sha256=False)
        with pytest.raises(AllowlistRejected):
            load_allowlist(str(p))

    def test_empty_sha256_rejected(self, tmp_path):
        p = _write_allowlist(tmp_path, [SRC_A], sha256="")
        with pytest.raises(AllowlistRejected):
            load_allowlist(str(p))

    def test_mismatched_sha256_rejected(self, tmp_path):
        p = _write_allowlist(tmp_path, [SRC_A], sha256="0" * 64)
        with pytest.raises(AllowlistRejected):
            load_allowlist(str(p))

    def test_non_string_source_rejected(self, tmp_path):
        p = _write_allowlist(tmp_path, [SRC_A], sha256=True)
        payload = json.loads(p.read_text())
        payload["sources"] = [SRC_A, 42]
        payload["sha256"] = _allowlist_digest([SRC_A])  # 哈希无法覆盖非串条目
        p.write_text(json.dumps(payload))
        with pytest.raises(AllowlistRejected):
            load_allowlist(str(p))

    def test_valid_allowlist_accepted(self, tmp_path):
        p = _write_allowlist(tmp_path, [SRC_A, SRC_B], sha256=True)
        allowed, digest = load_allowlist(str(p))
        assert allowed == {SRC_A, SRC_B}
        assert digest == _allowlist_digest([SRC_A, SRC_B])

    def test_main_missing_sha256_exits_failclosed(self, tmp_path, capsys):
        p = _write_allowlist(tmp_path, [SRC_A], sha256=False)
        code = gc_preflight.main(["--tombstone-days", "30", "--allowlist-json", str(p)])
        assert code == EXIT_FAILCLOSED
        assert "sha256" in capsys.readouterr().err.lower()


def _scope_versions() -> list[VersionRow]:
    return base_versions() + [VersionRow(SRC_D, "v-d0", G6, 7, 2)]


def _scope_gens() -> list[GenerationRow]:
    return base_gens() + [GenerationRow(G6, 70, "retired", NOW - timedelta(days=1), None)]


class TestEightTwentyOnlyScopeGate:
    """A 阻塞 2:合格退役代触及的目标外 UUID 必须单列并 fail-closed。"""

    def test_active_doc_retired_gen_uuids_out_of_scope(self):
        inv = base_inventory() + [(_u(f"{SRC_D}#{G6}#{i}"), SRC_D) for i in range(2)]
        res = compute_ledger(
            base_docs(), _scope_versions(), _scope_gens(), inv,
            tombstone_days=30, now=NOW, allowed_deleted_sources=ALLOWED,
        )
        oos = set(res.out_of_scope_generation_uuids)
        assert {_u(f"{SRC_D}#{G6}#{i}") for i in range(2)} <= oos
        assert not (oos & set(res.derived_deletable_uuids))
        assert any("另行授权" in v for v in res.violations)

    def test_out_of_scope_counted_even_when_absent_from_inventory(self):
        # GC 触达面由可推导集合决定,与对象是否在场无关(缺席点删匹配零)。
        res = compute_ledger(
            base_docs(), _scope_versions(), _scope_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=ALLOWED,
        )
        assert {_u(f"{SRC_D}#{G6}#{i}") for i in range(2)} == set(res.out_of_scope_generation_uuids)
        assert any("另行授权" in v for v in res.violations)

    def test_spillover_doc_never_enters_manifest_via_generation_path(self):
        # 外溢文档(C 不在 allowlist)的退役代 UUID 也绝不入清单(R2 收紧)。
        versions = base_versions() + [VersionRow(SRC_C, "v-c0", G6, 7, 2)]
        res = compute_ledger(
            base_docs(), versions, _scope_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=ALLOWED,
        )
        c_oos = {_u(f"{SRC_C}#{G6}#{i}") for i in range(2)}
        assert c_oos <= set(res.out_of_scope_generation_uuids)
        assert not (c_oos & set(res.derived_deletable_uuids))

    def test_in_scope_retired_gen_coverage_unchanged(self):
        # 范围门不改变 820 内账本:doomed 文档的退役代覆盖仍在清单内。
        res = run_ledger()
        assert G0 in res.eligible_generation_ids
        assert _u(f"{SRC_B}#{G0}#{0}") in res.derived_deletable_uuids
        assert res.out_of_scope_generation_uuids == []

    def test_as_dict_counts_out_of_scope(self):
        res = compute_ledger(
            base_docs(), _scope_versions(), _scope_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=ALLOWED,
        )
        assert res.as_dict()["out_of_scope_generation_uuids"] == 2


class _FakeGCApplyCollection:
    """离线 GC 对象存储:保留 UUID 读回、删除回执和对象存活状态。"""

    def __init__(self, uuids, failed_uuids=()):
        self.objects = {str(value).lower() for value in uuids}
        self.failed_uuids = {str(value).lower() for value in failed_uuids}
        self.read_requests = []
        self.delete_requests = []
        self.query = SimpleNamespace(fetch_objects=self.fetch_objects)
        self.data = SimpleNamespace(delete_many=self.delete_many)

    @staticmethod
    def _requested(filter_):
        values = getattr(filter_, "value", None)
        if not isinstance(values, (list, tuple, set)):
            raise TypeError(f"fake received a non UUID-list filter: {filter_!r}")
        return {str(value).lower() for value in values}

    def fetch_objects(self, *, filters, limit=None):
        requested = self._requested(filters)
        self.read_requests.append(requested)
        found = sorted(requested & self.objects)
        if limit is not None:
            found = found[:limit]
        return SimpleNamespace(
            objects=[SimpleNamespace(uuid=uuidlib.UUID(value)) for value in found]
        )

    def delete_many(self, *, where):
        requested = self._requested(where)
        self.delete_requests.append(requested)
        matched = requested & self.objects
        failed = matched & self.failed_uuids
        successful = matched - failed
        self.objects.difference_update(successful)
        return SimpleNamespace(
            successful=len(successful),
            failed=len(failed),
            matches=len(matched),
        )


class TestGCApplyHardNoGo:
    """A 阻塞 1:现役开放门 + 恒真硬否决;历史修复不再冒充当前缺陷。"""

    def test_reasons_only_report_current_open_gates(self):
        blob = "\n".join(HARD_NO_GO_REASONS)
        assert HARD_NO_GO_REASONS
        assert "820-only" in blob and "manifest" in blob
        assert "live snapshot" in blob and "重采" in blob
        assert "User" in blob and "授权" in blob
        assert "生产一致性" in blob and "恢复前置" in blob
        assert "忽略 collection.data.delete_many 返回" not in blob
        assert "仍按成功记账并继续提交 DB 元数据" not in blob
        assert "「已验证的对象删除」之前提交" not in blob

    def test_delete_many_partial_failure_is_rejected_for_exact_uuids(self):
        # 失败回执必须 fail closed;删除身份和前置读回都只能覆盖请求 UUID。
        from backend.services.lifecycle_gc import _delete_version_objects
        from backend.pipeline.ingest import chunk_uuids_for_version

        uuids = chunk_uuids_for_version(SRC_A, G1, 2, 3)
        failed_uuid = uuids[-1]
        collection = _FakeGCApplyCollection(uuids, failed_uuids={failed_uuid})

        with pytest.raises(RuntimeError, match="1 failed objects"):
            _delete_version_objects(collection, uuids)

        assert collection.read_requests == [set(uuids)]
        assert collection.delete_requests == [set(uuids)]
        assert collection.objects == {failed_uuid}

    def test_apply_partial_delete_preserves_identity_and_retries_remaining_uuids(self):
        # 失败回执不提交 PG 身份;重启后只删读回仍在场的 UUID,再提交 purged_at。
        from backend.services.lifecycle_gc import sweep as gc_sweep
        from backend.services import document_lifecycle as lifecycle
        from backend.pipeline.ingest import chunk_uuids_for_version
        from backend.db.models import DocumentVersion, DocumentVersionChunk, IndexGeneration

        gen_id = G1
        uuids = chunk_uuids_for_version(SRC_A, gen_id, 2, 3)
        failed_uuid = uuids[-1]
        fake_gen = SimpleNamespace(id=gen_id)
        fake_ver = SimpleNamespace(
            source_id=SRC_A,
            id="v-a1",
            generation_id=gen_id,
            generation_ordinal=2,
            chunk_count=3,
        )
        fake_gen_row = SimpleNamespace(
            id=gen_id,
            status=lifecycle.GenerationStatus.RETIRED,
            gc_eligible_at=NOW - timedelta(days=1),
            purged_at=None,
            ordinal=2,
            doc_count=1,
            chunk_count=3,
        )
        chunk_rows = [SimpleNamespace(chunk_index=i) for i in range(3)]
        collection = _FakeGCApplyCollection(uuids, failed_uuids={failed_uuid})
        pipeline = SimpleNamespace(_collection=collection)

        def _identity_sync_factory():
            class _Factory:
                def __init__(self):
                    self.log = []

                def __call__(self):
                    return self

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def execute(self, stmt):
                    entity = stmt.column_descriptions[0]["entity"]
                    self.log.append(("sync-execute", entity))
                    if entity is IndexGeneration:
                        rows = [fake_gen_row]
                    elif entity is DocumentVersion:
                        rows = [fake_ver]
                    elif entity is DocumentVersionChunk:
                        rows = chunk_rows
                    else:
                        raise AssertionError(f"unexpected sync GC query entity: {entity}")
                    return _FakeSyncResult(rows)

                def delete(self, obj):
                    self.log.append(("delete", obj))

                def commit(self):
                    self.log.append(("commit", None))

            return _Factory()

        async_sf = FakeAsyncSessionFactory([[fake_gen], [], []])
        sync_sf = _identity_sync_factory()
        pipeline._session_factory = sync_sf
        failed_report = asyncio.run(
            gc_sweep(async_sf, pipeline, tombstone_days=None, now=NOW, apply=True)
        )

        assert failed_report.errors and any("1 failed objects" in error for error in failed_report.errors)
        assert failed_report.objects_deleted == 0
        assert failed_report.chunk_rows_deleted == 0
        assert fake_gen_row.purged_at is None
        assert not any(op in {"delete", "commit"} for op, _ in sync_sf.log)
        assert collection.objects == {failed_uuid}
        assert collection.read_requests == [set(uuids)]
        assert collection.delete_requests == [set(uuids)]

        # 模拟进程重启:PG 身份仍在,Weaviate 仅剩失败 UUID;重试后才清理并盖章。
        collection.failed_uuids.clear()
        retry_async_sf = FakeAsyncSessionFactory([[fake_gen], [], []])
        retry_sync_sf = _identity_sync_factory()
        pipeline._session_factory = retry_sync_sf
        retry_report = asyncio.run(
            gc_sweep(retry_async_sf, pipeline, tombstone_days=None, now=NOW, apply=True)
        )

        assert retry_report.errors == []
        assert retry_report.objects_deleted == 1
        assert retry_report.chunk_rows_deleted == 3
        assert collection.objects == set()
        assert collection.read_requests == [set(uuids), set(uuids), set(uuids)]
        assert collection.delete_requests == [set(uuids), {failed_uuid}]
        assert fake_gen_row.purged_at == NOW
        assert sum(op == "delete" for op, _ in retry_sync_sf.log) == 3
        assert ("commit", None) in retry_sync_sf.log

    def test_main_output_carries_hard_no_go(self, monkeypatch, tmp_path):
        code, report, _calls = _run_live_main(monkeypatch, tmp_path)
        assert code == EXIT_OK
        assert report["gc_apply_hard_no_go"] is True
        assert report["gc_apply_hard_no_go_reasons"] == list(HARD_NO_GO_REASONS)


class TestCrosscheckDualSurfaceAndOrdering:
    """A 阻塞 3b/3c:对账覆盖代资格面;violations 先于 as_dict 落报告。"""

    def test_generation_only_drift_exits_3(self, monkeypatch, tmp_path):
        code, report, _calls = _run_live_main(
            monkeypatch, tmp_path, crosscheck=([SRC_A, SRC_B], [])
        )
        assert code == EXIT_ELIGIBILITY_DRIFT
        assert report["eligibility_drift"]["generations"] is not None
        assert any("漂移" in v for v in report["violations"])

    def test_report_violations_not_empty_on_drift_exit(self, monkeypatch, tmp_path):
        code, report, _calls = _run_live_main(
            monkeypatch, tmp_path, crosscheck=([SRC_C], [G0])
        )
        assert code == EXIT_ELIGIBILITY_DRIFT
        assert report["violations"], "exit 3 时报告 violations 不得为空(as_dict 必须在后)"
        assert report["eligibility_drift"]["documents"]["sweep"] == [SRC_C]
        assert report["eligibility_drift"]["documents"]["local"] == [SRC_A, SRC_B]

    def test_no_drift_parity_exits_ok(self, monkeypatch, tmp_path):
        code, report, _calls = _run_live_main(monkeypatch, tmp_path)
        assert code == EXIT_OK
        assert "eligibility_drift" not in report
        assert report["violations"] == []


class TestInventoryIdentityGates:
    """A 阻塞 3d:distinct UUID / 非空绑定 / 源↔UUID 一致性是代码门。"""

    def test_duplicate_uuid_failclosed(self):
        inv = base_inventory() + [(base_inventory()[0][0], SRC_A)]
        res = run_ledger(inventory=inv)
        assert any("重复" in v for v in res.violations)

    def test_null_source_id_failclosed(self):
        inv = base_inventory() + [(_u("ghost-null-binding"), None)]
        res = run_ledger(inventory=inv)
        assert any("null" in v.lower() for v in res.violations)

    def test_source_uuid_binding_mismatch_failclosed(self):
        stolen = _u(f"{SRC_A}#{G1}#{0}")  # 可推导自 SRC_A 的 v-a1
        inv = [x for x in base_inventory() if x[0] != stolen] + [(stolen, SRC_B)]
        res = run_ledger(inventory=inv)
        assert any("绑定" in v for v in res.violations)

    def test_consistent_inventory_has_no_binding_violation(self):
        res = run_ledger()
        assert not any("绑定" in v for v in res.violations)
        assert not any("重复" in v for v in res.violations)


# ---- 离线 fake SessionFactory(契约测试;零真实连接)---- #
class _FakeSyncResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        assert len(self._rows) == 1
        return self._rows[0]


class FakeSyncSession:
    """同步 Session 契约:sync 上下文管理器 + 同步 execute(行队列)。"""

    def __init__(self, queue, log):
        self._queue, self._log = queue, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt):
        self._log.append(("sync-execute", len(self._queue)))
        return _FakeSyncResult(self._queue.pop(0))

    def delete(self, obj):
        self._log.append(("delete", obj))

    def commit(self):
        self._log.append(("commit", None))


class FakeSyncSessionFactory:
    kind = "sync"

    def __init__(self, queue, log=None):
        self._queue = [list(r) for r in queue]
        self._log = log if log is not None else []

    @property
    def log(self):
        return self._log

    def __call__(self):
        return FakeSyncSession(self._queue, self._log)


class _FakeAsyncResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeAsyncSession:
    """异步 Session 契约:async 上下文管理器 + await execute(行队列)。"""

    def __init__(self, queue, log):
        self._queue, self._log = queue, log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self._log.append(("await-execute", len(self._queue)))
        return _FakeAsyncResult(self._queue.pop(0))


class FakeAsyncSessionFactory:
    kind = "async"

    def __init__(self, queue, log=None):
        self._queue = [list(r) for r in queue]
        self._log = log if log is not None else []

    @property
    def log(self):
        return self._log

    def __call__(self):
        return FakeAsyncSession(self._queue, self._log)


def _live_sweep_queue() -> list:
    """真实 ``lifecycle_gc.sweep``(apply=False) 在 LIVE fixture 下的查询序列。"""
    return [
        [SimpleNamespace(id=G0)],  # part1: 合格退役代
        [],                        # part2: superseded
        [],                        # part2: retirement 锚行
        [                          # part2: 墓碑窗命中(T=30, 40 天前删除)
            SimpleNamespace(source_id=SRC_A, lifecycle="deleted", superseded_at=None,
                            deleted_at=NOW - timedelta(days=40), metadata_={}),
            SimpleNamespace(source_id=SRC_B, lifecycle="deleted", superseded_at=None,
                            deleted_at=NOW - timedelta(days=40), metadata_={}),
        ],
    ]


def _run_live_main(monkeypatch, tmp_path, *, crosscheck=None, skip_crosscheck=False):
    """live 模式 main() 端到端(fake PG/Weaviate,零网络)。

    返回 (exit_code, report_dict, recorded_calls)。crosscheck=None 时跑
    真实 ``_sweep_crosscheck``(→ 真实 ``lifecycle_gc.sweep``)。
    skip_crosscheck=True 时向 main() 传 ``--skip-sweep-crosscheck``。
    """
    import backend.config as config_mod
    import backend.db.session as session_mod

    calls: dict = {}
    sync_sf = FakeSyncSessionFactory([list(LIVE_DOCS), list(LIVE_VERSIONS), list(LIVE_GENS)])
    async_log: list = []

    real_load = gc_preflight._load_live_rows

    def spy_load(sf):
        calls["load_rows_factory"] = getattr(sf, "kind", "?")
        return real_load(sf)

    monkeypatch.setattr(gc_preflight, "_load_live_rows", spy_load)

    if crosscheck is None:
        real_cross = gc_preflight._sweep_crosscheck
        async_sf = FakeAsyncSessionFactory(_live_sweep_queue(), async_log)

        async def spy_crosscheck(sf, tdays, now):
            calls["crosscheck_factory"] = getattr(sf, "kind", "?")
            return await real_cross(sf, tdays, now)
    else:
        async_sf = FakeAsyncSessionFactory([], async_log)

        async def spy_crosscheck(sf, tdays, now):
            calls["crosscheck_factory"] = getattr(sf, "kind", "?")
            return crosscheck

    monkeypatch.setattr(gc_preflight, "_sweep_crosscheck", spy_crosscheck)
    monkeypatch.setattr(
        config_mod, "load_settings",
        lambda: SimpleNamespace(
            postgres_dsn="postgresql+asyncpg://fake/fake",
            weaviate_url="http://127.0.0.1:8080",
            weaviate_class_name="Document",
        ),
    )
    monkeypatch.setattr(session_mod, "get_engine", lambda dsn: object())
    monkeypatch.setattr(session_mod, "get_session_factory", lambda engine: async_sf)
    monkeypatch.setattr(session_mod, "get_sync_session_factory", lambda dsn_or_engine: sync_sf)

    class _FakeObj:
        def __init__(self, u, s):
            self.uuid, self.properties = u, {"source_id": s}

    class _FakeRawCollection:
        def iterator(self, **k):
            return iter(_FakeObj(u, s) for u, s in LIVE_INVENTORY)

    class _FakeClient:
        def __init__(self):
            self.collections = SimpleNamespace(get=lambda name: _FakeRawCollection())

        def close(self):
            pass

    fake_weaviate = types.ModuleType("weaviate")
    fake_weaviate.connect_to_local = lambda **k: _FakeClient()
    monkeypatch.setitem(sys.modules, "weaviate", fake_weaviate)

    al = _write_allowlist(tmp_path, [SRC_A, SRC_B], sha256=True)
    rp = tmp_path / "report.json"
    argv = [
        "--tombstone-days", "30",
        "--allowlist-json", str(al),
        "--report-json", str(rp),
    ]
    if skip_crosscheck:
        argv.append("--skip-sweep-crosscheck")
    code = gc_preflight.main(argv)
    report = json.loads(rp.read_text())
    return code, report, calls


class TestSessionFactoryContracts:
    """A 阻塞 5(补充代码错误):sync/async 会话工厂契约,main() 不得错配。"""

    def test_load_live_rows_sync_contract(self):
        sf = FakeSyncSessionFactory([list(LIVE_DOCS), list(LIVE_VERSIONS), list(LIVE_GENS)])
        docs, versions, gens = gc_preflight._load_live_rows(sf)
        assert [d.source_id for d in docs] == [SRC_A, SRC_B]
        assert docs[0].lifecycle == "deleted"
        assert docs[0].deleted_at == LIVE_DOCS[0][2]
        assert versions[0].generation_id == G1
        assert gens[0].status == "retired" and gens[0].id == G0
        assert any(op == "sync-execute" for op, _ in sf.log)

    def test_load_live_rows_rejects_async_factory(self):
        # async_sessionmaker 只支持 async 上下文:同步 with 必须显式失败。
        sf = FakeAsyncSessionFactory([])
        with pytest.raises(TypeError):
            gc_preflight._load_live_rows(sf)

    def test_sweep_crosscheck_async_contract(self):
        # 真实 _sweep_crosscheck(→ 真实 lifecycle_gc.sweep)走 async 上下文
        # + await execute 契约。
        sf = FakeAsyncSessionFactory(_live_sweep_queue())
        docs_eligible, gens_eligible = asyncio.run(
            gc_preflight._sweep_crosscheck(sf, 30, NOW)
        )
        assert docs_eligible == [SRC_A, SRC_B]
        assert gens_eligible == [G0]
        assert any(op == "await-execute" for op, _ in sf.log)

    def test_sweep_crosscheck_rejects_sync_factory(self):
        sf = FakeSyncSessionFactory([])
        with pytest.raises(TypeError):
            asyncio.run(gc_preflight._sweep_crosscheck(sf, 30, NOW))

    def test_main_live_wires_sync_load_and_async_crosscheck(self, monkeypatch, tmp_path):
        code, _report, calls = _run_live_main(monkeypatch, tmp_path)
        assert code == EXIT_OK
        assert calls["load_rows_factory"] == "sync"
        assert calls["crosscheck_factory"] == "async"


# --------------------------------------------------------------------------- #
# R3 增补(A 2026-10-17T02:26Z REQUEST_CHANGES 三项阻塞)
# --------------------------------------------------------------------------- #

NOW_ISO = "2026-10-15T09:42:00+00:00"

OFFLINE_INVENTORY = (
    [(_u(f"{SRC_A}#{G1}#{i}"), SRC_A) for i in range(3)]
    + [(_u(f"{SRC_B}#{G2}#{0}"), SRC_B)]
)


def _write_offline_csvs(tmp_path):
    """冻结工件 CSV(与 LIVE fixture 同一身份集合;零生产连接)。"""
    d = tmp_path / "docs.csv"
    d.write_text(
        "source_id,lifecycle,deleted_at,current_version_id,ret_reason,ret_gc_anchor\n"
        f"{SRC_A},deleted,2026-09-05T09:42:00+00:00,v-a1,,\n"
        f"{SRC_B},deleted,2026-09-05T09:42:00+00:00,v-b1,,\n"
    )
    v = tmp_path / "versions.csv"
    v.write_text(
        "source_id,id,generation_id,generation_ordinal,chunk_count\n"
        f"{SRC_A},v-a1,{G1},2,3\n"
        f"{SRC_B},v-b1,{G2},3,1\n"
    )
    g = tmp_path / "gens.csv"
    g.write_text("id,ordinal,status,gc_eligible_at,purged_at\n")
    return str(d), str(v), str(g)


def _write_inventory_jsonl(tmp_path, entries):
    p = tmp_path / "inventory.jsonl"
    p.write_text("".join(json.dumps({"u": u, "s": s}) + "\n" for u, s in entries))
    return str(p)


def _run_offline_main(tmp_path, *, allowlist_sources, inventory_entries):
    """全离线 main() 端到端(CSV 冻结工件 + 清单 JSONL,零网络/零 PG)。"""
    docs_csv, versions_csv, gens_csv = _write_offline_csvs(tmp_path)
    inv = _write_inventory_jsonl(tmp_path, inventory_entries)
    al = _write_allowlist(tmp_path, allowlist_sources, sha256=True)
    rp = tmp_path / "report.json"
    code = gc_preflight.main([
        "--tombstone-days", "30",
        "--now-iso", NOW_ISO,
        "--allowlist-json", str(al),
        "--inventory-jsonl", inv,
        "--docs-csv", docs_csv,
        "--versions-csv", versions_csv,
        "--gens-csv", gens_csv,
        "--report-json", str(rp),
    ])
    report = json.loads(rp.read_text())
    return code, report


class TestR3EmptyAllowlistNeverLeaksManifest:
    """A 阻塞①:空 allowlist=授权 0 篇;违规路径清单恒为空集(绝不回退全量)。"""

    def test_empty_allowlist_is_authorized_zero(self, tmp_path):
        p = _write_allowlist(tmp_path, [], sha256=True)
        allowed, digest = load_allowlist(str(p))
        assert allowed == set()
        assert digest == _allowlist_digest([])

    def test_empty_allowlist_manifest_is_empty(self):
        res = compute_ledger(
            base_docs(), base_versions(), base_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=set(),
        )
        # 全部 doomed(A/B/C)都成外溢面:exit 2 由 violation 保证,
        # 且清单/manifest 必须对应空集 —— 空授权绝不泄漏全量清单。
        assert res.spillover_sources == [SRC_A, SRC_B, SRC_C]
        assert res.doomed_sources == []
        assert res.derived_deletable_uuids == []
        assert res.manifest_sha256 == hashlib.sha256(b"").hexdigest()
        assert any("外溢面拒绝" in v for v in res.violations)

    def test_none_allowlist_semantics_unchanged(self):
        # None=未提供 allowlist(内部路径):仍不做外溢裁决(既有语义)。
        res = compute_ledger(
            base_docs(), base_versions(), base_gens(), base_inventory(),
            tombstone_days=30, now=NOW, allowed_deleted_sources=None,
        )
        assert res.spillover_sources == []
        assert res.derived_deletable_uuids  # 既有全量推导行为不变

    def test_main_empty_allowlist_exits_2_with_empty_manifest(self, tmp_path):
        code, report = _run_offline_main(
            tmp_path, allowlist_sources=[], inventory_entries=OFFLINE_INVENTORY
        )
        assert code == EXIT_FAILCLOSED
        assert report["allowlist_size"] == 0
        assert report["derived_deletable_uuids"] == 0
        assert report["manifest_sha256"] == hashlib.sha256(b"").hexdigest()
        assert any("外溢面拒绝" in v for v in report["violations"])


class TestR3BlankSourceIdFailClosed:
    """A 阻塞②:None/空串/纯空白 source_id 一致按无有效身份 fail-closed。"""

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_blank_source_id_is_identity_violation(self, blank):
        inv = base_inventory() + [(_u("stray-blank-binding"), blank)]
        res = run_ledger(inventory=inv)
        assert any("null" in v.lower() for v in res.violations)

    def test_blank_source_id_blocks_exit0_path(self):
        # 修复前:该输入 violations 为空、以 exit 0 计入审计总数(旁路)。
        # (doomed ⊆ allowlist 消除外溢噪声,空白 source_id 是唯一问题)
        inv = base_inventory() + [(_u("stray-blank-binding"), "")]
        res = compute_ledger(
            base_docs(), base_versions(), base_gens(), inv,
            tombstone_days=30, now=NOW,
            allowed_deleted_sources={SRC_A, SRC_B, SRC_C},
        )
        assert res.violations, "空白 source_id 必须产生 violation(无有效身份)"
        # 无身份对象绝不进入清理清单。
        assert _u("stray-blank-binding") not in res.derived_deletable_uuids

    def test_main_blank_source_id_exits_failclosed_with_report(self, tmp_path):
        inv = OFFLINE_INVENTORY + [(_u("cli-blank-binding"), "")]
        code, report = _run_offline_main(
            tmp_path, allowlist_sources=[SRC_A, SRC_B], inventory_entries=inv
        )
        assert code == EXIT_FAILCLOSED
        assert any("null" in v.lower() for v in report["violations"])


def _run_mixed_main(monkeypatch, tmp_path):
    """混合输入 main() 端到端:冻结清单 JSONL × 当前 live PG(fake),零网络。"""
    import backend.config as config_mod
    import backend.db.session as session_mod

    calls: dict = {}
    sync_sf = FakeSyncSessionFactory([list(LIVE_DOCS), list(LIVE_VERSIONS), list(LIVE_GENS)])

    real_load = gc_preflight._load_live_rows

    def spy_load(sf):
        calls["load_rows_factory"] = getattr(sf, "kind", "?")
        return real_load(sf)

    monkeypatch.setattr(gc_preflight, "_load_live_rows", spy_load)
    monkeypatch.setattr(
        config_mod, "load_settings",
        lambda: SimpleNamespace(postgres_dsn="postgresql+asyncpg://fake/fake"),
    )
    monkeypatch.setattr(session_mod, "get_sync_session_factory", lambda dsn_or_engine: sync_sf)

    inv = _write_inventory_jsonl(tmp_path, LIVE_INVENTORY)
    al = _write_allowlist(tmp_path, [SRC_A, SRC_B], sha256=True)
    rp = tmp_path / "report.json"
    code = gc_preflight.main([
        "--tombstone-days", "30",
        "--allowlist-json", str(al),
        "--inventory-jsonl", inv,
        "--report-json", str(rp),
    ])
    report = json.loads(rp.read_text())
    return code, report, calls


class TestR3ParityNotSilentlyBypassable:
    """A 阻塞③:live 预检强制双面 parity;skip/mixed 只能得不可作安全门的非零。"""

    def test_skip_crosscheck_cannot_pass(self, monkeypatch, tmp_path):
        # 潜伏资格漂移(sweep 若真跑对账必然 exit 3)+ 启用跳过参数:
        # 不得得到可误认的 PASS,只能是 unverified + 非零。
        code, report, calls = _run_live_main(
            monkeypatch, tmp_path,
            crosscheck=([SRC_C], [G0]),
            skip_crosscheck=True,
        )
        assert "crosscheck_factory" not in calls  # 对账确实未跑
        assert code == EXIT_UNVERIFIED
        assert code != EXIT_OK
        assert report["unverified"] is True
        assert report["unverified_reason"]
        assert "eligibility_drift" not in report

    def test_mixed_frozen_inventory_with_live_pg_cannot_pass(self, monkeypatch, tmp_path):
        # 冻结清单 JSONL × 当前 live PG = 混合时点、无 parity 证明:
        # 修复前 drift=None 且 violations 空 → EXIT_OK(可误认 PASS)。
        code, report, calls = _run_mixed_main(monkeypatch, tmp_path)
        assert calls["load_rows_factory"] == "sync"
        assert code == EXIT_UNVERIFIED
        assert report["unverified"] is True

    def test_partial_csv_group_failclosed(self, tmp_path):
        # CSV 冻结工件必须三件成组;部分提供=混合时点歧义 → fail-closed。
        docs_csv, _v, _g = _write_offline_csvs(tmp_path)
        inv = _write_inventory_jsonl(tmp_path, OFFLINE_INVENTORY)
        al = _write_allowlist(tmp_path, [SRC_A, SRC_B], sha256=True)
        code = gc_preflight.main([
            "--tombstone-days", "30",
            "--now-iso", NOW_ISO,
            "--allowlist-json", str(al),
            "--inventory-jsonl", inv,
            "--docs-csv", docs_csv,
        ])
        assert code == EXIT_FAILCLOSED

    def test_live_without_skip_still_enforces_parity(self, monkeypatch, tmp_path):
        # 反向锚:未跳过时双面 parity 仍强制(漂移走 exit 3 通道,
        # 而非 unverified 通道),既有授权路径不被削弱。
        code, report, calls = _run_live_main(
            monkeypatch, tmp_path, crosscheck=([SRC_A, SRC_B], [])
        )
        assert code == EXIT_ELIGIBILITY_DRIFT
        assert calls["crosscheck_factory"] == "async"
        assert "unverified" not in report
