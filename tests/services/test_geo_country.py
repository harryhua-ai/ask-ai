"""#68 AC1/AC2:权威 request-country resolver 的信任边界单元测试。

RED 契约(: Issue #68 / CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917):
- Accept-Language / locale / timezone / 问题文本 / LLM 推断一律不能决定 Country;
- 转发的 geo 头仅在「对端 ∈ 显式受信代理 CIDR + 头名显式配置」时才是权威
  (客户端可伪造的任意头不是权威);
- 输出只有 ISO 3166-1 alpha-2 或 ``None``(Unknown 由持久层 NULL 表达);
- resolver 的返回接口里没有 raw IP 的位置 —— IP 只允许瞬时参与解析,不得外泄。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from backend.config import load_settings
from backend.services.geo_country import resolve_request_country

_TRUSTED = ("10.0.0.0/8", "127.0.0.0/8")


class _CaseInsensitiveHeaders(dict):
    """Starlette headers 的最小 get 仿真(小写键)。"""

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _StubRequest:
    """携带 headers/client/XFF 的最小请求仿真(无需 Starlette)。"""

    def __init__(self, headers=None, client_host="203.0.113.7", xff=None):
        merged = {k.lower(): v for k, v in (headers or {}).items()}
        if xff is not None:
            merged["x-forwarded-for"] = xff
        self.headers = _CaseInsensitiveHeaders(merged)
        self.client = type("Client", (), {"host": client_host})()


def _ingress_settings(header="geo-country"):
    return replace(
        load_settings(config_dir=Path(__file__).resolve().parents[2] / "config"),
        country_resolution_mode="ingress",
        country_ingress_header=header,
        geo_trusted_proxy_cidrs=_TRUSTED,
        geoip_database_path="",
    )


def _geoip_settings(db_path="/nonexistent/country.mmdb"):
    return replace(
        load_settings(config_dir=Path(__file__).resolve().parents[2] / "config"),
        country_resolution_mode="geoip",
        country_ingress_header="",
        geo_trusted_proxy_cidrs=_TRUSTED,
        geoip_database_path=db_path,
    )


# --------------------------------------------------------------------------- #
# AC1:Accept-Language 系不能决定 Country
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_resolver_off_yields_unknown_regardless_of_headers():
    """默认(off)下任何头都不产生国家 —— Accept-Language 启发式被整体移除。"""
    req = _StubRequest(
        headers={"accept-language": "en-US,en;q=0.9", "geo-country": "US"},
        client_host="10.1.2.3",
    )
    assert resolve_request_country(req, replace(load_settings(), country_resolution_mode="off")) == (
        None,
        None,
    )


@pytest.mark.unit
@pytest.mark.parametrize("lang", ["en-US", "zh-CN", "es-AR", "pt-BR;q=0.8, en;q=0.5"])
def test_accept_language_cannot_determine_country(lang):
    """ingress 模式(未配置受信头路径命中)下 Accept-Language 地区后缀不是权威。"""
    req = _StubRequest(headers={"accept-language": lang}, client_host="10.1.2.3")
    assert resolve_request_country(req, _ingress_settings()) == (None, None)
    assert resolve_request_country(req, _geoip_settings()) == (None, None)


@pytest.mark.unit
def test_timezone_and_question_text_are_not_inputs():
    """resolver 的权威输入只有 request + settings;time-zone 头与问题文本不参与。"""
    req = _StubRequest(
        headers={"timezone": "America/Argentina/Buenos_Aires", "x-timezone": "Asia/Shanghai"},
        client_host="10.1.2.3",
    )
    assert resolve_request_country(req, _ingress_settings()) == (None, None)


# --------------------------------------------------------------------------- #
# AC2:显式信任边界 —— 伪造头不是权威
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ingress_header_from_untrusted_peer_is_rejected():
    """非受信对端发来的 geo 头(可伪造)必须被拒绝。"""
    req = _StubRequest(headers={"geo-country": "US"}, client_host="203.0.113.7")
    assert resolve_request_country(req, _ingress_settings()) == (None, None)


@pytest.mark.unit
def test_ingress_header_from_trusted_peer_resolves_iso_alpha2():
    req = _StubRequest(headers={"geo-country": "US"}, client_host="10.1.2.3")
    assert resolve_request_country(req, _ingress_settings()) == ("US", "ingress")


@pytest.mark.unit
@pytest.mark.parametrize("value", ["usa", "U1", "", "  ", "XX", "CHN"])
def test_ingress_header_invalid_values_fail_honest(value):
    """非 ISO alpha-2 / 保留占位(XX)一律 Unknown,绝不猜测。"""
    req = _StubRequest(headers={"geo-country": value}, client_host="10.1.2.3")
    assert resolve_request_country(req, _ingress_settings()) == (None, None)


@pytest.mark.unit
def test_ingress_header_lowercase_trusted_value_is_normalized():
    """受信来源的大小写差异是格式而非语义(权威序仍只认 ISO alpha-2)。"""
    req = _StubRequest(headers={"geo-country": "us"}, client_host="10.1.2.3")
    assert resolve_request_country(req, _ingress_settings()) == ("US", "ingress")


@pytest.mark.unit
def test_ingress_without_configured_header_name_yields_unknown():
    """ingress 模式但未显式配置头名 = 没有受信权威 → Unknown(fail-honest)。"""
    req = _StubRequest(headers={"x-geo-country": "US"}, client_host="10.1.2.3")
    assert resolve_request_country(req, _ingress_settings(header="")) == (None, None)


@pytest.mark.unit
def test_ingress_without_trusted_cidrs_never_trusts_headers():
    """未配置受信代理 CIDR = 无人可被信任,配置了头名也必须 Unknown。"""
    settings = replace(
        _ingress_settings(), geo_trusted_proxy_cidrs=()
    )
    req = _StubRequest(headers={"geo-country": "US"}, client_host="127.0.0.1")
    assert resolve_request_country(req, settings) == (None, None)


# --------------------------------------------------------------------------- #
# AC2:server-side IP geolocation 路径
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_geoip_without_database_config_yields_unknown():
    req = _StubRequest(client_host="203.0.113.7")
    assert resolve_request_country(req, replace(_geoip_settings(), geoip_database_path="")) == (
        None,
        None,
    )


@pytest.mark.unit
def test_geoip_with_unloadable_database_yields_unknown():
    """库路径配置但不可加载(缺依赖/缺文件)→ fail-honest Unknown,不 crash。"""
    req = _StubRequest(client_host="203.0.113.7")
    assert resolve_request_country(req, _geoip_settings()) == (None, None)


@pytest.mark.unit
def test_geoip_uses_first_xff_hop_only_when_peer_trusted():
    """受信对端背后取 XFF 第一跳做 GeoIP;解析结果只含国家,不含 IP。"""
    seen = {}

    def fake_lookup(ip):
        seen["ip"] = ip
        return "DE"

    req = _StubRequest(client_host="10.1.2.3", xff="198.51.100.9, 10.0.0.1")
    result = resolve_request_country(
        req, _geoip_settings(db_path="stub.mmdb"), _geoip_lookup=fake_lookup
    )
    assert result == ("DE", "geoip")
    assert seen["ip"] == "198.51.100.9"


@pytest.mark.unit
def test_geoip_ignores_xff_from_untrusted_peer():
    """非受信对端携带的 XFF 是伪造输入,只允许用直连对端地址解析。"""
    seen = {}

    def fake_lookup(ip):
        seen["ip"] = ip
        return "FR"

    req = _StubRequest(client_host="203.0.113.7", xff="8.8.8.8")
    result = resolve_request_country(
        req, _geoip_settings(db_path="stub.mmdb"), _geoip_lookup=fake_lookup
    )
    assert result == ("FR", "geoip")
    assert seen["ip"] == "203.0.113.7"


@pytest.mark.unit
def test_geoip_lookup_unknown_ip_yields_unknown():
    def fake_lookup(_ip):
        return None

    req = _StubRequest(client_host="10.1.2.3")
    assert (
        resolve_request_country(
            req, _geoip_settings(db_path="stub.mmdb"), _geoip_lookup=fake_lookup
        )
        == (None, None)
    )


# --------------------------------------------------------------------------- #
# 接口健壮性
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_invalid_mode_fails_honest_to_unknown():
    """模式值拼错 = 关闭解析(告警),绝不抛异常打断问答主链路。"""
    req = _StubRequest(headers={"geo-country": "US"}, client_host="10.1.2.3")
    assert resolve_request_country(
        req, replace(_ingress_settings(), country_resolution_mode="bogus")
    ) == (None, None)


@pytest.mark.unit
def test_result_type_never_carries_ip():
    """返回值恒为 (ISO|None, source|None) 二元组 —— raw IP 无处可放。"""
    req = _StubRequest(headers={"geo-country": "US"}, client_host="10.1.2.3")
    result = resolve_request_country(req, _ingress_settings())
    assert isinstance(result, tuple) and len(result) == 2
    code, source = result
    assert code in (None, "US") and source in (None, "ingress")
