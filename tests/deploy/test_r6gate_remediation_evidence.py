"""R6(G3):整改证据工件 = rollback remediation gate 的唯一合法放行面。

权威裁决:Role A #138「A 自审更正与下一步实际推进」(2026-10-20):

- 「当前仅有字符串相等判断的 remediation_ack 本身不是安全整改证明,不能凭
  命令行传入相同字符串获得合法放行」;
- P3:「release-owned evaluator 和官方 workflow 需有合规、可回读、绑定具体
  目标发行/证据身份的机制来消费该事实」。

本文件零网络、零 docker、零生产 mutation;全部判定基于临时 manifest/证据
工件本地构造(fail-closed 语义矩阵):

- T-EV-01 合法证据 + gate/target_tag 双绑定 ⇒ rollback_ok PASS(exit 0),
  可回读身份字段(gate/target_tag/digest/ref/recorded_at/recorded_by)入 reason;
- T-EV-02 无任何输入 ⇒ rollback_remediation_gate_required fail(exit 2);
- T-EV-03 字符串 --remediation-ack 精确匹配但无证据 ⇒ fail(A P3:不构成
  整改证明;结构化指引指向证据工件);
- T-EV-04 证据 gate ≠ manifest 声明 ⇒ 绑定失败 fail;
- T-EV-05 证据 target_tag ≠ --release-tag ⇒ 跨版本证据不可移用 fail;
- T-EV-06 形状非法矩阵(版本不符/词表外字段/gate 形状/tag 形状/摘要非
  64hex/时间不可解析/缺 release-tag)⇒ 一律 fail-closed,错误不回显内容;
- T-EV-07 previous_compatible=true ⇒ 零变化(证据通道不参与判定);
- T-EV-08 update.sh / workflow 机械接线(静态断言):透传、--release-tag
  绑定、base64 词表守卫、证据通道可选(未配置维持阻断)、workflow 无裸
  ack 通道。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"

GATE = "upload-source-acl-verified-issue-121"
TAG = "v9.9.9"
DIGEST = "b" * 64

INCOMPATIBLE_MANIFEST = {
    "version": 1,
    "config": [],
    "host": [],
    "topology": [],
    "dependencies": [],
    "rollback": {"previous_compatible": False, "remediation_gate": "gate-token-x"},
}

COMPATIBLE_MANIFEST = {
    "version": 1,
    "config": [],
    "host": [],
    "topology": [],
    "dependencies": [],
    "rollback": {"previous_compatible": True},
}


def _write_manifest(tmp_path: Path, rollback: dict) -> Path:
    manifest = dict(INCOMPATIBLE_MANIFEST if not rollback else COMPATIBLE_MANIFEST)
    if rollback:
        manifest["rollback"] = {"previous_compatible": False, "remediation_gate": "gate-token-x"}
    else:
        manifest["rollback"] = {"previous_compatible": True}
    path = tmp_path / "compatibility.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_evidence(
    tmp_path: Path,
    *,
    gate: str = "gate-token-x",
    target_tag: str = TAG,
    record: dict | None = None,
) -> Path:
    body = {
        "version": 1,
        "gate": gate,
        "target_tag": target_tag,
        "evidence_digest": DIGEST,
        "evidence_ref": "recovery-drill/2026-10-20/bundle-sha",
        "recorded_at": "2026-10-20T12:00:00Z",
        "recorded_by": "role-a",
    }
    if record is not None:
        body = record
    path = tmp_path / "remediation-evidence.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str, manifest_rollback: bool = True) -> tuple[int, dict]:
    from scripts.release_preflight import main

    manifest = _write_manifest(tmp_path, rollback=manifest_rollback)
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--manifest", str(manifest), *extra])
    return code, json.loads(stdout.getvalue())


def _rollback_checks(out: dict) -> list[dict]:
    return [c for c in out["checks"] if c["section"] == "rollback"]


# --------------------------------------------------------------------------- #
# T-EV-01/02/03:合法放行面与 fail-closed 语义
# --------------------------------------------------------------------------- #


def test_valid_bound_evidence_passes_with_readable_identity(tmp_path):
    """T-EV-01:合法证据 + gate/target_tag 双绑定 ⇒ PASS,可回读身份字段
    全部入 reason(审计面),且 exit 0。"""
    ev = _write_evidence(tmp_path)
    code, out = _run(
        tmp_path,
        "--remediation-evidence-file", str(ev),
        "--release-tag", TAG,
    )
    assert code == 0, out
    assert out["status"] == "pass"
    ok = [c for c in _rollback_checks(out) if c["class"] == "rollback_ok"]
    assert len(ok) == 1
    reason = ok[0]["reason"]
    assert "gate-token-x" in reason and TAG in reason and DIGEST in reason
    assert "recovery-drill/2026-10-20/bundle-sha" in reason
    assert "2026-10-20T12:00:00Z" in reason and "role-a" in reason
    assert not any(
        c["class"] == "rollback_remediation_gate_required" for c in out["checks"]
    )


def test_no_input_keeps_gate_blocked(tmp_path):
    """T-EV-02:无任何 remediation 输入 ⇒ fail-closed(现状语义不变),
    拒绝信息点名声明 gate 与证据工件通道(actionable)。"""
    code, out = _run(tmp_path)
    assert code == 2
    assert out["status"] == "fail"
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert len(chk) == 1
    assert "gate-token-x" in chk[0]["reason"]
    assert "--remediation-evidence-file" in chk[0]["reason"]


def test_exact_string_ack_alone_no_longer_releases(tmp_path):
    """T-EV-03(A #138 P3 核心):字符串 --remediation-ack 即使与声明 gate
    精确匹配,也不再构成合法放行 —— 结构化拒绝并指向证据工件。
    契约方向 = 收紧(fail-closed 更严),非放宽。"""
    code, out = _run(tmp_path, "--remediation-ack", "gate-token-x")
    assert code == 2
    assert out["status"] == "fail"
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert len(chk) == 1
    assert "不构成" in chk[0]["reason"]
    assert "--remediation-evidence-file" in chk[0]["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


def test_wrong_ack_still_blocked(tmp_path):
    """错误/过期字符串 ack ⇒ 维持 fail-closed(与既有 #159 语义一致)。"""
    for bad in ("other-gate", "gate-token-x-stale", ""):
        code, out = _run(tmp_path, "--remediation-ack", bad)
        assert code == 2, bad
        assert not any(c["class"] == "rollback_ok" for c in out["checks"])


# --------------------------------------------------------------------------- #
# T-EV-04/05:绑定校验(值不相等 = 绑定失败)
# --------------------------------------------------------------------------- #


def test_evidence_gate_mismatch_blocked(tmp_path):
    """T-EV-04:证据 gate ≠ manifest 声明 ⇒ 绑定失败 fail-closed。"""
    ev = _write_evidence(tmp_path, gate="another-gate")
    code, out = _run(
        tmp_path,
        "--remediation-evidence-file", str(ev),
        "--release-tag", TAG,
    )
    assert code == 2
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert chk and "绑定失败" in chk[0]["reason"]
    assert "another-gate" in chk[0]["reason"]


def test_evidence_target_tag_mismatch_blocked(tmp_path):
    """T-EV-05:证据 target_tag ≠ 本次部署 --release-tag ⇒ 跨版本证据
    不可移作他用,fail-closed。"""
    ev = _write_evidence(tmp_path, target_tag="v9.9.8")
    code, out = _run(
        tmp_path,
        "--remediation-evidence-file", str(ev),
        "--release-tag", TAG,
    )
    assert code == 2
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert chk and "v9.9.8" in chk[0]["reason"] and TAG in chk[0]["reason"]


# --------------------------------------------------------------------------- #
# T-EV-06:形状非法矩阵(加载器 fail-closed;错误不回显文件内容)
# --------------------------------------------------------------------------- #


def _invalid_case(tmp_path, record, *extra, marker: str):
    ev = _write_evidence(tmp_path, record=record)
    code, out = _run(
        tmp_path, "--remediation-evidence-file", str(ev), "--release-tag", TAG, *extra
    )
    assert code == 2, record
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert chk and "不可用" in chk[0]["reason"], record
    assert marker not in chk[0]["reason"], "错误信息不得回显文件内容"


def test_invalid_evidence_matrix_fail_closed(tmp_path):
    """T-EV-06:版本不符/词表外字段/形状非法/缺绑定键 ⇒ 一律 fail-closed。"""
    base = json.loads(_write_evidence(tmp_path).read_text(encoding="utf-8"))

    bad_records = [
        ("version 不符", {**base, "version": 2}),
        ("词表外字段", {**base, "signed_by": "x"}),
        ("gate 缺失", {k: v for k, v in base.items() if k != "gate"}),
        ("gate 形状非法", {**base, "gate": "BAD GATE!"}),
        ("target_tag 形状非法", {**base, "target_tag": "1.2.3"}),
        ("digest 非 64hex", {**base, "evidence_digest": "ABCDEF"}),
        ("recorded_at 不可解析", {**base, "recorded_at": "yesterday"}),
        ("evidence_ref 为空", {**base, "evidence_ref": ""}),
        ("recorded_by 缺失", {k: v for k, v in base.items() if k != "recorded_by"}),
    ]
    for name, record in bad_records:
        _invalid_case(tmp_path, record, marker="SECRETMARKER", )

    # 缺 --release-tag ⇒ 绑定键缺失,fail-closed(即使证据本身合法)
    ev = _write_evidence(tmp_path)
    code, out = _run(tmp_path, "--remediation-evidence-file", str(ev))
    assert code == 2
    chk = [
        c
        for c in _rollback_checks(out)
        if c["class"] == "rollback_remediation_gate_required"
    ]
    assert chk and "--release-tag" in chk[0]["reason"]

    # 证据文件不存在/非 JSON ⇒ fail-closed
    code, out = _run(
        tmp_path,
        "--remediation-evidence-file", str(tmp_path / "missing.json"),
        "--release-tag", TAG,
    )
    assert code == 2
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out = _run(
        tmp_path,
        "--remediation-evidence-file", str(bad),
        "--release-tag", TAG,
    )
    assert code == 2


# --------------------------------------------------------------------------- #
# T-EV-07:previous_compatible=true 零变化
# --------------------------------------------------------------------------- #


def test_evidence_digest_normalized_like_trust_anchor(tmp_path):
    """摘要大小写规范化与信任锚同构(strip+lower 后 64hex);reason 回显
    规范化小写形态。"""
    ev = _write_evidence(tmp_path, record={
        "version": 1, "gate": "gate-token-x", "target_tag": TAG,
        "evidence_digest": "A" * 64,
        "evidence_ref": "recovery-drill/bundle", "recorded_at": "2026-10-20T12:00:00Z",
        "recorded_by": "role-a",
    })
    code, out = _run(
        tmp_path, "--remediation-evidence-file", str(ev), "--release-tag", TAG
    )
    assert code == 0, out
    ok = [c for c in _rollback_checks(out) if c["class"] == "rollback_ok"]
    assert ok and ("a" * 64) in ok[0]["reason"]


def test_compatible_release_unaffected_by_evidence_channel(tmp_path):
    """T-EV-07:声明兼容的发布 ⇒ 普通 previous-tag 回滚照常可用,证据通道
    不参与判定(零变化)。"""
    code, out = _run(tmp_path, manifest_rollback=False)
    assert code == 0, out
    ok = [c for c in _rollback_checks(out) if c["class"] == "rollback_ok"]
    assert ok and "普通 previous-tag 回滚兼容" in ok[0]["reason"]


# --------------------------------------------------------------------------- #
# T-EV-08:update.sh / workflow 机械接线(静态)
# --------------------------------------------------------------------------- #


def test_update_sh_passes_evidence_and_release_tag_to_evaluator():
    """T-EV-08a:update.sh 解析 --remediation-evidence-file 并与 --release-tag
    "$TAG" 一并透传 evaluator;初值空(无默认证据/ack)。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert 'REMEDIATION_EVIDENCE_FILE=""' in text
    assert "--remediation-evidence-file)" in text
    assert '--remediation-evidence-file=*)' in text
    assert 'EVIDENCE_ARGS+=(--remediation-evidence-file "$REMEDIATION_EVIDENCE_FILE")' in text
    assert '--release-tag "$TAG" \\' in text
    assert '"${EVIDENCE_ARGS[@]}" \\' in text
    assert 'REMEDIATION_ACK=""' in text


def test_workflow_evidence_channel_wiring_and_no_bare_ack():
    """T-EV-08b:workflow 经 PREFLIGHT_REMEDIATION_EVIDENCE_B64 提供证据通道
    (步骤3 容器内 + 步骤5 update.sh 两处);通道可选(未配置 ⇒ rollback 门
    维持阻断);workflow 全文无裸字符串 ack 通道。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    # 无裸 ack 通道(维持 #46/#159 契约)
    assert "--remediation-ack" not in text
    assert "remediation_ack" not in text
    # 证据 secret 在两个步骤声明(步骤3 preflight / 步骤5 deploy)
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_B64") >= 2
    # runner 侧 base64 词表守卫(防远端 env 前缀注入)
    assert text.count('case "${REMEDIATION_EVIDENCE_B64:-}" in') == 2
    # 步骤3:可选(不在 required-vars 循环内)+ 容器内 --release-tag 绑定
    required_line = [
        ln for ln in text.splitlines() if ln.strip().startswith("for v in SSH_KEY")
    ]
    assert required_line and all("REMEDIATION_EVIDENCE_B64" not in ln for ln in required_line)
    assert '--release-tag "$DEPLOY_TAG" \\' in text
    assert "--remediation-evidence-file /tmp/askai-remediation-evidence.json" in text
    # 容器内完整性核对 + 临时工件确定性清除
    assert 'sha256sum /tmp/askai-remediation-evidence.json' in text
    # 三处容器侧 rm(pre-clean / integrity-failure / post-clean)均含证据工件
    assert text.count("rm -f /tmp/askai-preflight-evaluator.py") == 3
    assert text.count("/tmp/askai-remediation-evidence.json || true") == 2
    # 步骤5:update.sh 透传证据文件(远端 0600 临时文件 + 确定性清理)
    assert '--remediation-evidence-file "$EVID_TMP"' in text
    assert 'chmod 600 "$EVID_TMP"' in text
    assert 'rm -f "${TMPDIR:-/tmp}"/askai-remediation-evidence.*' in text


def test_gate_token_not_hardcoded_into_evaluator_or_workflow():
    """反伪证:gate 令牌不得内嵌进 evaluator/workflow/update.sh(必须由
    操作者/manifest 显式提供;与 #159 反伪证同向)。"""
    for path in (REPO / "scripts" / "release_preflight.py", WORKFLOW, UPDATE_SH):
        assert GATE not in path.read_text(encoding="utf-8"), path.name
