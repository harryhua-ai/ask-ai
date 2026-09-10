"""v1.4.0 存量库升级路径测试(2026-09-10 生产事件矫正 · 失败类别的自动覆盖)。

事件:生产库(v1.3.0 schema)缺 site_experiences.launcher_presentation,而
fresh-DB 测试(create_all 直接建最终 schema)暴露不了这条升级路径 —— backend
v1.4.0 启动即 UndefinedColumnError 崩溃循环。

本模块**不使用 create_all 代表既有库**(那正是事故的测试盲区):显式以
v1.3.0 模型(column 集 blob=git show v1.3.0:backend/db/models.py)的等价 DDL
构造「存量库」,含真实行,然后执行**部署所用的同一条迁移路径**
(scripts/migrate_add_site_launcher_presentation.py 以子进程 __main__ 方式,
与镜像内 `python scripts/...` 同一入口)。

覆盖(任务 §8/§9/§10 逐项):
1. 初始无 launcher_presentation;2. 迁移成功;3. 列集 diff 恰为该列(加性、
无其他列变动);4. 列语义 = VARCHAR(10) NULLABLE(与 v1.4.0 模型一致);
5. 既有行数据保全;6. v1.4.0 模型 ORM 读写正常(NULL=未配置 → icon 契约);
7. 重复执行幂等;8. v1.3.0 形状访问(仅 v1.3 列集的 INSERT/SELECT)在迁移后
仍成立(回滚兼容:加性 nullable 列对旧应用不可见);9. 迁移失败 → 非零退出
(fail-closed 传播);10. 迁移日志不泄露 DSN 凭据。

pytestmark = integration(需真实 postgres;CI build-image test job 自带
postgres:16 服务,TEST_DATABASE_URL 惯例与 tests/scripts 既有迁移测试一致)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from backend.config import load_settings
from backend.db.models import SiteExperience, SiteTrustedAction
from backend.db.session import get_engine, get_session_factory

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_SCRIPT = REPO / "scripts" / "migrate_add_site_launcher_presentation.py"

LAUNCHER_COLUMN = "launcher_presentation"

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


def _dsn() -> str:
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    assert "ask_ai_test" in dsn, "存量库升级测试必须在 ask_ai_test 库上运行"
    return dsn


async def _columns(engine, table: str = "site_experiences") -> list[dict]:
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
            {
                "name": r[0],
                "data_type": r[1],
                "max_len": r[2],
                "nullable": r[3],
            }
            for r in result.fetchall()
        ]


def _run_migration(dsn: str) -> subprocess.CompletedProcess:
    """以部署同一入口执行迁移:脚本作为 __main__ 子进程(镜像内即 `python scripts/...`)。"""
    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = dsn
    env["APP_MODE"] = "dev"  # 非 prod:resolve_migration_dsn 路由到测试库(Issue #20 守卫)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-u", str(MIGRATION_SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=180, check=False,
    )


@pytest.fixture
async def v13_db():
    """构造 v1.3.0 形状的存量库(含真实行);teardown 还原为当前模型 schema。

    DROP 用 CASCADE:全量套件中先行测试可能已建 site_trusted_actions
    (FK → site_experiences,models.py:480);teardown 按 create_all 语义还原
    两表(CASCADE 会连带删掉其 FK,随后原样重建)。"""
    dsn = _dsn()
    engine = get_engine(dsn)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS site_experiences CASCADE"))
        await conn.execute(text(V13_DDL))
        for stmt in V13_ROWS:
            await conn.execute(text(stmt))
    cols_before = await _columns(engine)
    yield engine, dsn, cols_before
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS site_trusted_actions"))
        await conn.execute(text("DROP TABLE IF EXISTS site_experiences CASCADE"))
        # 还原当前模型 schema(按 create_all 语义重建两表及其 FK),后续测试环境一致
        await conn.run_sync(
            lambda sync_conn: SiteExperience.__table__.create(sync_conn, checkfirst=True)
        )
        await conn.run_sync(
            lambda sync_conn: SiteTrustedAction.__table__.create(sync_conn, checkfirst=True)
        )
    await engine.dispose()


# ---------------------------------------------------------------- 升级路径主线


@pytest.mark.asyncio
async def test_v130_existing_db_upgrade_to_v140(v13_db):
    engine, dsn, cols_before = v13_db

    # (1) 存量库初始无 launcher_presentation
    assert LAUNCHER_COLUMN not in {c["name"] for c in cols_before}
    assert set(c["name"] for c in cols_before) == set(V13_COLUMN_NAMES)

    # (2) 部署同路径迁移成功(logging 默认流 = stderr;编排日志两者皆收)
    proc = _run_migration(dsn)
    assert proc.returncode == 0, f"迁移失败:\n{proc.stdout}\n{proc.stderr}"
    assert "迁移完成" in proc.stdout + proc.stderr

    # (3) 列集 diff 恰为 launcher_presentation(加性;无其他列被改/删)
    cols_after = await _columns(engine)
    before_names = [c["name"] for c in cols_before]
    after_names = [c["name"] for c in cols_after]
    assert set(after_names) - set(before_names) == {LAUNCHER_COLUMN}
    assert set(before_names) - set(after_names) == set()
    for c_before in cols_before:
        c_after = next(c for c in cols_after if c["name"] == c_before["name"])
        assert c_after["data_type"] == c_before["data_type"]
        assert c_after["max_len"] == c_before["max_len"]
        assert c_after["nullable"] == c_before["nullable"]

    # (4) 列语义与 v1.4.0 模型一致:String(10) nullable,无默认回填
    launcher = next(c for c in cols_after if c["name"] == LAUNCHER_COLUMN)
    assert launcher["data_type"] == "character varying"
    assert launcher["max_len"] == 10
    assert launcher["nullable"] == "YES"

    # (5) 既有行数据保全(行数 + 关键列值)
    async with engine.begin() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM site_experiences"))).scalar()
        assert count == 3
        row = (
            await conn.execute(
                text(
                    "SELECT display_name, language, enabled, launcher_style,"
                    " launcher_theme FROM site_experiences WHERE site_id = 'camthink-website'"
                )
            )
        ).fetchone()
        assert row == ("CamThink Website", "zh", True, "current", "auto")
        legacy = (
            await conn.execute(
                text(
                    "SELECT launcher_style, launcher_theme, launcher_icon FROM"
                    " site_experiences WHERE site_id = 'legacy-site-b'"
                )
            )
        ).fetchone()
        assert legacy == (None, None, None)

    # (6) v1.4.0 模型 ORM 读写(迁移契约:既有行 NULL = 未配置 → legacy 行为)
    factory = get_session_factory(engine)
    async with factory() as session:
        site = await session.get(SiteExperience, "camthink-website")
        assert site is not None
        assert site.launcher_presentation is None
        site.launcher_presentation = "pill"
        await session.commit()
    async with factory() as session:
        site = await session.get(SiteExperience, "camthink-website")
        assert site.launcher_presentation == "pill"


# ---------------------------------------------------------------- 幂等 / 重试安全


@pytest.mark.asyncio
async def test_migration_reexecution_is_idempotent(v13_db):
    engine, dsn, _ = v13_db
    first = _run_migration(dsn)
    assert first.returncode == 0
    cols_once = await _columns(engine)
    async with engine.begin() as conn:
        rows_once = (await conn.execute(text("SELECT count(*) FROM site_experiences"))).scalar()

    # 部署重试 / 中断后重跑:第二次执行必须安全且无变化
    second = _run_migration(dsn)
    assert second.returncode == 0, f"重复执行失败(不幂等):\n{second.stdout}\n{second.stderr}"
    assert "迁移完成" in second.stdout + second.stderr
    cols_twice = await _columns(engine)
    assert cols_twice == cols_once
    async with engine.begin() as conn:
        rows_twice = (await conn.execute(text("SELECT count(*) FROM site_experiences"))).scalar()
    assert rows_twice == rows_once == 3


# ---------------------------------------------------------------- 回滚兼容(v1.3.0)


@pytest.mark.asyncio
async def test_v130_shaped_access_remains_valid_after_migration(v13_db):
    """加性 nullable 列对 v1.3.0 形状的应用不可见:仅 v1.3 列集的 INSERT/SELECT 仍成立。"""
    engine, dsn, _ = v13_db
    assert _run_migration(dsn).returncode == 0

    v13_insert = (
        "INSERT INTO site_experiences (site_id, display_name, allowed_origins, starters,"
        " welcome, language, welcome_i18n, starters_i18n, enabled, launcher_style,"
        " launcher_theme, launcher_icon, launcher_shape, entry_mode, proactive_timing,"
        " launcher_motion, launcher_size, launcher_brand, launcher_color, chat_theme,"
        " chat_accent_color, chat_size, greeting_override)"
        " VALUES ('rollback-compat', 'Rollback Compat', '[\"https://r.example\"]'::jsonb,"
        " '[\"q\"]'::jsonb, '欢迎', 'zh', NULL, NULL, TRUE, 'current', 'auto', NULL,"
        " NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
    )
    v13_select = (
        "SELECT site_id, display_name, language, enabled, launcher_style, launcher_theme,"
        " greeting_override, {launcher} FROM site_experiences WHERE site_id = 'rollback-compat'"
    ).format(launcher=LAUNCHER_COLUMN)
    async with engine.begin() as conn:
        await conn.execute(text(v13_insert))
        row = (await conn.execute(text(v13_select))).fetchone()
    assert row[0] == "rollback-compat"
    assert row[1] == "Rollback Compat"
    assert row[4] == "current"  # v1.3.0 的 launcher_style 语义未被触碰
    assert row[7] is None  # 新列对旧应用不可见:写入未提及 → NULL


# ---------------------------------------------------------------- 失败语义


@pytest.mark.asyncio
async def test_migration_failure_exits_nonzero(v13_db):
    """迁移失败 → 非零退出(fail-closed;编排层据此绝不 rollout)。"""
    engine, dsn, _ = v13_db
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE site_experiences"))
    proc = _run_migration(dsn)
    assert proc.returncode != 0
    assert "site_experiences" in (proc.stdout + proc.stderr)


@pytest.mark.asyncio
async def test_migration_logs_do_not_expose_credentials(v13_db):
    engine, dsn, _ = v13_db
    password = make_url(dsn).password
    assert password, "测试 DSN 必须带口令,否则本测试无意义"
    proc = _run_migration(dsn)
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert password not in combined, "迁移日志泄露 DSN 口令"


# ---------------------------------------------------------------- 冻结工件一致性


def test_migration_script_blob_matches_frozen_v140_tag():
    """本测试所验证的脚本 = v1.4.0 冻结镜像内的脚本(blob 级一致;
    镜像 Dockerfile COPY scripts/ → tag 41278f0 构建即含同一文件)。"""
    probe = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", "--quiet", "v1.4.0^{commit}"],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0:
        pytest.skip("本检出无 v1.4.0 tag(CI 浅检出);blob 一致性已在本任务执行报告中人工核实")
    head_blob = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", f"HEAD:{MIGRATION_SCRIPT.relative_to(REPO)}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    tag_blob = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", f"v1.4.0:{MIGRATION_SCRIPT.relative_to(REPO)}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head_blob == tag_blob
