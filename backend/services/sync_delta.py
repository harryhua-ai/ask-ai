"""可审计的同步增量记账契约(#65)。

``SyncLog.items_*`` 是历史字段，其中 ``items_updated`` 在旧版本中实际
表示写入 chunk 数，不能被读面静默重命名为“更新文档数”。新同步写入
``delta_counts``，所有并列增量都使用稳定的 document 单位；旧行没有该
字段时，调用方必须呈现单位不可用。
"""

from __future__ import annotations

from typing import Any

DELTA_SCHEMA_VERSION = 1
ADMIN_DELTA_UNIT = "document"


def _non_negative(name: str, value: int) -> int:
    value = int(value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def build_document_delta(
    *,
    new_count: int = 0,
    updated_count: int = 0,
    retired_count: int = 0,
    unchanged_count: int = 0,
    reason: str | None = None,
    ledger_rebuilt_count: int = 0,
    orphan_vectors_retired: int = 0,
    mirror_reconciled_count: int = 0,
) -> dict[str, Any]:
    """构造 document 级增量；一个文档只进入一个变更桶。

    加性事实键(#71 授权契约第 13 条):``ledger_rebuilt_count``(文档;
    孤儿向量对应的账本行重建)、``orphan_vectors_retired``(chunk;孤儿
    向量精确退休)与 ``mirror_reconciled_count``(#105;行镜像滞后残形的
    无变更轮对账)是投影修复计数,绝不混入 document 变更桶或 items_*。
    """
    result: dict[str, Any] = {
        "schema_version": DELTA_SCHEMA_VERSION,
        "unit": ADMIN_DELTA_UNIT,
        "new_count": _non_negative("new_count", new_count),
        "new_unit": ADMIN_DELTA_UNIT,
        "updated_count": _non_negative("updated_count", updated_count),
        "updated_unit": ADMIN_DELTA_UNIT,
        "retired_count": _non_negative("retired_count", retired_count),
        "retired_unit": ADMIN_DELTA_UNIT,
        "unchanged_count": _non_negative("unchanged_count", unchanged_count),
        "unchanged_unit": ADMIN_DELTA_UNIT,
        "ledger_rebuilt_count": _non_negative("ledger_rebuilt_count", ledger_rebuilt_count),
        "ledger_rebuilt_unit": ADMIN_DELTA_UNIT,
        "orphan_vectors_retired": _non_negative("orphan_vectors_retired", orphan_vectors_retired),
        "orphan_vectors_retired_unit": "chunk",
        "mirror_reconciled_count": _non_negative(
            "mirror_reconciled_count", mirror_reconciled_count
        ),
        "mirror_reconciled_unit": ADMIN_DELTA_UNIT,
    }
    if reason:
        result["reason"] = reason
    return result


def document_delta_from_log(log: Any) -> dict[str, Any] | None:
    """仅读取新契约；不从历史混合 ``items_updated`` 反推文档更新数。"""
    value = getattr(log, "delta_counts", None)
    return dict(value) if isinstance(value, dict) else None
