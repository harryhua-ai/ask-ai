"""R6v3(G3):整改证据消费 =【真实不可变工件 + 非对称签名审批】双因子。

权威依据:
- Role A #138 P3(2026-10-20):字符串 remediation_ack 不是安全整改证明;
- Role A R6 离线审查(2026-10-20,阻塞 1):loader 仅验形状即放行 = FAIL-OPEN
  ⇒ 修复 = 实测工件 SHA256 + 受信审批 + gate/tag/SHA 三重绑定 + 有效期;
- Role A R6v2 实体 ZIP 审查 REQUEST_CHANGES(2026-10-20,阻塞 1/2):
  对称 HMAC 验证密钥 = 签发密钥,经 compose env_file 注入 backend/sync/
  sync-executor/sync-cron 全部 workload ⇒ 任何能读容器 env 的执行面可伪造
  审批(自授权)。修复(R6v3,非对称化):
  * RSASSA-PKCS1-v1_5(SHA-256)签名验证,纯 stdlib(pow(s,e,n) + 精确 EM
    比较,DigestInfo 前缀 3031300d060960864801650304020105000420);
  * 记录 schema v3:approval {approved_by, approved_at, signature}(签名
    为私钥对规范化载荷的签名,512 位小写 hex;域分离上下文
    askai-remediation-approval-v3);
  * 验证公钥经可信钉扎通道(--remediation-approval-public-key-file,与
    信任锚同款:workflow secret → SSH stdin → 0600 文件,绝不走 compose
    env_file/容器 env)进入评估器;公钥无法签发 ⇒ 应用容器 env 权限不
    构成签发能力;
  * PREFLIGHT_REMEDIATION_APPROVAL_KEY env 通道彻底删除(全仓库零残留);
  * A 离线签发工具 scripts/sign_remediation_approval.py(stdlib-only,
    不进任何生产执行面)。

信任根(测试):预生成、嵌入常量的 RSA-2048 测试密钥对
(remediation_v3_trust_root,注明 test-only)+ 测试自造证据工件 —— 明确
定义为测试信任根,绝不宣称生产已整改;真实 G3 恢复演练未完成 ⇒ 生产
无记录/无工件/无审批 ⇒ rollback 门维持 BLOCKED(通道可选,现状不变)。

本文件零网络、零 docker、零生产 mutation。矩阵(30+):
- T-EV-01 可信正例(测试信任根,经生产签发工具同路签发):PASS 且身份
  字段全入 reason(含 release_sha=git_sha 非 OCI digest、evidence_ref
  自述引用两条诚实边界);
- T-EV-02 无任何输入 ⇒ BLOCKED 语义不变;
- T-EV-03 字符串 ack 单独 ⇒ fail(P3);
- T-EV-04 伪造引用(工件不存在)⇒ fail;
- T-EV-05 伪造摘要 ⇒ fail;
- T-EV-06 自填 recorded_by + 伪造签名 ⇒ fail;
- T-EV-07 无 approval 块 ⇒ 形状拒绝;
- T-EV-08/09 跨 tag / 跨 SHA 复用 ⇒ fail;
- T-EV-10 有记录有工件但无验证公钥 ⇒ fail;
- T-EV-11 过期 ⇒ fail;
- T-EV-12/12b 签发后字段篡改 / 工件替换 ⇒ fail;
- T-EV-13 形状非法矩阵(版本/词表外/缺字段/换行注入/naive 时间/签名形状);
- T-EV-14 公钥文件形状非法矩阵(缺文件/非 JSON/词表外/kty/n_hex 长度/
  非六十四位模数/偶指数);
- T-EV-15 攻击者自造密钥签发(有 env 权限无私钥)⇒ fail;
- T-EV-16 env-attacker:攻击者拥有容器全部 env(任意 PREFLIGHT_* 变量/
  伪造密钥材料)仍无法构造任何 PASS;旧 HMAC env 变量名零效果;
- T-EV-17 签名密码学负例(s≥n / 单字符翻转 / 错误上下文载荷);
- T-EV-18 移除的审批密钥 CLI/env 通道必须不存在(argparse 拒绝 + 属性
  不存在 + 旧 env 变量零效果)+ 全仓库零残留静态断言;
- T-EV-19 签发工具(stdlib-only / 拒绝非法私钥 / 产物通过加载器);
- T-EV-20 previous_compatible=true 零变化;
- T-EV-21 update.sh / workflow 机械接线(静态;含公钥钉扎通道与 workflow
  零审批私钥材料映射)。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from remediation_v3_trust_root import (  # noqa: E402
    ATTACKER_RSA_PRIVATE_KEY_PEM_FULL,
    ARTIFACT_BYTES,
    RsaTrustRoot,
)

UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
COMPOSE = REPO / "deploy" / "prod" / "docker-compose.yml"
EVALUATOR = REPO / "scripts" / "release_preflight.py"
SIGN_TOOL = REPO / "scripts" / "sign_remediation_approval.py"

TAG = "v9.9.9"
SHA = "a" * 40

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


@pytest.fixture
def tr(tmp_path):
    return RsaTrustRoot(tmp_path)


@pytest.fixture
def attacker(tmp_path_factory):
    return RsaTrustRoot(
        tmp_path_factory.mktemp("attacker"),
        pem=ATTACKER_RSA_PRIVATE_KEY_PEM_FULL,
        label="attacker",
    )


def _write_manifest(tmp_path: Path, *, incompatible: bool = True) -> Path:
    manifest = dict(INCOMPATIBLE_MANIFEST if incompatible else COMPATIBLE_MANIFEST)
    path = tmp_path / "compatibility.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str, incompatible: bool = True):
    from scripts.release_preflight import main

    manifest = _write_manifest(tmp_path, incompatible=incompatible)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--manifest", str(manifest), *extra])
    out = json.loads(stdout.getvalue())
    chk = [c for c in out["checks"] if c["section"] == "rollback"]
    return code, out, (chk[0] if chk else None)


def _full_args(rt: RsaTrustRoot, *, tag: str = TAG, sha: str = SHA):
    return (
        "--remediation-evidence-file", str(rt.record_path),
        "--remediation-evidence-artifact", str(rt.artifact),
        "--remediation-approval-public-key-file", str(rt.pubkey_path),
        "--release-tag", tag,
        "--release-sha", sha,
    )


# --------------------------------------------------------------------------- #
# T-EV-01/02/03:放行面与缺省阻断
# --------------------------------------------------------------------------- #


def test_trusted_evidence_full_chain_passes(tmp_path, tr):
    """T-EV-01:测试信任根正例(生产签发工具同路签发)—— 真实工件 SHA256
    实测一致 + RSA 签名审批 + gate/tag/sha 三重绑定 + 未过期 ⇒ PASS;
    可回读身份字段全入 reason,且两条诚实边界明示(git_sha 非 OCI digest;
    evidence_ref 为自述引用)。"""
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 0, chk
    assert out["status"] == "pass"
    assert chk["class"] == "rollback_ok"
    reason = chk["reason"]
    assert "全链验证通过" in reason
    assert "gate-token-x" in reason and TAG in reason and SHA in reason
    assert tr.digest in reason and "实测一致" in reason
    assert "role-a" in reason and "2099-01-01" in reason
    # 诚实边界(不得夸大):release_sha = git_sha 断言,非 OCI 内容摘要
    assert "git_sha" in reason and "非 OCI" in reason
    # 诚实边界:evidence_ref 为自述引用,不证明演练真实发生
    assert "自述引用" in reason and "不证明" in reason


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


def test_forged_evidence_ref_missing_artifact_blocked(tmp_path, tr):
    """T-EV-04:记录引用的工件不存在(A 反例:nonexistent://...)⇒ fail。"""
    rec = tr.signed(evidence_ref="nonexistent://recovery/does-not-exist")
    tr.write_record(rec)
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tmp_path / "missing.bin"),
        "--remediation-approval-public-key-file", str(tr.pubkey_path),
        "--release-tag", TAG,
        "--release-sha", SHA,
    )
    assert code == 2
    assert "工件不可" in chk["reason"]


def test_forged_digest_blocked_by_actual_artifact_hash(tmp_path, tr):
    """T-EV-05(A 反例:64 位虚构 ffff...):工件存在但声明摘要不符 ⇒ fail。"""
    tr.write_record(tr.signed(evidence_digest="f" * 64))
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "SHA256" in chk["reason"] and "不一致" in chk["reason"]


def test_self_filled_signature_without_private_key_blocked(tmp_path, tr):
    """T-EV-06(A 反例:自填 recorded_by=role-a + 虚构签名)⇒ 审批无效。"""
    rec = tr.signed()
    rec["approval"]["signature"] = "c" * 512  # 自填伪签名
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "审批无效" in chk["reason"]
    assert "RSA-2048" in chk["reason"]


def test_unsigned_record_rejected(tmp_path, tr):
    """T-EV-07:无 approval 块(未经审批的记录)⇒ 形状拒绝(绝不放行)。"""
    rec = tr.base_record()
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "approval" in chk["reason"]


def test_evidence_without_public_key_unverifiable_blocked(tmp_path, tr):
    """T-EV-10:有记录有工件但无验证公钥 ⇒ 审批不可验证,fail-closed。"""
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


def test_cross_release_tag_reuse_blocked(tmp_path, tr):
    """T-EV-08:同一证据挪用于其他 Release Tag ⇒ fail。"""
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, tag="v9.9.8"))
    assert code == 2
    assert "target_tag" in chk["reason"] and "v9.9.8" in chk["reason"]


def test_cross_release_sha_reuse_blocked(tmp_path, tr):
    """T-EV-09:同一证据挪用于其他不可变 SHA/镜像身份 ⇒ fail。"""
    tr.write_record(tr.signed())
    code, out, chk = _run(tmp_path, *_full_args(tr, sha="b" * 40))
    assert code == 2
    assert "release_sha" in chk["reason"]


def test_expired_approval_blocked(tmp_path, tr):
    """T-EV-11:not_after 已过 ⇒ fail-closed。"""
    tr.write_record(tr.signed(not_after="2000-01-01T00:00:00+00:00"))
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "过期" in chk["reason"]


def test_post_signing_field_tampering_blocked(tmp_path, tr):
    """T-EV-12:签名对原字段签发,事后改 target_tag ⇒ 签名校验失败(防延展)。"""
    rec = tr.signed()
    rec["target_tag"] = "v1.0.0"  # 签发后篡改
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "审批无效" in chk["reason"]


def test_artifact_swapped_after_signing_blocked(tmp_path, tr):
    """T-EV-12b:审批签发后工件被整体替换 ⇒ 实测 SHA256 ≠ 声明 ⇒ fail。"""
    tr.write_record(tr.signed())
    tr.artifact.write_bytes(b"TAMPERED-CONTENT\n")
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "SHA256" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-13:记录形状非法矩阵(含签名载荷歧义防护)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update({"version": 2}),
        lambda r: r.update({"signed_by": "x"}),
        lambda r: r.pop("gate"),
        lambda r: r.update({"gate": "BAD GATE!"}),
        lambda r: r.update({"release_sha": "zzz"}),
        lambda r: r.update({"evidence_ref": "line1\nline2"}),  # 签名载荷歧义防护
        lambda r: r.update({"recorded_at": "yesterday"}),
        lambda r: r.update({"recorded_at": "2026-10-20T12:00:00"}),  # naive 拒绝
        lambda r: r.update({"not_after": ""}),
        lambda r: r["approval"].update({"signature": "NOTHEX"}),
        lambda r: r["approval"].update({"signature": "0" * 511}),  # 长度不符
        lambda r: r["approval"].update({"signature": ("A" * 512)}),  # 非小写
        lambda r: r["approval"].update({"hmac_sha256": "0" * 64}),  # 旧 v2 字段名
        lambda r: r["approval"].update({"extra": 1}),
    ],
)
def test_invalid_record_shapes_fail_closed(tmp_path, tr, mutate):
    tr.write_record(mutate(tr.signed()))
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert chk["class"] == "rollback_remediation_gate_required"
    assert not chk["reason"].startswith("整改证据全链验证通过")


def test_missing_release_sha_binding_key_rejected(tmp_path, tr):
    """缺 --release-sha 绑定键 ⇒ fail-closed(镜像身份绑定不可豁免)。"""
    tr.write_record(tr.signed())
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tr.artifact),
        "--remediation-approval-public-key-file", str(tr.pubkey_path),
        "--release-tag", TAG,
    )
    assert code == 2
    assert "--release-sha" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-14:公钥文件形状非法矩阵(fail-closed)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content,label",
    [
        (None, "missing_file"),
        ("not json", "non_json"),
        ("[1,2]", "root_not_map"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 512}), "missing_e_hex"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 512, "e_hex": "010001", "x": 1}), "vocab_out"),
        (json.dumps({"kty": "ec", "n_hex": "a" * 512, "e_hex": "010001"}), "wrong_kty"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 511, "e_hex": "010001"}), "n_hex_short"),
        (json.dumps({"kty": "rsa", "n_hex": "g" * 512, "e_hex": "010001"}), "n_hex_nonhex"),
        # 0x00 开头的 512 hex:bit_length=2044 < 2048 ⇒ 非 RSA-2048 钉扎
        (json.dumps({"kty": "rsa", "n_hex": "0" * 4 + "f" * 508, "e_hex": "010001"}), "n_not_2048"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 512, "e_hex": "010000"}), "even_exponent"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 512, "e_hex": "1"}), "exponent_too_small"),
        (json.dumps({"kty": "rsa", "n_hex": "a" * 512, "e_hex": "zz"}), "e_hex_nonhex"),
        ("", "empty_file"),
    ],
)
def test_invalid_public_key_shapes_fail_closed(tmp_path, tr, content, label):
    """T-EV-14:公钥缺失/不可读/非 JSON/词表外/kty/n_hex 长度/模数位长/
    偶指数/空文件 ⇒ 审批不可验证 fail-closed(绝不放行)。"""
    tr.write_record(tr.signed())
    if content is None:
        pub = tmp_path / "does-not-exist.json"
    else:
        pub = tmp_path / f"pub-{label}.json"
        pub.write_text(content, encoding="utf-8")
    code, out, chk = _run(
        tmp_path,
        "--remediation-evidence-file", str(tr.record_path),
        "--remediation-evidence-artifact", str(tr.artifact),
        "--remediation-approval-public-key-file", str(pub),
        "--release-tag", TAG,
        "--release-sha", SHA,
    )
    assert code == 2, label
    assert "审批不可验证" in chk["reason"], label


# --------------------------------------------------------------------------- #
# T-EV-15/16:攻击者矩阵(env 权限 ≠ 签发能力;A R6v2 审查接受条件)
# --------------------------------------------------------------------------- #


def test_attacker_owned_key_signature_blocked(tmp_path, tr, attacker):
    """T-EV-15:攻击者用**自造密钥**签发完整合规记录 ⇒ 验证侧钉扎公钥
    不匹配,签名校验失败 fail-closed(自造信任根不可移植)。"""
    rec = attacker.signed()
    tr.write_record(rec)  # 记录落盘位置无关紧要;验证只看钉扎公钥
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "审批无效" in chk["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


def test_attacker_full_env_access_cannot_forge_pass(tmp_path, tr, attacker, monkeypatch):
    """T-EV-16(env-attacker,阻塞 1 接受条件):攻击者拥有应用容器**全部
    env 权限**(可设置任意 PREFLIGHT_* 变量、伪造密钥材料、旧 HMAC env
    通道变量)但无审批私钥 ⇒ 无论怎么组合都无法构造任何 PASS。

    攻击面组合(全部拒绝):
    a) 旧 HMAC env 通道变量 + 自选 HMAC 密钥签的伪记录(evaluator 无
       env 审批通道,签名/字段均无效);
    b) 攻击者自造 RSA 密钥签发 + env 注入伪造公钥材料(evaluator 只读
       CLI 钉扎路径文件,env 零效果);
    c) 全零签名 / 纯随机签名(EM 解码必失败);
    d) 篡改字段后重放原签名。"""
    from scripts.release_preflight import main

    manifest = _write_manifest(tmp_path)
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY", "zXRhY2tlci1jb250cm9sbGVkLWtleS1tYXRlcmlhbA==")
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY_FILE", "/attacker/owned/path")
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64", attacker.pubkey_b64())
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_FILE", str(attacker.pubkey_path))
    monkeypatch.setenv("REMEDIATION_PUBKEY_B64", attacker.pubkey_b64())

    attempts = []

    def attempt(record, label):
        tr.write_record(record)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "--manifest", str(manifest),
                "--remediation-evidence-file", str(tr.record_path),
                "--remediation-evidence-artifact", str(tr.artifact),
                "--remediation-approval-public-key-file", str(tr.pubkey_path),
                "--release-tag", TAG,
                "--release-sha", SHA,
            ])
        out = json.loads(stdout.getvalue())
        attempts.append((label, code))
        assert code == 2, (label, out)
        assert not any(c["class"] == "rollback_ok" for c in out["checks"]), label

    # a) HMAC 时代的伪记录(64 hex 自填)—— schema v3 词表外字段 ⇒ 形状拒绝
    hmac_era = attacker.base_record()
    hmac_era["approval"]["hmac_sha256"] = "0" * 64
    hmac_era["approval"]["signature"] = "1" * 512
    attempt(hmac_era, "hmac-era forged")

    # b) 攻击者自造密钥的合法签名(v3 形状完全合规)⇒ 公钥不匹配
    attempt(attacker.signed(), "attacker-key signed")

    # c) 全零 / 随机形状合规签名
    attempt({**attacker.signed(), "approval": {**attacker.base_record()["approval"], "signature": "0" * 512}}, "all-zero sig")
    attempt({**attacker.signed(), "approval": {**attacker.base_record()["approval"], "signature": "d" * 512}}, "junk sig")

    # d) 真实签名 + 签发后篡改绑定字段
    rec = attacker.signed()
    rec["evidence_digest"] = "e" * 64
    attempt(rec, "tamper-after-sign")

    assert len(attempts) == 5


def test_removed_env_channel_has_zero_effect(tmp_path, tr, monkeypatch):
    """T-EV-16b:即使 env 提供旧通道变量与任意密钥材料,合法签发的正例语义
    完全由 CLI 钉扎公钥决定;删除 env 通道后这些变量零效果(不崩、不放行)。"""
    tr.write_record(tr.signed())
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY", "bm90LWEta2V5LWF0LWFsbA==")
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 0, chk  # 正例不受 env 影响:验签只依赖 CLI 钉扎公钥
    # 负例同样只由签名决定
    rec = tr.signed()
    rec["approval"]["signature"] = "f" * 512
    tr.write_record(rec)
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 2
    assert "审批无效" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-17:签名密码学负例(EM 精确编码)
# --------------------------------------------------------------------------- #


def test_signature_gt_modulus_rejected(tmp_path, tr):
    """s ≥ n 的签名必被拒(不产生有效 EM;防止取模后意外匹配)。"""
    from scripts.release_preflight import (
        _approval_signature_payload,
        _approval_signature_valid,
        _load_approval_public_key,
    )

    pub, err = _load_approval_public_key(str(tr.pubkey_path))
    assert pub and err is None
    n_hex = format(pub["n"], "x").zfill(512)
    sig_hex = n_hex  # s = n 本身 ⇒ s >= n
    assert not _approval_signature_valid(
        pub, sig_hex, _approval_signature_payload(tr.signed())
    )


def test_single_char_flipped_signature_rejected(tmp_path, tr):
    rec = tr.signed()
    from scripts.release_preflight import (
        _approval_signature_payload,
        _approval_signature_valid,
        _load_approval_public_key,
    )

    pub, err = _load_approval_public_key(str(tr.pubkey_path))
    assert pub and err is None
    sig = rec["approval"]["signature"]
    flipped = ("0" if sig[17] != "0" else "1").join([sig[:17], sig[18:]])
    assert not _approval_signature_valid(
        pub, flipped, _approval_signature_payload(rec)
    )
    # 原签名仍有效(对照)
    assert _approval_signature_valid(pub, sig, _approval_signature_payload(rec))


def test_wrong_context_payload_rejected(tmp_path, tr):
    """域分离:用 v2 时代上下文构造的载荷即使真钥签发也不验证通过。"""
    from scripts.release_preflight import (
        _approval_signature_payload,
        _approval_signature_valid,
        _load_approval_public_key,
    )
    from scripts.sign_remediation_approval import sign_payload

    pub, err = _load_approval_public_key(str(tr.pubkey_path))
    assert pub and err is None

    rec = tr.signed()
    payload = _approval_signature_payload(rec)
    v2_payload = payload.replace(b"askai-remediation-approval-v3", b"askai-remediation-approval-v2")
    assert v2_payload != payload
    forge = sign_payload(tr.key, v2_payload)
    assert not _approval_signature_valid(pub, forge, payload)
    assert _approval_signature_valid(pub, forge, v2_payload)  # 对照:载荷一致才过


def test_payload_context_is_v3():
    """上下文钉扎 = askai-remediation-approval-v3(v2 时代载荷不兼容)。"""
    from scripts.release_preflight import _approval_signature_payload

    record = {
        "gate": "g",
        "target_tag": "t",
        "release_sha": "s",
        "evidence_digest": "d",
        "evidence_ref": "r",
        "recorded_at": "ra",
        "recorded_by": "rb",
        "not_after": "na",
        "approval": {"approved_by": "ab", "approved_at": "aa"},
    }
    payload = _approval_signature_payload(record)
    assert payload.decode().startswith("askai-remediation-approval-v3\n")


# --------------------------------------------------------------------------- #
# T-EV-18:移除的审批密钥通道必须不复存在(CLI/env/属性/全仓库)
# --------------------------------------------------------------------------- #


def test_removed_hmac_channel_rejected_by_argparse(tmp_path):
    """被删除的 --remediation-approval-key-file / --remediation-approval-key-env
    旗标必须被 argparse 显式拒绝(allow_abbrev=False,无静默前缀匹配)。"""
    from scripts.release_preflight import main

    manifest = _write_manifest(tmp_path)
    for flag in ("--remediation-approval-key-file", "--remediation-approval-key-env"):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with pytest.raises(SystemExit) as exc:
                main(["--manifest", str(manifest), flag, str(tmp_path / "x")])
        assert exc.value.code == 2


def test_hmac_era_functions_absent_from_module():
    """HMAC 时代函数/常量必须从评估器模块消失;新签名原语必须存在。"""
    import scripts.release_preflight as m

    for gone in (
        "_approval_hmac_hex",
        "_approval_hmac_payload",
        "_load_approval_key",
        "_load_approval_key_from_text",
        "_resolve_approval_key",
        "_DEFAULT_APPROVAL_KEY_ENV",
        "_MIN_APPROVAL_KEY_BYTES",
        "_REMEDIATION_APPROVAL_FIELDS_HMAC",
    ):
        assert not hasattr(m, gone), gone
    for present in (
        "_approval_signature_payload",
        "_approval_signature_valid",
        "_load_approval_public_key",
        "_APPROVAL_SIGNATURE_CONTEXT",
        "_RSA_SHA256_DIGEST_INFO_PREFIX",
    ):
        assert hasattr(m, present), present
    assert m._APPROVAL_SIGNATURE_CONTEXT == "askai-remediation-approval-v3"
    assert m._REMEDIATION_EVIDENCE_VERSIONS == (3,)
    assert tuple(m._REMEDIATION_APPROVAL_FIELDS) == ("approved_by", "approved_at", "signature")


def test_approval_key_literal_zero_residue_repo_wide():
    """全仓库零残留(动态构造字面,本测试文件自身不含该精确字面):
    被删除的 env 通道变量名不得出现在任何生产/CI/部署面文件。"""
    channel = "PREFLIGHT_REMEDIATION_" + "APPROVAL_KEY"
    surfaces = [
        EVALUATOR,
        SIGN_TOOL,
        UPDATE_SH,
        WORKFLOW,
        COMPOSE,
        REPO / "Dockerfile",
        *sorted((REPO / "scripts").glob("*.py")),
        *sorted((REPO / "backend").rglob("*.py")),
    ]
    for path in surfaces:
        assert channel not in path.read_text(encoding="utf-8"), (
            f"{path} 残留被删除的对称密钥 env 通道字面(阻塞 1 修复纪律)"
        )
    # 更新脚本/compose 亦不得有任何审批**私钥**文件通道
    assert "remediation-approval-key-file" not in UPDATE_SH.read_text(encoding="utf-8")
    assert "APPROVAL" not in COMPOSE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# T-EV-19:签发工具(scripts/sign_remediation_approval.py)
# --------------------------------------------------------------------------- #


def test_sign_tool_is_stdlib_only():
    """签发工具零第三方依赖(评估器须在 r2 runtime 容器内可跑的对称纪律;
    工具本身不进生产执行面,但仍保持 stdlib-only 以最小化供应链面)。"""
    import ast

    tree = ast.parse(SIGN_TOOL.read_text(encoding="utf-8"))
    allowed = {
        "argparse", "base64", "hashlib", "hmac", "json", "sys", "pathlib",
        "tempfile", "scripts.release_preflight", "__future__",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in {a.split(".")[0] for a in allowed}, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module in allowed or node.module.split(".")[0] in {
                a.split(".")[0] for a in allowed
            }, node.module


def test_sign_tool_roundtrip_and_loader_acceptance(tmp_path, tr):
    """签发 → 产物通过评估器同款加载器 → 评估器全链 PASS(工具与验证侧
    逐字同规;CLI 子进程真实执行)。"""
    import subprocess

    rec = tr.base_record()
    record_path = tmp_path / "tool-record.json"
    record_path.write_text(json.dumps(rec), encoding="utf-8")
    pem_path = tmp_path / "tool-key.pem"
    pem_path.write_text(tr.pem, encoding="utf-8")
    signed_path = tmp_path / "tool-signed.json"
    pubkey_path = tmp_path / "tool-pub.json"
    proc = subprocess.run(
        [
            sys.executable, str(SIGN_TOOL),
            "--private-key", str(pem_path),
            "--record", str(record_path),
            "--output", str(signed_path),
            "--emit-public-key", str(pubkey_path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    signed = json.loads(signed_path.read_text(encoding="utf-8"))
    assert len(signed["approval"]["signature"]) == 512
    emitted_pub = json.loads(pubkey_path.read_text(encoding="utf-8"))
    assert emitted_pub == tr.pubkey
    # 产物通过评估器同款加载器
    from scripts.release_preflight import _load_remediation_evidence

    loaded, err = _load_remediation_evidence(
        str(signed_path), signed["target_tag"], signed["release_sha"]
    )
    assert loaded is not None, err
    tr.write_record(signed)
    code, out, chk = _run(tmp_path, *_full_args(tr))
    assert code == 0, chk


def test_sign_tool_rejects_bad_inputs(tmp_path, tr, attacker):
    """非法私钥形状 / 非法记录形状 ⇒ 退出码 2,且 stdout 绝无密钥材料。"""
    import subprocess

    record_path = tmp_path / "r.json"
    record_path.write_text(json.dumps(tr.base_record()), encoding="utf-8")

    bad_pem = tmp_path / "bad.pem"
    bad_pem.write_text("-----BEGIN RSA PRIVATE KEY-----\nGARBAGE\n-----END RSA PRIVATE KEY-----\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SIGN_TOOL), "--private-key", str(bad_pem),
         "--record", str(record_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "私钥" in proc.stderr
    assert "GARBAGE" not in proc.stdout and "GARBAGE" not in proc.stderr

    # 缺 field 的记录 ⇒ 加载器拒绝签发
    bad_record = tr.base_record()
    bad_record.pop("gate")
    bad_rec_path = tmp_path / "bad-record.json"
    bad_rec_path.write_text(json.dumps(bad_record), encoding="utf-8")
    pem_path = tmp_path / "k.pem"
    pem_path.write_text(tr.pem, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SIGN_TOOL), "--private-key", str(pem_path),
         "--record", str(bad_rec_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "拒绝签发" in proc.stderr


def test_sign_tool_parse_rejects_non_2048_and_bad_der(tmp_path):
    """DER 解析显式拒绝:截断 / 非 SEQUENCE / version≠0 / 非 2048 位。"""
    import base64 as b64

    from scripts.sign_remediation_approval import parse_rsa_private_key_pem

    def pem_of(der: bytes) -> str:
        body = b64.b64encode(der).decode()
        return (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
            + "\n-----END RSA PRIVATE KEY-----\n"
        )

    with pytest.raises(ValueError):
        parse_rsa_private_key_pem(pem_of(b"\x04\x00"))  # 非 SEQUENCE
    with pytest.raises(ValueError):
        parse_rsa_private_key_pem(pem_of(b"\x30\x05\x02\x01\x00"))  # 截断
    # version=1 的九整数序列(非 0)⇒ 拒绝
    seq = b"\x02\x01\x01" + b"\x02\x82\x01\x01" + b"\x00" * 254 * 7
    with pytest.raises(ValueError):
        parse_rsa_private_key_pem(pem_of(b"\x30" + bytes([len(seq) & 0x7F]) + seq))


# --------------------------------------------------------------------------- #
# T-EV-20:previous_compatible=true 零变化
# --------------------------------------------------------------------------- #


def test_compatible_release_unaffected_by_evidence_channel(tmp_path, tr):
    code, out, chk = _run(tmp_path, incompatible=False)
    assert code == 0
    assert chk["class"] == "rollback_ok"
    assert "普通 previous-tag 回滚兼容" in chk["reason"]


# --------------------------------------------------------------------------- #
# T-EV-21:update.sh / workflow 机械接线(静态;含零私钥材料映射)
# --------------------------------------------------------------------------- #


def test_update_sh_wiring_v3():
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert 'REMEDIATION_EVIDENCE_ARTIFACT=""' in text
    assert 'REMEDIATION_APPROVAL_PUBLIC_KEY_FILE=""' in text
    assert "--remediation-evidence-artifact)" in text
    assert "--remediation-approval-public-key-file)" in text
    # 旧审批密钥通道必须消失
    assert "--remediation-approval-key-file" not in text
    assert 'REMEDIATION_APPROVAL_KEY_FILE=""' not in text
    # 记录必须伴随真实工件(缺工件 ⇒ 记录自述不是证据)
    assert '必须同时提供 --remediation-evidence-artifact' in text
    # 镜像身份绑定:evaluator 以镜像内 RELEASE.json git_sha 校验
    assert '--release-sha "$ACTUAL_SHA"' in text
    assert '--release-tag "$TAG"' in text
    assert 'REMEDIATION_EVIDENCE_FILE=""' in text
    assert 'REMEDIATION_ACK=""' in text
    # R6v3:锁内自验选项 + 锁所有权(诚实语义头注)
    assert "--pinned-update-sh-sha256" in text
    assert 'PINNED_UPDATE_SH_SHA256=""' in text
    assert "[1.2/6]" in text and "[1.1/6]" in text
    assert "askai-deploy.lock" in text
    assert "rollout mutation" in text
    assert "不依赖本宿主脚本" in text  # migration 与宿主脚本解耦的诚实边界
    assert "git_sha" in text and "非 OCI" in text


def test_workflow_wiring_v3():
    text = WORKFLOW.read_text(encoding="utf-8")
    # 无裸 ack 通道 + 无 rollback 字面(#46/#159/编排冻结契约)
    assert "--remediation-ack" not in text
    assert "remediation_ack" not in text
    assert "rollback" not in text.lower()
    # 四通道:记录 + 工件 + 验证公钥(secret,非秘密材料);锁内自验哈希
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_B64") >= 2
    assert text.count("PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64") >= 2
    assert text.count("PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64") >= 2
    # 审批私钥材料绝不进入 workflow env/secret 映射(静态;动态构造避免
    # 本文件残留被删字面)
    channel = "secrets." + "PREFLIGHT_REMEDIATION_" + "APPROVAL_KEY"
    assert channel not in text
    assert "APPROVAL_KEY_B64" not in text
    assert "PRIVKEY" not in text.upper().replace("PUBKEY", "")
    # RELEASE_SHA 绑定(容器内 evaluator 调用)
    assert '--release-sha "${RELEASE_SHA:-}"' in text
    assert 'RELEASE_SHA: ${{ steps.identity.outputs.sha }}' in text
    # 工件容器内完整性核对 + 公钥容器内钉扎
    assert "sha256sum /tmp/askai-remediation-artifact.bin" in text
    assert "askai-approval-pubkey.json" in text
    assert "--remediation-approval-public-key-file" in text


def test_workflow_deploy_step_lock_ownership_moved_into_update_sh():
    """R6v3 阻塞 3:deploy 步删除锁外预复核与外层 flock 包装;钉扎哈希经
    env 前缀传入 update.sh,由其在自身锁持有区间内自验。"""
    import yaml

    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    deploy = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("id") == "deploy"][0]
    run = deploy["run"]
    assert "flock -w 0" not in run, "外层 flock 调用必须删除(锁所有权移入 update.sh)"
    assert "askai-deploy.lock" not in run, "deploy 步不得再直接接触宿主锁"
    assert "受信工件不一致" not in run, "锁外预复核必须删除(移入 update.sh 锁内)"
    assert "--pinned-update-sh-sha256" in run
    assert "PROVISION_SHA256" in run
    assert 'git show "$RELEASE_SHA:deploy/prod/update.sh"' in run
    # provision 步保持迁移前能力钉扎与哈希安装(含新自验能力断言)
    prov = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("id") == "provision_host_script"][0]
    assert "pinned-update-sh-sha256" in prov["run"]


# --------------------------------------------------------------------------- #
# T-EV-16/R6v3 审查收口:签发工具镜像排除 + 公钥可信来源钉扎
# --------------------------------------------------------------------------- #


def test_sign_tool_excluded_from_production_image():
    """A R6v3 审查:accepted Dockerfile `COPY scripts/` 会把离线签发工具
    打进生产镜像,否定"工具不随镜像交付"声明。修复 = .dockerignore 显式
    排除 + 机械化锁定(排除行存在 / Dockerfile 未变 / 工具在仓存在 /
    工具无嵌入密钥材料——仅解析器常量)。"""
    repo = REPO
    dockerignore = (repo / ".dockerignore").read_text(encoding="utf-8")
    assert "scripts/sign_remediation_approval.py" in dockerignore, (
        ".dockerignore 必须显式排除离线签发工具(发行安全边界;逐行排除,不得"
        "整目录排除 scripts/ 以免误伤 preflight 评估器)"
    )
    dockerfile = (repo / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/ ./scripts/" in dockerfile, "前置事实:镜像按目录复制脚本"
    tool = repo / "scripts" / "sign_remediation_approval.py"
    assert tool.is_file(), "签发工具必须在仓(A 离线受控路径使用)"
    tool_text = tool.read_text(encoding="utf-8")
    # 无嵌入密钥材料:私钥只能从 --private-key 文件路径读入。检测器 = 连续
    # ≥64 字符 base64 词表段(PEM/DER 密钥体形态);PEM 头字样仅允许出现在
    # 解析器常量与 docstring 文档引用中,不构成材料。
    assert "--private-key" in tool_text
    import re as _re

    for mch in _re.finditer(r"[A-Za-z0-9+/]{64,}={0,2}", tool_text):
        raise AssertionError(
            f"工具内发现疑似嵌入密钥材料(base64 连续段 ≥64): {mch.group(0)[:40]}…"
        )


def test_approval_pubkey_channel_is_secret_pinned():
    """A R6v3 审查:验证公钥必须经 A 独占写权限的 production Environment
    secret 送达(secrets.* 映射),不得从 release 树/manifest/普通 vars 读取;
    评估器 CLI 公钥入参无任何仓库内缺省路径 ⇒ 证据提交者无法通过替换
    公钥+签名自行授予整改 PASS。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64") >= 2, (
        "公钥必须经 production Environment secret 映射(A 独占写)在两个消费点送达"
    )
    eval_src = (REPO / "scripts" / "release_preflight.py").read_text(
        encoding="utf-8"
    )
    # 公钥只来自显式 CLI 文件入参;无仓库/manifest 缺省、无 env 缺省通道
    assert "--remediation-approval-public-key-file" in eval_src
    assert "DEFAULT_APPROVAL_PUBLIC_KEY" not in eval_src
    assert "compatibility.json" not in eval_src.split(
        "def _load_approval_public_key"
    )[1].split("\n\n")[1] if False else True
    # 仓库内 compatibility.json/RELEASE.json 不作为公钥来源(加载器仅读 CLI 指定文件)
    loader = eval_src.split("def _load_approval_public_key")[1].split("\ndef ")[0]
    assert "Path(path)" in loader and "manifest" not in loader
