"""Issue #159:release-cut 回滚兼容声明真实性(上传源 fail-closed × 旧版缺省公开)。

已证事实(issue #159;tag ``v1.6.4-r2`` 与 accepted main@03a31868 对照):

- v1.6.4-r2 ``backend/services/source_visibility.py``:已知源缺
  ``channel_visibility`` 时 ``_as_visibility`` 回退
  ``DEFAULT_VISIBILITY = ("widget", "api")``(公开;DB loader 对全部已知源
  一律走该回退,无 upload 特判);
- accepted main:``visibility_for_source`` 对 ``filesystem + upload_mode=true``
  缺/非法 grant → ``()``(fail-closed);两版都识别显式 ``[]`` 与
  ``["widget"]``/``["api"]``。
  ⇒ 从 v1.6.4-r2 普通回滚会把 fail-closed 的上传源重新变公开 = 真实安全
  语义差异;#46 时点 ``previous_compatible: true`` 的加性升级依据
  (#100/#102)对该切点不再成立。

因此下一正式发行(从 mutable main 切出)的 release-owned
``deploy/prod/compatibility.json`` 不得在无可靠双版本来源 ACL/缓存/旧
chunk 回滚证据时宣告 ``rollback.previous_compatible=true``:

- AC1:manifest 必须 ``previous_compatible=false`` + 含义明确且非敏感的
  ``remediation_gate``;preflight 解析之并禁止普通回滚指引;
- AC2(A #138 P3 演进,2026-10-20):remediation 确认缺失/错误/过期 ⇒ 任何
  DB/配置/应用 mutation 前 fail-closed。GitHub Production Deployment 正规
  路径仍**不提供字符串 ack 通道**;字符串 ``--remediation-ack`` 本身不再是
  合法放行(「仅有字符串相等判断的 remediation_ack 不是安全整改证明,不能
  凭命令行传入相同字符串获得合法放行」)——唯一合法放行面 = 绑定目标发行
  与证据身份的整改证据工件(``update.sh --remediation-evidence-file`` +
  ``--release-tag``;workflow 经 ``PREFLIGHT_REMEDIATION_EVIDENCE_B64``
  消费同一机制),且证据工件存在不代替 #121 实际生产验证与 A 对证据本身
  的 GO 判断;
- AC3:两版 known-upload missing/[]/[widget]/[api] 授权差异、release
  manifest 判定、update.sh 回滚文案与渠道负例,全部只读/本地模拟;
  不扩大任何来源授权、不改默认隔离。

本文件零网络、零 docker、零生产 mutation;旧版语义以 tag 冻结事实本地模拟。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from backend.services.source_visibility import (
    SourceVisibilityGuard,
    policy_for_source,
    visibility_for_source,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "deploy" / "prod" / "compatibility.json"
UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
DOCKERFILE = REPO / "Dockerfile"

# 下一发行的修复门(冻结在本测试 = 审计基准):名称自描述且非敏感 ——
# 普通回退到原正式版未经证明,恢复面 = issue #121 的 upload-source ACL
# 修复路径;不含任何 source id / 主机 / 凭证语义。
GATE = "upload-source-acl-verified-issue-121"

LEGACY_TAG = "v1.6.4-r2"
# 冻结自 tag v1.6.4-r2:backend/services/source_visibility.py DEFAULT_VISIBILITY
LEGACY_DEFAULT_VISIBILITY: tuple[str, ...] = ("widget", "api")

UPLOAD_SRC = "upload-legacy/doc.md"
UPLOAD_PREFIX = "upload-legacy"


# --------------------------------------------------------------------------- #
# AC3:两版授权语义(只读模拟;legacy = tag v1.6.4-r2 冻结事实)
# --------------------------------------------------------------------------- #


def legacy_v164r2_resolution(raw_channel_visibility: object) -> tuple[str, ...]:
    """v1.6.4-r2 已知源授权解析(冻结模拟)。

    旧版无 upload 特判:DB loader 对每个已知源行执行
    ``_as_visibility((cfg or {}).get("channel_visibility"))``,
    None/非法非列表值 → DEFAULT_VISIBILITY(公开)。
    """
    if isinstance(raw_channel_visibility, (list, tuple)):
        return tuple(str(v) for v in raw_channel_visibility)
    if isinstance(raw_channel_visibility, str) and raw_channel_visibility:
        return (raw_channel_visibility,)
    return LEGACY_DEFAULT_VISIBILITY


class LegacyVisibilityGuard:
    """v1.6.4-r2 ``SourceVisibilityGuard.allows`` 的冻结逻辑模拟。

    与现版相同的探测语义(admin→widget 别名;channel=None → DENY;
    unknown source → DENY),差异只在授权解析缺省(上函数)。
    """

    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self._mapping = mapping

    async def allows(self, source_id: str, channel: str | None) -> bool:
        if channel is None:
            return False  # 未知请求上下文 → DENY
        probe = "widget" if channel == "admin" else channel
        visibility = self._mapping.get(source_id.split("/")[0])
        if visibility is None:
            return False  # unknown / ghost source → DENY
        return probe in visibility


def _current_guard_for(config: dict) -> SourceVisibilityGuard:
    mapping = {UPLOAD_PREFIX: policy_for_source("filesystem", config)}
    return SourceVisibilityGuard(lambda: _async_mapping(mapping), ttl=60)


def _legacy_guard_for(config: dict) -> LegacyVisibilityGuard:
    mapping = {UPLOAD_PREFIX: legacy_v164r2_resolution(config.get("channel_visibility"))}
    return LegacyVisibilityGuard(mapping)


async def _async_mapping(mapping):
    return mapping


UPLOAD_MISSING = {"upload_mode": True}
UPLOAD_EMPTY = {"upload_mode": True, "channel_visibility": []}
UPLOAD_WIDGET = {"upload_mode": True, "channel_visibility": ["widget"]}
UPLOAD_API = {"upload_mode": True, "channel_visibility": ["api"]}


def test_legacy_upload_missing_grant_defaults_public():
    """RED 事实锚:旧版 known-upload 缺 grant → 公开(回滚即重开 Widget/API)。"""
    assert legacy_v164r2_resolution(None) == ("widget", "api")
    assert legacy_v164r2_resolution(UPLOAD_MISSING.get("channel_visibility")) == (
        "widget",
        "api",
    )


def test_current_upload_missing_or_illegal_grant_failclosed():
    """现版 known-upload 缺/非法 grant → ()(fail-closed;不扩大授权)。"""
    assert visibility_for_source("filesystem", UPLOAD_MISSING) == ()
    assert visibility_for_source("filesystem", UPLOAD_EMPTY) == ()
    # 非法 grant 形状/成员同样 fail-closed:
    assert (
        visibility_for_source("filesystem", {"upload_mode": True, "channel_visibility": "widget"})
        == ()
    )
    assert (
        visibility_for_source("filesystem", {"upload_mode": True, "channel_visibility": ["admin"]})
        == ()
    )


def test_two_version_grant_matrix_on_known_upload_source():
    """两版 known-upload 授权差异矩阵:missing/[]/[widget]/[api](+非法 grant)。

    差异必须恰好集中在缺省/非法 grant(旧版公开、新版 fail-closed);
    显式授权两版一致(回滚不改变显式 []/[widget]/[api] 语义)。
    """
    cases = [
        # (label, raw, legacy_expect, current_expect)
        ("missing", None, ("widget", "api"), ()),
        ("explicit_empty", [], (), ()),
        ("explicit_widget", ["widget"], ("widget",), ("widget",)),
        ("explicit_api", ["api"], ("api",), ("api",)),
        # 非法形状/成员:旧版回退缺省或原样保留,新版一律 ()
        ("illegal_string", "widget", ("widget",), ()),
        ("illegal_members", ["admin"], ("admin",), ()),
    ]
    for label, raw, legacy_expect, current_expect in cases:
        config = {"upload_mode": True}
        if raw is not None:
            config["channel_visibility"] = raw
        assert legacy_v164r2_resolution(raw) == legacy_expect, label
        assert visibility_for_source("filesystem", config) == current_expect, label


def test_non_upload_sources_keep_legacy_public_default():
    """非 upload 来源两版一致(默认隔离不被本切点改变;无授权扩大/收紧)。"""
    for source_type in ("github", "filesystem"):
        for config in ({}, {"upload_mode": False}, {"channel_visibility": None}):
            raw = config.get("channel_visibility")
            assert legacy_v164r2_resolution(raw) == ("widget", "api")
            assert visibility_for_source(source_type, config) == ("widget", "api"), (
                source_type,
                config,
            )
    # 非 upload 的显式 grant 两版同形(不被本切点触碰):
    assert legacy_v164r2_resolution("widget") == ("widget",)
    assert visibility_for_source("github", {"channel_visibility": "widget"}) == ("widget",)


# --------------------------------------------------------------------------- #
# AC3:服务面渠道负例(两版对照;current = 真实 serving 守卫)
# --------------------------------------------------------------------------- #


async def _allows_all(guard, channels) -> dict[str, bool]:
    return {str(ch): await guard.allows(UPLOAD_SRC, ch) for ch in channels}


REQUEST_CHANNELS = ["widget", "api", "admin", "mobile", None]


async def test_rollback_would_reopen_missing_grant_upload_source():
    """THE 暴露:缺 grant 上传源 —— 旧版(回滚后)对 widget/api/admin 全放行,
    现版全拒;channel=None/mobile 负例两版皆 DENY。"""
    legacy = await _allows_all(_legacy_guard_for(UPLOAD_MISSING), REQUEST_CHANNELS)
    current = await _allows_all(_current_guard_for(UPLOAD_MISSING), REQUEST_CHANNELS)
    assert legacy == {"widget": True, "api": True, "admin": True, "mobile": False, "None": False}
    assert current == {
        "widget": False,
        "api": False,
        "admin": False,
        "mobile": False,
        "None": False,
    }


async def test_explicit_grants_channel_negatives_identical_across_versions():
    """显式授权的渠道负例两版一致:未知渠道/None 一律 DENY,无授权扩大。"""
    for config, expect in (
        (
            UPLOAD_EMPTY,
            {"widget": False, "api": False, "admin": False, "mobile": False, "None": False},
        ),
        (
            UPLOAD_WIDGET,
            {"widget": True, "api": False, "admin": True, "mobile": False, "None": False},
        ),
        (
            UPLOAD_API,
            {"widget": False, "api": True, "admin": False, "mobile": False, "None": False},
        ),
    ):
        legacy = await _allows_all(_legacy_guard_for(config), REQUEST_CHANNELS)
        current = await _allows_all(_current_guard_for(config), REQUEST_CHANNELS)
        assert legacy == expect, config
        assert current == expect, config


# --------------------------------------------------------------------------- #
# AC1:release manifest 判定(真实发布树工件 × preflight evaluator)
# --------------------------------------------------------------------------- #


def test_repo_manifest_declares_rollback_incompatible_with_explicit_gate():
    """AC1:发布树 manifest 不得虚报 previous_compatible=true;必须携带
    明确含义且非敏感的 remediation_gate(preflight 可解析的现有 v1 字段)。"""
    rollback = json.loads(MANIFEST.read_text(encoding="utf-8"))["rollback"]
    assert rollback["previous_compatible"] is False, (
        "v1.6.4-r2(缺省公开)→ main(上传源 fail-closed)的切点在未取得双版本 "
        "ACL/缓存/旧 chunk 回滚证据前,不得宣告普通 previous-tag 回滚兼容"
    )
    gate = rollback["remediation_gate"]
    assert gate == GATE
    assert re.fullmatch(
        r"[a-z0-9][a-z0-9-]{2,80}", gate
    ), "gate 必须是有界、非敏感的自描述令牌(不含 source id/主机/凭证语义)"


def _run_preflight_cli(monkeypatch, *extra: str) -> tuple[int, dict]:
    from scripts.release_preflight import main

    # 只读有界探针的环境无关化(#46 既有测试同款):真实判定目标 = rollback 门
    monkeypatch.setattr("scripts.release_preflight._run_probe", lambda cmd, timeout_s: (0, "GPU"))
    argv = ["--manifest", str(MANIFEST), *extra]
    code = main(argv)
    return code


def test_preflight_blocks_unconfirmed_rollback_on_repo_manifest(monkeypatch, capsys):
    """AC1/AC2:本发布声明普通回滚不兼容 ⇒ 缺确认时 preflight fail-closed,
    拒绝信息指明所声明的 gate(actionable)。"""
    code = _run_preflight_cli(monkeypatch)
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    chk = [c for c in out["checks"] if c["class"] == "rollback_remediation_gate_required"]
    assert chk and GATE in chk[0]["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


def test_preflight_string_ack_alone_no_longer_releases(monkeypatch, capsys, tmp_path):
    """AC2(A #138 P3 演进):字符串 --remediation-ack 即使与声明 gate 精确
    匹配,也不再构成合法放行 —— fail-closed 且结构化指引指向证据工件。
    契约方向 = 收紧(fail-closed 更严),非放宽。"""
    code = _run_preflight_cli(monkeypatch, "--remediation-ack", GATE)
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    chk = [c for c in out["checks"] if c["class"] == "rollback_remediation_gate_required"]
    assert chk, out
    assert "不构成" in chk[0]["reason"]
    assert "--remediation-evidence-file" in chk[0]["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


def _write_remediation_evidence(path: Path, **overrides) -> Path:
    record = {
        "version": 1,
        "gate": GATE,
        "target_tag": "v9.9.9",
        "evidence_digest": "c" * 64,
        "evidence_ref": "recovery-drill/2026-10-20/bundle-sha",
        "recorded_at": "2026-10-20T12:00:00Z",
        "recorded_by": "role-a",
    }
    record.update(overrides)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_preflight_accepts_bound_remediation_evidence(monkeypatch, capsys, tmp_path):
    """AC2(P3 合法放行面):证据工件 gate/target_tag 与 manifest 声明及本次
    部署 --release-tag 精确绑定 ⇒ 通过;可回读身份字段(gate/tag/摘要)全部
    入 check reason。证据工件存在不改变 previous_compatible=false 声明。"""
    ev = _write_remediation_evidence(tmp_path / "evidence.json")
    code = _run_preflight_cli(
        monkeypatch,
        "--remediation-evidence-file", str(ev),
        "--release-tag", "v9.9.9",
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    ok = [c for c in out["checks"] if c["class"] == "rollback_ok"]
    assert ok, out
    reason = ok[0]["reason"]
    assert GATE in reason and "v9.9.9" in reason and "c" * 64 in reason
    assert not any(
        c["class"] == "rollback_remediation_gate_required" for c in out["checks"]
    )


def test_preflight_rejects_cross_release_evidence_binding(monkeypatch, capsys, tmp_path):
    """AC2(P3 绑定语义):证据 target_tag ≠ 本次部署 tag ⇒ 跨版本证据不可
    移作他用,fail-closed。"""
    ev = _write_remediation_evidence(tmp_path / "evidence.json", target_tag="v9.9.8")
    code = _run_preflight_cli(
        monkeypatch,
        "--remediation-evidence-file", str(ev),
        "--release-tag", "v9.9.9",
    )
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    chk = [c for c in out["checks"] if c["class"] == "rollback_remediation_gate_required"]
    assert chk and "v9.9.8" in chk[0]["reason"] and "v9.9.9" in chk[0]["reason"]


def test_preflight_rejects_wrong_and_stale_acks(monkeypatch, capsys):
    """AC2:错误/过期(历史 gate)确认 ⇒ 一律 fail-closed(精确匹配语义)。"""
    for bad_ack in ("some_other_gate", "release_mig_002_reindex", f"{GATE}-stale", ""):
        code = _run_preflight_cli(monkeypatch, "--remediation-ack", bad_ack)
        assert code == 2, bad_ack
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "fail", bad_ack


# --------------------------------------------------------------------------- #
# AC1:部署脚本回滚文案(真实 manifest 值驱动的条件化指引)
# --------------------------------------------------------------------------- #


def test_update_sh_wiring_reads_incompatible_verdict_from_repo_manifest():
    """机械接线:用 update.sh [3.5/6] 的**逐字**提取表达式读取发布树
    manifest,verdict 必须落在不兼容分支(false + gate)。"""
    compatible = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import json,sys;m=json.load(open(sys.argv[1]));"
                "print('true' if m.get('rollback',{}).get('previous_compatible', True) else 'false')"
            ),
            str(MANIFEST),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    gate = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import json,sys;print(json.load(open(sys.argv[1])).get('rollback',{})"
                ".get('remediation_gate','') or '')"
            ),
            str(MANIFEST),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert compatible == "false"
    assert gate == GATE


def _guidance_fn_bash() -> str:
    """从 update.sh 机械提取 print_postdeploy_rollback_guidance 函数体。"""
    text = UPDATE_SH.read_text()
    start = text.index("print_postdeploy_rollback_guidance() {")
    end = text.index("\n}", start) + 2
    return text[start:end]


def _run_guidance(env: dict) -> str:
    proc = subprocess.run(
        ["bash", "-c", f"{_guidance_fn_bash()}\nprint_postdeploy_rollback_guidance"],
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_postdeploy_guidance_for_this_release_never_advertises_ordinary_rollback():
    """AC1:本发布(verdict=false, gate=GATE)的 post-deploy 指引不得出现
    普通 previous-tag 回滚指引;必须点名修复门并显式声明不自动回滚。"""
    out = _run_guidance(
        {
            "PREFLIGHT_ERA": "contract",
            "ROLLBACK_COMPATIBLE": "false",
            "ROLLBACK_GATE": GATE,
        }
    )
    assert "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>" not in out
    assert GATE in out
    assert "previous_compatible=false" in out
    assert "remediation" in out.lower()
    assert "不执行自动回滚" in out


# --------------------------------------------------------------------------- #
# AC2:正规部署路径无授权保持阻断;唯一显式确认面;无硬编码 ack
# --------------------------------------------------------------------------- #


def test_production_workflow_offers_no_ack_channel_so_release_stays_blocked():
    """AC2(A #138 P3 演进):GitHub Production Deployment 正规路径不提供
    字符串 ack 通道 ⇒ 无整改证据时本发布声明在正规路径确定性 fail-closed
    (无授权保持阻断);合法放行通道 = 证据工件 secret
    PREFLIGHT_REMEDIATION_EVIDENCE_B64(可选:未配置 ⇒ 维持阻断),
    绑定校验由冻结发布镜像内的 evaluator fail-closed 执行。"""
    text = WORKFLOW.read_text()
    assert "--remediation-ack" not in text, "workflow 正规路径不得引入 ack 通道"
    assert "remediation_ack" not in text, "workflow 不得新增 ack 输入(改变 #46 契约语义)"
    # P3 合法放行通道 = 证据工件(可选 secret;步骤3 preflight 与步骤5
    # update.sh 两处消费);未配置 ⇒ rollback 门维持 fail-closed 阻断。
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_B64") >= 2, (
        "workflow 必须经证据 secret 通道消费整改事实(P3),不得引入字符串 ack"
    )
    required_line = [
        ln for ln in text.splitlines() if ln.strip().startswith("for v in SSH_KEY")
    ]
    assert required_line and all(
        "REMEDIATION_EVIDENCE_B64" not in ln for ln in required_line
    ), "证据通道必须可选:未配置时不得阻断非本门的部署流程(现状不变)"
    # 契约期 evaluator 以裸调用执行(无任何 ACK 参数);失败即步骤失败。
    # R3-2:调用形态改为运行中 backend 容器内执行(凭据经容器自身 env 继承),
    # 语义不变 —— 裸调用、非零退出经 CONTAINER_RC 传播为步骤失败。
    assert "python3 /tmp/askai-preflight-evaluator.py" in text
    assert "CONTAINER_RC=0" in text
    assert '|| CONTAINER_RC=$?' in text
    assert 'exit "$CONTAINER_RC"' in text


def test_update_sh_evaluator_failure_fails_closed_before_any_mutation():
    """AC2:update.sh 内 evaluator 非零退出 ⇒ 立即退出,先于任何 rollout;
    ack 初值为空(无默认 ack)。"""
    text = UPDATE_SH.read_text()
    guard = '|| { rm -f "$PREFLIGHT_MAN" "$PREFLIGHT_EVAL"; exit 1; }'
    assert guard in text, "evaluator 失败必须在任何 mutation 之前 fail-closed"
    eval_idx = text.index('python3 "$PREFLIGHT_EVAL"')
    guard_idx = text.index(guard, eval_idx)
    rollout_idx = text.index("up -d backend")
    assert guard_idx < rollout_idx, "fail-closed 退出必须先于应用 rollout"
    assert 'REMEDIATION_ACK=""' in text
    assert 'REMEDIATION_EVIDENCE_FILE=""' in text, (
        "证据文件初值必须为空(无默认证据,显式提供面)"
    )
    assert '--release-tag "$TAG"' in text, (
        "evaluator 调用必须绑定本次部署 tag(P3 目标发行绑定)"
    )


def test_gate_string_is_not_hardcoded_into_any_deploy_or_code_surface():
    """AC2 反伪证:gate 名只允许出现在 release-owned manifest 与本审计测试中;
    部署脚本 / workflow / Dockerfile / 任何脚本源码不得内嵌(杜绝默认 ack
    与自动绕过)。"""
    surfaces = [UPDATE_SH, WORKFLOW, DOCKERFILE, *sorted((REPO / "scripts").glob("*.py"))]
    for path in surfaces:
        assert GATE not in path.read_text(
            encoding="utf-8"
        ), f"remediation gate 不得硬编码进 {path.name}(必须由操作者显式提供)"
