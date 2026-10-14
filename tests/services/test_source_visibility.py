"""SourceVisibilityGuard 单元测试(PC-01 防御纵深层;P0-rework fail-closed 语义)。

冻结契约(Part 4):AUTHORIZATION FAILURE MUST NOT BECOME AUTHORIZATION BYPASS。

- Known source + explicitly allowed                → ALLOW
- Known source + explicitly not allowed            → DENY
- Unknown / ghost source                           → DENY(不得进入生成上下文)
- No authoritative snapshot available              → DENY(不得放行未证实候选)
- Stale valid snapshot exists + refresh failure    → MAY use stale snapshot

附加:admin 按 widget 访客等价探测;channel=None 属未知请求上下文 → DENY;
TTL 内复用快照,过期后重新加载;loader 返回 {} 为权威空配置(全部拒)。
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


async def test_unknown_source_prefix_denies():
    """Case B:unknown / ghost source 不得进入生成上下文。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("internal",)}), ttl=60)
    assert await guard.allows("other-source/doc.md", "widget") is False


async def test_unknown_prefix_denied_even_when_public_snapshot():
    """未知前缀拒答不依赖该源在快照里的值——压根不在权威配置中即拒。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("widget", "api")}), ttl=60)
    assert await guard.allows("ghost-chunk/doc.md", "widget") is False


async def test_none_channel_denies():
    """channel=None 属未知请求上下文:不确定性不得放行(fail-closed)。"""
    guard = SourceVisibilityGuard(_loader_from({"src-a": ("widget", "api")}), ttl=60)
    assert await guard.allows("src-a/case.md", None) is False


async def test_loader_error_uses_stale_snapshot():
    """Stale valid snapshot + refresh failure → MAY use stale snapshot。"""
    calls = {"n": 0}

    async def flaky_loader():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"src-a": ("internal",), "pub-src": ("widget", "api")}
        raise RuntimeError("db down")

    guard = SourceVisibilityGuard(flaky_loader, ttl=0)
    assert await guard.allows("src-a/case.md", "widget") is False
    # 刷新失败仍沿用旧快照:受限源继续拒,公开源继续允许
    assert await guard.allows("src-a/case.md", "widget") is False
    assert await guard.allows("pub-src/doc.md", "widget") is True


async def test_loader_error_without_snapshot_denies():
    """Case A:无权威快照可用 → 不得放行未证实候选。"""
    async def broken_loader():
        raise RuntimeError("db down")

    guard = SourceVisibilityGuard(broken_loader, ttl=0)
    assert await guard.allows("src-a/case.md", "widget") is False
    assert await guard.allows("any-thing/doc.md", "widget") is False


async def test_empty_authoritative_mapping_denies_everything():
    """loader 成功但返回空映射 = 权威"零配置":无已授权源,全部拒。"""
    guard = SourceVisibilityGuard(_loader_from({}), ttl=60)
    assert await guard.allows("whatever/doc.md", "widget") is False


async def test_ttl_refreshes_snapshot():
    mapping = {"src-a": ("internal",)}

    loader = _loader_from(mapping)
    guard = SourceVisibilityGuard(loader, ttl=0.05)
    assert await guard.allows("src-a/case.md", "widget") is False
    mapping["src-a"] = ("widget", "api")  # 管理员改配置
    await asyncio.sleep(0.06)
    assert await guard.allows("src-a/case.md", "widget") is True


async def test_upload_visibility_requires_valid_explicit_public_grant():
    """Incident and newly created upload sources default closed; exact grants survive."""
    from backend.services.source_visibility import visibility_for_source

    incident = {"upload_mode": True}
    new_upload = {"upload_mode": True, "channel_visibility": "widget"}
    explicit_widget = {"upload_mode": True, "channel_visibility": ["widget"]}
    explicit_api = {"upload_mode": True, "channel_visibility": ["api"]}
    revoked = {"upload_mode": True, "channel_visibility": []}

    assert visibility_for_source("filesystem", incident) == ()
    assert visibility_for_source("filesystem", new_upload) == ()
    assert visibility_for_source("filesystem", explicit_widget) == ("widget",)
    assert visibility_for_source("filesystem", explicit_api) == ("api",)
    assert visibility_for_source("filesystem", revoked) == ()
    assert visibility_for_source("github", {}) == ("widget", "api")


async def test_guard_resolution_exposes_authoritative_upload_mode_and_channel_grant():
    from backend.services.source_visibility import (
        SourceVisibilityGuard,
        policy_for_source,
    )

    upload_policy = policy_for_source(
        "filesystem", {"upload_mode": True, "channel_visibility": ["widget"]}
    )
    case_policy = policy_for_source("filesystem", {"channel_visibility": ["widget"]})
    non_filesystem_policy = policy_for_source("github", {"upload_mode": True})
    assert upload_policy.upload_mode is True
    assert case_policy.upload_mode is False
    assert non_filesystem_policy.upload_mode is False

    async def load_policy():
        return {"upload-source": upload_policy}

    guard = SourceVisibilityGuard(load_policy, ttl=60)
    widget = await guard.resolve("upload-source/internal.md", "widget")
    api = await guard.resolve("upload-source/internal.md", "api")

    assert widget.allowed is True
    assert widget.upload_mode is True
    assert api.allowed is False
    assert api.upload_mode is True


async def test_guard_blocks_lagging_chunk_metadata_after_upload_grant_revoked():
    """Authoritative source snapshot blocks a stale public chunk projection."""
    from backend.services.source_visibility import visibility_for_source

    async def load_revoked_upload():
        return {
            "upload-source": visibility_for_source(
                "filesystem", {"upload_mode": True, "channel_visibility": []}
            )
        }

    guard = SourceVisibilityGuard(load_revoked_upload, ttl=60)
    assert await guard.allows("upload-source/customer-case.md", "widget") is False
    assert await guard.allows("upload-source/customer-case.md", "api") is False


async def test_upload_invalid_or_non_public_channel_values_fail_closed():
    from backend.services.source_visibility import visibility_for_source

    assert visibility_for_source(
        "filesystem", {"upload_mode": True, "channel_visibility": ["widget", "admin"]}
    ) == ()
    assert visibility_for_source(
        "filesystem", {"upload_mode": True, "channel_visibility": ["internal"]}
    ) == ()
    assert visibility_for_source(
        "filesystem", {"upload_mode": True, "channel_visibility": ["api"]}
    ) == ("api",)
