# local_git 真增量(Plan 2.5)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** local_git connector 支持 git log 真增量——`fetch_changes(since)` 只返回 since 之后变更的文件,`fetch_deleted(since)` 返回删除的文件;sync 后续 cron 只索引变更(秒-分钟级),不再全量回退。

**Architecture:** 对每个配置分支 `git checkout` 后,用 `git log --since=<since> --name-only --diff-filter=AMR` 拿变更文件,`--diff-filter=D` 拿删除文件;变更文件经 `_should_include`/`ExclusionPolicy` 过滤后 fetch content 构造 RawDocument。sync.py 区分首次(全量)vs 后续(增量):`fetch_changes` 空 且 documents 表已有该源记录 → 无变更跳过;否则回退 `fetch_all`(首次全量)。

**Tech Stack:** local_git connector(`backend/connectors/local_git.py`)、git CLI(`git log`)、pytest(tmp git repo fixture)。

**范围:** spec §13 后续「sync 增量优化」。改 `local_git.py` + `scripts/sync.py` 的回退判断。

## Global Constraints

- Python ≥3.12,类型注解,PEP 8
- 测试隔离 `TEST_DATABASE_URL=postgresql+asyncpg://...ask_ai_test`
- `source_id` 格式 `{cfg.id}/{branch}/{rel}` 不变(确定性 UUID 依赖)
- 分支名不含 `/`(当前语料均符合)
- git log `--since` 接受 ISO8601;`--diff-filter=AMR`(added/modified/renamed)算变更,`D`(deleted)算删除
- 不破坏现有 github/filesystem connector 的增量行为

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/connectors/local_git.py` | `fetch_changes`/`fetch_deleted` 改真增量(git log) | Modify |
| `scripts/sync.py` | `_sync_one`:fetch_changes 空 + documents 已有 → 跳过(无变更);否则回退 fetch_all(首次) | Modify |
| `tests/connectors/test_local_git.py` | 真增量 + 删除测试(tmp git repo 多 commit) | Modify |

---

### Task 1: local_git.fetch_changes 真增量(git log --since)

**Files:**
- Modify: `backend/connectors/local_git.py`(替换 `fetch_changes` 的"回退 fetch_all"为 git log)
- Test: `tests/connectors/test_local_git.py`

**Interfaces:**
- Produces: `fetch_changes(since: datetime) -> Iterator[RawDocument]`,只 yield since 后变更(AMR)且通过 `_should_include` 的文件,branch 字段已填
- Consumes: `SourceConfig.branches`、`ExclusionPolicy`、`RawDocument.branch`

- [ ] **Step 1: Write failing test**

```python
# tests/connectors/test_local_git.py(新增)
def test_fetch_changes_incremental_only_changed(tiny_repo_with_history):
    """fetch_changes(since) 只返回 since 之后变更的文件,不含未变更的。"""
    from datetime import datetime, UTC, timedelta
    cfg, repo_path = tiny_repo_with_history  # fixture:main 有 a.py+b.py,feat-x 加 c.py
    connector = LocalGitConnector(cfg)
    # since = 现在(所有 commit 都在之前)→ 应返回全部(cross branch 全量)
    all_docs = list(connector.fetch_changes(datetime.now(UTC) - timedelta(days=1)))
    titles = {d.metadata["path"] for d in all_docs}
    assert "c.py" in titles  # feat-x 新增
    # since = 未来 → 无变更
    future = list(connector.fetch_changes(datetime.now(UTC) + timedelta(days=1)))
    assert future == []
```

(fixture `tiny_repo_with_history`:建 main + a.py + b.py commit;checkout feat-x + c.py commit;checkout main。确保两分支 + 历史 commit。)

- [ ] **Step 2: Run — expect FAIL**(当前 fetch_changes 回退全量,future 也返回全部)

`TEST_DATABASE_URL=... .venv/bin/python -m pytest tests/connectors/test_local_git.py::test_fetch_changes_incremental_only_changed -v`

- [ ] **Step 3: Implement**

```python
# backend/connectors/local_git.py
from datetime import datetime

def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
    """增量抓取:对每个分支 git log --since 变更文件(AMR),过滤后 yield。"""
    since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    for branch in self._branches:
        self._checkout(branch)
        # git log --since 变更文件名(AMR:added/modified/renamed),去重
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--name-only", "--pretty=format:",
             "--diff-filter=AMR", "-M"],
            cwd=self._repo, capture_output=True, text=True, check=True,
        )
        changed = {ln for ln in result.stdout.splitlines() if ln.strip()}
        for rel in sorted(changed):
            if not self._should_include_path(rel):
                continue
            yield from self._fetch_one(branch, rel)

def _should_include_path(self, rel: str) -> bool:
    """对相对路径做 file_types + ExclusionPolicy 过滤(复用 _iter_files 逻辑)。"""
    p = self._repo / rel
    if p.suffix.lower() not in self._file_types:
        return False
    try:
        size = p.stat().st_size
    except OSError:
        return False
    return not self._policy.should_exclude(rel, size)

def _fetch_one(self, branch: str, rel: str) -> Iterator[RawDocument]:
    """fetch 单个文件 → RawDocument(branch 已填)。"""
    p = self._repo / rel
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    yield RawDocument(
        source_id=f"{self._config.id}/{branch}/{rel}",
        source_type="local_git", product=self.product, title=p.stem,
        content=content, url=f"file://{p.absolute()}",
        metadata={"repo": str(self._repo), "branch": branch, "path": rel},
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        channel_visibility=self._channel_visibility, branch=branch,
    )
```

(把原 `_iter_files` 的单文件构造拆出 `_fetch_one` 复用;`fetch_all` 也改用 `_fetch_one`。)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(local_git): fetch_changes 真增量(git log --since AMR)`

---

### Task 2: local_git.fetch_deleted 真增量(git log --diff-filter=D)

**Files:**
- Modify: `backend/connectors/local_git.py`(替换 `fetch_deleted` 的 `return []`)
- Test: `tests/connectors/test_local_git.py`

**Interfaces:**
- Produces: `fetch_deleted(since) -> list[str]`,返回 since 后删除(D)文件的 source_id(`{cfg.id}/{branch}/{rel}`)

- [ ] **Step 1: Write failing test**

```python
def test_fetch_deleted_returns_removed(tiny_repo_with_history):
    """fetch_deleted 返回 since 后删除的文件 source_id。"""
    from datetime import datetime, UTC, timedelta
    cfg, repo_path = tiny_repo_with_history
    # fixture:main 删了 old.py
    connector = LocalGitConnector(cfg)
    deleted = connector.fetch_deleted(datetime.now(UTC) - timedelta(days=1))
    assert any("old.py" in d for d in deleted)
```

(fixture 加:main 有 old.py commit → git rm old.py commit。)

- [ ] **Step 2: Run — expect FAIL**(当前返回 [])

- [ ] **Step 3: Implement**

```python
def fetch_deleted(self, since: datetime) -> list[str]:
    """增量删除:对每分支 git log --diff-filter=D --since,返回 source_id 列表。"""
    since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    deleted: list[str] = []
    seen: set[str] = set()
    for branch in self._branches:
        self._checkout(branch)
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--name-only", "--pretty=format:",
             "--diff-filter=D"],
            cwd=self._repo, capture_output=True, text=True, check=True,
        )
        for rel in result.stdout.splitlines():
            rel = rel.strip()
            if not rel or not self._should_include_path(rel):
                continue
            sid = f"{self._config.id}/{branch}/{rel}"
            if sid not in seen:
                deleted.append(sid)
                seen.add(sid)
    return deleted
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(local_git): fetch_deleted 真增量(git log --diff-filter=D)`

---

### Task 3: sync.py 区分首次全量 vs 后续增量

**Files:**
- Modify: `scripts/sync.py`(`_sync_one`:fetch_changes 空 → 查 documents 表判断首次 vs 无变更)

**Interfaces:**
- Consumes: Task 1 fetch_changes(真增量)、Task 2 fetch_deleted
- Produces: sync 对"已有数据 + 无变更"源跳过(不回退全量);首次(无 documents 记录)仍 fetch_all

- [ ] **Step 1: Write failing test**

```python
# tests/scripts/test_sync_db.py(新增)
@pytest.mark.integration
async def test_sync_skips_unchanged_source_when_documents_exist(db_session, tmp_git_repo):
    """源在 documents 表已有记录 + fetch_changes 空 → 不回退全量(跳过)。"""
    # seed documents 表(该 source_id 已有)
    # sync --source 该源 → fetch_changes 空 → 不 fetch_all → items_new=0
    ...
```

- [ ] **Step 2: Run — expect FAIL**(当前 _sync_one 空必 fetch_all)

- [ ] **Step 3: Implement**

```python
# scripts/sync.py — _sync_one 改回退判断
async def _sync_one(cfg, pipeline, session_factory, *, triggered_by, dry_run):
    start = time.monotonic()
    log_entry = SyncLog(source_id=cfg.id, source_type=cfg.type, status="success", triggered_by=triggered_by)
    try:
        connector = ConnectorRegistry.create(cfg)
        since = datetime.now(UTC) - timedelta(hours=24)
        docs = list(connector.fetch_changes(since))
        if not docs:
            # 区分首次(无 documents 记录)vs 无变更
            existing = await _count_documents(session_factory, cfg.id)
            if existing > 0:
                logger.info("数据源 %s 无变更,跳过(documents 已有 %d)", cfg.id, existing)
                log_entry.items_new = 0
                log_entry.items_unchanged = existing
                log_entry.finished_at = datetime.now(UTC)
                log_entry.duration_ms = int((time.monotonic() - start) * 1000)
                return
            logger.info("数据源 %s 首次同步,回退全量", cfg.id)
            docs = list(connector.fetch_all())
        # ... 现有 ingest + delete 逻辑 ...
```

新增 `_count_documents(session_factory, source_id_prefix)`:`SELECT count(*) FROM documents WHERE source_id LIKE '<id>/%'`。

- [ ] **Step 4: Run — expect PASS**(首次全量 + 后续无变更跳过)

- [ ] **Step 5: Commit** — `feat(sync): 首次全量 vs 后续增量判断(无变更跳过)`

---

### Task 4: 端到端增量验证(tesla-t4)

**Files:** 无代码改动,验证 task

- [ ] **Step 1: 全量基线**(当前 tesla-t4 sync 跑完,documents 有记录)

- [ ] **Step 2: 再跑 sync(无 corpus 变更)→ 应秒级跳过**

```bash
ssh tesla-t4 "cd ~/ask-ai && time .venv/bin/python scripts/sync.py --source ne301-local 2>&1 | tail -5"
# 期望:"数据源 ne301-local 无变更,跳过" + 耗时秒级(非 ~小时)
```

- [ ] **Step 3: 模拟变更(tesla-t4 corpus 改一个文件)→ sync 只索引变更**

```bash
ssh tesla-t4 "echo '# test change' >> ~/ask-ai-corpus/ne301/README.md && cd ~/ask-ai-corpus/ne301 && git -c user.name=t -c user.email=t@t commit -aqm 'test change'"
ssh tesla-t4 "cd ~/ask-ai && time .venv/bin/python scripts/sync.py --source ne301-local 2>&1 | tail -5"
# 期望:只索引 README.md(秒级),非全量
```

- [ ] **Step 4: 验证 documents 增量 + Weaviate 不重复**

```bash
docker exec deploy-postgres-1 psql -U ask_ai -d ask_ai -c "SELECT count(*) FROM documents WHERE source_id LIKE 'ne301-local/%';"
# Weaviate 总数应稳定(确定性 UUID 覆盖,不重复)
```

---

## Self-Review

**1. Spec 覆盖**:spec §13 后续「sync 增量优化」→ Task 1-3 ✓;Task 4 端到端验证 ✓

**2. 占位符**:Task 3 test 的 `...`(seed documents + sync)是 fixture 框架,执行时按现有 `test_sync_db.py` 模式填(已注明)。其余代码完整。

**3. 类型一致性**:`fetch_changes(since) -> Iterator[RawDocument]`、`fetch_deleted(since) -> list[str]`、`_fetch_one(branch, rel) -> Iterator[RawDocument]`、`_count_documents(session_factory, prefix) -> int` 在各 task 一致 ✓

**4. 风险**:
- `git log --since` 跨分支:每分支 checkout + log,分支多(ne301 7)时多次 checkout(每次 `git checkout` 几秒,可接受)
- `--diff-filter=AMR` 含 renamed:`fetch_changes` 拿新名,旧名删除由 `fetch_deleted` 处理(renamed 在 git 是 D+A,--diff-filter=R 也算);可能重名双索引,确定性 UUID 覆盖兜底
- Task 3 `_count_documents` LIKE '<id>/%':source_id 含 branch,LIKE 前缀匹配 cfg.id 安全(id 不含特殊字符)
- 首次判断靠 documents 表:如果 documents 表被清(drop_all bug 重现),首次判断误判(回退全量)—— 可接受(全量幂等)
