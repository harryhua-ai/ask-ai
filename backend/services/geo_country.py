"""权威 request-country resolver(#68 / Country Truth Contract)。

语义边界(冻结于 CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917):
- 唯一输出:ISO 3166-1 alpha-2 或 ``None``(Unknown 由持久层 NULL 表达);
  返回二元组 ``(country, source)``,接口里没有 raw IP 的位置 —— IP 只允许
  瞬时参与解析,不落库、不进日志、不外泄。
- 权威序:① 受信 ingress/edge geo 头;② 受信服务端 IP 地理库;③ Unknown。
- 信任边界是显式的:转发 geo/IP 元数据只在对端(直连 peer)地址落在
  ``settings.geo_trusted_proxy_cidrs`` 且头名经 ``settings.country_ingress_header``
  显式配置时才被接受。客户端可伪造的任意头不是权威;未配置 CIDR = 无人可信。
- ``Accept-Language``、locale、timezone、问题文本、LLM 推断一律不作地理依据
  —— 本模块的输入面只有 request headers(geo 头与 XFF)与配置。
- 解析失败 fail-honest:返回 Unknown,绝不抛异常打断问答主链路。
"""

from __future__ import annotations

import functools
import ipaddress
import logging
import re

logger = logging.getLogger(__name__)

# 权威来源标记(持久化到 conversations.country_source)
SOURCE_INGRESS = "ingress"
SOURCE_GEOIP = "geoip"

# 部分 CDN 用保留占位表达「未知国家」(如 CF-IPCountry 的 XX)→ Unknown
_RESERVED_COUNTRY_CODES = frozenset({"XX"})

_ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")

_RESOLUTION_MODES = ("off", "ingress", "geoip")


def _parse_cidrs(entries) -> tuple:
    """解析受信代理 CIDR 列表;非法项跳过并告警(配置错不崩启动)。"""
    networks = []
    for entry in entries or ():
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("geo 受信代理 CIDR 非法,已忽略: %r", entry)
    return tuple(networks)


def _peer_address(request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    host = getattr(getattr(request, "client", None), "host", None)
    if not host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_trusted_peer(request, settings) -> bool:
    peer = _peer_address(request)
    if peer is None:
        return False
    return any(peer in network for network in _parse_cidrs(settings.geo_trusted_proxy_cidrs))


def _first_forwarded_ip(request) -> str | None:
    raw = request.headers.get("x-forwarded-for", "")
    for candidate in raw.split(","):
        candidate = candidate.strip()
        if candidate:
            return candidate
    return None


def _effective_client_ip(request, settings) -> str | None:
    """GeoIP 查询用的客户端地址:仅当对端受信时才采信 XFF 第一跳。"""
    if _is_trusted_peer(request, settings):
        forwarded = _first_forwarded_ip(request)
        if forwarded:
            return forwarded
    peer = _peer_address(request)
    return str(peer) if peer is not None else None


def _is_iso_country(value: str) -> bool:
    return bool(_ISO_ALPHA2.fullmatch(value)) and value not in _RESERVED_COUNTRY_CODES


def _country_from_ingress(request, settings) -> str | None:
    header_name = (settings.country_ingress_header or "").strip().lower()
    if not header_name:
        return None
    if not _is_trusted_peer(request, settings):
        return None
    raw = (request.headers.get(header_name) or "").strip().upper()
    if not _is_iso_country(raw):
        return None
    return raw


@functools.lru_cache(maxsize=4)
def _load_geoip_reader(database_path: str):
    """惰性加载 MMDB reader;不可用返回 None(fail-honest),结果按路径缓存。"""
    try:
        import geoip2.database
    except ImportError:
        logger.warning("geoip 模式已配置但 geoip2 未安装;国家解析降级为 Unknown")
        return None
    try:
        return geoip2.database.Reader(database_path)
    except Exception:
        logger.warning("GeoIP 数据库不可加载: %r;国家解析降级为 Unknown", database_path)
        return None


def _country_from_geoip(request, settings, lookup=None) -> str | None:
    database_path = (settings.geoip_database_path or "").strip()
    if not database_path:
        return None
    ip = _effective_client_ip(request, settings)
    if not ip:
        return None
    if lookup is None:
        reader = _load_geoip_reader(database_path)
        if reader is None:
            return None

        def lookup(ip_address: str) -> str | None:
            try:
                response = reader.country(ip_address)
            except Exception:
                return None
            code = getattr(response, "country", None)
            code = getattr(code, "iso_code", None)
            return code if code and _is_iso_country(code.upper()) else None

    try:
        code = lookup(ip)
    except Exception:
        return None
    if code and _is_iso_country(code.upper()):
        return code.upper()
    return None


def resolve_request_country(request, settings, *, _geoip_lookup=None) -> tuple[str | None, str | None]:
    """解析请求国家真相,返回 ``(country, source)``。

    Returns:
        权威值时 ``(ISO alpha-2, 'ingress'|'geoip')``;无权威时 ``(None, None)``
        (持久层表达 Unknown)。永不抛异常。
    """
    mode = (getattr(settings, "country_resolution_mode", "") or "").strip().lower()
    if mode not in _RESOLUTION_MODES:
        if mode:
            logger.warning("country_resolution_mode 非法: %r;按 off 处理", mode)
        return (None, None)
    try:
        if mode == "ingress":
            code = _country_from_ingress(request, settings)
            return (code, SOURCE_INGRESS) if code else (None, None)
        if mode == "geoip":
            code = _country_from_geoip(request, settings, lookup=_geoip_lookup)
            return (code, SOURCE_GEOIP) if code else (None, None)
        return (None, None)
    except Exception:  # 解析链路的任何意外都不得影响问答主链路
        logger.exception("国家解析异常;按 Unknown 处理")
        return (None, None)
