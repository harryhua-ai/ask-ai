"""Issue #20 — 迁移工具 TEST_DATABASE_URL 守卫测试。

- resolve_migration_dsn:APP_MODE=prod + TEST_DATABASE_URL → 硬失败;
  非 prod 沿用测试惯例;未设置回落权威生产 DSN。
- grep 级守卫:任何 scripts/migrate_*.py 对 TEST_DATABASE_URL 的读取
  必须经由 resolve_migration_dsn(防止未来脚本重引裸读模式)。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import resolve_migration_dsn

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


class TestResolveMigrationDsn:
    def test_prod_with_test_dsn_refuses(self, monkeypatch):
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setenv(
            "TEST_DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/ask_ai_test"
        )
        with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
            resolve_migration_dsn()

    def test_dev_keeps_test_convention(self, monkeypatch):
        monkeypatch.setenv("APP_MODE", "dev")
        monkeypatch.setenv(
            "TEST_DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/ask_ai_test"
        )
        assert resolve_migration_dsn().endswith("ask_ai_test")

    def test_no_test_dsn_falls_back_to_settings(self, monkeypatch):
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("APP_MODE", "prod")
        # 不经 load_settings()(prod secrets 校验依赖真实 .env):stub 即可
        stub = SimpleNamespace(postgres_dsn="postgresql+asyncpg://p:p@pg:5432/ask_ai")
        assert resolve_migration_dsn(stub) == "postgresql+asyncpg://p:p@pg:5432/ask_ai"

    def test_prod_without_test_dsn_ok(self, monkeypatch):
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("APP_MODE", "prod")
        stub = SimpleNamespace(postgres_dsn="postgresql+asyncpg://p:p@pg:5432/ask_ai")
        assert resolve_migration_dsn(stub) == "postgresql+asyncpg://p:p@pg:5432/ask_ai"


class TestGrepGuard:
    def test_migrate_scripts_must_use_guarded_resolver(self):
        """任何读取 TEST_DATABASE_URL 的迁移脚本必须经 resolve_migration_dsn。"""
        offenders = []
        for f in sorted(SCRIPTS.glob("migrate_*.py")):
            src = f.read_text(encoding="utf-8")
            if "TEST_DATABASE_URL" in src and "resolve_migration_dsn" not in src:
                offenders.append(f.name)
        assert offenders == [], (
            f"迁移脚本裸读 TEST_DATABASE_URL(Issue #20): {offenders};"
            "请改用 backend.config.resolve_migration_dsn"
        )

    def test_resolver_exists_in_config(self):
        import backend.config as cfg

        assert hasattr(cfg, "resolve_migration_dsn")
