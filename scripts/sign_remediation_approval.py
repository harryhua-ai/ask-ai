#!/usr/bin/env python3
"""A 离线整改审批签发工具(stdlib-only;绝不进入任何生产执行面)。

用途(R6v3,A R6v2 审查阻塞 1 修复的签发侧):
    Role A 在离线受控路径对整改证据记录(v3 schema)的规范化载荷签发
    RSASSA-PKCS1-v1_5(SHA-256)签名,产出带 ``approval.signature`` 的完整
    记录与验证公钥 JSON。审批私钥(RSA-2048,PKCS#1 PEM)**只**在本工具
    与 A 受控环境出现;生产评估器(scripts/release_preflight.py)仅持验证
    公钥(经可信钉扎通道送达),无法签发 ⇒ 应用容器 env 权限不构成签发能力。

用法:
    python3 scripts/sign_remediation_approval.py \\
        --private-key /secure/approval-2048.pem \\
        --record record.json \\
        [--output record.signed.json]        # 缺省写 stdout
        [--emit-public-key approval-pub.json]  # 同时输出验证公钥 JSON

输入记录(v3 封闭词表;approval.signature 缺省占位均可,签发时覆写):
    {"version":3,"gate":...,"target_tag":...,"release_sha":...,
     "evidence_digest":...,"evidence_ref":...,"recorded_at":...,
     "recorded_by":...,"not_after":...,
     "approval":{"approved_by":...,"approved_at":...}}

私钥文件:PEM PKCS#1(``-----BEGIN RSA PRIVATE KEY-----``)。DER 解析为
固定 RSAPrivateKey 九整数序列(纯 stdlib ~40 行;本工具场景模数恒 2048,
无嵌套/可选结构,显式拒绝其它形状)。私钥材料绝不入 argv、绝不出现在
任何错误/日志输出;记录/公钥输出为非秘密。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

# 与评估器同一载荷构造(单一事实源,杜绝两侧规范化漂移)。以文件路径
# 直接运行时 sys.path[0] 为本目录,显式前置仓库根保证 import 可用。
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.release_preflight import (  # noqa: E402
    _APPROVAL_RSA_MODULUS_BITS,
    _APPROVAL_SIGNATURE_HEX_LEN,
    _RSA_SHA256_DIGEST_INFO_PREFIX,
    _approval_signature_payload,
    _load_remediation_evidence,
)

_PEM_BEGIN = "-----BEGIN RSA PRIVATE KEY-----"
_PEM_END = "-----END RSA PRIVATE KEY-----"


# --------------------------------------------------------------------------- #
# PKCS#1 RSAPrivateKey DER 解析(固定九整数序列;显式拒绝其它形状)
# --------------------------------------------------------------------------- #
def _der_tlv(data: bytes, off: int) -> tuple[int, bytes, int]:
    """读取单个 DER TLV → (tag, value, next_offset)(定长形式即可覆盖本场景)。"""
    if off + 2 > len(data):
        raise ValueError("DER 截断")
    tag = data[off]
    length = data[off + 1]
    off += 2
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or off + n > len(data):
            raise ValueError("DER 长度头非法")
        length = int.from_bytes(data[off : off + n], "big")
        off += n
    if off + length > len(data):
        raise ValueError("DER 值越界")
    return tag, data[off : off + length], off + length


def parse_rsa_private_key_pem(pem_text: str) -> dict:
    """PKCS#1 PEM → {n, e, d}(version≠0/序列非九整数/非 RSA-2048 一律拒绝)。"""
    lines = [ln.strip() for ln in pem_text.splitlines()]
    if not (
        _PEM_BEGIN in lines
        and _PEM_END in lines
        and lines.index(_PEM_BEGIN) < lines.index(_PEM_END)
    ):
        raise ValueError("私钥须为 PEM PKCS#1(RSA PRIVATE KEY)形状")
    body = "".join(lines[lines.index(_PEM_BEGIN) + 1 : lines.index(_PEM_END)])
    try:
        der = base64.b64decode(body, validate=True)
    except Exception as exc:  # noqa: BLE001 - 统一结构化拒绝
        raise ValueError("私钥 base64 非法") from exc
    tag, seq, rest = _der_tlv(der, 0)
    if tag != 0x30 or rest != len(der):
        raise ValueError("私钥 DER 顶层必须为单一 SEQUENCE")
    ints: list[int] = []
    off = 0
    while off < len(seq):
        itag, ivalue, off = _der_tlv(seq, off)
        if itag != 0x02:
            raise ValueError("RSAPrivateKey 序列只允许 INTEGER 成员")
        ints.append(int.from_bytes(ivalue, "big"))
    # version, n, e, d, p, q, exponents, coefficient = 恰 9 个整数
    if len(ints) != 9 or ints[0] != 0:
        raise ValueError("RSAPrivateKey 须为 version=0 的九整数序列")
    _version, n, e, d = ints[0], ints[1], ints[2], ints[3]
    if n.bit_length() != _APPROVAL_RSA_MODULUS_BITS:
        raise ValueError(
            f"私钥模数必须为恰 {_APPROVAL_RSA_MODULUS_BITS} 位(RSA-2048 钉扎)"
        )
    if d <= 0 or d >= n:
        raise ValueError("私钥指数形状非法")
    return {"n": n, "e": e, "d": d}


# --------------------------------------------------------------------------- #
# RSASSA-PKCS1-v1_5(SHA-256)签发(与评估器精确 EM 验证互为镜像)
# --------------------------------------------------------------------------- #
def sign_payload(key: dict, payload: bytes) -> str:
    """EM = 0x00 0x01 || FF..FF || 0x00 || DigestInfo(SHA-256) || H(payload);
    签名 = pow(EM, d, n),输出 %d 位小写 hex。""" % _APPROVAL_SIGNATURE_HEX_LEN
    n, d = int(key["n"]), int(key["d"])
    k = _APPROVAL_RSA_MODULUS_BITS // 8
    digest_info = _RSA_SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(payload).digest()
    ps_len = k - 3 - len(digest_info)
    if ps_len < 8:
        raise ValueError("RSA 参数导致 PKCS#1 padding 空间不足")
    em = b"\x00\x01" + b"\xff" * ps_len + b"\x00" + digest_info
    m = int.from_bytes(em, "big")
    if m >= n:
        raise ValueError("EM 超出模数范围(私钥形状非法)")
    return pow(m, d, n).to_bytes(k, "big").hex()


def public_key_json(key: dict) -> dict:
    return {
        "kty": "rsa",
        "n_hex": format(int(key["n"]), "x").zfill(_APPROVAL_SIGNATURE_HEX_LEN),
        "e_hex": format(int(key["e"]), "x"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sign_remediation_approval",
        description="A 离线整改审批签发(RSA-2048 PKCS#1 v1.5 + SHA-256;"
        "stdlib-only;绝不进入生产执行面)",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--private-key", required=True, metavar="PATH",
        help="审批私钥 PEM PKCS#1 路径(RSA-2048;仅 A 离线受控路径;绝不入 argv/日志)",
    )
    parser.add_argument(
        "--record", required=True, metavar="PATH",
        help="整改证据记录 JSON(v3;approval.signature 允许缺省,签发时覆写)",
    )
    parser.add_argument(
        "--output", default=None, metavar="PATH",
        help="签发后记录输出路径(缺省 stdout;输出为非秘密)",
    )
    parser.add_argument(
        "--emit-public-key", default=None, metavar="PATH",
        help="同时输出验证公钥 JSON({kty,n_hex,e_hex};非秘密)",
    )
    args = parser.parse_args(argv)

    try:
        key = parse_rsa_private_key_pem(
            Path(args.private_key).read_text(encoding="utf-8")
        )
    except OSError:
        print("❌ 私钥文件不可读", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"❌ 私钥形状非法: {exc}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ 记录不可读/非合法 JSON({type(exc).__name__})", file=sys.stderr)
        return 2
    if not isinstance(raw, dict):
        print("❌ 记录根必须是映射", file=sys.stderr)
        return 2
    # 签发前以评估器同款加载器校验记录(approval.signature 先占位;
    # 占位值形状合法 ⇒ 校验只针对其余字段与绑定形状)。经临时文件复用
    # 同一加载器,保证签发侧与验证侧逐字同规(单一事实源)。
    probe = json.loads(json.dumps(raw))
    probe.setdefault("approval", {})
    if not isinstance(probe["approval"], dict):
        print("❌ 记录 approval 必须是映射", file=sys.stderr)
        return 2
    probe["approval"]["signature"] = "0" * _APPROVAL_SIGNATURE_HEX_LEN
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(probe, fh, ensure_ascii=False)
        tmp_path = fh.name
    try:
        checked, err = _load_remediation_evidence(
            tmp_path, probe.get("target_tag"), probe.get("release_sha")
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if checked is None:
        print(f"❌ 记录形状校验失败({err})—— 拒绝签发", file=sys.stderr)
        return 2

    signature = sign_payload(key, _approval_signature_payload(checked))
    checked["approval"]["signature"] = signature
    text = json.dumps(checked, ensure_ascii=False, indent=1) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"✅ 已签发 → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    if args.emit_public_key:
        Path(args.emit_public_key).write_text(
            json.dumps(public_key_json(key)) + "\n", encoding="utf-8"
        )
        print(f"✅ 验证公钥 → {args.emit_public_key}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
