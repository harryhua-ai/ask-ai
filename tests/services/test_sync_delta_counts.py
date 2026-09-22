"""#65 同步增量单位闭合契约测试。"""

import pytest


def test_document_delta_counts_use_one_stable_unit_without_double_counting():
    from backend.services.sync_delta import build_document_delta

    delta = build_document_delta(
        new_count=2,
        updated_count=3,
        retired_count=1,
        unchanged_count=4,
    )

    assert delta == {
        "schema_version": 1,
        "unit": "document",
        "new_count": 2,
        "new_unit": "document",
        "updated_count": 3,
        "updated_unit": "document",
        "retired_count": 1,
        "retired_unit": "document",
        "unchanged_count": 4,
        "unchanged_unit": "document",
        # #71 加性事实键:投影修复计数与 document 变更桶分离
        "ledger_rebuilt_count": 0,
        "ledger_rebuilt_unit": "document",
        "orphan_vectors_retired": 0,
        "orphan_vectors_retired_unit": "chunk",
        # #105 加性事实键:行镜像滞后残形的无变更轮对账(投影修复计数)
        "mirror_reconciled_count": 0,
        "mirror_reconciled_unit": "document",
    }


def test_document_delta_counts_reject_negative_values():
    from backend.services.sync_delta import build_document_delta

    with pytest.raises(ValueError, match="non-negative"):
        build_document_delta(new_count=-1)


def test_sync_log_legacy_items_updated_is_not_used_as_document_delta():
    from backend.db.models import SyncLog
    from backend.services.sync_delta import document_delta_from_log

    log = SyncLog(items_new=2, items_updated=99, items_deleted=1, items_unchanged=4)

    assert document_delta_from_log(log) is None
