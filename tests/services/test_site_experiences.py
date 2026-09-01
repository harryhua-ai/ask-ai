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
        assert normalize_origin("https://www.camthink.ai/some/path?q=1") == "https://www.camthink.ai"

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
            await resolve_site(factory, "camthink-store", "https://store.camthink.ai")

    async def test_missing_origin_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", None)

    async def test_authorized_origin_resolved(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        site = await resolve_site(factory, "camthink-store", "https://Store.CamThink.ai")
        assert isinstance(site, ResolvedSite)
        assert site.site_id == "camthink-store"
        assert site.display_name
        assert len(site.starters) > 0

    async def test_unrelated_origin_denied(self, db_engine):
        factory = get_session_factory(db_engine)
        await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml")
        with pytest.raises(SiteDenied):
            await resolve_site(factory, "camthink-store", "https://evil.example")

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
            await resolve_site(factory, "camthink-store", "https://store.camthink.ai")


# --------------------------------------------------------------------------- #
# seed / YAML
# --------------------------------------------------------------------------- #


class TestSeedDefaultSites:
    async def test_seeds_three_sites_from_repo_yaml(self, db_engine):
        factory = get_session_factory(db_engine)
        assert await seed_default_sites(factory, REPO_ROOT / "config" / "sites.yaml") == 3
        async with factory() as session:
            rows = (await session.execute(__import__("sqlalchemy").select(SiteExperience))).scalars().all()
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
            count = (await session.execute(select(func.count()).select_from(SiteExperience))).scalar()
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
