"""#114 阶段 E(R2 修正版):GeoIP2 受信国家信号候选工件的结构与机械门断言。

候选工件(deploy/prod/geoip2/)仅供离线评审;本文件把「默认 off」、
「隐私/凭据红线」与 R2 五项阻塞的修复固化为机械断言:

- AC2 默认不启用:nginx 片段示例、env 装配示例全部处于注释态;
  生产 compose 不含任何 COUNTRY_/GEO_ 键(装配只经宿主 .env 示例);
- AC4 凭据红线:更新脚本 license key **零 argv**(只进 0600 curl 配置文件)、
  stderr 脱敏、不 set -x;成功更新后保留 .bak(--rollback 恒可用);
  MMDB 校验 = 真实结构解析(合成 MMDB 正/负样本单测);
- AC1/AC5 预检机械门:G6b 受信 CIDR = 网桥网关 /32 **精确相等**(整网段
  假 PASS 负向 fixture 必拒);G7 基于 nginx -T 生效配置(注释假 PASS/
  静态值假 PASS 负向 fixture 必拒);G8 发布端口仅 loopback(受信跳边界);
  G5 全程类别化输出(真实网关/子网值不回显);
- AC3/AC5 DSN 纪律:离线契约测试缺 TEST_DATABASE_URL / 非测试库名 /
  APP_MODE=prod 时在收集期拒绝(subprocess 导入守卫,证明不可能连默认
  生产同名 DSN)。

零网络、零 docker、零生产 mutation(纯仓库静态检查 + 本地子进程导入)。
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GEOIP2_DIR = REPO / "deploy" / "prod" / "geoip2"
NGINX_EXAMPLE = GEOIP2_DIR / "nginx-geoip2.conf.example"
ENV_EXAMPLE = GEOIP2_DIR / "geoip2.env.example"
UPDATE_SH = GEOIP2_DIR / "update-geolite2.sh"
PRECHECK_SH = GEOIP2_DIR / "precheck-geoip2.sh"
MMDB_VALIDATE = GEOIP2_DIR / "mmdb_validate.py"
PRECHECK_CHECKS = GEOIP2_DIR / "precheck_checks.py"
COMPOSE = REPO / "deploy" / "prod" / "docker-compose.yml"
CONTRACT_TEST = REPO / "tests" / "api" / "test_geoip2_ingress_contract_offline.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _active_lines(text: str) -> list[str]:
    """去掉注释与空行后的「生效行」(nginx/bash 通用近似)。"""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


# --------------------------------------------------------------------------- #
# AC2:默认不启用
# --------------------------------------------------------------------------- #


def test_nginx_example_has_no_active_directive():
    """示例文件内不得有任何未注释的 nginx 指令(默认关闭 = 纯文档态)。"""
    text = NGINX_EXAMPLE.read_text(encoding="utf-8")
    active = [ln for ln in _active_lines(text) if not ln.startswith("#")]
    directive_like = [
        ln
        for ln in active
        if re.search(r"\b(geoip2|map|proxy_set_header|server|location|include|auto_reload)\b", ln)
    ]
    assert directive_like == [], f"示例含未注释生效指令: {directive_like}"
    # 关键语义仍必须以注释形态存在(可审查、可复制启用)
    assert "geoip2 " in text and "auto_reload" in text
    assert "proxy_set_header geo-country" in text
    assert "XX" in text  # 保留码 → Unknown 的双重防线


def test_env_example_all_keys_commented():
    """三键在示例中必须全部处于注释态(默认关闭)。"""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("COUNTRY_RESOLUTION_MODE", "COUNTRY_INGRESS_HEADER", "GEO_TRUSTED_PROXY_CIDRS"):
        active = [ln for ln in _active_lines(text) if ln.startswith(key + "=")]
        assert active == [], f"{key} 在示例中被启用: {active}"
        assert f"# {key}=" in text, f"{key} 缺少注释态装配行"


def test_prod_compose_untouched_by_geo_keys():
    """生产 compose 不得出现三键(装配通道只有宿主 .env;compose 零改动)。"""
    text = COMPOSE.read_text(encoding="utf-8")
    for key in ("COUNTRY_RESOLUTION_MODE", "COUNTRY_INGRESS_HEADER", "GEO_TRUSTED_PROXY_CIDRS"):
        assert key not in text, f"compose 出现 {key} —— 越出 env_file 装配契约"


# --------------------------------------------------------------------------- #
# AC4:凭据与更新脚本安全红线(R2 修正:零 argv 凭据 + 常备回滚)
# --------------------------------------------------------------------------- #


def test_no_license_key_file_in_repo():
    """仓库(geoip2 候选目录)不得含任何 key/凭据文件。"""
    for p in GEOIP2_DIR.rglob("*"):
        name = p.name.lower()
        assert not re.search(
            r"license[-_]?key|\.key$|credential|secret", name
        ), f"疑似凭据文件入库: {p}"


def test_update_script_credential_never_on_argv():
    """R2 阻塞项:license key 不得进 curl 命令行参数(OS 进程可见)。

    机械断言:
    - curl 调用走 -K/--config 配置文件,配置文件 chmod 0600;
    - 任何含 curl 的生效行不得插值 $key/${key};
    - 输出类命令(echo/log/die)永不携带 key;printf 携带 key 仅允许写入
      curl 配置文件那一条(0600、随 tmpdir 清理);
    - curl stderr 须经脱敏(key 与 license_key= 查询参数抹除)后才输出;
    - 仍无 set -x。
    """
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    active = "\n".join(_active_lines(text))
    assert not re.search(r"set\s+-[a-zA-Z]*x", active), "禁止 set -x(会回显凭据)"
    # curl 配置文件机制在位
    assert re.search(r"\bcurl\b\s+-K\b", active), "curl 必须经 -K 配置文件(零 argv)"
    assert 'chmod 0600 "$curlcfg"' in active
    # curl 命令行不得出现 key
    for line in _active_lines(text):
        if re.search(r"\bcurl\b", line):
            assert not re.search(r"\$\{?key\b", line), f"curl argv 携带 key: {line!r}"
    # 输出类命令永不携带 key
    for m in re.finditer(r"(?:echo|log|die)\s+[^#\n]*\$\{?key\b", active):
        raise AssertionError(f"凭据可能被输出: {m.group(0)!r}")
    # printf 仅允许「写 curl 配置文件」携带 key
    for m in re.finditer(r"printf\s+[^#\n]*\$\{?key\b", active):
        assert '>"$curlcfg"' in m.group(0), f"key 只允许写入 0600 curl 配置文件: {m.group(0)!r}"
    # stderr 脱敏在位:key 经环境变量(非 argv)传给脱敏器
    assert "_redact_and_die" in active
    assert 'CURL_SCRUB_KEY="$key"' in active
    assert "license_key=" in active  # 脱敏器抹除 license_key= 查询参数


def test_update_script_atomic_replace_and_rollback_always_available():
    """同目录 mktemp + rename(2) 原子替换;成功更新后 .bak **保留**(R2:
    旧实现成功即删 .bak,--rollback 恰在最需要时不可用)。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "mktemp -d" in text and "mv -f" in text, "缺少临时目录 + 原子 rename"
    assert not re.search(r">\s*\"\$\{?MMDB_PATH\}?\"", text), "禁止就地覆写现网 MMDB"
    assert ".bak" in text and "--rollback" in text and "validate_mmdb" in text
    # 成功路径不得删除 .bak
    assert 'rm -f "${MMDB_PATH}.bak"' not in text, "成功更新后必须保留 .bak(回滚常备)"
    assert "上一个已验证有效库保留于" in text


def test_update_script_validation_is_hard_parse():
    """MMDB 校验 = 真实结构解析(R2:标记子串 + 体积下限不证明可读树)。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "command -v curl" in text and "command -v python3" in text
    assert "mmdb_validate.py" in text, "校验必须走 mmdb_validate.py 硬结构门"
    validator = MMDB_VALIDATE.read_text(encoding="utf-8")
    # 真实解码器语义在位(控制字节驱动 + 走树越界门),而非子串匹配
    assert "def _decode" in validator and "node_count" in validator
    assert "METADATA_MARKER" in validator and "visited" in validator
    assert "database_type" in validator and "record_size" in validator


# --------------------------------------------------------------------------- #
# AC1:真实性与信任边界不被放宽
# --------------------------------------------------------------------------- #


def test_nginx_example_does_not_promote_xff_to_remote_addr():
    """示例不得配置 real_ip_*(X-Forwarded-For 可伪造,禁止成为地理输入)。"""
    text = NGINX_EXAMPLE.read_text(encoding="utf-8")
    active = [ln for ln in _active_lines(text)]
    assert not any("real_ip_" in ln for ln in active)


def test_backend_resolver_trust_gate_not_relaxed():
    """resolver 仍只有 ingress 单一权威路径;客户端可控输入不得成为真值。"""
    text = (REPO / "backend" / "services" / "geo_country.py").read_text(encoding="utf-8")
    assert '_RESOLUTION_MODES = ("off", "ingress")' in text
    # 语种/时区等不做地理依据(注释契约仍在,防止无声放宽)
    assert "Accept-Language" in text


def test_no_real_internal_cidr_in_candidate():
    """候选工件不得包含真实内网 CIDR(占位符替换;公网主机地址按既有仓库惯例不出现)。"""
    banned = [
        r"\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+",  # RFC1918 172.16/12 具体地址
        r"\b10\.\d+\.\d+\.\d+/\d+",  # 10/8 具体 CIDR
        r"\b192\.168\.\d+\.\d+",
    ]
    for p in GEOIP2_DIR.iterdir():
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for pattern in banned:
            hits = re.findall(pattern, text)
            assert hits == [], f"{p.name} 含真实内网地址字面量: {hits}"


def test_precheck_script_is_fail_closed_and_mechanical():
    """预检:任一门 FAIL 必须非零退出;门逻辑机械化(R2 修正)。"""
    text = PRECHECK_SH.read_text(encoding="utf-8")
    assert "exit 1" in text and "fail-closed" in text
    assert "--expect" in text
    # 机械门外置(独立纯函数模块)+ 精确语义在位
    assert "precheck_checks.py" in text
    assert "mmdb_validate.py" in text, "G3 必须走硬结构校验"
    assert "nginx -T" in text, "G7 必须基于生效配置,不得源码 grep"
    assert "sites-enabled" not in text, "禁止源码 grep vhost(grep 命中注释 = 假 PASS)"
    assert "HostIp" in text and "G8" in text, "G8 发布端口边界门必须在位"
    # G5/G6 类别化:真实网关/子网值不回显(R2 红线)
    assert "gateway=${BRIDGE_GW}" not in text and "subnet=${BRIDGE_SUBNET}" not in text
    assert "值仅现场比对,不回显" in text


def test_precheck_documented_change_is_true_disable_not_copy():
    """回退序列必须是真禁用(mv 出 include 通配),不是 cp 一份副本(R2)。"""
    example = NGINX_EXAMPLE.read_text(encoding="utf-8")
    assert "cp -a /etc/nginx/conf.d/ask-ai-geoip2.conf" not in example
    assert "mv /etc/nginx/conf.d/ask-ai-geoip2.conf" in example
    readme = (GEOIP2_DIR / "README.md").read_text(encoding="utf-8")
    assert "cp -a /etc/nginx/conf.d/ask-ai-geoip2.conf" not in readme
    assert "mv /etc/nginx/conf.d/ask-ai-geoip2.conf" in readme
    # nginx -t 失败不得中止后续回退步骤(恢复 + 继续语义在文档中固化)
    assert "继续执行第 3 步" in example


# --------------------------------------------------------------------------- #
# mmdb_validate:合成 MMDB 正/负样本(R2:硬解析必须有真判定力)
# --------------------------------------------------------------------------- #


def _mmdb_helpers():
    return _load_module(MMDB_VALIDATE, "mmdb_validate_under_test")


def _enc_str(s: str) -> bytes:
    b = s.encode()
    assert len(b) < 29
    return bytes([(2 << 5) | len(b)]) + b


def _enc_uint16(n: int) -> bytes:
    return bytes([(5 << 5) | 2]) + n.to_bytes(2, "big")


def _enc_uint32(n: int) -> bytes:
    return bytes([(6 << 5) | 4]) + n.to_bytes(4, "big")


def _enc_meta(meta: dict) -> bytes:
    out = bytearray([(7 << 5) | len(meta)])
    for k, v in meta.items():
        out += _enc_str(k) + v
    return bytes(out)


def _enc_str_any(s: str) -> bytes:
    """按官方规范编码 utf8 string(支持 29/30/31 变长 size 标记):
    <29 直接 5 位;29..284 = 29+1B;285..65820 = 285+2B;≥65821 = 65821+3B。"""
    b = s.encode()
    n = len(b)
    if n < 29:
        return bytes([(2 << 5) | n]) + b
    if n < 285:
        return bytes([(2 << 5) | 29, n - 29]) + b
    if n < 65_821:
        return bytes([(2 << 5) | 30]) + (n - 285).to_bytes(2, "big") + b
    return bytes([(2 << 5) | 31]) + (n - 65_821).to_bytes(3, "big") + b


def _build_synthetic_mmdb(
    db_type: str = "GeoLite2-Country",
    corrupt_node0_right: int | None = None,
    description: bytes | None = None,
    datablob: bytes | None = None,
) -> bytes:
    """最小合法 MMDB(record_size=24,3 节点):走树可命中/未命中两路。
    node0: 0→node1, 1→node2;node1: 0/0(not found);node2: 0→not found,
    1→数据指针。corrupt_node0_right 用于构造越界数据指针的损坏树。
    (规范:数据指针值 ≥ node_count+16;+0..+15 落在 16B 分隔符内 = 非法。)"""
    mod = _mmdb_helpers()
    marker = mod.METADATA_MARKER
    right0 = 2 if corrupt_node0_right is None else corrupt_node0_right
    tree = (
        bytes([0, 0, 1])
        + right0.to_bytes(3, "big")  # node0 右记录(损坏时 = 越界数据指针)
        + bytes([0, 0, 0]) * 2  # node1: 0/0 → not found
        + bytes([0, 0, 0])  # node2 左:0 → not found
        + (3 + 16).to_bytes(3, "big")  # node2 右:数据指针 = node_count+16 → 数据段偏移 0
    )
    sep = marker + b"\x00\x00"  # 16B 数据段分隔符
    datablob = b"\x00" * 8 if datablob is None else datablob
    meta = {
        "binary_format_major_version": _enc_uint16(2),
        "binary_format_minor_version": _enc_uint16(0),
        "build_epoch": bytes([0x08, 0x02]) + (1700000000).to_bytes(8, "big"),
        "database_type": _enc_str(db_type),
        "description": description if description is not None else bytes([7 << 5]),
        "ip_version": _enc_uint16(4),
        "languages": bytes([0x00, 0x04]),  # extended: array, size 0
        "node_count": _enc_uint32(3),
        "record_size": _enc_uint16(24),
    }
    return tree + sep + datablob + marker + _enc_meta(meta)


def test_mmdb_validator_accepts_wellformed_synthetic(tmp_path):
    mod = _mmdb_helpers()
    f = tmp_path / "good.mmdb"
    f.write_bytes(_build_synthetic_mmdb())
    msg = mod.validate_file(str(f), min_bytes=0)
    assert "硬结构校验通过" in msg
    # CLI 通道同样通过(脚本接线面)
    r = subprocess.run(
        [sys.executable, str(MMDB_VALIDATE), str(f), "--min-bytes", "0"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0 and "硬结构校验通过" in r.stdout


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda b: b[:-5], "metadata 截断"),
        (lambda b: _build_synthetic_mmdb(corrupt_node0_right=200000), "走树越界数据指针"),
        (lambda b: _build_synthetic_mmdb(db_type="GeoLite2-City"), "database_type 不符"),
        (lambda b: bytes(len(b)), "无 metadata 标记"),
        # R3 阻塞 ① 负例:数据指针落在 16B 分隔符内部(offset 1..15)= 规范非法
        (lambda b: _build_synthetic_mmdb(corrupt_node0_right=3 + 5), "数据指针落入分隔符内部"),
    ],
)
def test_mmdb_validator_rejects_malformed(tmp_path, mutate, reason):
    mod = _mmdb_helpers()
    f = tmp_path / "bad.mmdb"
    f.write_bytes(mutate(_build_synthetic_mmdb()))
    with pytest.raises(mod.MMDBInvalid):
        mod.validate_file(str(f), min_bytes=0)


class TestMMDBSpecVarSizeAndPointer:
    """R3 阻塞 ①:变长 size 与 pointer 编解码必须与 MaxMind DB v2 官方规范一致。

    旧实现:29/30/31 ⇒ +7/+7+256/+7+256+65536(恰差 22)→ 合法长字符串被
    截短 → metadata 错位误拒;pointer 按 0/1/2/3 字节读且无偏移基数 → 全错。
    官方规范(https://maxmind.github.io/MaxMind-DB/):29+1B / 285+2B /
    65,821+3B;pointer 宽度 1/2/3/4 字节,基数 0/2048/526,336/0。
    """

    @pytest.mark.parametrize("n", [29, 284, 285, 300, 65_820, 65_821, 65_825])
    def test_varsize_string_roundtrip(self, n):
        """marker 29/30/31 三档及边界:解码必须还原完整字符串。"""
        mod = _mmdb_helpers()
        s = "x" * n
        enc = _enc_str_any(s)
        val, pos = mod._decode(enc, 0)
        assert val == s and pos == len(enc)

    def test_long_description_synthetic_mmdb_passes(self, tmp_path):
        """合成合法 MMDB 含 >28B description(真实 GeoLite2 文件形态:走
        marker 29)—— 旧实现截短 22B → metadata 错位误拒;修正后必须通过。"""
        mod = _mmdb_helpers()
        desc = "GeoLite2 Country offline structural validation fixture (fake data only)"
        assert len(desc.encode()) >= 29  # 走 marker 29 变长路径
        f = tmp_path / "long-desc.mmdb"
        f.write_bytes(_build_synthetic_mmdb(description=_enc_str_any(desc)))
        assert "硬结构校验通过" in mod.validate_file(str(f), min_bytes=0)

    def test_pointer_widths_and_bases_per_spec(self):
        """四种指针宽度 1/2/3/4 字节、基数 0/2048/526,336/0(4 字节档低 3 位
        忽略),且解析即解引用(pointer_base 由调用方给定,目标落位精确)。"""
        mod = _mmdb_helpers()
        target = _enc_str("OK")  # 目标值统一为 "OK"(3 字节)

        def stub(head: bytes, target_offset: int, pointer_base: int):
            """head 后接填充至 target_offset,再放目标值;返回 (缓冲, 期望值)。"""
            body = bytearray(head)
            body.extend(b"\x00" * (target_offset - len(head)))
            body.extend(target)
            val, pos = mod._decode(bytes(body), 0, pointer_base=pointer_base)
            return val, pos, bytes(body)

        # width 0:1 字节,值 = 低 3 位<<8 | next,基数 0;低 3 位参与取值
        val, pos, _ = stub(bytes([(1 << 5) | (0 << 3) | 0b000, 0x02]), 2, 0)
        assert val == "OK" and pos == 2
        val, pos, _ = stub(bytes([(1 << 5) | (0 << 3) | 0b001, 0x02]), 0x102, 0)
        assert val == "OK" and pos == 2
        # width 1:2 字节,值 = 低 3 位<<16 | next2,基数 2048
        val, pos, _ = stub(bytes([(1 << 5) | (1 << 3) | 0b000, 0x00, 0x00]), 2048, 0)
        assert val == "OK" and pos == 3
        val, pos, _ = stub(
            bytes([(1 << 5) | (1 << 3) | 0b001, 0x01, 0x00]), (1 << 16) + 0x100 + 2048, 0
        )
        assert val == "OK" and pos == 3
        # width 2:3 字节,值 = 低 3 位<<24 | next3,基数 526,336
        val, pos, _ = stub(bytes([(1 << 5) | (2 << 3) | 0b000, 0x00, 0x00, 0x00]), 526_336, 0)
        assert val == "OK" and pos == 4
        # width 3:4 字节读满 32 位,低 3 位忽略,基数 0
        val, pos, _ = stub(bytes([(1 << 5) | (3 << 3) | 0b111, 0x00, 0x00, 0x00, 0x05]), 5, 0)
        assert val == "OK" and pos == 5
        # pointer_base 语义:目标 = pointer_base + 指针值(metadata 传 metadata 起点)
        val, _, _ = stub(bytes([(1 << 5) | (0 << 3) | 0b000, 0x00]), 100, 100)
        assert val == "OK"

    def test_data_section_pointer_dereference(self, tmp_path):
        """数据段内共享值经 pointer 解引用(真实库压缩形态):记录值 →
        数据段偏移 0 处的 pointer → 偏移 5 处的字符串,走树+解码全链一致。"""
        mod = _mmdb_helpers()
        # 数据段:[0]=pointer 控制字(width0,high=0),[1]=目标偏移 5,[5..7]="SE"
        blob = bytes([0b001_00_000, 0x05]) + b"\x00" * 3 + _enc_str("SE")
        assert len(blob) == 8
        f = tmp_path / "ptr.mmdb"
        f.write_bytes(_build_synthetic_mmdb(datablob=blob))
        data = f.read_bytes()
        mod.validate_bytes(data, min_bytes=0)  # 结构门通过
        # 手工走树(node0 --1--> node2;node2 --1--> 数据记录 = node_count+16
        # → 数据段偏移 0)+ 解码:pointer → 偏移 5 处字符串
        meta, _ = mod._decode(data, data.rfind(mod.METADATA_MARKER) + len(mod.METADATA_MARKER))
        tree_size = meta["node_count"] * meta["record_size"] * 2 // 8
        bits = [1, 1]
        node = 0
        while True:
            rec = mod._read_record(data, node, bits.pop(0), meta["record_size"], tree_size)
            assert rec != 0
            if rec >= meta["node_count"]:
                break
            node = rec
        val, _ = mod._decode(
            data, tree_size + (rec - meta["node_count"]), pointer_base=tree_size + 16
        )
        assert val == "SE"

    def test_real_world_mmdb_cross_check_if_provided(self, tmp_path):
        """真实 MaxMind 文件离线一致性验证(可选,不引入凭据/许可前置)。

        R3 一次性实证(已记录于 README §8):公开 MaxMind-DB test-data 的
        GeoLite2-Country-Test.mmdb(sha256 87b5464d8ea1f348994f89b029f01ef4
        38c6f5c1e040a825e375e4dbe28da321,13,733B;description 76B 走 marker
        29;record_size=28 nibble 拆分、ip_version=6、node_count=896)在本
        校验器下通过,metadata 全字段与官方 maxminddb reader 一致,且
        244/244 个源数据网络记录级一致。生产 GeoLite2 文件本身仍属 owner
        许可前置(UNKNOWN 保持,不下载);提供真实文件路径时本用例自动复验。"""
        path = os.environ.get("MMDB_REAL_WORLD_FILE")
        if not path:
            pytest.skip("UNKNOWN: 未提供真实 MaxMind 文件(生产库属 owner 许可前置)")
        mod = _mmdb_helpers()
        raw = Path(path).read_bytes()
        assert "硬结构校验通过" in mod.validate_bytes(raw, min_bytes=0)
        import hashlib

        if hashlib.sha256(raw).hexdigest() == (
            "87b5464d8ea1f348994f89b029f01ef438c6f5c1e040a825e375e4dbe28da321"
        ):
            meta, _ = mod._decode(raw, raw.rfind(mod.METADATA_MARKER) + len(mod.METADATA_MARKER))
            # R3 一次性验证中经官方 maxminddb 3.2.0 reader 比对的权威值
            assert meta["node_count"] == 896 and meta["record_size"] == 28
            assert meta["ip_version"] == 6 and meta["binary_format_major_version"] == 2
            assert meta["description"] == {
                "en": "GeoLite2 Country Test Database (fake GeoIP2 data, for example purposes only)"
            }


# --------------------------------------------------------------------------- #
# precheck_checks:G6b/G7/G8 机械门负向 fixture(R2 假 PASS 闭合)
# --------------------------------------------------------------------------- #

_checks = None


def _pc():
    global _checks
    if _checks is None:
        _checks = _load_module(PRECHECK_CHECKS, "precheck_checks_under_test")
    return _checks


# 合成网关/地址一律用 RFC 5737 文档段(仓库纪律:真实内网地址不入库)
_GW = "203.0.113.193"


class TestTrustedCidrsExactGateway:
    """G6b:受信 CIDR 必须与网桥网关 /32 精确相等。"""

    def test_exact_gateway_slash32_passes(self):
        ok, msg = _pc().check_trusted_cidrs_exact(f"{_GW}/32", _GW)
        assert ok and "精确相等" in msg

    def test_whole_bridge_subnet_is_rejected(self):
        """R2 假 PASS 负向 fixture:含网关的整网段(旧实现整 /24 也过)必拒。"""
        ok, msg = _pc().check_trusted_cidrs_exact("203.0.113.192/27", _GW)
        assert not ok and "宽于" in msg

    def test_gateway_plus_extra_entry_rejected(self):
        ok, _ = _pc().check_trusted_cidrs_exact(f"{_GW}/32,203.0.113.194/32", _GW)
        assert not ok

    def test_single_non_gateway_entry_rejected(self):
        ok, _ = _pc().check_trusted_cidrs_exact("203.0.113.194/32", _GW)
        assert not ok

    def test_empty_rejected(self):
        ok, _ = _pc().check_trusted_cidrs_exact("", _GW)
        assert not ok

    def test_malformed_rejected(self):
        ok, _ = _pc().check_trusted_cidrs_exact("not-a-cidr", _GW)
        assert not ok

    def test_messages_never_echo_values(self):
        """红线:结论消息不回显真实 CIDR/网关值。"""
        for cidrs in (f"{_GW}/32", "203.0.113.192/27", "not-a-cidr", "203.0.113.194/32"):
            _, msg = _pc().check_trusted_cidrs_exact(cidrs, _GW)
            assert _GW not in msg and cidrs not in msg


class TestPublishBinding:
    """G8:发布端口必须仅 loopback(0.0.0.0 发布 = DNAT 旁路网关 /32)。"""

    def test_loopback_v4_passes(self):
        ok, msg = _pc().check_publish_binding("127.0.0.1")
        assert ok and "loopback" in msg

    def test_loopback_v6_passes(self):
        ok, _ = _pc().check_publish_binding("::1")
        assert ok

    def test_wildcard_v4_rejected(self):
        ok, msg = _pc().check_publish_binding("0.0.0.0")
        assert not ok and "另行授权" in msg

    def test_wildcard_v6_rejected(self):
        ok, _ = _pc().check_publish_binding("::")
        assert not ok

    def test_missing_binding_info_rejected(self):
        ok, _ = _pc().check_publish_binding("")
        assert not ok

    def test_public_host_ip_rejected(self):
        ok, _ = _pc().check_publish_binding("203.0.113.7")
        assert not ok


def _bindings(ports: dict, backend_port: int = 18000):
    import json as _json

    return _pc().check_publish_bindings(_json.dumps(ports), backend_port=backend_port)


class TestPublishBindingsAllMappings:
    """R3 阻塞 ②:G8 必须审计**全部**发布映射的**每一条** HostIp/HostPort
    (单项缺失/非法 fail closed),并与 nginx 实际使用端口一致。
    旧实现只取第一条绑定:第一条 127.0.0.1、第二条 0.0.0.0 时假 PASS。"""

    def test_all_loopback_single_binding_passes(self):
        ok, msg = _bindings({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]})
        assert ok and "loopback" in msg

    def test_dual_stack_loopback_passes(self):
        ok, _ = _bindings(
            {
                "8000/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "18000"},
                    {"HostIp": "::1", "HostPort": "18000"},
                ]
            }
        )
        assert ok

    def test_second_binding_public_rejected(self):
        ok, _ = _bindings(
            {
                "8000/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "18000"},
                    {"HostIp": "0.0.0.0", "HostPort": "18000"},
                ]
            }
        )
        assert not ok

    def test_binding_order_swapped_still_rejected(self):
        """负例 fixture:双绑定顺序互换(不安全项在前)同样必拒。"""
        ok, _ = _bindings(
            {
                "8000/tcp": [
                    {"HostIp": "0.0.0.0", "HostPort": "18000"},
                    {"HostIp": "127.0.0.1", "HostPort": "18000"},
                ]
            }
        )
        assert not ok

    def test_ipv4_loopback_with_ipv6_wildcard_rejected(self):
        """负例 fixture:IPv4+IPv6 混合(0.0.0.0 已挡,:: 也必须挡)。"""
        ok, _ = _bindings(
            {
                "8000/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "18000"},
                    {"HostIp": "::", "HostPort": "18000"},
                ]
            }
        )
        assert not ok

    def test_missing_hostip_field_rejected(self):
        """单项字段缺失 = fail closed(不得当作通配猜测)。"""
        ok, _ = _bindings({"8000/tcp": [{"HostPort": "18000"}]})
        assert not ok

    def test_missing_hostport_field_rejected(self):
        ok, _ = _bindings({"8000/tcp": [{"HostIp": "127.0.0.1"}]})
        assert not ok

    def test_non_integer_hostport_rejected(self):
        ok, _ = _bindings({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000-18010"}]})
        assert not ok

    def test_extra_published_public_port_rejected(self):
        """其它容器端口公开发布同样纳入审计(非 loopback 必拒)。"""
        ok, _ = _bindings(
            {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}],
                "9090/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9090"}],
            }
        )
        assert not ok

    def test_nginx_facing_port_mismatch_rejected(self):
        """审计的绑定必须与 nginx 实际使用的 backend 端口一致。"""
        ok, msg = _bindings({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19999"}]})
        assert not ok and "端口" in msg

    def test_missing_container_port_mapping_rejected(self):
        ok, _ = _bindings({"9999/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9999"}]})
        assert not ok

    def test_empty_or_unparsable_fail_closed(self):
        import json as _json

        for payload in ("", "not-json", _json.dumps([]), _json.dumps({})):
            ok, _ = _pc().check_publish_bindings(payload, backend_port=18000)
            assert not ok, payload
        # 绑定列表为 null(未发布)
        ok, _ = _bindings({"8000/tcp": None})
        assert not ok

    def test_messages_never_echo_binding_values(self):
        """红线:结论消息不回显 HostIp/HostPort 值(不落入持久日志)。"""
        import json as _json

        for ports in (
            {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18000"}]},
            {"8000/tcp": [{"HostIp": "203.0.113.7", "HostPort": "18000"}]},
            {"8000/tcp": [{"HostPort": "18000"}]},
            {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19999"}]},
        ):
            _, msg = _pc().check_publish_bindings(_json.dumps(ports), backend_port=18000)
            for v in ("0.0.0.0", "203.0.113.7", "18000", "19999"):
                assert v not in msg, (ports, msg)


def test_bindings_cli_never_echoes_host_ip():
    """集成级字符串不泄露:bindings 子进程对公开发布绑定的全部输出中
    不得出现宿主 IP 字面量(R2 实证 G8 FAIL 消息插值 ${HOSTIP} 泄漏)。"""
    import json as _json

    payload = _json.dumps(
        {
            "8000/tcp": [
                {"HostIp": "127.0.0.1", "HostPort": "18000"},
                {"HostIp": "203.0.113.7", "HostPort": "18001"},
            ]
        }
    )
    r = subprocess.run(
        [sys.executable, str(PRECHECK_CHECKS), "bindings", "--backend-port", "18000"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = r.stdout + r.stderr
    assert r.returncode == 1, combined
    assert "203.0.113.7" not in combined and "18001" not in combined, combined


_NGINX_OK = """http {
    geoip2 /etc/nginx/geoip/GeoLite2-Country.mmdb {
        auto_reload 5m;
        $ask_ai_geoip_country_code country iso_code;
    }
    map $ask_ai_geoip_country_code $ask_ai_geo_country {
        default "";
        XX "";
    }
    server {
        listen 443 ssl;
        location / {
            proxy_pass http://127.0.0.1:18000;
            proxy_set_header Host $host;
            proxy_set_header geo-country $ask_ai_geo_country;
        }
    }
}
"""


def _ngx(**kw):
    defaults = {
        "header": "geo-country",
        "mmdb_path": "/etc/nginx/geoip/GeoLite2-Country.mmdb",
        "backend_port": 18000,
        "expect": "on",
    }
    defaults.update(kw)
    return _pc().check_effective_nginx_config(defaults.pop("dump", _NGINX_OK), **defaults)


class TestEffectiveNginxConfig:
    """G7:基于 nginx -T 生效配置的覆盖链机械校验。"""

    def test_wellformed_chain_passes(self):
        ok, msg = _ngx()
        assert ok and "覆盖链完整" in msg

    def test_comment_only_directives_do_not_pass(self):
        """R2 假 PASS 负向 fixture:指令只存在于注释中(旧 grep 会过)必拒。
        nginx -T dump 本不含注释;此处构造「无生效 geo 指令」的 dump。"""
        dump = """http {
    server {
        listen 443 ssl;
        location / {
            proxy_pass http://127.0.0.1:18000;
        }
    }
}
"""
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_static_header_value_rejected(self):
        """静态值覆盖(proxy_set_header geo-country US)必拒 —— 请求路径上
        不是 $ask_ai_geo_country 计算值。"""
        dump = _NGINX_OK.replace(
            "proxy_set_header geo-country $ask_ai_geo_country;", "proxy_set_header geo-country US;"
        )
        ok, msg = _ngx(dump=dump)
        assert not ok and "非计算值" in msg

    def test_location_local_proxy_headers_shadow_server_level(self):
        """location 内一旦出现任一 proxy_set_header,父级全部失效(nginx 语义):
        头只在 server 级、location 级另有 proxy_set_header ⇒ 生效层没有该头,必拒。"""
        dump = _NGINX_OK.replace(
            "            proxy_set_header geo-country $ask_ai_geo_country;\n", ""
        )
        ok, msg = _ngx(dump=dump)
        assert not ok and "覆盖链断裂" in msg

    def test_server_level_header_passes_when_location_has_none(self):
        dump = _NGINX_OK.replace("            proxy_set_header Host $host;\n", "").replace(
            "            proxy_set_header geo-country $ask_ai_geo_country;\n",
            "        proxy_set_header geo-country $ask_ai_geo_country;\n",
        )
        ok, _ = _ngx(dump=dump)
        assert ok

    def test_header_inside_if_block_rejected(self):
        """if 包裹的 geo 头(条件下发)破坏无条件覆盖语义 —— 即使无条件行也在。"""
        dump = _NGINX_OK.replace(
            "            proxy_set_header geo-country $ask_ai_geo_country;",
            "            proxy_set_header geo-country $ask_ai_geo_country;\n"
            "            if ($request_method = GET) { proxy_set_header geo-country US; }",
        )
        ok, msg = _ngx(dump=dump)
        assert not ok and "if 块" in msg

    def test_mmdb_path_mismatch_rejected(self):
        ok, _ = _ngx(mmdb_path="/etc/nginx/geoip/other.mmdb")
        assert not ok

    def test_missing_auto_reload_rejected(self):
        dump = _NGINX_OK.replace("        auto_reload 5m;\n", "")
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_map_without_xx_guard_rejected(self):
        dump = _NGINX_OK.replace('        XX "";\n', "")
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_no_proxy_pass_to_backend_port_rejected(self):
        dump = _NGINX_OK.replace(
            "proxy_pass http://127.0.0.1:18000;", "proxy_pass http://127.0.0.1:9999;"
        )
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_empty_header_name_rejected(self):
        ok, _ = _ngx(header="  ")
        assert not ok

    def test_off_mode_clean_dump_passes(self):
        dump = """http {
    server {
        listen 443 ssl;
        location / {
            proxy_pass http://127.0.0.1:18000;
            proxy_set_header Host $host;
        }
    }
}
"""
        ok, msg = _ngx(dump=dump, expect="off")
        assert ok and "默认关闭成立" in msg

    def test_off_mode_with_geoip2_rejected(self):
        ok, _ = _ngx(expect="off")
        assert not ok

    def test_off_mode_with_comment_only_geo_config_passes(self):
        """注释态示例文件(未展开)不算启用 —— 生效配置无 geo 指令。"""
        dump = """http {
    # geoip2 /etc/nginx/geoip/GeoLite2-Country.mmdb { auto_reload 5m; }
    server { listen 443; location / { proxy_pass http://127.0.0.1:18000; } }
}
"""
        ok, _ = _ngx(dump=dump, expect="off")
        assert ok


_NGINX_CHAIN_HEAD = """http {
    geoip2 /etc/nginx/geoip/GeoLite2-Country.mmdb {
        auto_reload 5m;
        $ask_ai_geoip_country_code country iso_code;
    }
    map $ask_ai_geoip_country_code $ask_ai_geo_country {
        default "";
        XX "";
    }
    server {
        listen 443 ssl;
"""


def _two_location_dump(first: str, second: str) -> str:
    """两个 location 反代同一 backend 端口;first/second 为 location 体。"""
    return _NGINX_CHAIN_HEAD + f"""        {first}
        {second}
    }}
}}
"""


_LOC_SAFE = """location /api/ {
            proxy_pass http://127.0.0.1:18000;
            proxy_set_header geo-country $ask_ai_geo_country;
        }"""

_LOC_UNSAFE = """location / {
            proxy_pass http://127.0.0.1:18000;
        }"""


class TestAllBackendPathsAudited:
    """R3 阻塞 ③:多条 backend 反代路径必须**全部**逐一证明生效层无条件
    同名头覆盖 —— 旧实现找到首个 :port 路径即 break,第二条不安全路由假 PASS。"""

    def test_second_unsafe_path_rejected(self):
        dump = _two_location_dump(_LOC_SAFE, _LOC_UNSAFE)
        ok, msg = _ngx(dump=dump)
        assert not ok and "覆盖链断裂" in msg

    def test_unsafe_first_swapped_still_rejected(self):
        """负例 fixture:顺序互换(不安全项在前)同样必拒。"""
        dump = _two_location_dump(_LOC_UNSAFE, _LOC_SAFE)
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_both_paths_with_header_passes(self):
        safe = _LOC_SAFE.replace("location /api/", "location /api2/")
        dump = _two_location_dump(_LOC_SAFE, safe)
        ok, _ = _ngx(dump=dump)
        assert ok

    def test_second_vhost_without_header_rejected(self):
        """server 级多 vhost:第一个 vhost 覆盖、第二个裸 proxy_pass 必拒。"""
        dump = _NGINX_CHAIN_HEAD + """        location / {
            proxy_pass http://127.0.0.1:18000;
            proxy_set_header geo-country $ask_ai_geo_country;
        }
    }
    server {
        listen 8443 ssl;
        location / {
            proxy_pass http://127.0.0.1:18000;
        }
    }
}
"""
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_vhost_order_swapped_still_rejected(self):
        dump = _NGINX_CHAIN_HEAD + """        location / {
            proxy_pass http://127.0.0.1:18000;
        }
    }
    server {
        listen 8443 ssl;
        location / {
            proxy_pass http://127.0.0.1:18000;
            proxy_set_header geo-country $ask_ai_geo_country;
        }
    }
}
"""
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_nested_location_inheritance_shadow_rejected(self):
        """继承遮蔽:server 级有 geo 头,但中间层 location /a 有任一
        proxy_set_header(仅 Host)⇒ 内层 /a/b 生效层 = /a,geo 头失效。
        旧实现跳过中间层直接看 server 级 → 假 PASS。"""
        dump = _NGINX_CHAIN_HEAD + """        proxy_set_header geo-country $ask_ai_geo_country;
        location /a/ {
            proxy_set_header Host $host;
            location /a/b/ {
                proxy_pass http://127.0.0.1:18000;
            }
        }
    }
}
"""
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_intermediate_level_header_passes_when_covered(self):
        """同型配置但 geo 头落在中间层(遮蔽后生效层恰有计算值)⇒ 通过。"""
        dump = _NGINX_CHAIN_HEAD + """        location /a/ {
            proxy_set_header Host $host;
            proxy_set_header geo-country $ask_ai_geo_country;
            location /a/b/ {
                proxy_pass http://127.0.0.1:18000;
            }
        }
    }
}
"""
        ok, _ = _ngx(dump=dump)
        assert ok

    def test_upstream_backend_path_with_header_passes(self):
        """显式 upstream(其 server 含 backend 端口)= 可审计 backend 路径;
        旧实现按 :port 字面匹配 → 合法 upstream 部署被误拒。"""
        dump = (
            "http {\n    upstream ask_backend {\n        server 127.0.0.1:18000;\n    }\n"
            + _NGINX_CHAIN_HEAD[len("http {\n") :]
            + """        location / {
            proxy_pass http://ask_backend;
            proxy_set_header geo-country $ask_ai_geo_country;
        }
    }
}
"""
        )
        ok, _ = _ngx(dump=dump)
        assert ok

    def test_upstream_backend_path_without_header_rejected(self):
        dump = (
            "http {\n    upstream ask_backend {\n        server 127.0.0.1:18000;\n    }\n"
            + _NGINX_CHAIN_HEAD[len("http {\n") :]
            + """        location / {
            proxy_pass http://ask_backend;
        }
    }
}
"""
        )
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_upstream_without_explicit_port_rejected(self):
        """歧义 upstream 命名(server 无显式端口)→ 无法审计 → 拒绝。"""
        dump = (
            "http {\n    upstream ask_backend {\n        server 127.0.0.1;\n    }\n"
            + _NGINX_CHAIN_HEAD[len("http {\n") :]
            + """        location / {
            proxy_pass http://ask_backend;
            proxy_set_header geo-country $ask_ai_geo_country;
        }
    }
}
"""
        )
        ok, _ = _ngx(dump=dump)
        assert not ok

    def test_unauditable_variable_proxy_pass_rejected(self):
        """变量型 proxy_pass(不能证明是否可达 backend)→ 不可审计 → 拒绝。"""
        dump = _NGINX_OK.replace(
            "    server {",
            """    server {
        location /assets/ {
            proxy_pass http://$upstream_assets;
        }""",
            1,
        )
        ok, msg = _ngx(dump=dump)
        assert not ok and "不可审计" in msg

    def test_set_real_ip_from_rejected(self):
        """生效配置含 set_real_ip_from(可伪造 XFF 可被提升为 $remote_addr;
        受信 RealIP 拓扑不可机械证实)→ fail closed,而非仅 README 声明。"""
        dump = _NGINX_OK.replace(
            "http {",
            "http {\n    set_real_ip_from 127.0.0.1;\n    real_ip_header X-Forwarded-For;",
        )
        ok, msg = _ngx(dump=dump)
        assert not ok and "real_ip" in msg

    def test_real_ip_header_without_set_from_rejected(self):
        dump = _NGINX_OK.replace("http {", "http {\n    real_ip_header X-Forwarded-For;")
        ok, _ = _ngx(dump=dump)
        assert not ok


def test_precheck_checks_cli_wiring():
    r = subprocess.run(
        [sys.executable, str(PRECHECK_CHECKS), "binding", "--host-ip", "0.0.0.0"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 1 and "保持 off" in r.stdout
    r = subprocess.run(
        [sys.executable, str(PRECHECK_CHECKS), "cidr", "--cidrs", f"{_GW}/32", "--gateway", _GW],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0 and "精确相等" in r.stdout


class TestPrecheckShellGates:
    """R3 阻塞 ②/④:precheck-geoip2.sh 入口与 G8 接线面机械断言。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(PRECHECK_SH), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_expect_typo_rejected_immediately(self):
        """R3 阻塞 ④:--expect onn(拼写错误)必须在 root 检查前非零退出,
        不得静默落入 off 语义(旧实现按 off 路径可返回 0「未检查却成功」)。"""
        for bad in ("onn", "ON", "On", "1", "yes", ""):
            r = self._run("--expect", bad)
            combined = r.stdout + r.stderr
            assert r.returncode != 0, (bad, combined)
            assert "off|on" in combined, (bad, combined)
            assert "sudo" not in combined, f"{bad}: 校验必须先于 root 检查: {combined}"

    def test_expect_missing_value_rejected(self):
        r = self._run("--expect")
        combined = r.stdout + r.stderr
        assert r.returncode != 0 and "off|on" in combined and "sudo" not in combined

    def test_expect_valid_values_reach_root_check(self):
        """合法值(off/on)才进入后续门检(非 root 下表现为 sudo 提示)。"""
        for good in ("off", "on"):
            r = self._run("--expect", good)
            combined = r.stdout + r.stderr
            assert "sudo" in combined, (good, combined)

    def test_g8_audits_all_published_bindings(self):
        """R3 阻塞 ②接线:G8 必须读**全部**发布映射(json .NetworkSettings.Ports
        → precheck_checks bindings 子命令),且 FAIL 消息不得插值 HOSTIP。"""
        text = PRECHECK_SH.read_text(encoding="utf-8")
        assert "json .NetworkSettings.Ports" in text, "G8 必须审计全部发布映射"
        assert "bindings --backend-port" in text, "G8 必须走 check_publish_bindings 全量审计"
        assert "binding --host-ip" not in text, "G8 不得只审单条绑定"
        assert "${HOSTIP" not in text, "G8 结论消息不得插值 HOSTIP(日志泄漏红线)"


# --------------------------------------------------------------------------- #
# AC3/AC5:离线契约测试 DSN 纪律守卫(R2:缺 TEST_DATABASE_URL 不得连默认 DSN)
# --------------------------------------------------------------------------- #


def _import_contract_subprocess(
    tmp_path: Path, env_overrides: dict[str, str]
) -> subprocess.CompletedProcess:
    """在隔离子进程中导入离线契约测试模块,验证 DSN fail-closed 守卫。

    sitecustomize 使 dotenv.load_dotenv 失效(隔离宿主/仓库 .env 的
    TEST_DATABASE_URL 注入,守卫必须对「变量缺失」本身成立);
    显式注入的 env 覆盖优先于一切。"""
    site = tmp_path / "guard_site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(
        "try:\n"
        "    import dotenv\n"
        "    dotenv.load_dotenv = lambda *a, **k: False\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_DATABASE_URL", "APP_MODE")}
    env.update(env_overrides)
    env["PYTHONPATH"] = os.pathsep.join([str(site), str(REPO), env.get("PYTHONPATH", "")])
    code = (
        "import importlib.util as iu\n"
        f"spec = iu.spec_from_file_location('contract_under_test', {str(CONTRACT_TEST)!r})\n"
        "mod = iu.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "print('CONTRACT_DSN_OK')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_contract_refuses_without_explicit_test_database_url(tmp_path):
    """缺 TEST_DATABASE_URL ⇒ 收集期拒绝(绝不回落配置默认 DSN)。"""
    r = _import_contract_subprocess(tmp_path, {})
    assert r.returncode != 0, f"缺显式测试 DSN 时不得导入成功: {r.stdout}"
    assert "TEST_DATABASE_URL" in r.stderr


def test_contract_refuses_non_test_database_name(tmp_path):
    """库名不含 'test'(生产同名库形态)⇒ 拒绝;DSN/凭据不回显。"""
    r = _import_contract_subprocess(
        tmp_path, {"TEST_DATABASE_URL": "postgresql+asyncpg://u:pw@127.0.0.1:5432/ask_ai"}
    )
    assert r.returncode != 0, "非测试库名必须被拒绝"
    assert "专用测试库" in r.stderr
    assert "pw" not in r.stderr and "ask_ai" not in r.stderr


def test_contract_refuses_prod_mode(tmp_path):
    """APP_MODE=prod ⇒ 一律拒绝(生产环境禁任何测试写面)。

    注入合法形态的 prod 密钥以越过 backend.config 的 prod 密钥校验,
    从而精确断言本守卫(而非密钥校验)拒绝执行。"""
    r = _import_contract_subprocess(
        tmp_path,
        {
            "TEST_DATABASE_URL": "postgresql+asyncpg://u:pw@127.0.0.1:5432/ask_ai_test",
            "APP_MODE": "prod",
            "ENCRYPTION_KEY": "g" * 40,
            "JWT_SECRET": "guard-non-default-jwt-secret-for-prod-mode-test",
        },
    )
    assert r.returncode != 0 and "APP_MODE=prod" in r.stderr


def test_contract_accepts_explicit_test_database_url(tmp_path):
    """显式专用测试库 ⇒ 正常导入(既有 CI/本地口径不受影响)。"""
    r = _import_contract_subprocess(
        tmp_path, {"TEST_DATABASE_URL": "postgresql+asyncpg://u:pw@127.0.0.1:5432/ask_ai_test"}
    )
    assert r.returncode == 0, f"显式测试库必须可导入: {r.stderr[-2000:]}"
    assert "CONTRACT_DSN_OK" in r.stdout
