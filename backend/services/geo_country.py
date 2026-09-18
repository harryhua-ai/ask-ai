"""权威 request-country resolver(#68 / Country Truth Contract)。

语义边界(冻结于 CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917;
REVIEW_1 收窄:本候选只支持**单一权威路径 = 受信 ingress geo 头**):
- 唯一输出:ISO 3166-1 alpha-2 或 ``None``(Unknown 由持久层 NULL 表达);
  返回二元组 ``(country, source)``,接口里没有 raw IP 的位置 —— IP 不落库、
  不进日志、不参与本路径解析。
- 权威路径:受信 ingress/edge geo 头 —— 仅当
  ``COUNTRY_RESOLUTION_MODE=ingress`` 且头名经 ``country_ingress_header``
  显式配置 且直连 peer 落在 ``geo_trusted_proxy_cidrs`` 内时,头值才是权威。
- **显式信任边界**:客户端可伪造的任意头不是权威;未配置 CIDR = 无人可信。
- ``Accept-Language``、locale、timezone、问题文本、LLM 推断一律不作地理依据
  —— 本模块的输入面只有 request headers(geo 头)与配置。
- 解析失败 fail-honest:返回 Unknown,绝不抛异常打断问答主链路。

REVIEW_1 收窄说明(与 A 对齐):契约权威序第 2 级(trusted server-side IP
geolocation)**有意不在本候选交付** —— geoip2 不在冻结镜像依赖集内,交付它
会形成「宣称能力 ≠ 交付能力」。窄化为单一路径后宣称与实现一致;若运维后续
需要 tier-2,作为独立增量补依赖 + 具代表性验证后再交付。
"""

from __future__ import annotations

import ipaddress
import logging
import re

logger = logging.getLogger(__name__)

# 权威来源标记(持久化到 conversations.country_source)
SOURCE_INGRESS = "ingress"

# 部分 CDN 用保留占位表达「未知国家」(如 CF-IPCountry 的 XX)→ Unknown
_RESERVED_COUNTRY_CODES = frozenset({"XX"})

_ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")

_RESOLUTION_MODES = ("off", "ingress")


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


def resolve_request_country(request, settings) -> tuple[str | None, str | None]:
    """解析请求国家真相,返回 ``(country, source)``。

    Returns:
        权威值时 ``(ISO alpha-2, 'ingress')``;无权威时 ``(None, None)``
        (持久层表达 Unknown)。永不抛异常。
    """
    mode = (getattr(settings, "country_resolution_mode", "") or "").strip().lower()
    if mode not in _RESOLUTION_MODES:
        if mode:
            # REVIEW_1 收窄:geoip 等历史/未知值一律按 off 处理(诚实降级)
            logger.warning("country_resolution_mode 非法或不受支持: %r;按 off 处理", mode)
        return (None, None)
    if mode != "ingress":
        return (None, None)
    try:
        code = _country_from_ingress(request, settings)
        return (code, SOURCE_INGRESS) if code else (None, None)
    except Exception:  # 解析链路的任何意外都不得影响问答主链路
        logger.exception("国家解析异常;按 Unknown 处理")
        return (None, None)
