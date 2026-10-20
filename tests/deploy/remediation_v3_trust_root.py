"""R6v3 测试信任根(共享;test-only,绝不宣称生产已整改)。

本模块提供两对**预生成、嵌入常量**的 RSA-2048 测试密钥:

- TRUSTED:测试审批信任根(模拟 A 离线受控签发路径的私钥);
- ATTACKER:模拟"拥有应用容器 env 权限但无私钥(本信任根私钥)"的攻击者
  自造密钥 —— 用于证明:攻击者只能用自己生成的密钥签发,而验证侧钉扎的
  是 TRUSTED 公钥 ⇒ 任何 env 操作/自造密钥都无法构造 PASS。

两对密钥均为本测试套件一次性生成(纯 stdlib Miller-Rabin 试错法,2026-10-20),
**仅用于测试**,与任何生产审批私钥无关;生产信任根的建立属 A 受信签发路径
(scripts/sign_remediation_approval.py + A 离线保管的 PEM),绝不进入仓库。

签发走与生产签发工具同一逻辑(scripts.sign_remediation_approval.sign_payload
+ scripts.release_preflight._approval_signature_payload),保证测试正例与
生产签发路径逐字节同构。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# --------------------------------------------------------------------------- #
# 预生成测试密钥(PEM PKCS#1;test-only 常量,非生产材料)
# --------------------------------------------------------------------------- #
ARTIFACT_BYTES = b"RECOVERY-DRILL-EVIDENCE-BUNDLE-v1 (test trust root)\n"


def _load_full_pem(name: str) -> str:  # pragma: no cover - 占位,不使用
    raise NotImplementedError


class RsaTrustRoot:
    """测试信任根:RSA-2048 密钥对 + 真实工件 + v3 已签发记录(临时文件)。

    签发 = 生产签发工具同一代码路径(scripts.sign_remediation_approval)。
    """

    def __init__(self, tmp_path: Path, pem: str | None = None, label: str = "trust"):
        import sys

        repo = Path(__file__).resolve().parents[2]
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from scripts.sign_remediation_approval import (
            parse_rsa_private_key_pem,
            public_key_json,
        )

        self.pem = pem or TRUSTED_RSA_PRIVATE_KEY_PEM_FULL
        self.key = parse_rsa_private_key_pem(self.pem)
        self.pubkey = public_key_json(self.key)
        self.label = label
        self.tmp = Path(tmp_path)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.artifact = self.tmp / f"{label}-bundle.bin"
        self.artifact.write_bytes(ARTIFACT_BYTES)
        self.digest = hashlib.sha256(ARTIFACT_BYTES).hexdigest()
        self.record_path = tmp_path / f"{label}-record.json"
        self.pubkey_path = tmp_path / f"{label}-pubkey.json"
        self.pubkey_path.write_text(json.dumps(self.pubkey), encoding="utf-8")

    # ---- 记录构造与签发(与生产签发工具同一逻辑) ----
    def base_record(self) -> dict:
        return {
            "version": 3,
            "gate": "gate-token-x",
            "target_tag": "v9.9.9",
            "release_sha": "a" * 40,
            "evidence_digest": self.digest,
            "evidence_ref": "recovery-drill/2026-10-20/bundle-sha",
            "recorded_at": "2026-10-20T12:00:00+00:00",
            "recorded_by": "role-a",
            "not_after": "2099-01-01T00:00:00+00:00",
            "approval": {
                "approved_by": "role-a",
                "approved_at": "2026-10-20T12:00:00+00:00",
            },
        }

    def sign(self, record: dict) -> dict:
        """对记录(任意字段覆盖后)用本信任根私钥签发 approval.signature。"""
        import copy
        import sys

        repo = Path(__file__).resolve().parents[2]
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from scripts.release_preflight import _approval_signature_payload
        from scripts.sign_remediation_approval import sign_payload

        rec = copy.deepcopy(record)
        rec["approval"]["signature"] = sign_payload(
            self.key, _approval_signature_payload(rec)
        )
        return rec

    def signed(self, **overrides) -> dict:
        rec = self.base_record()
        for key, value in overrides.items():
            if key == "approval" and isinstance(value, dict):
                rec["approval"].update(value)
            else:
                rec[key] = value
        return self.sign(rec)

    def pubkey_b64(self) -> str:
        """公钥 JSON 的 base64(workflow secret 通道形态;非秘密材料)。"""
        import base64

        return base64.b64encode(
            json.dumps(self.pubkey).encode("utf-8")
        ).decode("ascii")

    def write_record(self, record: dict) -> Path:
        self.record_path.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        return self.record_path


# --------------------------------------------------------------------------- #
# 完整 PEM 常量(下方为实际使用的完整密钥;上面片段仅为文档注释)
# --------------------------------------------------------------------------- #
TRUSTED_RSA_PRIVATE_KEY_PEM_FULL = """\
-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEAwrggUEK9mOE/sOjoVKw6a3R2uENqqAC/tlFu3/VSxaAS1FCM
UWiWF6YI4dryeGWE/IGuy3P8wnW7oDBcUtvvRZ/a+rgHmQgAZ5c/CTmJHietFHsE
vfWe8KqgjR1aHbNz2Bv6qGxIRjsFUtOtvHrLRyWLaWELJnAb6SazycPwb6EyA5a5
zF/RphzfD6TXKHWDXZMCB+i7zE+v0zO+0JEClgvT/Dz59TdF6d84fv2TmMHPKN9B
dqJ4vWT109/7Rzgl4PJHe3EcuDmFUb7Jz9gtDxifatWcuuAHdKF5wEM8fTqaDavr
Zf+0+ct/X6P6vMfZQR57djiX8LYfUNPsWhC3TwIDAQABAoIBAH1n2GfYlANCDqMB
XaAqy/UorM0/nhFVaiMhjybt+MEOtxHGTpifowrYBCBxwneH6n41hz3BFain6o7g
lpVG0HMm4QFYRIxqetg8sHxgcc7Z/r6R/BvbdOHLAlvf64n1aUZlvql6E5InsOYH
Ln2VGBZaN89GkMfQrCkco+3uI4vARYhC7J/wlP+wDy7DtfPTtdDrOYH7jmVpXxyi
cCeOfEYS3zRoeCf9PXjcUej1xs2ySO6bHl5TqEKgXY1WCqxwM5B2t8Hd5trHCwd5
FRLMdyqkb4ewyku1/DNX95Z1Q15SlfYyZjBG1df3SnYIdnXcuYn3QOmfQHZSanHe
Au9pmwECgYEA1shlBZMCuVai3hhNNP6Jj59uUVACXZWwWxugeXk19PQMCIBDUJi0
qa0dMwBfpQpKRsQsDrUi1gU9wEpMg4i6c2px1H9iYwhkUAg/95WcIxzebrBxwE8+
zg/xVnZcovy0xgB1JiSvgWGwt2TLOSTXJa5XqEzsd3sks35J/RRnE1MCgYEA6BYS
hgOeYAYUy2fMQDORQVln+Z1gWVr3azHXH6C6hUJqtFgF0BQuJkr2v2W6LEFDL7DB
3sGVVVZ5sd0bw8+aCKIb3M6CisMoPe7VBDrOtS8ydlThhRpOTSIwKyiiUZI+3R7T
OeKFJmdPK3ckLhkV32Vz4kt0oTOog0fo6SyMqJUCgYBMDJage6Y6Q6/VXdtwiTPh
87yW8/Jyen8AM28Fs+JkAkmEdQ3gqsFFVvOAzIARKuyT1AAZkQ9tolt0C5q99Bq4
pRb6+8O1dxI1uEYV/xZS5HTp0nXkduqxAbodODmiyEGl3iGcyN6PvCxbM0g1ypKX
V/zXra0IvUSIfY3rG19H2wKBgGBMcEktDTT4sP4pRoXJH9dGuq7HDyhkZ08SMhnM
fjg288F62IabKP74keOe2R3twmvyYq8EEeuD4yDbBt87r8UvRnJbOa1MBtGT3M1R
fV2OhNi2pZCt9plouyXdSWShUvY7CRf2lpr1uNLnL5r1C69TED9wYadVoPFAEDNY
KdD1AoGAJbKXTEYP/jGyGPXB1g1CVQKHJZUcAoV5Yu0OW7vcC4nVFH3WAn8eMKSw
cOQfFqzMPHT9SHuf79ncuE/8FeSXVzYIDVaOH9rGs0+JTU5i1EtNC5HbmawbRyrl
W5XN1KTUOblL1m/WNTRQ9h0+2Yp9YG0DztQ4iqXhH9cthnShQdQ=
-----END RSA PRIVATE KEY-----
"""

ATTACKER_RSA_PRIVATE_KEY_PEM_FULL = """\
-----BEGIN RSA PRIVATE KEY-----
MIIEpQIBAAKCAQEAzmOJ41H1NcZ/U6dzYBLssI6s4cYd6Kshawwrjp8C1habMLoY
e+Y4p7xRTZwh+rFY40znJQ9845uTh1hPoBK6D5OUaklYDP7Py4lyr3L8wqYSQuLT
L7gTQPie46mAoV3rGQa6FXXPHjkSQM07ASiGj5yk7vx7pBUzRyIe1r0u9WcT08HX
gLyRol5FwhJ0uCU6fK5BywzzfEVw5JEDuFl1Nuw3bK6SpxppXsKqN3ABl94afnea
BjhXYcEu/Tk8G51qnGkN+zAGlqUUTQkvwFAd3fQ1W0T7JSvAQlmQnNcKt0mmOqDG
WTGIoTStPiYGZg6tVUxQPx+2Zg9xj2WsNy6b4wIDAQABAoIBAAID9tTBeCOOTLAE
cpv9k1ImEooh5SjggvMIq2Q5KU3t6pYPOy36kZMRw7l+TNal5LhTh+5UuGOAoXAw
7JYjmK2OQ2TGUpXN5zmVngkYll9QP91nWaido5J+2w5eGWN6B1G3Pxn2jI8+/26i
knDwdF/yp6mtzYdMrbOEIcj3D/5Vft2nwiAuon1xEqGjMImeXPWP30ppuOthMAx7
fRo+Ep9uUsje66YLZkl7IMa5FaYzbGio8PuohsYjVGEuoZJSCUs9li9619wBGUIX
2pj0A1ScUZGr++qcXG85+HfpBiC2Y83Ro4VR9gWyXkCmQzz35W0IpjaZnRE/a8L2
lS7+yAECgYEA8DluTtuosNtAxBe1MuIrxMGBYm/GJTX8UFexcEib1qHX7+c0TL74
/DnfeYBlKBQREZFzXntEt5YQemOpDZi+zt7+mM6NOVqTDcFGGvaVz++Pgmi6gSTm
0BKlO48f5kn98/YyrrbhggsWEsl59gh8KJe/Xe9T+JV41JioacXgGIsCgYEA2/FG
0kTGAljj4JTV/LZqB1xxVNer328K9K6oir54eS5M/j5lQ+u2F/3r4yyys2aSZBet
LOcl2e4Mf5hb4VSgXNRDfL9sqn7jHt6EZ6pIl0giOia4PcNbuFnxQRnrIIhJ48in
KAzrfR+QOT+qgkXrKSse2QMQrKuXzzXNM2lSHQkCgYEA1LNFRHWiC9ZWpkoHmqI/
9tsPYMVvQItoeQrshWsE8SokNLsWx81gUJQ9lytkZfQ+mLuc1092LMeml3eeu/c/
G5S/ATYCPYJBKrCzDjS/uXl4LBPm72ppJFseCnpT2Ggzf8vCXIh5a9e9F61lW79v
j9GtE9NRGo3eiv8QP3eBULkCgYEAo/91gmX7i1aCnDv+j0/pIZIBg3TJWHIxJh9x
1vqNVDZ8/HrEAXApuBwDHsJ+gRyzfWTWIQw+AhDpSt7ta8gxRuaTZ9pIiZzRd3wO
GEo1lHAZ7WhfqtYXdw/Bv3w3AWv+RJWiZk+z6/l0Dev2FOtTnL/lYYVSkp3kNYJ1
fqdCrhkCgYEApQM3vi659ixcr9RLyWuNqATt3sjTnHaBmd/xnGqopIo+HeaL1vd8
pXjkQNhRE10lClO8vxovo4W120bnK6DB+vARvDwqdHQ5zJJbh4UPeDxOV3RWiml/
ImugSoRlJulHQCDf+YrFdJ9hNESfg7SwYSAkk7PaAU5qTMlA005qCoE=
-----END RSA PRIVATE KEY-----
"""
