"""Issue #107 — #102 lock-safety 测试必须遵循 canonical 测试库解析契约。

生产实证(v1.6.3-r9 release wave):tag/release CI 提供了
``TEST_DATABASE_URL``,但 ``tests/db/test_init_db_lock_safety.py`` 的
``_sync_dsn()``/``ddl_counting_engine`` fixture 裸读
``load_settings().postgres_dsn``,导致:

- CI 形状下测试解析到与注入测试库**不同/不可用**的目标,以 harness
  缺陷(连接失败)失败,而非 lock-safety 不变量失败 —— 主 artifact
  发布路径被测试环境 DSN bug 拖挂,倒逼 break-glass host build;
- 更高危:若 settings 恰好指向可达的生产形状库,``init_db``/DDL/
  ``LOCK TABLE`` 类测试会**直接打在生产库上**。

契约(conftest.py db_engine 权威口径 + #20 resolve_migration_dsn 先例):

- ``TEST_DATABASE_URL`` 是测试执行的权威 DSN(优先级最高);
- 无 env 时回落 settings 仅限非 prod 形状;``APP_MODE=prod`` 且无显式
  测试 DSN ⇒ fail-closed 拒绝(绝不静默把测试打在生产库);
- grep 级守卫:lock-safety 测试文件不得绕过该 resolver 裸读
  ``postgres_dsn``(镜像 #20 迁移脚本守卫,防未来重引缺陷)。

不削弱 #102 任何并发/锁序/lock_timeout/稳态零 DDL 断言。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

MODULE = "tests.db.test_init_db_lock_safety"

TEST_DSN = "postgresql+asyncpg://t:t@localhost:5432/ask_ai_test"
UNREACHABLE_PROD_SHAPE = "postgresql+asyncpg://prod:secret@pg.internal:5432/ask_ai"


def _module():
    return importlib.import_module(MODULE)


class TestCanonicalTestDsnResolution:
    """AC1/AC2:release-CI 形状 — env 提供且 settings 指向别处。"""

    def test_env_test_dsn_is_authoritative_over_settings(
        self, monkeypatch
    ):
        """CI 提供 TEST_DATABASE_URL ⇒ 解析必须命中注入测试库。

        修复前缺陷:裸读 settings.postgres_dsn ⇒ 返回 settings 指向的
        不同/不可用库(harness 缺陷失败,而非 lock 不变量失败)。
        """
        mod = _module()
        monkeypatch.setenv("TEST_DATABASE_URL", TEST_DSN)
        monkeypatch.setenv("APP_MODE", "prod")
        # 模拟 CI 生产形状 settings:与注入测试库完全不同且不可达
        monkeypatch.setattr(
            mod,
            "load_settings",
            lambda *a, **kw: SimpleNamespace(postgres_dsn=UNREACHABLE_PROD_SHAPE),
        )
        assert mod._test_dsn() == TEST_DSN
        assert mod._sync_dsn() == TEST_DSN.replace("+asyncpg", "+psycopg2").replace(
            "+psycopg2", ""
        )

    def test_prod_without_test_dsn_fails_closed(self, monkeypatch):
        """生产形状(APP_MODE=prod)且无显式测试 DSN ⇒ 拒绝执行。

        绝不允许 init_db/DDL/LOCK 类测试静默落到 settings(生产库)上。
        (patch 掉 prod secrets 校验,让失败精准落在 DSN 守卫本身,
        而不是 .env 密钥形状。)
        """
        import backend.config as config_mod

        mod = _module()
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setattr(
            config_mod, "_validate_prod_secrets", lambda settings: None
        )
        with pytest.raises(RuntimeError, match="TEST_DATABASE_URL|APP_MODE"):
            mod._test_dsn()

    def test_dev_fallback_keeps_settings_convention(self, monkeypatch):
        """非 prod 且无 env ⇒ 沿用 canonical 回落 settings(不回归)。"""
        mod = _module()
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("APP_MODE", "dev")
        fallback = "postgresql+asyncpg://dev:dev@localhost:5432/ask_ai_dev"
        monkeypatch.setattr(
            mod,
            "load_settings",
            lambda *a, **kw: SimpleNamespace(postgres_dsn=fallback),
        )
        assert mod._test_dsn() == fallback


class TestGrepGuard:
    def test_lock_safety_module_must_use_canonical_resolver(self):
        """lock-safety 测试文件不得绕过 resolver 裸读 postgres_dsn。

        镜像 #20 迁移脚本守卫:允许 load_settings 仅出现在 resolver
        内部;任何其它 ``postgres_dsn`` 裸读都是缺陷重引。
        """
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "db" / "test_init_db_lock_safety.py"
        ).read_text(encoding="utf-8")
        lines = src.splitlines()
        # 唯一合法点:resolver 函数体(顶层 def _test_dsn 到下一个顶层语句)
        legal: set[int] = set()
        resolver_start = None
        for i, line in enumerate(lines):
            if line.startswith("def _test_dsn"):
                resolver_start = i
            elif resolver_start is not None and line and not line[0].isspace():
                # resolver 结束(回到顶层)
                legal.update(range(resolver_start, i))
                resolver_start = None
        if resolver_start is not None:
            legal.update(range(resolver_start, len(lines)))
        offenders = [
            f"{i + 1}: {line.strip()}"
            for i, line in enumerate(lines)
            if "postgres_dsn" in line and i not in legal
        ]
        assert offenders == [], (
            f"lock-safety 测试裸读 postgres_dsn(Issue #107): {offenders};"
            "请经由 _test_dsn()(canonical TEST_DATABASE_URL 契约)"
        )
