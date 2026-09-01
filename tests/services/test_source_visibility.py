"""SourceVisibilityGuard 单元测试(PC-01 防御纵深层)。

行为契约:
- loader 返回 {source_id_prefix: channel_visibility};guard 按请求渠道探测:
  渠道在白名单 → 可见;不在/白名单为空 → 不可见。
- admin 渠道按 widget 探测(与 HybridSearcher._VISIBILITY_CHANNEL_ALIAS 一致)。
- 未知 source 前缀(不在 DB 配置中)→ 允许(chunk 级过滤为主防线,guard 只做纵深)。
- loader 故障 → 沿用最近一次成功快照;从未成功 → 全部允许(fail-open)。
- TTL 内复用快照,过期后重新加载。
"""

import asyncio

from backend.services.source_visibility import SourceVisibilityGuard


def _loader_from(mapping: dict[str, tuple[str, ...]]):
    async def _load() -> dict[str, tuple[str, ...]]:
        return mapping

    return _load


async def test_channel_in_visibility_allows():
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("widget", "api")}), ttl=60)
    assert await guard.allows("src-a/doc.md", "widget") is True


async def test_channel_not_in_visibility_denies():
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("internal",)}), ttl=60)
    assert await guard.allows("src-a/case.md", "widget") is False


async def test_empty_visibility_denies_all_channels():
    """空白名单 = 内部源,任何访客等价渠道都不可见(PC-01/PC-03:仍存储可管理)。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ()}), ttl=60)
    assert await guard.allows("src-a/case.md", "widget") is False
    assert await guard.allows("src-a/case.md", "discord") is False


async def test_admin_probes_as_widget():
    """admin 访客等价:widget 不可见 ⇒ admin 也不可见(AC-06)。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("internal",)}), ttl=60)
    assert await guard.allows("src-a/case.md", "admin") is False


async def test_unknown_source_prefix_allows():
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("internal",)}), ttl=60)
    assert await guard.allows("other-source/doc.md", "widget") is True


async def test_none_channel_allows():
    """channel=None 时与 HybridSearcher 语义一致:不收紧(该路径本就无过滤)。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("internal",)}), ttl=60)
    assert await guard.allows("src-a/case.md", None) is True


async def test_loader_error_uses_last_good_snapshot():
    calls = {"n": 0}

    async def flaky_loader():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"src-a": ("internal",)}
        raise RuntimeError("db down")

    guard = SourceVisibilityGuard(flaky_loader, ttl=0)
    assert await guard.allows("src-a/case.md", "widget") is False
    assert await guard.allows("src-a/case.md", "widget") is False  # 用旧快照,仍拒绝


async def test_loader_error_without_snapshot_fails_open():
    async def broken_loader():
        raise RuntimeError("db down")

    guard = SourceVisibilityGuard(broken_loader, ttl=0)
    assert await guard.allows("src-a/case.md", "widget") is True


async def test_ttl_refreshes_snapshot():
    mapping = {"src-a": ("internal",)}

    loader = _loader_from(mapping)
    guard = SourceVisibilityGuard(loader, ttl=0.05)
    assert await guard.allows("src-a/case.md", "widget") is False
    mapping["src-a"] = ("widget", "api")  # 管理员改配置
    await asyncio.sleep(0.06)
    assert await guard.allows("src-a/case.md", "widget") is True
