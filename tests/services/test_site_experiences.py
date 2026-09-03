"""站点体验身份与来源授权服务测试(MSW 多站点 Widget,P1)。

覆盖契约:
- site_id 是标识符非凭证:未知/禁用站点、无 Origin、来源不匹配一律 SiteDenied;
- legacy(无 site_id)不触发任何校验;
- seed 从 config/sites.yaml 幂等 upsert;
- Conversation.site_id 持久化(channel 语义不变,另由路由测试覆盖)。
"""

from pathlib import Path

import pytest

from backend.db.models import Conversation, SiteExperience
from backend.db.session import get_session_factory
from backend.services.site_experiences import (
    ResolvedSite,
    SiteDenied,
    load_sites_config,
    normalize_origin,
    resolve_site,
    seed_default_sites,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# normalize_origin
# --------------------------------------------------------------------------- #


class TestNormalizeOrigin:
    def test_strips_path_and_lowercases(self):
        assert (
            normalize_origin("https://www.camthink.ai/some/path?q=1") == "https://www.camthink.ai"
        )

    def test_strips_default_port(self):
        assert normalize_origin("https://store.camthink.ai:443") == "https://store.camthink.ai"
        assert normalize_origin("http://localhost:80") == "http://localhost"

    def test_keeps_non_default_port(self):
        assert normalize_origin("http://localhost:8081") == "http://localhost:8081"

    def test_rejects_non_http_scheme_and_garbage(self):
        assert normalize_origin("javascript:alert(1)") is None
        assert normalize_origin("not a url") is None
        assert normalize_origin("") is None
        assert normalize_origin(None) is None

    def test_bare_ip_trailing_slash_is_canonicalized(self):
        """用户描述的地址常带尾部「/」;浏览器 Origin 形式 = scheme://host 无路径。"""
        assert normalize_origin("http://42.194.138.11/") == "http://42.194.138.11"
        assert normalize_origin("http://42.194.138.11") == "http://42.194.138.11"


# --------------------------------------------------------------------------- #
# resolve_site(真实 DB,经 conftest db_engine 隔离)
# --------------------------------------------------------------------------- #


class TestResolveSite:
    async def test_empty_site_id_is_legacy_none(self, db_engine):
        factory = get_session_factory(db_engine)
        assert await resolve_site(factory, None, "https://store.camthink.ai") is None
        assert await resolve_site(factory, "", "https://store.camthink.ai") is None

    async def test_unknown_site_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://www.camthink.ai")

    async def test_missing_origin_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", None)

    async def test_authorized_origin_resolved(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        site = await resolve_site(factory, "camthink-store", "https://WWW.CamThink.ai")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-store"
        assert site.display_name
        assert len(site.starters) > 0

    async def test_unrelated_origin_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://evil.example")

    async def test_bare_ip_integration_origin_allowed_for_website(self, db_engine):
        """外部对接测试页 http://42.194.138.11:Origin(带尾斜杠)与 Referer(带路径)均命中。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        site = await resolve_site(factory, "camthink-website", "http://42.194.138.11/")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-website"
        site = await resolve_site(factory, "camthink-website", "http://42.194.138.11/page")
        assert isinstance(site, ResolvedSite)

    async def test_bare_ip_origin_authorized_for_wiki_and_store(self, db_engine):
        """合作方测试服务器三站镜像授权(A1-A3):同一 Origin 按站点区分体验均可命中。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        # /store/ 页面 Referer 带路径(A7):归一化后仍精确命中 scheme://host。
        site = await resolve_site(factory, "camthink-store", "http://42.194.138.11/store/foo")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-store"
        site = await resolve_site(factory, "camthink-wiki", "http://42.194.138.11/wiki/")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-wiki"
        site = await resolve_site(factory, "camthink-store", "http://42.194.138.11")
        assert isinstance(site, ResolvedSite)

    async def test_unlisted_bare_ip_variants_denied_for_all_sites(self, db_engine):
        """白名单精确性(A4-A6):相邻 IP/https 变体/非默认端口对三站一律拒绝。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        for site_id in ("camthink-website", "camthink-wiki", "camthink-store"):
            for origin in (
                "http://42.194.138.12",
                "https://42.194.138.11",
                "http://42.194.138.11:8080",
            ):
                with pytest.raises(SiteDenied):
                    await resolve_site(factory, site_id, origin)

    async def test_official_origins_remain_authorized(self, db_engine):
        """既有官方 origins 零回归(A8 + Issue #8):bare-IP 三站镜像不挤掉任何既有授权;
        store 官方 origin = https://www.camthink.ai(正式 Store 在 www.camthink.ai/store/);
        website apex https://camthink.ai 按 Issue #8 既有契约保留(REDIRECT ONLY 不动)。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        authorized = {
            "camthink-website": ("https://www.camthink.ai", "https://camthink.ai"),
            "camthink-wiki": ("https://wiki.camthink.ai",),
            "camthink-store": ("https://www.camthink.ai",),
        }
        for site_id, origins in authorized.items():
            for origin in origins:
                site = await resolve_site(factory, site_id, origin)
                assert isinstance(site, ResolvedSite)
                assert site.site_id == site_id

    async def test_store_production_origin_authorized(self, db_engine):
        """Issue #8:生产故障场景回归钉 —— /store/neoeyes-503/ 页面的真实浏览器
        Origin = https://www.camthink.ai 必须通过 camthink-store 授权(修复前 403)。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        site = await resolve_site(factory, "camthink-store", "https://www.camthink.ai")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-store"

    async def test_store_url_path_not_part_of_authorization(self, db_engine):
        """Issue #8:/store/ 是 path 不属于 Origin;授权只依据 Origin ——
        带路径的 Referer 归一化剥路径后精确命中 scheme://host,与无路径等价。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        site = await resolve_site(
            factory, "camthink-store", "https://www.camthink.ai/store/neoeyes-503/"
        )
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-store"

    async def test_obsolete_store_subdomain_origin_denied(self, db_engine):
        """Issue #8:store.camthink.ai 为 OBSOLETE 非权威 origin,必须拒绝
        (修复回归钉:修复前该 origin 曾被错误列入 camthink-store 授权)。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://store.camthink.ai")

    async def test_suffix_spoofed_origin_denied(self, db_engine):
        """store.camthink.ai.evil.com 含授权串但不是授权 origin(精确匹配)。"""
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://store.camthink.ai.evil.com")

    async def test_disabled_site_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        async with factory() as session:
            row = await session.get(SiteExperience, "camthink-store")
            row.enabled = False
            await session.commit()
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://www.camthink.ai")


# --------------------------------------------------------------------------- #
# seed / YAML
# --------------------------------------------------------------------------- #


class TestSeedDefaultSites:
    async def test_seeds_three_sites_from_repo_yaml(self, db_engine):
        factory = get_session_factory(db_engine)
        assert await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml") == 3
        async with factory() as session:
            rows = (
                (await session.execute(__import__("sqlalchemy").select(SiteExperience)))
                .scalars()
                .all()
            )
            assert {r.site_id for r in rows} == {
                "camthink-website",
                "camthink-wiki",
                "camthink-store",
            }

    async def test_seed_is_idempotent_and_upserts_changes(self, db_engine, tmp_path):
        from sqlalchemy import func, select

        yaml_text = (REPO_ROOT / "config" / "sites.yaml").read_text(encoding="utf-8")
        v1 = tmp_path / "sites.yaml"
        v1.write_text(yaml_text, encoding="utf-8")
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, v1)
        v2 = tmp_path / "sites.yaml"
        v2.write_text(yaml_text.replace("CamThink Store", "CamThink Store v2"), encoding="utf-8")
        await seed_default_sites(factory, v2)
        async with factory() as session:
            count = (
                await session.execute(select(func.count()).select_from(SiteExperience))
            ).scalar()
            row = await session.get(SiteExperience, "camthink-store")
        assert count == 3
        assert row.display_name == "CamThink Store v2"


class TestLoadSitesConfig:
    def test_repo_yaml_defines_three_camthink_sites(self):
        sites = load_sites_config(REPO_ROOT / "config" / "sites.yaml")
        assert [s["site_id"] for s in sites] == [
            "camthink-website",
            "camthink-wiki",
            "camthink-store",
        ]
        for s in sites:
            assert s["allowed_origins"], s["site_id"]
            assert s["starters"], s["site_id"]

    def test_repo_yaml_origins_are_canonical(self):
        """所有 allowed_origins 必须已是 canonical 形式(运行时精确命中依赖它)。"""
        for s in load_sites_config(REPO_ROOT / "config" / "sites.yaml"):
            for origin in s["allowed_origins"]:
                assert origin == normalize_origin(origin), (s["site_id"], origin)

    def test_bare_ip_integration_origin_listed_for_all_three_sites(self):
        """合作方测试 Origin 三站镜像授权(A1-A3 配置面);canonical 形式逐站一致。"""
        sites = {s["site_id"]: s for s in load_sites_config(REPO_ROOT / "config" / "sites.yaml")}
        for site_id in ("camthink-website", "camthink-wiki", "camthink-store"):
            assert "http://42.194.138.11" in sites[site_id]["allowed_origins"], site_id

    def test_store_origin_frozen_truth_issue8(self):
        """Issue #8 冻结产品事实(配置面回归钉):
        - store 授权 origin 必须含 https://www.camthink.ai(正式 Store 在
          www.camthink.ai/store/,/store/ 是 path 不属于 Origin);
        - store.camthink.ai 为 OBSOLETE 非权威 origin,必须缺席;
        - 通配符禁止(与全局面 test_no_wildcard_or_path_origins_anywhere 双保险)。"""
        sites = {s["site_id"]: s for s in load_sites_config(REPO_ROOT / "config" / "sites.yaml")}
        store_origins = sites["camthink-store"]["allowed_origins"]
        assert "https://www.camthink.ai" in store_origins
        assert "https://store.camthink.ai" not in store_origins
        assert not any("*" in o for o in store_origins)
        # 相邻站点行为不变:website 含 www + apex(Issue #8 REDIRECT 契约),wiki 独占子域。
        assert "https://www.camthink.ai" in sites["camthink-website"]["allowed_origins"]
        assert "https://camthink.ai" in sites["camthink-website"]["allowed_origins"]
        assert sites["camthink-wiki"]["allowed_origins"] == [
            "https://wiki.camthink.ai",
            "http://42.194.138.11",
        ]

    def test_no_wildcard_or_path_origins_anywhere(self):
        """A10:配置面禁止通配符/带路径/裸 host 形式(canonical 不变量的显式安全面)。"""
        for s in load_sites_config(REPO_ROOT / "config" / "sites.yaml"):
            for origin in s["allowed_origins"]:
                assert origin != "*", (s["site_id"], origin)
                assert "*" not in origin, (s["site_id"], origin)
                assert origin.startswith(("http://", "https://")), (s["site_id"], origin)
                assert "://" in origin and "/" not in origin.split("://", 1)[1], (
                    s["site_id"],
                    origin,
                )

    def test_missing_config_is_loud(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_sites_config(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #


class TestConversationSitePersistence:
    async def test_conversation_site_id_roundtrip(self, db_session):
        conv = Conversation(question="q", answer="a", channel="widget", site_id="camthink-wiki")
        db_session.add(conv)
        await db_session.commit()
        await db_session.refresh(conv)
        assert conv.site_id == "camthink-wiki"
        assert conv.channel == "widget"
