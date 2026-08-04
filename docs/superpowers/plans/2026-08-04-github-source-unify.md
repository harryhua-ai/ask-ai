# GitHub 数据源统一 + API 增量感知 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 GitHub 数据源类型(消除 github/local_git 双类型)+ 修 local_git 数据陈旧 bug(补 git fetch+reset)+ API SHA 智能触发 fetch + 全新实现 git clone/fetch/reset 能力。

**Architecture:** `github.py` 重构为唯一 git 源类型(全新实现 clone 管理 + fetch+reset 同步 + API SHA 感知,吸收 local_git 的 checkout+遍历)。`local_git` 移除 `@register`(降为实现细节)。admin 表单字段 schema 变更(owner/repo → repo_url + clone_path)。

**Tech Stack:** Python 3.12 / subprocess(git CLI)/ httpx(GitHub API)/ pytest(mock subprocess + httpx)/ React + zod(admin 表单)。

**Spec:** `docs/superpowers/specs/2026-08-04-github-source-unify-brainstorm.md`(双路审核 2 轮收敛,用户确认决策 1A/2A/3A/4A)

**Terminal Target:** implementation(tested branch,不 integrate — 等当前 P0#2 reindex 完成后,merge 本重构再跑一次 reindex 统一 source_type)

## Global Constraints

- 测试用 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(conftest drop_all 清开发库)
- venv: `.venv/bin/python`
- `GITHUB_TOKEN` 从 env,永不硬编码
- 新 connector 写 `source_type="github"`(统一,非 local_git)
- git 操作用 subprocess(与 local_git.py:73 一致),clone 只读副本(reset --hard 安全)
- **决策 4A**:clone 不可用(首次 clone 失败/磁盘满/无访问)报错跳过该源,**不降级逐文件 API**
- 不碰 working tree 未提交改动(query_rewrite.py / conftest.py / widget)
- 不 integrate(P0#2 reindex 跑中,不抢 Weaviate)

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `backend/connectors/github.py` | 重构:全新 clone+fetch+reset + API SHA 感知 + 吸收 checkout+遍历 | 修改(大改) |
| `backend/connectors/local_git.py` | 移除 `@register`(逻辑被 github.py 复用) | 修改(小) |
| `admin/src/pages/DataSources.tsx` | github 表单字段 schema 变更;SOURCE_TYPES 移除 local_git | 修改 |
| `admin/src/types/api.ts` | DataSourceType 移除 local_git(若定义在此) | 修改 |
| `config/data_sources.yaml` | github config schema 全量重写 | 修改 |
| `scripts/migrate_github_source_schema.py` | DB data_sources 迁移:local_git → github + schema | 新增 |
| `tests/connectors/test_github.py` | 重写:clone/fetch/reset/SHA 感知/边界 | 修改 |
| `tests/connectors/test_local_git.py` | 调整:@register 移除后的测试 | 修改 |

---

## Task 1: GitHubConnector 核心 — clone 管理 + fetch+reset 同步

**Files:**
- Modify: `backend/connectors/github.py`
- Test: `tests/connectors/test_github.py`

**Interfaces:**
- Consumes: `DataSourceConnector`、`RawDocument`、`SourceConfig`、`ConnectorRegistry`、`local_git.py` 的 `_iter_files`/`_should_include_path`/`_fetch_one` 逻辑(复用)
- Produces: 重构的 `GitHubConnector`(clone + fetch+reset + API SHA + 遍历)

- [ ] **Step 1: 写失败测试(核心机制)**

追加到 `tests/connectors/test_github.py`(新 GitHubConnector 测试;旧 REST API 测试随实现删除调整):

```python
"""GitHubConnector 测试(统一类型 + clone/fetch/reset + API SHA 感知)。

mock subprocess(git CLI)+ httpx(GitHub API)。不触真实 GitHub。
"""
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from backend.connectors.registry import ConnectorRegistry, SourceConfig


def _make_config(**overrides):
    config = {
        "repo_url": "https://github.com/camthink-ai/ne301.git",
        "branches": ["main"],
        "file_types": [".py", ".md"],
        "clone_path": "/tmp/fake-clone",  # 测试用 temp
    }
    config.update(overrides)
    return SourceConfig(
        id="ne301", type="github", product="ne301", enabled=True,
        config=config, sync_interval="1h",
    )


@pytest.mark.unit
def test_github_registered():
    import backend.connectors.github  # noqa
    assert "github" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_local_git_not_registered():
    """决策 4A:local_git 不再作为用户类型。"""
    import backend.connectors.github, backend.connectors.local_git  # noqa
    assert "local_git" not in ConnectorRegistry._connectors


@pytest.mark.unit
def test_github_repo_url_parsing():
    """repo_url → owner/repo 解析。"""
    import backend.connectors.github
    cfg = _make_config()
    conn = ConnectorRegistry.create(cfg)
    assert conn._owner == "camthink-ai"
    assert conn._repo == "ne301"


@pytest.mark.unit
def test_github_ensure_cloned_first_time(tmp_path):
    """clone_path 不存在 → git clone 被调(全新代码)。"""
    import backend.connectors.github
    clone_path = str(tmp_path / "new-clone")
    cfg = _make_config(clone_path=clone_path)
    conn = ConnectorRegistry.create(cfg)
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        conn._ensure_cloned("main")
    # git clone 被调
    assert any("clone" in str(call.args[0]) for call in mock_run.call_args_list)


@pytest.mark.unit
def test_github_ensure_cloned_exists_no_op(tmp_path):
    """clone_path 已存在 → 不 clone。"""
    import backend.connectors.github
    clone_path = str(tmp_path)  # 已存在
    cfg = _make_config(clone_path=clone_path)
    conn = ConnectorRegistry.create(cfg)
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        conn._ensure_cloned("main")
    mock_run.assert_not_called()


@pytest.mark.unit
def test_github_ensure_cloned_failure_raises(tmp_path):
    """clone 失败 → 报错,不降级(决策 4A)。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path / "fail"))
    conn = ConnectorRegistry.create(cfg)
    with patch("backend.connectors.github.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "git")):
        with pytest.raises(subprocess.CalledProcessError):
            conn._ensure_cloned("main")


@pytest.mark.unit
def test_github_git_sync_branch_fetch_and_reset(tmp_path):
    """_git_sync_branch: fetch + reset --hard(修 staleness bug)。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path))
    conn = ConnectorRegistry.create(cfg)
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        conn._git_sync_branch("main")
    cmds = [str(call.args[0]) for call in mock_run.call_args_list]
    assert any("fetch" in c for c in cmds)
    assert any("reset" in c and "--hard" in c for c in cmds)


@pytest.mark.unit
def test_github_remote_has_updates_sha_diff(tmp_path):
    """API SHA != 本地 → True。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path))
    conn = ConnectorRegistry.create(cfg)
    with patch.object(conn, "_api_get_latest_sha", return_value="remote-abc"), \
         patch.object(conn, "_git_local_sha", return_value="local-xyz"):
        assert conn._remote_has_updates("main") is True


@pytest.mark.unit
def test_github_remote_has_updates_sha_same(tmp_path):
    """API SHA == 本地 → False(跳过 fetch)。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path))
    conn = ConnectorRegistry.create(cfg)
    with patch.object(conn, "_api_get_latest_sha", return_value="same-sha"), \
         patch.object(conn, "_git_local_sha", return_value="same-sha"):
        assert conn._remote_has_updates("main") is False


@pytest.mark.unit
def test_github_remote_has_updates_api_failure_degrade(tmp_path):
    """API 异常 → True(降级触发 fetch)。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path))
    conn = ConnectorRegistry.create(cfg)
    with patch.object(conn, "_api_get_latest_sha", side_effect=RuntimeError("API down")), \
         patch.object(conn, "_git_local_sha", return_value="any"):
        assert conn._remote_has_updates("main") is True


@pytest.mark.unit
def test_github_private_repo_token_in_url(tmp_path):
    """私有仓库:clone URL 含 x-access-token:{token}@。"""
    import backend.connectors.github
    cfg = _make_config(clone_path=str(tmp_path / "priv"))
    conn = ConnectorRegistry.create(cfg)
    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}):
        url = conn._authed_url()
    assert "x-access-token:ghp_test123@" in url
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/test_github.py -k "registered or repo_url or ensure_cloned or git_sync or remote_has or private" -q
```

Expected: FAIL(新方法/字段不存在)

- [ ] **Step 3: 重构 github.py**

**删除**旧 REST API 逐文件逻辑(`_fetch_tree`/`_fetch_file_content`/`_api_url`/`_should_include` 的 tree 版)。**`test_github.py` 现有 486 行旧测试(REST API 逐文件)大量作废** —— Task 1 Step 1 的新测试替代;实施时**重写 test_github.py**(删旧 REST 测试,加新 clone/fetch/reset/SHA 测试)。**保留并改造**:

```python
"""GitHub 仓库数据源 Connector(唯一 git 源类型)。

统一 github/local_git 双类型(决策:local_git 降为实现细节)。
全新实现 git clone + fetch + reset(代码库原无 git 操作)。
修 local_git 数据陈旧 bug(从不 fetch → API SHA 智能触发 fetch+reset)。
"""
import logging
import os
import re
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

_REPO_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", re.IGNORECASE)


@ConnectorRegistry.register("github")
class GitHubConnector(DataSourceConnector):
    """GitHub 仓库数据源。

    config:
    - repo_url (str, 必填): 完整 HTTPS URL(如 https://github.com/camthink-ai/ne301.git)
    - branches (list, 可选): 多分支,默认 ["main"]
    - file_types (list, 可选): 后缀白名单,默认 [".py"]
    - clone_path (str, 可选): 本地 clone 路径,默认 ~/ask-ai-corpus/<repo>
    - include_dirs / exclude_regex (可选): 过滤(沿用现状)
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._repo_url: str = config.config["repo_url"]
        self._owner, self._repo = self._parse_repo_url(self._repo_url)
        self._branches: tuple[str, ...] = config.branches or tuple(config.config.get("branches", ["main"]) or ["main"])
        # branches 在 SourceConfig 是 tuple(复数);config.branches(单)兼容旧
        self._file_types: set[str] = {*config.config.get("file_types", [".py"])}
        self._clone_path: Path = Path(
            config.config.get("clone_path")
            or f"~/ask-ai-corpus/{self._repo}"
        ).expanduser()
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
        self._policy = ExclusionPolicy(config.config)
        self._token: str = os.environ.get("GITHUB_TOKEN", "")

    @staticmethod
    def _parse_repo_url(repo_url: str) -> tuple[str, str]:
        """repo_url → (owner, repo)。支持 https://github.com/{owner}/{repo}[.git]。"""
        m = _REPO_URL_RE.search(repo_url)
        if not m:
            raise ValueError(f"无法解析 repo_url: {repo_url}")
        return m.group(1), m.group(2)

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _authed_url(self) -> str:
        """私有仓库:HTTPS URL 内嵌 token(无 token 则原样)。"""
        if not self._token:
            return self._repo_url
        # https://github.com/... → https://x-access-token:{token}@github.com/...
        return self._repo_url.replace("https://", f"https://x-access-token:{self._token}@")

    def _ensure_cloned(self, branch: str) -> None:
        """首次 clone(clone_path 不存在)。失败报错,不降级(决策 4A)。"""
        if self._clone_path.exists():
            return
        self._clone_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", branch, self._authed_url(), str(self._clone_path)],
            check=True, capture_output=True,
        )

    def _git_sync_branch(self, branch: str) -> None:
        """fetch + reset 工作区到远端最新(修 staleness bug)。clone 只读,reset 安全。"""
        subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=self._clone_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{branch}"],
            cwd=self._clone_path, check=True, capture_output=True,
        )

    def _git_local_sha(self, branch: str) -> str:
        """本地 HEAD SHA(git rev-parse)。"""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._clone_path, check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()

    def _api_get_latest_sha(self, branch: str) -> str:
        """GitHub API:GET /repos/{owner}/{repo}/commits/{branch} → 最新 SHA。"""
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits/{branch}"
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        with httpx.Client(timeout=30, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()[0]["sha"]

    def _remote_has_updates(self, branch: str) -> bool:
        """API SHA vs 本地 HEAD。API 故障 → True(降级触发 fetch)。"""
        try:
            return self._api_get_latest_sha(branch) != self._git_local_sha(branch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("API 感知失败,降级直接 fetch: %s: %s", branch, str(exc)[:200])
            return True

    # 文件遍历(吸收 local_git 的 checkout+遍历,但用 reset 替代 checkout)
    def _should_include_path(self, rel: str) -> bool:
        """file_types + ExclusionPolicy 过滤(沿用 local_git 逻辑)。"""
        p = self._clone_path / rel
        if p.suffix.lower() not in self._file_types:
            return False
        try:
            size = p.stat().st_size
        except OSError:
            return False
        return not self._policy.should_exclude(rel, size)

    def _make_document(self, rel: str, content: str, branch: str) -> RawDocument:
        import hashlib
        return RawDocument(
            source_id=f"{self._config.id}/{branch}/{rel}",
            source_type="github",  # 统一(非 local_git)
            product=self.product,
            title=Path(rel).stem,
            content=content,
            url=f"https://github.com/{self._owner}/{self._repo}/blob/{branch}/{rel}",
            metadata={"path": rel, "branch": branch, "repo_url": self._repo_url},
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            channel_visibility=self._channel_visibility,
            branch=branch,
        )

    def _iter_files(self, branch: str) -> Iterator[RawDocument]:
        """遍历 clone 副本(吸收 local_git._iter_files)。"""
        for path in sorted(self._clone_path.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self._clone_path))
            if not self._should_include_path(rel):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                yield self._make_document(rel, content, branch)
            except OSError as exc:
                logger.warning("读取失败 %s: %s", rel, exc)

    def fetch_all(self) -> Iterator[RawDocument]:
        for branch in self._branches:
            self._ensure_cloned(branch)
            self._git_sync_branch(branch)
            yield from self._iter_files(branch)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        for branch in self._branches:
            self._ensure_cloned(branch)
            if self._remote_has_updates(branch):
                self._git_sync_branch(branch)
                yield from self._read_local_changes(branch, since)
            # SHA 相同:跳过

    def _read_local_changes(self, branch: str, since: datetime) -> Iterator[RawDocument]:
        """git log --since 拿变更文件(沿用 local_git 逻辑)。"""
        since_iso = since.strftime("%Y-%m-%d %H:%M:%S")
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--name-only", "--pretty=format:", "--diff-filter=AMR", "-M"],
            cwd=self._clone_path, check=True, capture_output=True, text=True,
        )
        seen = set()
        for line in result.stdout.splitlines():
            rel = line.strip()
            if rel and rel not in seen and self._should_include_path(rel):
                seen.add(rel)
                try:
                    content = (self._clone_path / rel).read_text(encoding="utf-8", errors="replace")
                    yield self._make_document(rel, content, branch)
                except OSError:
                    continue

    def fetch_deleted(self, since: datetime) -> list[str]:
        """git log --since diff-filter=D 拿删除文件(沿用 local_git 逻辑)。"""
        since_iso = since.strftime("%Y-%m-%d %H:%M:%S")
        deleted = []
        for branch in self._branches:
            result = subprocess.run(
                ["git", "log", f"--since={since_iso}", "--name-only", "--pretty=format:", "--diff-filter=D"],
                cwd=self._clone_path, check=True, capture_output=True, text=True,
            )
            for line in result.stdout.splitlines():
                rel = line.strip()
                if rel:
                    deleted.append(f"{self._config.id}/{branch}/{rel}")
        return deleted
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/test_github.py -q
```

Expected: PASS(新测试绿;旧 REST API 测试已随实现删除调整)

- [ ] **Step 5: Commit**

```bash
git add backend/connectors/github.py tests/connectors/test_github.py
git commit -m "feat(github): 重构 GitHubConnector — 全新 clone/fetch/reset + API SHA 感知(修 staleness bug)"
```

---

## Task 2: local_git 移除 @register(降为实现细节)

**Files:**
- Modify: `backend/connectors/local_git.py`(移除 `@register`)
- Modify: `tests/connectors/test_local_git.py`(调整)

- [ ] **Step 1: 移除 `@ConnectorRegistry.register("local_git")`**

`backend/connectors/local_git.py`:删除 `@ConnectorRegistry.register("local_git")` 装饰器(L31),保留 `class LocalGitConnector` 定义(内部逻辑可被 github.py 复用,但不再作为用户类型)。加注释说明。

- [ ] **Step 2: 调整 test_local_git.py**

删除/调整断言 `"local_git" in ConnectorRegistry._connectors` 的测试(改为 `"local_git" not in`)。保留 LocalGitConnector 内部逻辑的单元测试(若 github.py 复用其方法)。

- [ ] **Step 3: 运行测试**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/ -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/connectors/local_git.py tests/connectors/test_local_git.py
git commit -m "refactor(local_git): 移除 @register,降为实现细节(github 统一类型)"
```

---

## Task 3: admin 表单字段 schema 变更

**Files:**
- Modify: `admin/src/pages/DataSources.tsx`
- Modify: `admin/src/types/api.ts`(若 DataSourceType 定义在此)

- [ ] **Step 1: SOURCE_TYPES 移除 local_git**

`admin/src/pages/DataSources.tsx:22`:
```typescript
const SOURCE_TYPES = ["github", "filesystem"] as const;  // 移除 "local_git"
```

`formSchema` 的 `type` enum(`admin/src/pages/DataSources.tsx:27`):移除 `"local_git"`。

- [ ] **Step 2: github 表单字段改 {repo_url, clone_path}**

替换原 github 表单(owner/repo 输入,L273-277)为:
```tsx
{type === "github" && (
  <>
    <Input {...register("repo_url")} placeholder="https://github.com/camthink-ai/ne301.git" />
    <Input {...register("clone_path")} placeholder="~/ask-ai-corpus/ne301(可选,默认缓存)" />
    <Input {...register("branches")} placeholder="main, hw-v1.2" />
    <Input {...register("file_types")} placeholder=".md, .py" />
  </>
)}
```

移除 local_git 表单分支(repo_path 输入,L307)。

- [ ] **Step 3: formSchema + buildConfig + dsToForm 适配**

- `formSchema`(L25):字段加 `repo_url: z.string().optional(), clone_path: z.string().optional()`(可保留 owner/repo 为 optional 兼容,或移除)
- `buildConfig`(L72):github 分支输出 `{repo_url, clone_path, branches, file_types}`(从逗号分隔字符串转 list)
- `dsToForm`(L103):github 反向映射

- [ ] **Step 4: types/api.ts DataSourceType**

若 `DataSourceType` 枚举含 `local_git`,移除。

- [ ] **Step 5: 构建验证**

```bash
cd admin && npm run build  # tsc + vite build
```

Expected: 无 TS 错误

- [ ] **Step 6: Commit**

```bash
git add admin/src/pages/DataSources.tsx admin/src/types/api.ts
git commit -m "feat(admin): github 表单字段 schema 变更(owner/repo→repo_url+clone_path,移除 local_git)"
```

---

## Task 4: config/data_sources.yaml schema 全量重写

**Files:**
- Modify: `config/data_sources.yaml`

- [ ] **Step 1: github 源 schema 全量改写**

把 10 个 github 源从旧 schema(`{owner, repo, branch, include_dirs, exclude_regex}`)改为新(`{repo_url, branches, clone_path, file_types}`)。例:
```yaml
- id: "ne301"
  type: "github"
  product: "ne301"
  enabled: true
  config:
    repo_url: "https://github.com/camthink-ai/ne301.git"
    branches: ["main"]
    file_types: [".c", ".h", ".md", ".rst"]
    clone_path: "~/ask-ai-corpus/ne301"
  sync_interval: "1h"
  channel_visibility: ["widget", "api"]
```

> 注:YAML 仅 seed/参考,生产读 DB。但保持 schema 一致便于 migrate 脚本复用。

- [ ] **Step 2: 冒烟(YAML 解析 + schema 校验)**

```bash
.venv/bin/python -c "
import yaml
from backend.connectors.registry import ConnectorRegistry
d = yaml.safe_load(open('config/data_sources.yaml'))
cfgs = ConnectorRegistry.load_configs(d)
print(f'{len(cfgs)} sources parsed')
for c in cfgs:
    if c.type == 'github':
        assert 'repo_url' in c.config, f'{c.id} 缺 repo_url'
print('✓ github schema OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add config/data_sources.yaml
git commit -m "feat(config): github data_sources schema 全量重写(repo_url+branches+clone_path)"
```

---

## Task 5: DB 迁移脚本(local_git → github + schema)

**Files:**
- Create: `scripts/migrate_github_source_schema.py`

- [ ] **Step 1: 写迁移脚本**

```python
"""DB data_sources 迁移:type=local_git → github + config schema。

把 local_git 源(repo_path/branches)改为 github 源(repo_url/branches/clone_path),
并禁用废弃的旧 github 源(已被 local_git 取代的)。

用法:
    python scripts/migrate_github_source_schema.py [--dry-run]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from backend.config import load_settings
from backend.db.session import get_engine

# repo_path ~/ask-ai-corpus/<repo> → repo_url 推断(camthink-ai org)
# 实际映射需按 DB 现有 repo_path 核对,这里给默认推断逻辑
def infer_repo_url(repo_path: str, product: str) -> str:
    """从 repo_path 或 product 推断 GitHub URL。"""
    name = Path(repo_path).name  # ne301-local → ne301-local
    # 简化:camthink-ai/<name>(实际需核对 DB 里 repo_path 的真实仓库名)
    return f"https://github.com/camthink-ai/{name.replace('-local','')}.git"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    async with engine.begin() as conn:
        # 1. local_git → github + schema 迁移
        result = await conn.execute(text("SELECT id, config FROM data_sources WHERE type = 'local_git'"))
        rows = result.fetchall()
        print(f"local_git 源: {len(rows)} 个")
        for ds_id, config in rows:
            repo_path = config.get("repo_path", "")
            new_config = {
                "repo_url": infer_repo_url(repo_path, config.get("product", "")),
                "branches": list(config.get("branches", ["main"])),
                "file_types": config.get("file_types", [".py", ".md"]),
                "clone_path": repo_path,
            }
            if args.dry_run:
                print(f"[dry-run] {ds_id}: local_git → github, config={new_config}")
            else:
                await conn.execute(
                    text("UPDATE data_sources SET type='github', config=:c WHERE id=:id"),
                    {"c": new_config, "id": ds_id},
                )
                print(f"{ds_id}: migrated")

        # 2. 废弃旧 disabled github 源(已被取代)— 删除或保持 disabled
        if not args.dry_run:
            result = await conn.execute(text("DELETE FROM data_sources WHERE type='github' AND enabled=false"))
            print(f"删除废弃 disabled github 源: {result.rowcount}")
        else:
            result = await conn.execute(text("SELECT count(*) FROM data_sources WHERE type='github' AND enabled=false"))
            print(f"[dry-run] 待删废弃 github: {result.scalar()}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

> **注意**:`infer_repo_url` 是简化推断,**实施前需核对 DB 里 local_git 源的 repo_path 实际对应哪个 GitHub 仓库**(如 ne301-local → github.com/camthink-ai/ne301)。核对后调整映射表。

- [ ] **Step 2: dry-run 验证**

```bash
.venv/bin/python scripts/migrate_github_source_schema.py --dry-run
```

Expected: 输出 10 个 local_git → github 映射 + 废弃 github 计数;**人工核对 repo_url 推断正确**

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_github_source_schema.py
git commit -m "feat(migrate): local_git→github data_sources schema 迁移脚本(幂等,dry-run)"
```

---

## Task 6: 全量回归 + Real-Run Gate

**Files:**
- No code change;run tests + 手工核验

- [ ] **Step 1: 全量后端测试回归**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/ tests/pipeline/ -q
```

Expected: PASS

- [ ] **Step 2: sync.py import 触发 github register**

确认 `scripts/sync.py` 的 connector import 含 github(`import backend.connectors.github`),触发 `@register("github")`。

- [ ] **Step 3: Real-Run Gate — clone+fetch+reset 链路(本地 git 仓库模拟)**

用本地 init 的 git 仓库(非真实 GitHub)验证:
```bash
# 准备 "远端" 仓库
mkdir -p /tmp/fake-remote && cd /tmp/fake-remote && git init --bare
# 准备 clone 副本 + 推一个 commit
mkdir -p /tmp/fake-work && cd /tmp/fake-work && git init
echo "test" > a.py && git add . && git commit -m "init" && git remote add origin /tmp/fake-remote && git push origin main

# 测试 GitHubConnector clone + fetch+reset
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig
cfg = SourceConfig(id='test', type='github', product='test', enabled=True,
    config={'repo_url': 'file:///tmp/fake-remote', 'branches': ['main'], 'clone_path': '/tmp/test-clone'},
    sync_interval='1h')
conn = GitHubConnector(cfg)
conn._ensure_cloned('main')  # 首次 clone
print('clone OK:', list(conn._iter_files('main')))
# 模拟远端更新
"
```

Expected: clone 成功 + 文件遍历正确

> **注意**:`_parse_repo_url` 用 `github.com/...` 正则,**file:// URL 不兼容**。Real-Run 测试需:
> - 要么临时 mock `_parse_repo_url`/`_owner`/`_repo`(绕过解析,直接测 clone+fetch+reset)
> - 要么用真实 camthink GitHub 仓库(HTTPS + token)小 scope 测
> - file:// 的本地 git 仓库测试不可行(解析失败)。推荐:mock _parse + 用 temp 本地 git 仓库测 clone/fetch/reset 链路(不依赖真实 GitHub)。

> **更可靠的 Real-Run**:用真实 camthink 仓库(ne301)测——clone + fetch+reset,验证 `source_type="github"` 写入。但这依赖网络 + token,实施时在小 scope 验证。

- [ ] **Step 4: 记录 Real-Run 结果**

在 commit body 记录 clone+fetch+reset 链路验证。

---

## Self-Review Checklist

- [ ] `github` 唯一注册类型(`local_git` 移除 `@register`)
- [ ] GitHubConnector:clone + fetch+reset + API SHA 感知(全新 git 能力)
- [ ] `_git_sync_branch` = fetch + reset --hard(修 staleness,与 force-push 统一)
- [ ] `_remote_has_updates` API 故障降级(True → 触发 fetch)
- [ ] clone 不可用报错不降级(决策 4A)
- [ ] `source_type="github"` 写入 RawDocument
- [ ] repo_url 解析(owner/repo)+ 私有仓库 token
- [ ] admin github 表单 = {repo_url, clone_path, branches, file_types};SOURCE_TYPES 无 local_git
- [ ] YAML github schema 全量重写
- [ ] DB 迁移脚本(幂等 + dry-run + repo_url 核对)
- [ ] 单测全绿 + Real-Run(clone+fetch+reset 链路)

---

## 后续衔接(不在本 plan)

- **source_type 统一(决策 2A)**:merge 本重构后,等 P0#2 reindex 完成 → 再跑 `--reindex`(新 connector 写 github,自然统一)
- **intent-routing §1.2 数字更新**:`local_git 579,688` → `github 579,688`
- **Issues/PR/Releases 索引**(决策 1A):独立 spec
- **since 窗口优化**:改 `HEAD...origin/branch` 替代 `--since=24h`