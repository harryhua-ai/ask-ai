"""v1.4.0 存量库升级路径共享 fixtures(v1.3.0 等价 DDL/行集/列内省)。

供 test_v140_existing_db_upgrade_path.py 与 test_container_import_path.py 共用,
避免两份 DDL 漂移。
"""

from __future__ import annotations

import os

from sqlalchemy import text

from backend.config import load_settings

# v1.3.0 site_experiences 等价 DDL(列集/类型/可空性与 git show v1.3.0:backend/db/models.py
# 的 SiteExperience 逐一对应;Boolean 无 CHECK 约束 —— SQLAlchemy 1.4+ create_all
# 默认 create_constraint=False,生产 v1.3.0 表即纯 BOOLEAN)。
V13_DDL = """
CREATE TABLE site_experiences (
    site_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    allowed_origins JSONB,
    starters JSONB,
    welcome VARCHAR(500),
    language VARCHAR(10),
    welcome_i18n JSONB,
    starters_i18n JSONB,
    enabled BOOLEAN,
    launcher_style VARCHAR(50),
    launcher_theme VARCHAR(10),
    launcher_icon VARCHAR(50),
    launcher_shape VARCHAR(20),
    entry_mode VARCHAR(20),
    proactive_timing VARCHAR(10),
    launcher_motion VARCHAR(20),
    launcher_size VARCHAR(10),
    launcher_brand VARCHAR(10),
    launcher_color VARCHAR(20),
    chat_theme VARCHAR(10),
    chat_accent_color VARCHAR(20),
    chat_size VARCHAR(10),
    greeting_override VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (site_id)
)
"""

# 存量行(镜像生产实况:含崩溃时正在查询的 'camthink-website';含 NULL 密集
# legacy 行与已配置行)。
V13_ROWS = [
    (
        "INSERT INTO site_experiences (site_id, display_name, allowed_origins, starters,"
        " welcome, language, enabled, launcher_style, launcher_theme)"
        " VALUES ('camthink-website', 'CamThink Website', '[\"https://camthink.ai\"]'::jsonb,"
        " '[]'::jsonb, NULL, 'zh', TRUE, 'current', 'auto')"
    ),
    (
        "INSERT INTO site_experiences (site_id, display_name, allowed_origins, starters,"
        " welcome, language, enabled)"
        " VALUES ('legacy-site-b', 'Legacy B', '[\"https://b.example\"]'::jsonb,"
        " '[\"q1\"]'::jsonb, '你好', 'en', TRUE)"
    ),
    (
        "INSERT INTO site_experiences (site_id, display_name, allowed_origins, starters,"
        " welcome, language, enabled, launcher_style, launcher_theme, launcher_icon,"
        " launcher_shape, chat_theme)"
        " VALUES ('config-site-c', 'Configured C', '[\"https://c.example\"]'::jsonb,"
        " '[\"q2\"]'::jsonb, 'Hi', 'en', TRUE, 'pill', 'dark', 'sparkle', 'rounded',"
        " 'light')"
    ),
]

V13_COLUMN_NAMES = [
    "site_id", "display_name", "allowed_origins", "starters", "welcome", "language",
    "welcome_i18n", "starters_i18n", "enabled", "launcher_style", "launcher_theme",
    "launcher_icon", "launcher_shape", "entry_mode", "proactive_timing",
    "launcher_motion", "launcher_size", "launcher_brand", "launcher_color",
    "chat_theme", "chat_accent_color", "chat_size", "greeting_override",
    "created_at", "updated_at",
]


async def columns(engine, table: str = "site_experiences") -> list[dict]:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable"
                " FROM information_schema.columns WHERE table_name = :t"
                " ORDER BY ordinal_position"
            ),
            {"t": table},
        )
        return [
            {"name": r[0], "data_type": r[1], "max_len": r[2], "nullable": r[3]}
            for r in result.fetchall()
        ]


def dsn() -> str:
    d = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    assert "ask_ai_test" in d, "v1.4.0 存量库相关测试必须在 ask_ai_test 库上运行"
    return d
