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


def _build_synthetic_mmdb(
    db_type: str = "GeoLite2-Country", corrupt_node0_right: int | None = None
) -> bytes:
    """最小合法 MMDB(record_size=24,3 节点):走树可命中/未命中两路。
    node0: 0→node1, 1→node2;node1: 0/0(not found);node2: 0→not found,
    1→数据指针。corrupt_node0_right 用于构造越界数据指针的损坏树。"""
    mod = _mmdb_helpers()
    marker = mod.METADATA_MARKER
    right0 = 2 if corrupt_node0_right is None else corrupt_node0_right
    tree = (
        bytes([0, 0, 1])
        + right0.to_bytes(3, "big")  # node0 右记录(损坏时 = 越界数据指针)
        + bytes([0, 0, 0]) * 2  # node1: 0/0 → not found
        + bytes([0, 0, 0])  # node2 左:0 → not found
        + (3).to_bytes(3, "big")  # node2 右:数据指针(node_count+0)
    )
    sep = marker + b"\x00\x00"  # 16B 数据段分隔符
    datablob = b"\x00" * 8
    meta = {
        "binary_format_major_version": _enc_uint16(2),
        "binary_format_minor_version": _enc_uint16(0),
        "build_epoch": bytes([0x08, 0x02]) + (1700000000).to_bytes(8, "big"),
        "database_type": _enc_str(db_type),
        "description": bytes([7 << 5]),
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
    ],
)
def test_mmdb_validator_rejects_malformed(tmp_path, mutate, reason):
    mod = _mmdb_helpers()
    f = tmp_path / "bad.mmdb"
    f.write_bytes(mutate(_build_synthetic_mmdb()))
    with pytest.raises(mod.MMDBInvalid):
        mod.validate_file(str(f), min_bytes=0)


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
