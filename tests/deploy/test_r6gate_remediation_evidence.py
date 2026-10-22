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


def _forward_args(*, tag: str = TAG, deployed: str = "1.6.3-r9"):
    """2026-10-22 通道语义:前向/重部署(目标 >= 已部署)合法放行路径。"""
    return ("--release-tag", tag, "--deployed-release-version", deployed)


def _load_evidence(rt_or_path, tag: str = TAG, sha: str = SHA):
    """审计面直调:签发/加载与 CLI 解耦后,加载器测试经本助手直调。"""
    from scripts.release_preflight import _load_remediation_evidence

    path = getattr(rt_or_path, "record_path", None)
    return _load_remediation_evidence(str(path or rt_or_path), tag, sha)


# --------------------------------------------------------------------------- #
# T-EV-01/02/03:放行面与缺省阻断
# --------------------------------------------------------------------------- #


def test_forward_deploy_passes_without_any_remediation_input(tmp_path, tr):
    """2026-10-22 通道(T-EV-01 替换):前向部署(目标 >= 已部署)在【零
    remediation 输入、零新增 Secret】下放行;记录/工件/公钥通道不再存在。
    """
    tr.write_record(tr.signed())  # 即使盘上存在历史记录,通道也不消费
    code, out, chk = _run(tmp_path, "--release-tag", TAG, "--deployed-release-version", "1.6.3-r9")
    assert code == 0, chk
    assert out["status"] == "pass"
    assert chk["class"] == "rollback_ok"
    assert TAG in chk["reason"] and "1.6.3-r9" in chk["reason"]
    # 诚实边界保留:手工最高权限旁路如实声明
    assert "手工" in chk["reason"]


def test_no_deployed_version_blocks_direction_judgement(tmp_path):
    """T-EV-02(重定义):previous_compatible=false 且已部署版本事实缺失 ⇒
    回滚方向无法判定,BLOCKED(不谎报 PASS;空宿主 bootstrap 语境见通道文档)。"""
    code, out, chk = _run(tmp_path, "--release-tag", TAG)
    assert code == 2
    assert chk["class"] == "rollback_direction_unprovable"
    assert "--deployed-release-version" in chk["reason"]


def test_exact_string_ack_alone_no_longer_releases(tmp_path):
    """T-EV-03(A #138 P3 原则保留):字符串 --remediation-ack 即使精确匹配
    声明 gate 也显式 FAIL(退役通道不给出任何静默 PASS 面)。"""
    code, out, chk = _run(
        tmp_path, "--release-tag", TAG, "--deployed-release-version", "1.6.3-r9",
        "--remediation-ack", "gate-token-x",
    )
    assert code == 2
    assert chk["class"] == "rollback_ack_not_accepted"
    assert "不构成" in chk["reason"]
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])


def test_older_target_refused_against_incompatible_deployed(tmp_path):
    """T-EV-04(新):目标旧于已部署且已部署声明 previous_compatible=false
    ⇒ 拒绝(r2 旧上传来源默认可见性语义可能重暴露已清理数据)。"""
    code, out, chk = _run(
        tmp_path, "--release-tag", "v1.6.4-r2", "--deployed-release-version", "1.6.4-r3",
    )
    assert code == 2
    assert chk["class"] == "rollback_incompatible_refused"
    assert "1.6.4-r2" in chk["reason"] and "1.6.4-r3" in chk["reason"]
    assert "gate-token-x" in chk["reason"]


def test_redeploy_same_version_passes(tmp_path):
    """同版本重部署不构成回滚,放行。"""
    code, out, chk = _run(
        tmp_path, "--release-tag", TAG, "--deployed-release-version", "9.9.9",
    )
    assert code == 0, chk
    assert chk["class"] == "rollback_ok"


def test_unparsable_versions_fail_closed(tmp_path):
    """目标/已部署版本形状不可解析 ⇒ 方向无法判定,fail-closed。"""
    code, out, chk = _run(
        tmp_path, "--release-tag", "not-a-version", "--deployed-release-version", "1.6.4-r3",
    )
    assert code == 2 and chk["class"] == "rollback_target_tag_unparsable"
    code, out, chk = _run(
        tmp_path, "--release-tag", TAG, "--deployed-release-version", "banana",
    )
    assert code == 2 and chk["class"] == "rollback_deployed_version_unparsable"


def test_evidence_channel_cli_args_removed(tmp_path, tr):
    """退役通道的三个 CLI 参数必须被 argparse 显式拒绝(allow_abbrev=False,
    无静默前缀匹配;历史证据/工件即使落盘也不再构成任何发布输入)。"""
    tr.write_record(tr.signed())
    for flag in (
        "--remediation-evidence-file",
        "--remediation-evidence-artifact",
        "--remediation-approval-public-key-file",
    ):
        with pytest.raises(SystemExit) as exc:
            _run(tmp_path, flag, str(tr.record_path))
        assert exc.value.code == 2


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
    """审计面(直调加载器):v3 记录形状矩阵全部拒绝 —— 加载器保留为辅助
    审计代码,形状契约不因通道退役而放松。"""
    rec = mutate(tr.signed())
    path = tmp_path / "record.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    loaded, err = _load_evidence(path)
    assert loaded is None and err, err


def test_missing_release_sha_binding_key_rejected(tmp_path, tr):
    """审计面:缺 release_sha 绑定键 ⇒ 加载器拒绝(镜像身份绑定不可豁免)。"""
    tr.write_record(tr.signed())
    from scripts.release_preflight import _load_remediation_evidence

    loaded, err = _load_remediation_evidence(str(tr.record_path), TAG, None)
    assert loaded is None and err and "--release-sha" in err


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
    from scripts.release_preflight import _load_approval_public_key

    if content is None:
        pub = tmp_path / "does-not-exist.json"
    else:
        pub = tmp_path / f"pub-{label}.json"
        pub.write_text(content, encoding="utf-8")
    loaded, err = _load_approval_public_key(str(pub))
    assert loaded is None and err, (label, err)


# --------------------------------------------------------------------------- #
# T-EV-15/16:攻击者矩阵(env 权限 ≠ 签发能力;A R6v2 审查接受条件)
# --------------------------------------------------------------------------- #


def test_attacker_owned_key_signature_blocked(tmp_path, tr, attacker):
    """T-EV-15(审计面直调):攻击者用自造密钥签发完整合规记录 ⇒ 对验证侧
    信任根公钥验签失败。部署链层面该通道已整体退役(CLI 参数被 argparse
    拒绝,见 test_evidence_channel_cli_args_removed)。"""
    from scripts.release_preflight import (
        _approval_signature_payload,
        _approval_signature_valid,
        _load_approval_public_key,
    )

    rec = attacker.signed()
    pub, err = _load_approval_public_key(str(tr.pubkey_path))
    assert pub and err is None
    assert not _approval_signature_valid(
        pub, rec["approval"]["signature"], _approval_signature_payload(rec)
    )


def test_attacker_full_env_access_cannot_forge_pass(tmp_path, tr, attacker, monkeypatch):
    """T-EV-16(env-attacker,结构化):部署链没有任何 env 审批/证据通道;
    攻击者设置全部历史通道变量后,evaluator 行为与未设置完全一致 —— 前向
    部署语义只由 tag/deployed-version 决定,不存在可被 env 撬动的放行面。"""
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY", "zXRhY2tlci1jb250cm9sbGVkLWtleS1tYXRlcmlhbA==")
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY_FILE", "/attacker/owned/path")
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64", attacker.pubkey_b64())
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_FILE", str(attacker.pubkey_path))
    monkeypatch.setenv("REMEDIATION_PUBKEY_B64", attacker.pubkey_b64())
    code, out, chk = _run(
        tmp_path, "--release-tag", "v1.6.4-r2", "--deployed-release-version", "1.6.4-r3",
    )
    assert code == 2
    assert chk["class"] == "rollback_incompatible_refused"
    assert not any(c["class"] == "rollback_ok" for c in out["checks"])
    # 历史通道 env 变量对前向部署路径同样零效果
    code2, out2, chk2 = _run(
        tmp_path, "--release-tag", TAG, "--deployed-release-version", "1.6.3-r9",
    )
    assert code2 == 0 and chk2["class"] == "rollback_ok"


def test_removed_env_channel_has_zero_effect(tmp_path, tr, monkeypatch):
    """T-EV-16b:旧通道变量存在与否,部署语义完全一致(不崩、不放行旧版)。"""
    monkeypatch.setenv("PREFLIGHT_REMEDIATION_APPROVAL_KEY", "bm90LWEta2V5LWF0LWFsbA==")
    code, out, chk = _run(
        tmp_path, "--release-tag", "v1.6.4-r2", "--deployed-release-version", "1.6.4-r3",
    )
    assert code == 2 and chk["class"] == "rollback_incompatible_refused"


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
    # 产物通过评估器同款加载器(审计面;发布链不再消费证据通道)
    from scripts.release_preflight import _load_remediation_evidence

    loaded, err = _load_remediation_evidence(
        str(signed_path), signed["target_tag"], signed["release_sha"]
    )
    assert loaded is not None, err


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
    """2026-10-22 通道接线(机械):退役证据通道零残留;deployed-version
    回滚守卫 + 宿主部署标记 + 锁内自验在位。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "--remediation-evidence-file" not in text
    assert "--remediation-evidence-artifact" not in text
    assert "--remediation-approval-public-key-file" not in text
    assert "REMEDIATION_EVIDENCE" not in text
    assert "REMEDIATION_APPROVAL" not in text
    assert 'REMEDIATION_ACK=""' in text
    assert "ASKAI_DEPLOYED_VERSION_GUARD_V1" in text
    assert "[1.3/6]" in text and "[6.1/6]" in text
    assert ".deployed-release.json" in text
    assert "--deployed-release-version" in text
    assert "previous_compatible" in text
    assert '--release-sha "$ACTUAL_SHA"' in text
    assert '--release-tag "$TAG"' in text
    assert "--pinned-update-sh-sha256" in text
    assert 'PINNED_UPDATE_SH_SHA256=""' in text
    assert "[1.2/6]" in text and "[1.1/6]" in text
    assert "askai-deploy.lock" in text
    assert "rollout mutation" in text
    assert "不依赖本宿主脚本" in text
    assert "bootstrap" in text


def test_workflow_wiring_v3():
    """2026-10-22 通道接线(机械):四 PREFLIGHT_* secret / 证据通道零残留;
    已审核身份事实与上传守卫随镜像提取;deployed-version 必传。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    for gone in (
        "PREFLIGHT_TRUST_ANCHOR_B64",
        "PREFLIGHT_REMEDIATION_EVIDENCE_B64",
        "PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64",
        "PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64",
    ):
        assert gone not in text, gone
    assert "--remediation-ack" not in text
    assert "remediation-evidence" not in text
    assert "approval-public-key" not in text
    assert "rollback" not in text.lower()
    assert text.count("secrets.PROD_DEPLOY_SSH_KEY") >= 1
    assert 'SSH_KNOWN_HOSTS_B64: ${{ vars.PROD_SSH_KNOWN_HOSTS_B64 }}' in text
    assert "deploy/prod/production-identity.json" in text
    assert "deploy/prod/uploads-unknown-guard.tsv" in text
    assert '"$H_ID:/tmp/askai-production-identity.json"' in text
    assert '"$H_GUARD:$GUARD_TARGET"' in text, '守卫完整性核对绑定身份声明路径'
    assert 'GUARD_CREATED' in text and 'cat > $GUARD_TARGET' in text, '三态送达+创建范围清理在位'
    assert 'if [ -L' in text and '__G3_SYMLINK__' in text, 'symlink 逃逸探测在位'
    assert "--deployed-release-version" in text
    assert "已部署版本不可读" in text
    assert "--verify-upload-isolation" in text
    assert "--isolation-trust-anchor-file /tmp/askai-production-identity.json" in text
    assert '--release-sha "${RELEASE_SHA:-}"' in text


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
    prov = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("id") == "provision_host_script"][0]
    assert "pinned-update-sh-sha256" in prov["run"]
    assert "ASKAI_DEPLOYED_VERSION_GUARD_V1" in prov["run"]


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
    assert "--private-key" in tool_text
    import re as _re

    for mch in _re.finditer(r"[A-Za-z0-9+/]{64,}={0,2}", tool_text):
        raise AssertionError(
            f"工具内发现疑似嵌入密钥材料(base64 连续段 ≥64): {mch.group(0)[:40]}…"
        )


def test_approval_pubkey_channel_fully_removed():
    """2026-10-22 通道:验证公钥钉扎通道随 RSA 审批一起退出发布链 ——
    workflow 零 secret 映射、evaluator 零 CLI 入参、update.sh 零透传
    (审计面辅助函数保留,但不存在任何发布路径消费它)。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    channel = "PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64"
    assert channel not in text
    eval_src = EVALUATOR.read_text(encoding="utf-8")
    assert "--remediation-approval-public-key-file" not in eval_src
    assert "--remediation-evidence-file" not in eval_src
    assert "_load_approval_public_key" in eval_src
