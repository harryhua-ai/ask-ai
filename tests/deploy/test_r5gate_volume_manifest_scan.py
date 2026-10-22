"""r3gate R5:卷清单哈希假 PASS 定向窄修 —— 真实容器 RED→GREEN 与 fail-closed 证据。

A 审查裁决(issuecomment-6281863560):R4 卷清单扫描管道
``find . -type f -printf "%P\\t%s\\t%T@\\n" 2>/dev/null | LC_ALL=C sort | sha256sum``
三缺陷 —— ①`-printf` 为 GNU 扩展,Weaviate 1.28.0 官方镜像(Alpine/BusyBox
v1.37.0)不支持;②`2>/dev/null` 吞掉扫描错误;③无逐段校验,空输入仍得
有效哈希 e3b0c442…(两次扫同卷均同一空清单哈希)→ G2 控制面假 PASS 风险。

R5 修复(单一窄修对象,其余 R1–R4 成果不返工):
- 新规范脚本 scripts/weaviate_volume_manifest_scan.sh:逐段显式校验
  (卷根可达 → find 退出码 + stderr 必须为空 → 清单非空 -s → 逐文件
  stat 成功 + size/mtime 纯数字 → sort/sha256sum 退出码 → 64-hex 形状
  → FILES≥1),空/部分清单 fail-closed 退出码 3、stdout 绝无哈希,
  stderr 始终透传;**元数据清单,绝不读文件内容**(路径|大小|mtime 秒)。
- workflow 内嵌同字节副本经 stdin 送入容器执行(`docker exec -i "$WID"
  sh -s /var/lib/weaviate`,同 R3 脚本-via-stdin 无注入面模式);runner
  端三重校验:远端退出码 + 64-hex 哈希 + FILES≥1 证据行,任一缺失 →
  fail-closed 阻断 evaluator 与 migration;A 采锚路径同步(同一脚本同一
  形态,注释钉住)。

本模块证据(2026-10-20,真实容器 r4-weaviate-128,BusyBox v1.37.0):
- RED(真实容器):旧管道对非空卷 rc=0 输出空清单哈希 e3b0c442…(R5S-10);
- GREEN(真实容器):新扫描稳定输出、内容 A→B(mtime/size)变化敏感
  (R5S-11/12);空目录/根不可达/工具缺失/000 目录(以 nobody)全部
  fail-closed 无哈希(R5S-13..15);真实卷全量 FILES 与独立 find 计数
  交叉一致且两次运行确定(R5S-17)。

诚实边界(如实,PARTIAL 残余不宣称排除):
- 元数据清单原理性限制:内容被整体替换而 path/size/mtime 秒级元数据恰好
  一致时不可辨别(R4-1 既有残余,原样保留);
- 000 **常规文件**的元数据仍可 stat(元数据读取不需要文件读权限)→
  不构成扫描故障(R5S-16 钉住该边界);000 **目录**造成部分遍历,
  find 报错且 rc=1 → fail-closed(R5S-15);
- 路径按 find 换行协议;含 `|` 的文件名被行形状校验拦截为 fail。

红线:全部离线本地容器/静态断言;凭据零新增;不连生产、不 push、
不改门值;真实执行路径(真实容器 docker exec,非 fake shim)。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import uuid

import pytest
from test_r4gate_weaviate_identity_anchor import (
    REPO,
    WORKFLOW,
    _preflight_run_text,
    _volscan_embedded_script,
)

SCAN_SRC = REPO / "scripts" / "weaviate_volume_manifest_scan.sh"
CONTAINER = "r4-weaviate-128"

# R4 被移除的旧管道逐字命令(仅在本模块内作为 RED 复现/回归钉住对象,
# workflow 与扫描脚本中已不存在)
_OLD_PIPELINE = (
    'cd "{root}" && find . -type f -printf "%P\\t%s\\t%T@\\n" '
    "2>/dev/null | LC_ALL=C sort | sha256sum"
)

_OK_RE = re.compile(r"^VOLSCAN_OK MANIFEST_SHA256=([0-9a-f]{64}) FILES=([1-9][0-9]*)$")


def _script_text() -> str:
    return SCAN_SRC.read_text(encoding="utf-8")


def _parse_ok(stdout: str) -> tuple[str, int]:
    """成功输出必须恰一行且形状合法(64hex 哈希 + FILES≥1)。"""
    lines = [l for l in stdout.splitlines() if l.strip()]
    assert len(lines) == 1, f"成功输出必须恰一行,得: {stdout!r}"
    m = _OK_RE.match(lines[0])
    assert m, f"输出形状异常: {lines[0]!r}"
    return m.group(1), int(m.group(2))


def _exec_sh(root: str, *, user: str | None = None) -> subprocess.CompletedProcess:
    """与 workflow 同形态:扫描脚本经 stdin 送入容器执行。"""
    cmd = ["docker", "exec"]
    if user:
        cmd += ["--user", user]
    cmd += ["-i", CONTAINER, "sh", "-s", root]
    return subprocess.run(
        cmd, input=_script_text(), capture_output=True, text=True, timeout=120,
        check=False,
    )


def _container_sh(cmd: str, *, user: str | None = None,
                  timeout: int = 120) -> subprocess.CompletedProcess:
    argv = ["docker", "exec"]
    if user:
        argv += ["--user", user]
    argv += [CONTAINER, "sh", "-c", cmd]
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _container_up() -> bool:
    try:
        return subprocess.run(
            ["docker", "exec", CONTAINER, "true"],
            capture_output=True, timeout=15, check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_requires_container = pytest.mark.skipif(
    not _container_up(), reason="本地真实 weaviate 容器未运行(r4-weaviate-128)"
)


def _strip_comment_lines(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


@pytest.fixture
def seeded_dir():
    """容器内非空测试目录(2 个常规文件,确定 mtime);teardown 确定性清理。"""
    name = f"/tmp/r5gate-{uuid.uuid4().hex[:12]}"
    r = _container_sh(
        f'mkdir -p "{name}/sub" && printf AAA > "{name}/a.txt" && '
        f'printf BBBB > "{name}/sub/b.txt" && '
        f'touch -t 202601010000.00 "{name}/a.txt" "{name}/sub/b.txt"'
    )
    assert r.returncode == 0, r.stderr
    yield name, 2
    _container_sh(f'rm -rf "{name}"')


# --------------------------------------------------------------------------- #
# 静态断言(无容器):缺陷移除、接线、内嵌一致性、元数据边界
# --------------------------------------------------------------------------- #


def test_r5s01_old_defective_pipeline_removed_from_workflow():
    """旧管道(-printf/吞 stderr/末环独信)不再存在于任何可执行行;
    缺陷命令仅允许出现在注释(修复说明)中。"""
    run_exec = _strip_comment_lines(_preflight_run_text())
    assert "-printf" not in run_exec
    assert "2>/dev/null | LC_ALL=C sort | sha256sum" not in run_exec
    wf_text = WORKFLOW.read_text(encoding="utf-8")
    assert "find . -type f -printf" not in _strip_comment_lines(wf_text)


def test_r5s02_scan_script_retained_as_audit_tool_not_deploy_wired():
    """2026-10-22 通道裁决:动态卷清单哈希退出发布强制锚(活卷随活跃同步
    漂移;见 docs/release/v164-r3-g2-anchor-drift-analysis.md)。扫描脚本
    保留为辅助审计工具(仓库内存在且自身行为不变),但 workflow 不再内嵌
    副本、不再在部署链消费 —— 机械锁定"非接线"状态,防止静默复活或误配。
    """
    import yaml

    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "VOLSCAN_SH" not in wf, "workflow 不再内嵌卷扫描脚本(退出发布链)"
    assert "VOLSCAN_OK" not in wf and "MANIFEST_SHA256" not in wf, (
        "发布链不得消费动态清单哈希"
    )
    # 脚本本体保留为审计工具
    assert SCAN_SRC.is_file(), "扫描脚本保留为辅助审计工具(scripts/)"
    # 审计使用形态在脚本头注文档化(sh -s /var/lib/weaviate),与仓库脚本一致
    assert "sh -s /var/lib/weaviate" in SCAN_SRC.read_text(encoding="utf-8")



def test_r5s03_deploy_chain_has_no_dynamic_manifest_consumption():
    """2026-10-22:部署链零 VOLSCAN 消费点(退出强制锚);预检数据隔离
    断言由容器内 evaluator + 已审核身份事实承担(见 test_channel_adapt_*)。
    本测试钉住"无消费"状态:防止未来有人把动态哈希重新接线而未过评审。"""
    import yaml

    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    preflight = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("id") == "preflight"][0]
    run = preflight["run"]
    assert "VOLSCAN" not in run
    assert "sha256sum" in run, "容器内工件完整性核对(R4-3①)保留"
    assert "--verify-upload-isolation" in run, "数据隔离断言保留"

def test_r5s04_scanner_never_reads_volume_file_contents():
    """元数据清单边界:扫描器绝不读卷内文件内容 —— 无 cat/xargs/重定向
    读文件;sha256sum 仅作用于元数据清单临时文件。"""
    s = _script_text()
    exec_lines = _strip_comment_lines(s)
    assert 'cat "$ERR" >&2' in exec_lines, "cat 仅允许透传 find stderr 捕获文件"
    assert "cat" not in exec_lines.replace('cat "$ERR" >&2', "")
    assert "xargs" not in exec_lines and "< \"$F\"" not in exec_lines
    assert "head -c" not in exec_lines and "dd " not in exec_lines
    assert 'sha256sum "$META"' in exec_lines
    assert exec_lines.count('sha256sum "$META"') == 1, \
        "sha256sum 仅调用一次且仅作用于元数据清单,绝不用于卷内文件"
    assert 'sha256sum "$F"' not in exec_lines
    assert "stat -c '%n|%s|%Y' \"$F\"" in exec_lines, "卷内文件只允许 stat(元数据)"


def test_r5s05_dynamic_anchor_retirement_documented():
    """2026-10-22:动态锚退役与替代身份事实在 workflow 头注 + 漂移分析
    文档双向锚定;旧 GNU find -printf 采锚命令仍被显式禁止(审计面)。"""
    wf_text = WORKFLOW.read_text(encoding="utf-8")
    assert "deploy/prod/production-identity.json" in wf_text, "已审核身份事实文件被引用"
    drift_doc = (REPO / "docs" / "release" / "v164-r3-g2-anchor-drift-analysis.md")
    assert drift_doc.is_file(), "漂移语义分析文档在仓"
    assert "活性指纹" in drift_doc.read_text(encoding="utf-8")
    scan_text = SCAN_SRC.read_text(encoding="utf-8")
    assert "-printf" in scan_text, "扫描脚本头注继续显式禁止旧 GNU 命令"


@_requires_container
def test_r5s10_red_old_pipeline_empty_manifest_hash_on_nonempty_volume(seeded_dir):
    """RED(真实容器):旧管道对非空卷 rc=0 且输出**空清单哈希** e3b0c442…
    (-printf 报错被 2>/dev/null 吞掉 → 管道空输入 → sha256sum 照常出哈希)
    —— R5 要修复的假 PASS 本体,钉住防回归。"""
    root, n = seeded_dir
    assert n >= 1
    r = _container_sh(_OLD_PIPELINE.format(root=root))
    empty_hash = hashlib.sha256(b"").hexdigest()
    assert r.returncode == 0, "旧管道对扫描失败仍返回 0(缺陷 3)"
    assert r.stdout.split()[0] == empty_hash == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ), "非空卷必须复现空清单哈希"
    assert r.stderr == "", "旧管道 stderr 被吞(缺陷 2)"


@_requires_container
def test_r5s11_green_stable_wellformed_output(seeded_dir):
    """GREEN(真实容器):新扫描非空目录 → rc=0、恰一行合法证据输出
    (64hex + FILES=实际文件数),两次运行确定。"""
    root, n = seeded_dir
    r1 = _exec_sh(root)
    r2 = _exec_sh(root)
    for r in (r1, r2):
        assert r.returncode == 0, r.stderr
    hex1, files1 = _parse_ok(r1.stdout)
    hex2, files2 = _parse_ok(r2.stdout)
    assert hex1 == hex2 and files1 == files2 == n


@_requires_container
def test_r5s12_green_change_sensitivity_matrix(seeded_dir):
    """GREEN(真实容器):内容 A→B 变化敏感 —— 追加(size+mtime)/仅
    mtime(touch)/新增/删除 均改变哈希;还原后回到基线(确定性)。"""
    root, _ = seeded_dir
    base, base_n = _parse_ok(_exec_sh(root).stdout)

    def scan_hex() -> str:
        r = _exec_sh(root)
        assert r.returncode == 0, r.stderr
        h, n = _parse_ok(r.stdout)
        return f"{h}:{n}"

    # (a) 追加内容:size 与 mtime 同时变化
    _container_sh(f'printf MORE >> "{root}/a.txt"')
    assert scan_hex() != f"{base}:{base_n}", "追加内容未改变哈希"
    # (b) 仅 mtime 变化(同 size)
    _container_sh(f'touch -t 202701010000.00 "{root}/a.txt"')
    assert scan_hex() != f"{base}:{base_n}", "仅 mtime 变化未改变哈希"
    # (c) 新增文件(FILES 计数随之变化)
    _container_sh(f'printf NEW > "{root}/new.txt"')
    h_add, n_add = _parse_ok(_exec_sh(root).stdout)
    assert n_add == base_n + 1 and h_add != base
    # (d) 删除文件
    _container_sh(f'rm "{root}/new.txt"')
    _, n_del = _parse_ok(_exec_sh(root).stdout)
    assert n_del == base_n
    # (e) 还原内容与 mtime → 回到基线(同一清单哈希,确定可复算)
    _container_sh(
        f'printf AAA > "{root}/a.txt" && touch -t 202601010000.00 "{root}/a.txt"'
    )
    h_back, n_back = _parse_ok(_exec_sh(root).stdout)
    assert (h_back, n_back) == (base, base_n)


@_requires_container
def test_r5s13_failclosed_empty_dir_and_missing_root(seeded_dir):
    """空目录/根不可达 → rc=3、stdout 绝无哈希、stderr 原因可见
    (空清单哈希 e3b0c442… 绝不产生)。"""
    empty = f"/tmp/r5gate-empty-{uuid.uuid4().hex[:12]}"
    _container_sh(f'mkdir -p "{empty}"')
    try:
        for bad_root in (empty, "/tmp/r5gate-does-not-exist"):
            r = _exec_sh(bad_root)
            assert r.returncode == 3, (bad_root, r.stdout, r.stderr)
            assert "VOLSCAN FAIL" in r.stderr
            assert not re.search(r"[0-9a-f]{64}", r.stdout), "fail 路径绝不输出哈希"
    finally:
        _container_sh(f'rm -rf "{empty}"')


@_requires_container
def test_r5s14_fault_tools_missing_fail_closed(seeded_dir):
    """故障注入:容器内扫描依赖缺失(PATH=/nonexistent)→ mktemp/find/
    stat/sha256sum 不可用 → fail-closed rc=3、无哈希、原因在 stderr。"""
    root, _ = seeded_dir
    cmd = ["docker", "exec", "-i", CONTAINER,
           "/bin/busybox", "env", "-i", "PATH=/nonexistent",
           "/bin/sh", "-s", root]
    r = subprocess.run(
        cmd, input=_script_text(), capture_output=True, text=True, timeout=60,
        check=False,
    )
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "VOLSCAN FAIL" in r.stderr and not re.search(r"[0-9a-f]{64}", r.stdout)


@_requires_container
def test_r5s15_fault_permission_denied_dir_as_nobody(seeded_dir):
    """故障注入(权限异常):000 目录使 nobody 的 find 部分遍历 → stderr
    透传(Permission denied 可见)+ rc=3 → BLOCKED,stdout 无哈希。"""
    root, _ = seeded_dir
    secret = f"{root}/secret"
    _container_sh(
        f'mkdir -p "{secret}" && printf SEC > "{secret}/h.txt" && '
        f'chmod 000 "{secret}"'
    )
    try:
        r = _exec_sh(root, user="nobody")
        assert r.returncode == 3, (r.stdout, r.stderr)
        assert "Permission denied" in r.stderr, "stderr 必须透传(不隐藏)"
        assert "VOLSCAN FAIL" in r.stderr
        assert not re.search(r"[0-9a-f]{64}", r.stdout), "部分清单绝不产生哈希"
    finally:
        _container_sh(f'chmod 755 "{secret}" && rm -rf "{secret}"')


@_requires_container
def test_r5s16_boundary_000_regular_file_metadata_still_statable(seeded_dir):
    """诚实边界钉住:000 **常规文件**的元数据(path/size/mtime)仍可 stat
    (元数据读取不需要文件读权限)→ 扫描成功且计入 FILES;内容仍零读取。
    这与元数据清单语义一致,如实保留为边界(000 目录才会部分遍历被拦)。"""
    root, n = seeded_dir
    locked = f"{root}/locked.txt"
    _container_sh(f'printf SECRET > "{locked}" && chmod 000 "{locked}"')
    try:
        r = _exec_sh(root, user="nobody")
        assert r.returncode == 0, r.stderr
        h, files = _parse_ok(r.stdout)
        assert files == n + 1, "000 常规文件元数据仍应计入清单(边界语义)"
        assert re.fullmatch(r"[0-9a-f]{64}", h)
    finally:
        _container_sh(f'chmod 644 "{locked}" && rm -f "{locked}"')


@_requires_container
def test_r5s17_full_real_volume_deterministic_and_cross_checked():
    """真实数据卷全量:对 /var/lib/weaviate 扫描 rc=0,FILES 与独立
    find 计数交叉一致(≥1),两次运行哈希确定;空清单哈希绝不出现。"""
    r = _exec_sh("/var/lib/weaviate")
    assert r.returncode == 0, r.stderr
    hex1, files1 = _parse_ok(r.stdout)
    assert hex1 != hashlib.sha256(b"").hexdigest()
    cnt = _container_sh(
        'cd /var/lib/weaviate && find . -type f -print | wc -l'
    )
    assert cnt.returncode == 0
    assert files1 == int(cnt.stdout.strip().split()[-1]) >= 1, "FILES 与独立计数交叉一致"
    hex2, files2 = _parse_ok(_exec_sh("/var/lib/weaviate").stdout)
    assert (hex2, files2) == (hex1, files1), "两次全量扫描确定"


@_requires_container
def test_r5s18_exit_code_propagates_through_docker_exec(seeded_dir):
    """runner 端可感知:脚本 fail-closed 退出码经 docker exec 原样透出
    (rc=3),workflow 端 VOLSCAN_RC 捕获通道真实有效。"""
    root, _ = seeded_dir
    r = _exec_sh(f"{root}/no-such-subpath")
    assert r.returncode == 3, "退出码必须穿透 docker exec(供 runner 端校验)"
    assert "卷根目录不可达" in r.stderr
