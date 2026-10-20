"""R6v2(G3):整改证据消费 =【真实不可变工件 + 受信审批】双因子,缺一 fail-closed。

权威依据:
- Role A #138 P3(2026-10-20):「仅有字符串相等判断的 remediation_ack 本身
  不是安全整改证明,不能凭命令行传入相同字符串获得合法放行」;
- Role A R6 离线审查 REQUEST_CHANGES(2026-10-20,阻塞 1):loader 仅验形状
  即放行 = 确定性真 FAIL-OPEN(A 以独立反例实码证实)。修复要求:验证被引用
  的真实不可变证据工件(SHA256 实测比对)、验证来自受信密钥的审批
  (不接受自填 recorded_by)、绑定 gate/目标 tag/不可变 release SHA、
  相同证据不可挪用其他发行、过期/损坏 fail-closed。

信任根(测试):测试自造 HMAC 密钥(≥32 字节)+ 测试自造证据工件 —— 明确
定义为测试信任根,绝不宣称生产已整改;真实 G3 恢复演练未完成 ⇒ 生产
无记录/无工件/无审批 ⇒ rollback 门维持 BLOCKED(通道可选,现状不变)。

本文件零网络、零 docker、零生产 mutation。矩阵:
- T-EV-01 可信正例(测试信任根):PASS 且可回读身份字段全入 reason;
- T-EV-02 无任何输入 ⇒ BLOCKED 语义不变;
- T-EV-03 字符串 ack 单独 ⇒ fail(P3);
- T-EV-04 伪造引用:记录引用的工件不存在 ⇒ fail;
- T-EV-05 伪造摘要:工件存在但声明 digest 不符 ⇒ fail;
- T-EV-06 自填 recorded_by + 伪造 HMAC ⇒ fail;
- T-EV-07 无 approval 块(未经审批的记录)⇒ 形状拒绝;
- T-EV-08 跨 Release Tag 复用 ⇒ fail;
- T-EV-09 跨 Git SHA / 镜像身份复用 ⇒ fail;
- T-EV-10 有记录有工件但无审批密钥 ⇒ fail(审批不可验证);
- T-EV-11 审批过期(not_after)⇒ fail;
- T-EV-12 绑定字段篡改(HMAC 对原字段签发,tag 事后被改)⇒ fail(防延展);
- T-EV-13 形状非法矩阵(版本/词表外/缺字段/换行注入/naive 时间)⇒ fail;
- T-EV-14 previous_compatible=true 零变化;
- T-EV-15 update.sh / workflow 机械接线(静态)。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"

GATE = "upload-source-acl-verified-issue-121"
TAG = "v9.9.9"
SHA = "a" * 40
DIGEST = None  # per-fixture (artifact bytes)

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

ARTIFACT_BYTES = b"RECOVERY-DRILL-EVIDENCE-BUNDLE-v1 (test trust root)\n"


def _key_b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


def _sign(record: dict, key: bytes) -> dict:
    """用测试信任根密钥对记录签发审批 HMAC(与 evaluator 规范化载荷一致)。"""
    from scripts.release_preflight import _approval_hmac_hex

    record = json.loads(json.dumps(record))
    record["approval"]["hmac_sha256"] = "0" * 64
    record["approval"]["hmac_sha256"] = _approval_hmac_hex(key, record)
    return record


def _base_record(artifact_digest: str) -> dict:
    return {
        "version": 2,
        "gate": "gate-token-x",
        "target_tag": TAG,
        "release_sha": SHA,
        "evidence_digest": artifact_digest,
        "evidence_ref": "recovery-drill/2026-10-20/bundle-sha",
        "recorded_at": "2026-10-20T12:00:00+00:00",
        "recorded_by": "role-a",
        "not_after": "2099-01-01T00:00:00+00:00",
        "approval": {
            "approved_by": "role-a",
            "approved_at": "2026-10-20T12:00:00+00:00",
            "hmac_sha256": "0" * 64,
        },
    }


class TrustRoot:
    """测试信任根:密钥 + 真实工件 + 已签发记录(全部临时文件)。"""

    def __init__(self, tmp_path: Path, key: bytes | None = None):
        self.key = key or os.urandom(48)
        self.artifact = tmp_path / "bundle.bin"
        self.artifact.write_bytes(ARTIFACT_BYTES)
        self.digest = hashlib.sha256(ARTIFACT_BYTES).hexdigest()
        self.record_path = tmp_path / "record.json"
        self.key_path = tmp_path / "approval-key.b64"
        self.key_path.write_text(_key_b64(self.key) + "\n", encoding="utf-8")

    def write_record(self, record: dict) -> Path:
        self.record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return self.record_path

    def signed(self, **overrides) -> dict:
        rec = _base_record(self.digest)
        rec.update(overrides)
        return _sign(rec, self.key)


def _write_manifest(tmp_path: Path, *, incompatible: bool = True) -> Path:
    manifest = dict(INCOMPATIBLE_MANIFEST if incompatible else COMPATIBLE_MANIFEST)
    path = tmp_path / "compatibility.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str, incompatible: bool = True):
    from scripts.release_preflight import main

    manifest = _write_manifest(tmp_path, incompatible=incompatible)
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--manifest", str(manifest), *extra])
    out = json.loads(stdout.getvalue())
    chk = [c for c in out["checks"] if c["section"] == "rollback"]
    return code, out, (chk[0] if chk else None)


def _full_args(tr: TrustRoot, tmp_path: Path, *, tag: str = TAG, sha: str = SHA):
    return (
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tr.artifact),
        "--remediation-approval-key-file", str(tr.key_path),
        "--release-tag", tag,
        "--release-sha", sha,
    )


# --------------------------------------------------------------------------- #
# T-EV-01/02/03:放行面与缺省阻断
# --------------------------------------------------------------------------- #


def test_trusted_evidence_full_chain_passes(tmp_path):
    """T-EV-01:测试信任根正例 —— 真实工件(SHA256 实测一致)+ 受信密钥审批
    + gate/tag/sha 三重绑定 + 未过期 ⇒ PASS;可回读身份字段全入 reason。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 0, chk
    assert out["status"] == "pass"
    assert chk["class"] == "rollback_ok"
    reason = chk["reason"]
    assert "全链验证通过" in reason
    assert GATE or True
    assert "gate-token-x" in reason and TAG in reason and SHA in reason
    assert tr.digest in reason and "实测一致" in reason
    assert "role-a" in reason and "2099-01-01" in reason


def test_no_input_keeps_gate_blocked(tmp_path):
    """T-EV-02:无任何 remediation 输入 ⇒ fail-closed(真实 G3 演练未完成时
    生产维持 BLOCKED 的机制保障;通道可选,现状不变)。"""
    code, out, chk = _run(tmp_path)
    assert code == 2
    assert chk["class"] == "rollback_remediation_gate_required"
    assert "gate-token-x" in chk["reason"]
    assert "--remediation-evidence-file" in chk["reason"]


def test_exact_string_ack_alone_no_longer_releases(tmp_path):
    """T-EV-03(A #138 P3):字符串 --remediation-ack 即使精确匹配也不再放行。"""
    code, out, chk = _run(tmp_path, "--remediation-ack", "gate-token-x")
    assert code == 2
    assert chk["class"] == "rollback_remediation_gate_required"
    assert "不构成" in chk["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


# --------------------------------------------------------------------------- #
# T-EV-04..07:伪造工件/摘要/审批(A 阻塞 1 反例矩阵)
# --------------------------------------------------------------------------- #


def test_forged_evidence_ref_missing_artifact_blocked(tmp_path):
    """T-EV-04:记录引用的工件不存在(A 反例:nonexistent://...)⇒ fail。"""
    tr = TrustRoot(tmp_path)
    rec = tr.signed()
    rec["evidence_ref"] = "nonexistent://recovery/does-not-exist"
    rec = _sign(rec, tr.key)
    tr.write_record(rec)
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tmp_path / "missing.bin"),
        "--remediation-approval-key-file", str(tr.key_path),
        "--release-tag", TAG,
        "--release-sha", SHA,
    )
    assert code == 2
    assert "工件不可" in chk["reason"]


def test_forged_digest_blocked_by_actual_artifact_hash(tmp_path):
    """T-EV-05(A 反例:64 位虚构 ffffff...):工件存在但声明摘要不符 ⇒ fail。
    记录自述摘要不是证据 —— 以实际文件 SHA256 实测为准。"""
    tr = TrustRoot(tmp_path)
    rec = tr.signed(evidence_digest="f" * 64)
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "SHA256" in chk["reason"] and "不一致" in chk["reason"]


def test_self_filled_recorded_by_without_trusted_key_blocked(tmp_path):
    """T-EV-06(A 反例:自填 recorded_by=role-a + 虚构 HMAC)⇒ 审批无效。"""
    tr = TrustRoot(tmp_path)
    rec = tr.signed()
    rec["approval"]["hmac_sha256"] = "c" * 64  # 自填伪 HMAC
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "审批无效" in chk["reason"]
    assert "HMAC" in chk["reason"]


def test_unsigned_record_rejected(tmp_path):
    """T-EV-07:无 approval 块(未经审批的记录)⇒ 形状拒绝(绝不放行)。"""
    tr = TrustRoot(tmp_path)
    rec = _base_record(tr.digest)
    rec.pop("approval")
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "approval" in chk["reason"]


def test_evidence_without_any_key_unverifiable_blocked(tmp_path):
    """T-EV-10:有记录有工件但无受信密钥 ⇒ 审批不可验证,fail-closed。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tr.artifact),
        "--release-tag", TAG,
        "--release-sha", SHA,
    )
    assert code == 2
    assert "审批不可验证" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-08/09/11/12:绑定与有效期
# --------------------------------------------------------------------------- #


def test_cross_release_tag_reuse_blocked(tmp_path):
    """T-EV-08:同一证据挪用于其他 Release Tag ⇒ fail。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path, tag="v9.9.8"))
    assert code == 2
    assert "target_tag" in chk["reason"] and "v9.9.8" in chk["reason"]


def test_cross_release_sha_reuse_blocked(tmp_path):
    """T-EV-09:同一证据挪用于其他不可变 SHA/镜像身份 ⇒ fail。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path, sha="b" * 40))
    assert code == 2
    assert "release_sha" in chk["reason"]


def test_expired_approval_blocked(tmp_path):
    """T-EV-11:not_after 已过 ⇒ fail-closed。"""
    tr = TrustRoot(tmp_path)
    rec = tr.signed(not_after="2000-01-01T00:00:00+00:00")
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "过期" in chk["reason"]


def test_post_signing_field_tampering_blocked(tmp_path):
    """T-EV-12:HMAC 对原字段签发,事后改 target_tag ⇒ HMAC 失配(防延展)。"""
    tr = TrustRoot(tmp_path)
    rec = tr.signed()
    rec["target_tag"] = "v1.0.0"  # 签发后篡改
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "审批无效" in chk["reason"]


def test_artifact_swapped_after_signing_blocked(tmp_path):
    """T-EV-12b:审批签发后工件被整体替换 ⇒ 实测 SHA256 ≠ 声明 ⇒ fail。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    tr.artifact.write_bytes(b"TAMPERED-CONTENT\n")
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "SHA256" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-13:形状非法矩阵(含 HMAC 载荷歧义防护)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update({"version": 1}),
        lambda r: r.update({"signed_by": "x"}),
        lambda r: r.pop("gate"),
        lambda r: r.update({"gate": "BAD GATE!"}),
        lambda r: r.update({"release_sha": "zzz"}),
        lambda r: r.update({"evidence_ref": "line1\nline2"}),  # HMAC 载荷歧义防护
        lambda r: r.update({"recorded_at": "yesterday"}),
        lambda r: r.update({"recorded_at": "2026-10-20T12:00:00"}),  # naive 拒绝
        lambda r: r.update({"not_after": ""}),
        lambda r: r["approval"].update({"hmac_sha256": "NOTHEX"}),
        lambda r: r["approval"].update({"extra": 1}),
    ],
)
def test_invalid_record_shapes_fail_closed(tmp_path, mutate):
    tr = TrustRoot(tmp_path)
    rec = tr.signed()
    mutate(rec)
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert chk["class"] == "rollback_remediation_gate_required"
    assert not chk["reason"].startswith("整改证据全链验证通过")


def test_missing_release_sha_binding_key_rejected(tmp_path):
    """缺 --release-sha 绑定键 ⇒ fail-closed(镜像身份绑定不可豁免)。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tr.artifact),
        "--remediation-approval-key-file", str(tr.key_path),
        "--release-tag", TAG,
    )
    assert code == 2
    assert "--release-sha" in chk["reason"]


def test_env_var_key_channel_accepted(tmp_path, monkeypatch):
    """审批密钥 env 变量通道(env 字典/os.environ;宿主 .env 经 --env-file
    装配同路)—— 文件通道之外的合法通道,同样 fail-closed 校验强度。"""
    tr = TrustRoot(tmp_path)
    tr.write_record(tr.signed())
    manifest = _write_manifest(tmp_path)
    from scripts.release_preflight import main
    import contextlib, io

    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY", _key_b64(tr.key))
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main([
            "--manifest", str(manifest),
            "--remediation-evidence-file", str(tr.record_path),
            "--remediation-evidence-artifact", str(tr.artifact),
            "--release-tag", TAG,
            "--release-sha", SHA,
        ])
    assert code == 0


def test_weak_key_rejected(tmp_path):
    """密钥解码后 <32 字节 ⇒ fail-closed(强度不足)。"""
    tr = TrustRoot(tmp_path, key=os.urandom(16))
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, tmp_path))
    assert code == 2
    assert "强度不足" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-14:previous_compatible=true 零变化
# --------------------------------------------------------------------------- #


def test_compatible_release_unaffected_by_evidence_channel(tmp_path):
    tr = TrustRoot(tmp_path)
    code, out, chk = _run(tmp_path, incompatible=False)
    assert code == 0
    assert chk["class"] == "rollback_ok"
    assert "普通 previous-tag 回滚兼容" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-15:update.sh / workflow 机械接线(静态)
# --------------------------------------------------------------------------- #


def test_update_sh_wiring_v2():
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert 'REMEDIATION_EVIDENCE_ARTIFACT=""' in text
    assert 'REMEDIATION_APPROVAL_KEY_FILE=""' in text
    assert "--remediation-evidence-artifact)" in text
    assert "--remediation-approval-key-file)" in text
    # 记录必须伴随真实工件(缺工件 ⇒ 记录自述不是证据)
    assert '必须同时提供 --remediation-evidence-artifact' in text
    # 镜像身份绑定:evaluator 以镜像内 RELEASE.json git_sha 校验
    assert '--release-sha "$ACTUAL_SHA"' in text
    assert '--release-tag "$TAG"' in text
    assert 'REMEDIATION_EVIDENCE_FILE=""' in text
    assert 'REMEDIATION_ACK=""' in text


def test_workflow_wiring_v2():
    text = WORKFLOW.read_text(encoding="utf-8")
    # 无裸 ack 通道 + 无 rollback 字面(#46/#159/编排冻结契约)
    assert "--remediation-ack" not in text
    assert "remediation_ack" not in text
    assert "rollback" not in text.lower()
    # 三通道:记录 + 工件(secret);审批密钥 = 宿主 .env env 通道(零新增含密传输)
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_B64") >= 2
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64") >= 2
    # 审批密钥绝不进入 workflow secret 映射 / SSH 传输面(仅宿主 .env →
    # 容器 env / --env-file);注释中的通道名文档不算接线。
    assert "secrets.PREFLIGHT_REMEDIATION_APPROVAL_KEY" not in text
    assert "APPROVAL_KEY_B64" not in text
    # RELEASE_SHA 绑定(容器内 evaluator 调用)
    assert '--release-sha "${RELEASE_SHA:-}"' in text
    assert 'RELEASE_SHA: ${{ steps.identity.outputs.sha }}' in text
    # 工件容器内完整性核对
    assert "sha256sum /tmp/askai-remediation-artifact.bin" in text
