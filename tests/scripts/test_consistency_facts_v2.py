"""一致性事实 v2(Issue #13 共享遥测五字段)契约测试。

PROPOSED_SHARED_INTERFACE 落地形态:全部收敛进 Wave-0 既有
``SyncRun.consistency`` jsonb 的增量键,不建第二套 observability model:
    duplicate_doc_count / polluted_artifact_chunks / retired_chunks /
    repaired_ledger_rows / repair_required
Wave-0 既有六键不变(消费方兼容);无账本上下文的调用点不伪造 0(键省略)。
"""

import pytest

from scripts.sync import _consistency_facts


def _report(*, expected=10, actual=10, orphans=0, refill=None, missing=None):
    from backend.services.vector_consistency import VectorGapReport

    return VectorGapReport(
        expected_chunks=expected,
        actual_chunks=actual,
        missing_source_ids=missing or [],
        refill_source_ids=refill or [],
        stale_chunk_count=0,
        orphan_count=orphans,
    )


def test_wave0_six_keys_unchanged():
    """既有六键逐字节兼容(共享契约消费方零感知)。"""
    facts = _consistency_facts(_report())
    assert facts == {
        "expected_chunks": 10,
        "actual_chunks": 10,
        "missing": 0,
        "refill": 0,
        "stale_chunk_count": 0,
        "orphan_count": 0,
        "repair_required": False,
    }


def test_repair_required_on_any_gap():
    assert _consistency_facts(_report(actual=8, refill=["x"]))["repair_required"] is True
    assert _consistency_facts(_report(orphans=2))["repair_required"] is True
    # 孤儿为零但存在污染 artifact(healthy 之外的事实)→ 仍需修复
    facts = _consistency_facts(
        _report(), identity_facts={"polluted_artifact_chunks": 5, "duplicate_doc_count": 0}
    )
    assert facts["repair_required"] is True
    assert facts["polluted_artifact_chunks"] == 5


def test_identity_and_repair_keys_only_when_known():
    facts = _consistency_facts(
        _report(orphans=1),
        identity_facts={"duplicate_doc_count": 3, "polluted_artifact_chunks": 21},
        retired_chunks=287,
        repaired_ledger_rows=1,
    )
    assert facts["duplicate_doc_count"] == 3
    assert facts["polluted_artifact_chunks"] == 21
    assert facts["retired_chunks"] == 287
    assert facts["repaired_ledger_rows"] == 1
    assert facts["repair_required"] is True
    # 无 identity_facts 时增量身份键省略(不伪造 0)
    bare = _consistency_facts(_report(orphans=1))
    assert "duplicate_doc_count" not in bare
    assert "polluted_artifact_chunks" not in bare
    assert "retired_chunks" not in bare
    assert "repaired_ledger_rows" not in bare
