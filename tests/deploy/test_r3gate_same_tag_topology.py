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


# --------------------------------------------------------------------------- #
# R2-6③:同 tag 守卫逻辑的运行时动态验证(静态文本断言之上升级)
#
# 静态断言只证明"片段存在";本节把 update.sh 中的 [6/6] tag 校验片段在
# 测试运行时**原样提取**(markers: ``for SVC in backend sync-cron
# sync-executor; do`` 起始,至配对 ``done``),在受控 bash fixture 中配合
# fake docker(受控 PATH)对正/负例真实执行 —— 守卫逻辑行为被动态验证,
# 而非仅文本存在。若上游片段被改名/移除,提取失败即测试失败(钉住不放松)。
# 全程零真实 docker/compose 调用(fake docker 只读状态文件),无任何 mutation。
# --------------------------------------------------------------------------- #

_FOR_MARKER = "for SVC in backend sync-cron sync-executor; do"


def _extract_same_tag_fragment() -> str:
    """从发布树 update.sh 原样提取 [6/6] tag 校验 for 循环片段。"""
    script = (_REPO_ROOT / "deploy" / "prod" / "update.sh").read_text(encoding="utf-8")
    lines = script.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == _FOR_MARKER.strip()),
        None,
    )
    assert start is not None, "update.sh 缺同 tag 校验 for 循环(守卫被移除?)"
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        collected.append(line)
        if line.strip() == "done":
            break
    else:
        raise AssertionError("update.sh 同 tag 校验 for 循环缺配对 done(片段被破坏)")
    return "\n".join(collected)


def _write_fake_docker(bin_dir: Path, state_file: Path) -> None:
    """受控 docker 替身:compose ps -q <svc> → 状态文件查 CID;inspect → 查镜像。"""
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'STATE="$FAKE_DOCKER_STATE"\n'
        'if [ "$1" = "compose" ]; then\n'
        "  for _last; do :; done\n"
        '  awk -F "\\t" -v svc="$_last" \'$1=="cid" && $2==svc {print $3}\' "$STATE"\n'
        'elif [ "$1" = "inspect" ]; then\n'
        '  awk -F "\\t" -v cid="$4" \'$1=="img" && $2==cid {print $3}\' "$STATE"\n'
        "else\n"
        '  echo "unexpected docker call: $*" >&2\n'
        "  exit 64\n"
        "fi\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)


def _run_fragment(tag: str, images: dict, tmp_path: Path) -> "subprocess.CompletedProcess":
    import os
    import subprocess

    state = tmp_path / "state.tsv"
    cids = {}
    lines = []
    for i, (svc, image) in enumerate(images.items()):
        cid = f"cid-{i}"
        cids[svc] = cid
        lines.append(f"cid\t{svc}\t{cid}")
        lines.append(f"img\t{cid}\t{image}")
    state.write_text("\n".join(lines) + "\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_fake_docker(bin_dir, state)

    fragment = _extract_same_tag_fragment()
    script = tmp_path / "same_tag_guard.sh"
    script.write_text(
        f"TAG={tag}\nCOMPOSE_FILE=/nonexistent/compose.yml\n{fragment}\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_DOCKER_STATE"] = str(state)
    return subprocess.run(  # noqa: S603 - 固定词表 argv,受控 fixture
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_same_tag_guard_runtime_dynamic_all_match_passes(tmp_path):
    """正例:三服务镜像 tag == 部署 tag → 提取的真实守卫逻辑退出 0。"""
    tag = "v1.6.4-r2"
    proc = _run_fragment(
        tag,
        {
            "backend": f"ghcr.io/harryhua-ai/ask-ai-backend:{tag}",
            "sync-cron": f"ghcr.io/harryhua-ai/ask-ai-sync-cron:{tag}",
            "sync-executor": f"ghcr.io/harryhua-ai/ask-ai-sync-executor:{tag}",
        },
        tmp_path,
    )
    assert proc.returncode == 0, f"正例必须通过:{proc.stdout}{proc.stderr}"
    assert proc.stdout.count("✅") == 3, "三服务必须逐一核对"


def test_same_tag_guard_runtime_dynamic_mismatch_fails(tmp_path):
    """负例:任一服务镜像 tag 不一致 → 真实守卫逻辑非零退出并点名服务。"""
    proc = _run_fragment(
        "v1.6.4-r2",
        {
            "backend": "ghcr.io/harryhua-ai/ask-ai-backend:v1.6.4-r2",
            "sync-cron": "ghcr.io/harryhua-ai/ask-ai-sync-cron:v1.6.4-r2",
            "sync-executor": "ghcr.io/harryhua-ai/ask-ai-sync-executor:v1.6.3",
        },
        tmp_path,
    )
    assert proc.returncode == 1, f"镜像不一致必须非零退出:{proc.stdout}{proc.stderr}"
    assert "sync-executor" in proc.stdout, "必须点名不一致的服务"


def test_same_tag_guard_runtime_dynamic_suffix_not_confused(tmp_path):
    """负例(边界):TAG=v1.6.4 vs 镜像 …:v1.6.4-rc1 —— *\":$TAG\" 锚定
    冒号后完整 tag,rc 变体不得被误判为同 tag(放行即跨版本部署面)。"""
    proc = _run_fragment(
        "v1.6.4",
        {
            "backend": "ghcr.io/x/backend:v1.6.4",
            "sync-cron": "ghcr.io/x/sync-cron:v1.6.4",
            "sync-executor": "ghcr.io/x/sync-executor:v1.6.4-rc1",
        },
        tmp_path,
    )
    assert proc.returncode == 1, "rc 变体不得冒充同 tag(冒号锚定后缀必须精确)"
