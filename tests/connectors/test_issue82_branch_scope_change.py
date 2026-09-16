"""Issue #82 branch scope 收窄/扩大 — 表征性证据(真实本地 git 仓 + 真实账本)。

生产现场(ne301-local,2026-09-15 只读取证)与 b338c3c 代码共同确立的事实:

1. **收窄方向(narrowing)是健康的** —— 本文件 A 组在当前 main 上**通过**:
   `branches=[main, halow] → [main]` 且 Git HEAD 完全不变时,
   `reconcile_membership` 依据 `membership_source_ids()` 的分支维度复合键
   (`{cfg.id}/{branch}/{rel}`)把账本中残留的 halow 文档识别为 stale 并按
   #71 语义墓碑退休。Issue #82 预设的 RED(「收窄后 halow 文档不被退休」)
   **在当前实现上不可复现** —— 每轮必跑的成员对账(sync.py 无变更/SHA 短路
   轮同样执行)已覆盖该语义。

2. **真正的缺陷在扩大方向(expansion)** —— 本文件 B1 为 **RED**:
   分支后加入配置时,若其远端 tip 已在初始全量 clone 的
   `refs/remotes/origin/<branch>` 中(SHA 相同 → 短路),且其提交历史全部
   早于增量窗口 `since`(生产实况:halow tip 2026-07-08,窗口为最近一轮
   成功同步),`fetch_changes` 对该分支**永远零产出** —— 内容从未进入账本。
   而成员对账只计算 `stale = ledger − authority`(退休方向),
   `authority − ledger`(缺失补灌方向)无任何组件可见:
   - `fetch_changes`:SHA 短路 + 窗口双重复跳过(B1);
   - `reconcile_membership`:账本 ⊆ 权威 ⇒ stale=∅,truth 记 current;
   - 生产证据:ne301-local 配置 branches=[main, ir-ver],ir-ver 树与 main
     逐字节相同、tip 2026-07-17,但账本 0 行 ir-ver 文档;9928 轮同步全部
     success/current;用户感知的「5534 未变更」实为 5379 serving + 155 已
     墓碑(2026-09-15 对账首次生效时退休的 main 上游删除文档)。

零外网:git 全部走本地 origin 仓;GitHub API 边界以真实 tip stub(与
test_github_multibranch_change_detection 同法)。账本用共享测试库
(TEST_DATABASE_URL),SRC 前缀隔离,前后清理。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource, Document, DocumentVersion
from backend.services.document_lifecycle import DocLifecycle
from backend.services.membership_currency import reconcile_membership

pytestmark = pytest.mark.unit

# 数据源 ID(前缀隔离;前后清理,不污染共享测试库)
SRC = "issue82-scope-local"

_SINCE_FUTURE = datetime.now(UTC) + timedelta(seconds=1)


# --------------------------------------------------------------------------- #
# fixtures / helpers(与 test_github_multibranch_change_detection 同法)
# --------------------------------------------------------------------------- #


def _git(args: list[str], cwd: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _sha(ref: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", ref], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture()
def origin_repo(tmp_path: Path) -> Path:
    """origin:main 与 halow 两分支,tip 都在「过去」(模拟生产:分支历史远早于增量窗口)。

    - main.md:两分支共有(同路径跨分支,source_id 因 branch 维度而不同);
    - halow-only.md:仅 halow 存在(收窄后应退休/扩大后应补灌的标志文档)。
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["init", "-b", "main", "."], cwd=origin)
    (origin / "main.md").write_text("# shared main v1\n", encoding="utf-8")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "m1"], cwd=origin)
    _git(["checkout", "-b", "halow"], cwd=origin)
    (origin / "halow-only.md").write_text("# halow only knowledge\n", encoding="utf-8")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "h1"], cwd=origin)
    _git(["checkout", "main"], cwd=origin)
    return origin


def _make_clone(origin: Path, tmp_path: Path) -> Path:
    """初始全量 clone(生产等价:`git clone --branch main` 会带入全部 origin/* ref)。"""
    clone = tmp_path / "clone"
    _git(["clone", str(origin), str(clone)], cwd=tmp_path)
    return clone


def _tips(origin: Path) -> dict[str, str]:
    return {
        "main": _sha("refs/heads/main", origin),
        "halow": _sha("refs/heads/halow", origin),
    }


def _connector(clone: Path, branches: list[str], tips: dict[str, str] | None = None) -> GitHubConnector:
    """构造 connector;tips 给定时 stub 掉纯网络的 API SHA 边界(git 行为全真)。"""
    cfg = SourceConfig(
        id=SRC,
        type="github",
        product="p",
        config={
            "repo_url": "https://github.com/o/r.git",
            "clone_path": str(clone),
            "file_types": [".md"],
            "branches": branches,
        },
        enabled=True,
        sync_interval="1h",
    )
    conn = GitHubConnector(cfg)
    if tips is not None:
        conn._api_get_latest_sha = types.MethodType(lambda self, branch: tips[branch], conn)
    return conn


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _sync_factory():
    """同步账本面(与 pipeline._session_factory 同语义;test_membership_currency 同法)。"""
    from backend.config import load_settings

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = create_engine(dsn.replace("+asyncpg", "+psycopg2"))
    return sessionmaker(bind=engine), engine


def _mk_active_doc(session, source_id: str) -> None:
    doc = Document(
        source_id=source_id,
        source_type="github",
        product="p",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://example.com/{source_id}.md",
        branch=source_id.split("/")[1],
        chunk_count=1,
        content_hash=_hash(source_id),
        lifecycle=DocLifecycle.ACTIVE,
    )
    session.add(doc)
    session.flush()
    version = DocumentVersion(
        source_id=source_id,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash=_hash("m" + source_id),
        generation_id="00000000-0000-0000-0000-000000000000",
        generation_ordinal=0,
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=1,
    )
    session.add(version)
    doc.current_version_id = version.id
    session.flush()


def _ledger_cleanup(engine) -> None:
    with engine.begin() as session:
        for model in (DocumentVersion, Document):
            session.execute(delete(model).where(model.source_id.like(f"{SRC}/%")))
        session.execute(delete(DataSource).where(DataSource.id == SRC))


def _lifecycle_of(factory, source_id: str) -> str:
    with factory() as session:
        doc = (
            session.execute(select(Document).where(Document.source_id == source_id))
            .scalar_one()
        )
        return doc.lifecycle


# ======================  A. 收窄方向(现状健康,GREEN 表征)  ======================


def test_a1_narrowing_with_unchanged_git_retires_removed_branch_docs(origin_repo, tmp_path):
    """Issue #82 字面 RED 不可复现:收窄 + Git HEAD 不变 ⇒ halow 文档被对账退休。

    branches=[main, halow] 全量灌入账本后收窄为 [main],origin 两分支 tip 全程
    不变(「无 Git diff」)。#71 每轮必跑的成员对账(无变更轮同样执行)必须
    把 {SRC}/halow/halow-only.md 判为 stale 并墓碑退休;main 文档不受影响。
    """
    clone = _make_clone(origin_repo, tmp_path)
    tips = _tips(origin_repo)

    # 全量灌入(配置含 halow 时的权威全集)
    conn_full = _connector(clone, ["main", "halow"], tips)
    ingested = {d.source_id for d in conn_full.fetch_all()}
    assert ingested == {f"{SRC}/main/main.md", f"{SRC}/halow/main.md", f"{SRC}/halow/halow-only.md"}

    factory, engine = _sync_factory()
    _ledger_cleanup(engine)
    try:
        with factory() as session:
            session.add(DataSource(id=SRC, type="github", product="p", config={}))
            for sid in sorted(ingested):
                _mk_active_doc(session, sid)
            session.commit()

        # 收窄配置(账本不变、Git HEAD 不变)→ 对账
        conn_narrow = _connector(clone, ["main"], tips)
        result = reconcile_membership(factory, conn_narrow, SRC, reason="issue82:narrow")

        # 权威全集收窄后,branch=halow 的全部复合键(main.md 同路径跨分支亦然)
        # 都退出 membership —— stale = 账本在服 − 权威,分支维度逐键判定
        assert result.status == "completed"
        assert set(result.stale_ids) == {f"{SRC}/halow/halow-only.md", f"{SRC}/halow/main.md"}
        assert result.retired == 2
        assert result.residual_ids == ()
        assert (
            _lifecycle_of(factory, f"{SRC}/halow/halow-only.md") == DocLifecycle.DELETED
        ), "收窄分支的文档必须进入既有 retirement 语义(墓碑),而非继续在服"
        assert (
            _lifecycle_of(factory, f"{SRC}/main/main.md") == DocLifecycle.ACTIVE
        ), "retained 分支的在服文档不得受收窄影响"
    finally:
        _ledger_cleanup(engine)
        engine.dispose()


def test_a2_narrowed_scope_reports_no_git_change_but_shrinks_authority(origin_repo, tmp_path):
    """「无变更」日志与权威范围收窄并不矛盾:fetch_changes 管的是 Git 事件,
    membership_source_ids 管的是配置范围真值 —— 两者在收窄轮同时成立。"""
    clone = _make_clone(origin_repo, tmp_path)
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main"], tips)  # 收窄后的配置
    assert list(conn.fetch_changes(_SINCE_FUTURE)) == []  # Git 无事件 → 无变更(允许的 fast path)
    assert conn.membership_source_ids() == {f"{SRC}/main/main.md"}  # halow 键已退出权威全集


# ======================  B. 扩大方向(真实缺陷,B1 为 RED)  ======================


def test_b1_branch_expansion_never_ingests_prewindow_content_red(origin_repo, tmp_path):
    """RED:分支后加入配置时,其早于增量窗口的内容永远不会被灌入账本。

    生产等价序列:初始仅 [main] 全量灌入 → 配置扩大为 [main, halow];halow
    tip 已在初始 clone 的 refs/remotes/origin 中(SHA 相同 → 短路),其提交
    历史全部早于 since(生产:last_success 窗口 vs halow tip 2026-07-08)。
    当前实现 fetch_changes 对 halow 零产出;membership_source_ids 却能看到
    halow 键 —— `authority − ledger` 缺口两侧都无人负责(对账只算
    ledger − authority 退休方向),新增分支的 membership 永远无法扩大。
    """
    clone = _make_clone(origin_repo, tmp_path)
    tips = _tips(origin_repo)

    # 初始态:仅 main 在配置里(生产:首次全量灌入只发生一次)
    conn_initial = _connector(clone, ["main"], tips)
    initial_ids = {d.source_id for d in conn_initial.fetch_all()}
    assert initial_ids == {f"{SRC}/main/main.md"}  # halow 内容此刻尚未入账本

    # 配置扩大:[main] → [main, halow];Git HEAD(两分支 tip)不变
    conn_expanded = _connector(clone, ["main", "halow"], tips)

    # 权威枚举看得到 halow 文档(配置范围确已扩大,复合键含 branch 维度)
    assert f"{SRC}/halow/halow-only.md" in conn_expanded.membership_source_ids()

    # RED:增量同步必须把新纳入范围的既有内容补灌进账本;当前实现零产出
    docs = list(conn_expanded.fetch_changes(_SINCE_FUTURE))
    got = {d.source_id for d in docs}
    assert f"{SRC}/halow/halow-only.md" in got, (
        "branch-scope 扩大后,新分支早于窗口的 in-scope 内容必须被补灌"
        f"(authority−ledger 缺口当前对 fetch 路径不可见);实际抓到: {sorted(got)}"
    )


def test_b2_branch_reorder_causes_no_membership_pseudochange(origin_repo, tmp_path):
    """控制(Acceptance 3):branch 顺序变化不得造成权威全集伪变化。"""
    clone = _make_clone(origin_repo, tmp_path)
    tips = _tips(origin_repo)

    forward = _connector(clone, ["main", "halow"], tips).membership_source_ids()
    backward = _connector(clone, ["halow", "main"], tips).membership_source_ids()
    assert forward == backward == {
        f"{SRC}/main/main.md",
        f"{SRC}/halow/main.md",
        f"{SRC}/halow/halow-only.md",
    }


def test_b3_unchanged_config_keeps_true_nochange_fast_path(origin_repo, tmp_path):
    """控制(Acceptance 3):配置未变化 + SHA 未变化 ⇒ 保留真正 no-change fast path。"""
    clone = _make_clone(origin_repo, tmp_path)
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main"], tips)
    assert list(conn.fetch_changes(_SINCE_FUTURE)) == []
    assert list(conn.fetch_changes(_SINCE_FUTURE)) == []  # 连续轮同样零 fetch 零产出
