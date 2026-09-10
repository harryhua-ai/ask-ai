"""容器导入路径矫正的运行时忠实测试(run 34463498223 失败类别的自动覆盖)。

生产事实(2026-09-10 run 34463498223):冻结 v1.4.0 镜像内以脚本路径形式执行
`python scripts/migrate_add_site_launcher_presentation.py` 时,Python 把
**脚本目录**(/app/scripts)前置到 sys.path,而 WORKDIR(/app,backend/ 之父)
不在导入根中 → `from backend.config import …` 在 import 时即失败
(ModuleNotFoundError: No module named 'backend'),发生在任何 SQL 之前。
生产调用已由 `compose run -e PYTHONPATH=/app` 修正(容器导入根)。

本模块三层验证:

1. **失败复现(不依赖 DB、不设 PYTHONPATH)**:以容器等价布局
   (<root>/backend + <root>/scripts/迁移脚本——脚本字节与仓库真实文件一致,
   backend 为指向仓库真实包的符号链接)执行**未修正**形式,必须复现
   ModuleNotFoundError('backend') —— 证明失败纯属导入根解析、先于任何 DB 执行;
2. **修正环境全链**:同一布局 + `PYTHONPATH=<容器根等价>` + 一次性 postgres
   (v1.3 存量 DDL)→ 迁移成功、列语义 VARCHAR(10) NULLABLE、既有行保全、
   重复执行幂等;DSN 仍经 resolve_migration_dsn 按 TEST_DATABASE_URL 路由
   (PYTHONPATH 不触及 DSN/发布身份语义);
3. **真实冻结镜像 opt-in**:docker + 本地已有 ghcr.io/harryhua-ai/ask-ai:v1.4.0
   (amd64)且提供 ASKAI_IMAGE_VERIFY_DSN(容器可达的一次性库)与
   ASKAI_IMAGE_VERIFY_NETWORK(容器网络)时,以真实镜像逐字节复现
   BEFORE(失败)/AFTER(成功)两形态;否则诚实跳过。
   (该验证已于 2026-09-10 在 amd64 生产主机以一次性容器人工完成并记录于执行
   报告 §17。)

与既有升级路径测试的关系:test_v140_existing_db_upgrade_path._run_migration 的
PYTHONPATH=<仓库根> 即本修正后的主机等价形式(容器根 /app 的对应物),不再
掩盖生产条件 —— 未修正形态的失败由本模块显式复现锁定。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.db.session import get_engine

from tests.scripts._v140_upgrade_fixtures import (
    V13_DDL,
    V13_ROWS,
    columns as _columns,
    dsn as _dsn,
)

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parent.parent.parent
REAL_SCRIPT = REPO / "scripts" / "migrate_add_site_launcher_presentation.py"
IMAGE = "ghcr.io/harryhua-ai/ask-ai:v1.4.0"


def _container_layout(tmp_path: Path) -> Path:
    """构造容器等价布局:<root>/backend(真实包符号链接)+ <root>/scripts/<迁移脚本
    (真实文件逐字节拷贝)>,对应镜像 /app 布局。"""
    root = tmp_path / "app"
    (root / "scripts").mkdir(parents=True)
    (root / "backend").symlink_to(REPO / "backend", target_is_directory=True)
    shutil.copy2(REAL_SCRIPT, root / "scripts" / REAL_SCRIPT.name)
    # 防漂移:布局内的脚本必须与仓库真实脚本逐字节一致
    assert (root / "scripts" / REAL_SCRIPT.name).read_bytes() == REAL_SCRIPT.read_bytes()
    return root


def _clean_env() -> dict:
    """生产复现环境:剥离 PYTHONPATH(镜像本无)与测试库路由,证明失败先于 DB。"""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "TEST_DATABASE_URL")}
    env["APP_MODE"] = "dev"
    return env


def _run_script(root: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-u", f"scripts/{REAL_SCRIPT.name}"],
        capture_output=True, text=True, env=env, cwd=str(root), timeout=180, check=False,
    )


@pytest.fixture
async def v13_db():
    """一次性 v1.3 存量库(与升级路径测试同一 DDL/行集);teardown 还原当前 schema。"""
    dsn = _dsn()
    engine = get_engine(dsn)
    from backend.db.models import SiteExperience, SiteTrustedAction

    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS site_trusted_actions"))
        await conn.execute(text("DROP TABLE IF EXISTS site_experiences CASCADE"))
        await conn.execute(text(V13_DDL))
        for stmt in V13_ROWS:
            await conn.execute(text(stmt))
    yield engine, dsn
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS site_trusted_actions"))
        await conn.execute(text("DROP TABLE IF EXISTS site_experiences CASCADE"))
        await conn.run_sync(
            lambda sc: SiteExperience.__table__.create(sc, checkfirst=True)
        )
        await conn.run_sync(
            lambda sc: SiteTrustedAction.__table__.create(sc, checkfirst=True)
        )
    await engine.dispose()


# ---------------------------------------------------------------- 1. 失败复现(先于 DB)


def test_unfixed_form_reproduces_production_import_failure(tmp_path):
    """未修正形式(无 PYTHONPATH)必须复现 run 34463498223 的失败:ModuleNotFoundError
    'backend',发生在 import 行、任何 SQL 之前(本用例不提供任何数据库)。

    宿主 venv 的 editable 安装(`__editable__.ask_ai-0.1.0.pth` → meta finder)会把
    仓库根注入 meta_path,恰好掩盖镜像内「根不在导入路径」的生产条件 —— wrapper 先
    摘除该 finder 与仓库路径,再以 run_path 保持脚本形式执行(脚本目录进 sys.path、
    根不进),与镜像语义一致。"""
    root = _container_layout(tmp_path)
    wrapper = (
        "import os, sys\n"
        # editable install() 会把 finder **类本身**追加进 meta_path(type(cls)=type/
        # __module__='builtins'),必须按 repr 过滤
        "sys.meta_path = [m for m in sys.meta_path if 'editable' not in repr(m).lower()]\n"
        # -c 形式会把 cwd 注入 sys.path[0];镜像脚本形式没有 cwd、只有脚本目录 ——
        # 剥离 cwd/'' 项,并摘除 editable finder 与仓库源路径(保留 .venv 内 site-packages)
        "sys.path = [p for p in sys.path if p not in ('', os.getcwd())]\n"
        f"sys.path = [p for p in sys.path if not (p.startswith({str(REPO)!r}) and '.venv' not in p)]\n"
        "import runpy\n"
        f"runpy.run_path({str(root / 'scripts' / REAL_SCRIPT.name)!r}, run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-u", "-c", wrapper],
        capture_output=True, text=True, env=_clean_env(), cwd=str(root), timeout=180, check=False,
    )
    assert proc.returncode != 0
    assert "No module named 'backend'" in proc.stderr
    assert "from backend.config import" in proc.stderr  # 失败位于 import 行(脚本 L22)
    assert "迁移完成" not in proc.stdout + proc.stderr  # 未进入迁移执行


# ---------------------------------------------------------------- 2. 修正环境全链


@pytest.mark.asyncio
async def test_corrected_import_environment_runs_migration(tmp_path, v13_db):
    engine, dsn = v13_db
    root = _container_layout(tmp_path)
    env = _clean_env()
    env["PYTHONPATH"] = str(root)  # 容器导入根(/app)的主机等价物
    env["TEST_DATABASE_URL"] = dsn

    proc = _run_script(root, env)
    assert proc.returncode == 0, f"修正环境仍失败:\n{proc.stdout}\n{proc.stderr}"
    assert "迁移完成" in proc.stdout + proc.stderr

    cols = await _columns(engine)
    launcher = next(c for c in cols if c["name"] == "launcher_presentation")
    assert launcher["data_type"] == "character varying"
    assert launcher["max_len"] == 10
    assert launcher["nullable"] == "YES"
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT count(*) FROM site_experiences"))).scalar()
    assert rows == 3  # 既有行保全


@pytest.mark.asyncio
async def test_corrected_form_is_idempotent(tmp_path, v13_db):
    engine, dsn = v13_db
    root = _container_layout(tmp_path)
    env = _clean_env()
    env["PYTHONPATH"] = str(root)
    env["TEST_DATABASE_URL"] = dsn

    assert _run_script(root, env).returncode == 0
    cols_once = await _columns(engine)
    assert _run_script(root, env).returncode == 0  # 部署重试/重跑安全
    assert await _columns(engine) == cols_once
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT count(*) FROM site_experiences"))).scalar()
    assert rows == 3


# ---------------------------------------------------------------- 3. 真实冻结镜像(opt-in)


def _docker() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


@pytest.mark.skipif(
    not _docker()
    or subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0
    or not os.environ.get("ASKAI_IMAGE_VERIFY_DSN")
    or not os.environ.get("ASKAI_IMAGE_VERIFY_NETWORK"),
    reason="需 docker + 本地已有真实 v1.4.0 镜像(amd64)+ 一次性库 DSN/网络"
    "(ASKAI_IMAGE_VERIFY_DSN / ASKAI_IMAGE_VERIFY_NETWORK);该验证已于 2026-09-10 "
    "在 amd64 主机人工完成并记录于执行报告 §17",
)
class TestRealFrozenImageExecution:
    """以真实冻结镜像逐字节复现 BEFORE/AFTER 两形态(仅显式供给一次性库时运行)。"""

    DSN = os.environ.get("ASKAI_IMAGE_VERIFY_DSN", "")
    NETWORK = os.environ.get("ASKAI_IMAGE_VERIFY_NETWORK", "")

    def _run(self, *extra_env: tuple[str, str]) -> subprocess.CompletedProcess:
        env_args: list[str] = ["-e", "APP_MODE=dev", "-e", f"TEST_DATABASE_URL={self.DSN}"]
        for k, v in extra_env:
            env_args += ["-e", f"{k}={v}"]
        return subprocess.run(
            ["docker", "run", "--rm", "--network", self.NETWORK, *env_args, IMAGE,
             "python", "scripts/migrate_add_site_launcher_presentation.py"],
            capture_output=True, text=True, check=False, timeout=300,
        )

    def test_before_form_fails_with_module_error(self):
        proc = self._run()  # 不注入 PYTHONPATH = 生产失败形态
        assert proc.returncode != 0
        assert "No module named 'backend'" in proc.stderr

    def test_after_form_succeeds(self):
        proc = self._run(("PYTHONPATH", "/app"))
        assert proc.returncode == 0, proc.stderr
        assert "迁移完成" in proc.stdout + proc.stderr
