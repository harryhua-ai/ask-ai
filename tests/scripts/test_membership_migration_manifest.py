"""#71 R2 — release migration contract for schema-dependent membership truth.

冻结部署契约(deploy/prod/migrations.json $contract):schema 变更必须先在
清单登记迁移脚本,再合入依赖它的应用代码。本测试把「membership_* 货币真值
列 ↔ 迁移清单登记」绑定为回归断言:未来候选若新增这些 schema 依赖列而遗漏
清单登记(或列与迁移脚本覆盖面漂移),必须在测试期即红,而非等到部署编排的
fail-closed 解析器在发布期拦截。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MEMBERSHIP_MIGRATION = "scripts/migrate_add_membership_currency.py"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest() -> dict:
    return json.loads((REPO_ROOT / "deploy/prod/migrations.json").read_text(encoding="utf-8"))


def test_m1_membership_truth_migration_is_registered_exactly_once():
    manifest = _manifest()
    entries = manifest["migrations"]
    assert entries.count(MEMBERSHIP_MIGRATION) == 1, (
        f"{MEMBERSHIP_MIGRATION} 必须在 deploy/prod/migrations.json 登记且恰好一次;"
        f"当前清单:{entries}"
    )
    # 既有登记保持原序且完好(加性位置 = 追加,不重排不删除)
    assert all(Path(REPO_ROOT, e).is_file() for e in entries), "清单条目必须存在于树内"


def test_m2_migration_covers_exactly_the_membership_model_columns():
    """列面 ↔ 迁移覆盖面逐字对齐:模型新增/删除 membership_* 列而未同步迁移
    (或反向)时即红 —— schema 依赖应用代码先于登记进入发布树的防线。"""
    from backend.db.models import DataSource
    import importlib

    model_columns = {
        c.name for c in DataSource.__table__.columns if c.name.startswith("membership_")
    }
    assert model_columns, "membership 货币真值列不应从模型中消失(#71 契约)"

    mod = importlib.import_module("scripts.migrate_add_membership_currency")
    migration_columns = set(mod._EXPECTED_COLUMNS)
    assert migration_columns == model_columns, (
        f"迁移脚本列覆盖面与模型漂移: migration-only={migration_columns - model_columns} "
        f"model-only={model_columns - migration_columns}"
    )
