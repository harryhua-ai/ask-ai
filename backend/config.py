"""配置模块。

提供全局配置 Settings 数据类、YAML 配置加载与环境变量展开能力。
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    """全局配置(不可变)。

    所有字段均通过环境变量注入,避免硬编码。
    """

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    weaviate_url: str
    weaviate_class_name: str
    deepseek_api_key: str
    deepseek_api_base: str
    deepseek_model: str
    embedder_device: str
    model_cache_dir: Path
    github_token: str
    api_host: str
    api_port: int
    log_level: str
    config_dir: Path
    jwt_secret: str
    encryption_key: str
    embedder_batch_size: int = 12
    embedder_max_length: int = 8192

    @property
    def postgres_dsn(self) -> str:
        """返回异步 PostgreSQL DSN。"""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _env(key: str, default: str = "") -> str:
    """从环境变量读取值,缺失时返回默认值。"""
    return os.environ.get(key, default)


def _validate_prod_secrets(settings: Settings) -> None:
    """prod 模式强制安全配置；dev/test 跳过。

    ENCRYPTION_KEY 为空会导致 api_key 加密失效（写侧 fail-closed，
    但读侧静默 fallback 把密文当明文用）；JWT_SECRET 用默认值会让
    token 可被公开已知密钥伪造。两者在 prod 必须显式设置。
    """
    if os.environ.get("APP_MODE", "dev") != "prod":
        return
    issues: list[str] = []
    if not settings.encryption_key or len(settings.encryption_key.encode()) < 32:
        issues.append("ENCRYPTION_KEY 必须非空且 ≥32 字节")
    if settings.jwt_secret == "dev-secret-change-in-production":
        issues.append("JWT_SECRET 不能使用默认值")
    if issues:
        raise RuntimeError("prod 安全配置校验失败: " + "; ".join(issues))


def load_settings(config_dir: Path | None = None) -> Settings:
    """从环境变量加载 Settings 实例。"""
    project_root = Path(__file__).resolve().parent.parent
    settings = Settings(
        postgres_host=_env("POSTGRES_HOST", "localhost"),
        postgres_port=int(_env("POSTGRES_PORT", "5432")),
        postgres_db=_env("POSTGRES_DB", "ask_ai"),
        postgres_user=_env("POSTGRES_USER", "ask_ai"),
        postgres_password=_env("POSTGRES_PASSWORD", "changeme"),
        weaviate_url=_env("WEAVIATE_URL", "http://localhost:8080"),
        weaviate_class_name=_env("WEAVIATE_CLASS_NAME", "Document"),
        deepseek_api_key=_env("DEEPSEEK_API_KEY"),
        deepseek_api_base=_env("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
        embedder_device=_env("EMBEDDER_DEVICE", "auto"),
        embedder_batch_size=int(_env("EMBEDDER_BATCH_SIZE", "12")),
        embedder_max_length=int(_env("EMBEDDER_MAX_LENGTH", "8192")),
        model_cache_dir=Path(_env("MODEL_CACHE_DIR", str(project_root / "models"))),
        github_token=_env("GITHUB_TOKEN"),
        api_host=_env("ASKAI_API_HOST", "0.0.0.0"),
        api_port=int(_env("ASKAI_API_PORT", "8000")),
        log_level=_env("LOG_LEVEL", "INFO"),
        config_dir=config_dir or Path("config"),
        jwt_secret=_env("JWT_SECRET", "dev-secret-change-in-production"),
        encryption_key=_env("ENCRYPTION_KEY", ""),
    )
    _validate_prod_secrets(settings)
    return settings


def _expand_env(value: Any) -> Any:
    """递归展开字典/列表中字符串里的 ${VAR} 占位符。"""
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: _env(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def resolve_migration_dsn(settings: "Settings | None" = None) -> str:
    """迁移工具 DSN 解析(Issue #20:生产迁移绝不静默选择测试库)。

    规则:
    - ``APP_MODE=prod`` 且环境带 ``TEST_DATABASE_URL`` → **硬失败**:
      生产迁移指向测试库是最高危误路由,拒绝执行优于任何静默回退;
      恢复手段 = 取消该环境变量(生产运行时不应携带测试专用 DSN);
    - 非 prod 沿用既有测试惯例(测试库 schema 对齐迁移);
    - 未设置时回落 load_settings() 的权威生产 DSN。

    所有 ``scripts/migrate_*.py`` 对 ``TEST_DATABASE_URL`` 的读取必须
    经由本函数(由 tests/scripts/test_migration_dsn_guard.py 强制)。
    """
    test_dsn = os.environ.get("TEST_DATABASE_URL")
    if test_dsn and os.environ.get("APP_MODE", "dev") == "prod":
        raise RuntimeError(
            "TEST_DATABASE_URL is set but APP_MODE=prod: refusing to run a "
            "production migration against a test database. Unset "
            "TEST_DATABASE_URL (production runtime must not carry test-only "
            "DSN overrides) and re-run."
        )
    if test_dsn:
        return test_dsn
    return (settings or load_settings()).postgres_dsn


def load_yaml_config(path: Path) -> dict:
    """加载 YAML 配置文件,并展开其中的 ${VAR} 环境变量占位符。"""
    with path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)
    return _expand_env(data)
