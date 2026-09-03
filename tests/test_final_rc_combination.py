"""Final RC 组合门(CamThink V1 Final Release Candidate Assembly)。

跨契约不变量(任务 §10C)中**未被既有单侧测试覆盖**的组合语义在此锁定;
其余组合(#13→#11 Correction Gate、#14+W2 telemetry、S0 lifecycle gating、
compose/update.sh 契约)由既有测试承载并在本门全量回归中执行:
- tests/api/admin/test_sync_health_derivation.py / test_sync_health_pure.py(#13→#11)
- tests/pipeline/test_ingest_fallback.py / tests/embedder/test_fallback.py /
  tests/scripts/test_sync_device.py / test_sync_run_runtime_facts.py(#14×W2)
- tests/services/test_source_lifecycle.py(S0 lifecycle gating)
- tests/scripts/test_release_tooling.py + tests/test_release_identity.py(#10)
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.db.models import Document
from backend.pipeline.ingest import _build_props, _derived_product
from backend.product_taxonomy import get_taxonomy
from backend.release import ReleaseIdentityError, get_release_identity, reset_release_identity_cache


# --------------------------------------------------------------------------- #
# 不变量 2/3:#5 产品推导与 #13 路径身份在 ingestion 共存;
# taxonomy 被 ingest 与 metadata migration 一致使用
# --------------------------------------------------------------------------- #


class TestProductDerivationWithPathIdentity:
    def test_derived_product_and_path_identity_coexist(self):
        """同一 #13 路径身份 source_id:#5 推导出产品、#13 语义保持路径串主键。"""
        sid = "wiki-documents-local/main/docs/6-neoeyes-ne503-series/user-guide.md"
        doc = SimpleNamespace(
            source_id=sid,
            product="wiki",
            url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/user-guide.md",
            title="guide",
            branch="main",
        )
        # #5:taxonomy 规则推导(非猜测;按源标签分组规则)
        assert _derived_product(doc) == "ne503"
        # #13:Document 主键 = source_id 路径串(模型层身份不变)
        assert Document.__mapper__.primary_key[0].name == "source_id"
        # chunk 级确定性 uuid 只由 #13 路径身份(source_id, index)决定,
        # 与 #5 product 元数据完全独立(两套身份正交共存)
        from backend.pipeline.ingest import _deterministic_uuid

        assert _deterministic_uuid(sid, 0) == _deterministic_uuid(sid, 0)
        assert _deterministic_uuid(sid, 0) != _deterministic_uuid(sid, 1)

    def test_build_props_carries_both_identities(self):
        """_build_props 同时承载 #13 source_id 路径身份与 #5 canonical product。"""
        doc = SimpleNamespace(
            source_id="wiki-documents-local/main/docs/4-ai-application/quickstart.md",
            source_type="github",
            product="wiki",
            url="u",
            title="t",
            content_hash="h" * 8,
            branch="main",
        )
        chunk = SimpleNamespace(
            text="hello",
            chunk_index=0,
            doc_section="",
            chunk_type="text",
            channel_visibility=("widget", "api"),
            symbol_name=None,
            symbol_signature=None,
            symbol_node_type=None,
            symbol_tokens=None,
        )
        props = _build_props(chunk, doc)
        assert props["source_id"] == doc.source_id  # #13 路径身份
        assert props["product"] == "ai-common"  # #5 taxonomy(共享桶,非猜测)
        assert props["channel_visibility"] == ["widget", "api"]


# --------------------------------------------------------------------------- #
# 不变量 3+#5 closure:taxonomy(含 bc16eeb closure 规则)被 metadata
# migration dry-run 一致使用;B 类合法 unknown 语义保持
# --------------------------------------------------------------------------- #


class _FakeCol:
    """plan_migration 可用的最小 Weaviate collection 桩(与既有迁移测试同款)。"""

    def __init__(self, props_list):
        self._props = props_list

    def iterator(self, include_vector=False, return_properties=None):
        for p in self._props:
            yield SimpleNamespace(uuid="u-" + p["source_id"], properties=p)


class _FakeCollections:
    def __init__(self, props_list):
        self._props = props_list

    def get(self, name):
        return _FakeCol(self._props)


class _FakeClient:
    def __init__(self, props_list):
        self.collections = _FakeCollections(props_list)


class TestClosureThroughMigrationDryRun:
    def test_i18n_mirror_and_toolstack_no_longer_unknown_in_dry_run(self):
        """closure 规则经 plan_migration 生效:镜像树文档/ai-tool-stack 页得 canonical 值。"""
        from backend.services.product_migration import plan_migration

        props = [
            {"source_id": "wiki-documents-local/main/i18n/en/docusaurus-plugin-content-docs/current/6-neoeyes-ne503-series/3-software-guide/0-system-architecture.md", "product": "wiki", "url": "u1"},
            {"source_id": "website-camthink/tools/ai-tool-stack", "product": "website", "url": "https://www.camthink.ai/tools/ai-tool-stack/"},
            # B 类合法 unknown:非产品事实内容保持 unknown(契约语义不消失)
            {"source_id": "wiki-documents-local/main/package-lock.json", "product": "wiki", "url": "u3"},
            {"source_id": "website-camthink/blog/xyz", "product": "website", "url": "https://www.camthink.ai/blog/xyz/"},
        ]
        report = plan_migration(_FakeClient(props), class_name="Document", source_ids=["wiki-documents-local", "website-camthink"])
        assert report.total_scanned == 4
        assert report.total_unknown == 2  # 仅 B 类保持 unknown
        wiki = next(s for s in report.sources if s.source_id == "wiki-documents-local")
        assert wiki.mapping["wiki"]["ne503"] == 1  # 镜像树 → canonical 产品
        assert wiki.mapping["wiki"]["unknown"] == 1
        web = next(s for s in report.sources if s.source_id == "website-camthink")
        assert web.mapping["website"]["aitoolstack"] == 1

    def test_migration_derivation_uses_same_taxonomy_singleton(self):
        """ingest 与 migration 共用同一 taxonomy 实例(配置单源,零漂移)。"""
        tax = get_taxonomy()
        assert tax.derive_product("wiki", "x/i18n/en/docusaurus-plugin-content-docs/current/5-neoeyes-ne301-series/a.md", "").slug == "ne301"
        assert tax.derive_product("website", "y", "https://www.camthink.ai/tools/battery-calculator/").slug == "unknown"


# --------------------------------------------------------------------------- #
# 不变量 13:production APP_MODE=prod 要求有效 RELEASE.json(fail-closed)
# --------------------------------------------------------------------------- #


class TestReleaseFailClosedAtStartup:
    def test_prod_without_manifest_startup_identity_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setattr("backend.release._RELEASE_FILE", tmp_path / "RELEASE.json")
        reset_release_identity_cache()
        with pytest.raises(ReleaseIdentityError):
            get_release_identity()
        reset_release_identity_cache()

    def test_prod_with_manifest_identity_serves(self, tmp_path: Path, monkeypatch):
        f = tmp_path / "RELEASE.json"
        f.write_text(json.dumps({
            "version": "1.0.0", "git_sha": "c" * 40, "built_at": "2026-09-03T00:00:00Z",
            "image": "ghcr.io/harryhua-ai/ask-ai:v1.0.0", "ci_run_id": "1",
        }), encoding="utf-8")
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setattr("backend.release._RELEASE_FILE", f)
        reset_release_identity_cache()
        rid = get_release_identity()
        assert rid.version == "1.0.0" and rid.app_mode == "production" and rid.source == "manifest"
        reset_release_identity_cache()
