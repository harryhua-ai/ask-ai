"""#114 阶段 E:GeoIP2 受信国家信号候选工件的**默认关闭与安全红线**结构断言。

候选工件(deploy/prod/geoip2/)仅供离线评审;本文件把「默认 off」与
「隐私/凭据红线」固化为机械断言,防止未来改动无声破坏:

- AC2 默认不启用:nginx 片段示例、env 装配示例全部处于注释态;
  生产 compose 不含任何 COUNTRY_/GEO_ 键(装配只经宿主 .env 示例);
- AC4 凭据红线:仓库内无 license key 文件;更新脚本不回显凭据、
  不 set -x、凭据只经文件读取且要求 0600;
- AC4 原子替换:更新脚本以同目录 rename 落库(不就地写、不覆盖 mmap 旧文件),
  失败恢复(.bak 回滚)路径存在;
- AC1 真实性:nginx 片段不引入 real_ip_*(XFF 不得成为地理输入);
  backend resolver 信任门未被放宽(仍只有 ingress 单一路径)。

零网络、零 docker、零生产 mutation(纯仓库静态检查)。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEOIP2_DIR = REPO / "deploy" / "prod" / "geoip2"
NGINX_EXAMPLE = GEOIP2_DIR / "nginx-geoip2.conf.example"
ENV_EXAMPLE = GEOIP2_DIR / "geoip2.env.example"
UPDATE_SH = GEOIP2_DIR / "update-geolite2.sh"
PRECHECK_SH = GEOIP2_DIR / "precheck-geoip2.sh"
COMPOSE = REPO / "deploy" / "prod" / "docker-compose.yml"


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
    # 允许的「非指令」行:仅块注释说明或以分隔线组成的横幅 —— 过滤后必须为空
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
# AC4:凭据与更新脚本安全红线
# --------------------------------------------------------------------------- #


def test_no_license_key_file_in_repo():
    """仓库(geoip2 候选目录)不得含任何 key/凭据文件。"""
    for p in GEOIP2_DIR.rglob("*"):
        name = p.name.lower()
        assert not re.search(
            r"license[-_]?key|\.key$|credential|secret", name
        ), f"疑似凭据文件入库: {p}"


def test_update_script_never_echoes_credential():
    """更新脚本:不 set -x、不打印 key 变量、下载 URL(含 key)不回显。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text, "缺少严格模式(set -euo pipefail)"
    # 只扫生效行(注释里的「不 set -x」说明文字不算违规)
    active = "\n".join(_active_lines(text))
    assert not re.search(r"set\s+-[a-zA-Z]*x", active), "禁止 set -x(会回显含 key 的 URL)"
    # key 只被读入变量,不得出现在 echo/printf/log/die 的参数里
    for m in re.finditer(r"(?:echo|printf|log|die)\s+[^#\n]*\$\{?key\b", active):
        raise AssertionError(f"凭据可能被输出: {m.group(0)!r}")
    # 下载行必须经变量拼接且命令本身不被打印
    assert "license_key=${key}" in active


def test_update_script_atomic_replace_and_rollback():
    """同目录 mktemp + rename(2) 原子替换;.bak 失败恢复路径存在。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "mktemp -d" in text and "mv -f" in text, "缺少临时目录 + 原子 rename"
    # 禁止以 > 直接就地写目标文件(会覆盖被 mmap 的旧库)
    assert not re.search(r">\s*\"\$\{?MMDB_PATH\}?\"", text), "禁止就地覆写现网 MMDB"
    assert ".bak" in text, "缺少失败恢复(.bak)路径"
    assert "--rollback" in text, "缺少手动回滚入口"
    assert "validate_mmdb" in text, "缺少结构校验门"


def test_update_script_downstream_validation_is_stdlib_only():
    """结构校验只依赖宿主已实证存在的 python3/curl(#144 探针),不虚构依赖。"""
    text = UPDATE_SH.read_text(encoding="utf-8")
    assert "command -v curl" in text and "command -v python3" in text
    assert b"\xab\xcd\xef".decode("latin-1") in text or "metadata" in text


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


def test_precheck_script_is_fail_closed():
    """预检:任一门 FAIL 必须非零退出(默认 off / 期望 on 两态都有门)。"""
    text = PRECHECK_SH.read_text(encoding="utf-8")
    assert "exit 1" in text and "fail-closed" in text
    assert "--expect" in text
    # CIDR 收敛检查必须存在(拒绝全零/过宽授信)
    assert "num_addresses" in text or "subnet_of" in text
