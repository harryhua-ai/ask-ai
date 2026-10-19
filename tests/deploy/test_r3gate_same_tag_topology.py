"""T8:backend/sync-cron/sync-executor 混合版本 → same_tag_all_services 断言钉住。

评估器不可证 ⇒ preflight 显式 defer(test_release_preflight.py 已钉 defer 语义);
部署原语 ``deploy/prod/update.sh`` [6/6] 是真正的同 tag 强制点(三应用服务
逐一核对镜像 tag,任一不一致即非零退出)。本文件钉住发布树两端的接线证据,
防止任何一侧静默失联(胶囊:缺则补)。
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_tree_declares_same_tag_topology_requirement():
    manifest = json.loads(
        (_REPO_ROOT / "deploy" / "prod" / "compatibility.json").read_text(encoding="utf-8")
    )
    assert manifest["topology"] == [{"requirement": "same_tag_all_services"}]


def test_update_sh_same_tag_assertion_pinned():
    script = (_REPO_ROOT / "deploy" / "prod" / "update.sh").read_text(encoding="utf-8")
    assert "[6/6]" in script, "同 tag 一致性强制步 [6/6] 必须存在"
    for svc in ("backend", "sync-cron", "sync-executor"):
        assert svc in script, f"三应用服务 {svc} 必须被逐一核对"
    assert '*":$TAG"' in script, "必须逐一断言容器镜像 tag == 部署 tag"
    assert script.count("exit 1") >= 1
