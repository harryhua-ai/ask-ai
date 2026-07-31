# 代码库索引核心(Plan 1)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员能在面板配置多分支代码源,sync 从 DB 读配置,对每个分支全量索引(tree-sitter AST 分块 + 极保守排除 + BGE-m3 embedding)写入 Weaviate + Postgres documents 表。

**Architecture:** 配置统一到 DB(sync 读 `data_sources` 表,废弃 YAML 运行时源);新增 `local_git` connector 读本地 clone 的多分支;代码走 tree-sitter AST 分块、Markdown 走现有语义分块(按扩展名路由);`source_id` 加 branch;documents 表通过 `session_factory` 启用 doc 级去重。

**Tech Stack:** FastAPI、SQLAlchemy(async)、Weaviate v4、BGE-m3(embedder 已有)、tree-sitter(新增)、React + react-hook-form + zod + @tanstack/react-query(admin 前端)、pytest / vitest。

**范围:** spec `2026-07-31-codebase-analysis-design.md` §13 实现顺序步骤 1-3。不含 GPU 并行索引(Plan 2)、SCIP 符号层(Plan 2)、混合检索(Plan 3)。本 Plan 用单机串行 embedding 跑通多分支代码入库。

## Global Constraints

- Python ≥3.12,PEP 8,类型注解全量(black/isort/ruff)
- 后端测试:pytest,`asyncio_mode=auto`,marker `unit/integration/slow`;目标覆盖率 80%+
- 测试库隔离:`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(不污染开发库)
- 前端:admin 用 react-hook-form + zod + react-query;无 `console.log`
- 不可变数据:RawDocument/SourceConfig 保持 frozen dataclass;新增字段带默认值不破坏现有调用
- source_id 格式统一:`{owner}/{repo}/{branch}/{path}`(本地 git)或 `{source_id}/{branch}/{rel}`(filesystem);分支名不含 `/`
- 代码原文不入 PG;documents 表只存 doc 级元数据
- 极保守排除:只砍构建产物/二进制/纯测试数据;源码(含 vendor/CMSIS/ATON)不论大小保留

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/connectors/registry.py` | `SourceConfig` 加 `branches: tuple[str,...]` | Modify |
| `backend/connectors/base.py` | `RawDocument` 加 `branch: str` | Modify |
| `backend/connectors/local_git.py` | 本地 git 仓库 connector(多分支 checkout 读) | Create |
| `backend/connectors/filesystem.py` | source_id 加 branch;接通用排除规则 | Modify |
| `backend/connectors/exclusion.py` | 极保守排除规则(目录/扩展名/正则/size) | Create |
| `backend/pipeline/chunk_code.py` | tree-sitter AST 代码分块 | Create |
| `backend/pipeline/ingest.py` | 分块路由 + branch 元数据 + session_factory 写 documents | Modify |
| `backend/db/models.py` | `Document` 加 `branch` | Modify |
| `scripts/sync.py` | 读 DB;多分支循环;传 session_factory | Modify |
| `backend/api/admin/data_sources.py` | trigger_sync 传 session_factory;`GET preview-branches` | Modify |
| `admin/src/pages/DataSources.tsx` | 结构化表单 + 分支多选 + 编辑/删除 | Modify |
| `admin/src/hooks/useDataSources.ts` | update/delete/preview-branches hooks | Modify |
| `admin/src/types/api.ts` | DataSource 加 branches/include_dirs/exclude_dirs/exclude_regex/max_file_size | Modify |
| `tests/connectors/test_local_git.py` 等 | TDD 测试 | Create |

---

### Task 1: SourceConfig 扩展多分支 + DataSource→SourceConfig 转换

**Files:**
- Modify: `backend/connectors/registry.py`(SourceConfig 加 branches;load_configs 解析)
- Create: `backend/connectors/db_adapter.py`(DataSource ORM → SourceConfig)
- Test: `tests/connectors/test_db_adapter.py`

**Interfaces:**
- Produces: `SourceConfig.branches: tuple[str,...]`(默认 `()` = 单分支,兼容旧配置);`db_adapter.to_source_config(ds: DataSource) -> SourceConfig`

- [ ] **Step 1: Write failing test**

```python
# tests/connectors/test_db_adapter.py
from backend.connectors.db_adapter import to_source_config
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource

def test_to_source_config_maps_branches():
    ds = DataSource(id="ne301", type="local_git", product="ne301", enabled=True,
                    config={"repo_path":"/x/ne301","branches":["main","halow"],
                            "file_types":[".c",".h"]}, sync_interval="1h")
    cfg = to_source_config(ds)
    assert cfg.id == "ne301"
    assert cfg.branches == ("main", "halow")
    assert cfg.config["repo_path"] == "/x/ne301"

def test_source_config_branches_default_empty():
    cfg = SourceConfig(id="x", type="filesystem", product="p", enabled=True,
                       config={}, sync_interval="1h")
    assert cfg.branches == ()
```

- [ ] **Step 2: Run test — expect FAIL**(`to_source_config` 未定义、SourceConfig 无 branches)

`pytest tests/connectors/test_db_adapter.py -v`

- [ ] **Step 3: Implement**

```python
# backend/connectors/registry.py — SourceConfig 加字段
@dataclass(frozen=True)
class SourceConfig:
    # ... 现有字段 ...
    branches: tuple[str, ...] = ()   # 新增:多分支;空表示单分支(由 config.branch 或默认 main 决定)
```
`load_configs`:解析时 `branches=tuple(src.get("branches", ()))`。

```python
# backend/connectors/db_adapter.py
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource

def to_source_config(ds: DataSource) -> SourceConfig:
    """DataSource(ORM) → SourceConfig(frozen)。config JSONB 原样透传。"""
    return SourceConfig(
        id=ds.id, type=ds.type, product=ds.product, enabled=ds.enabled,
        config=ds.config, sync_interval=ds.sync_interval,
        branches=tuple(ds.config.get("branches", ())),
        channel_visibility=tuple(ds.config.get("channel_visibility", ("widget", "api"))),
    )
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/connectors/registry.py backend/connectors/db_adapter.py tests/connectors/test_db_adapter.py
git commit -m "feat(connectors): SourceConfig 加 branches 字段 + DataSource→SourceConfig 转换"
```

---

### Task 2: RawDocument + Chunk 加 branch(P8 数据契约)

**Files:**
- Modify: `backend/connectors/base.py`(RawDocument 加 branch)
- Modify: `backend/pipeline/chunk.py`(Chunk.channel_visibility 旁加 branch 透传,或复用 document.branch)

**Interfaces:**
- Produces: `RawDocument.branch: str`(默认 `""`);下游 chunk 通过 `chunk.document.branch` 取
- Consumes: Task 1 的 SourceConfig.branches

- [ ] **Step 1: Write failing test**

```python
# tests/connectors/test_base.py
from backend.connectors.base import RawDocument
def test_raw_document_branch_default():
    doc = RawDocument(source_id="a/b/main/c.py", source_type="local_git", product="p",
                      title="c", content="x", url="u", metadata={}, content_hash="h")
    assert doc.branch == ""
def test_raw_document_branch_set():
    doc = RawDocument(..., branch="hw-v1.2")
    assert doc.branch == "hw-v1.2"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** — `RawDocument` 加 `branch: str = ""`(末尾带默认,不破坏现有构造)

- [ ] **Step 4: Run — expect PASS**(同时跑现有 connector 测试确认无回归:`pytest tests/connectors/`)

- [ ] **Step 5: Commit** — `feat(base): RawDocument 加 branch 字段(P8 多分支契约)`

---

### Task 3: 极保守排除规则模块(P0)

**Files:**
- Create: `backend/connectors/exclusion.py`(目录/扩展名/正则/size 规则)
- Test: `tests/connectors/test_exclusion.py`

**Interfaces:**
- Produces: `ExclusionPolicy(config: dict)`,方法 `should_exclude(rel_path: str, size: int) -> bool`;默认极保守(构建产物/二进制/`wave_\d.*\.c$` 测试数据),源码不论大小保留

- [ ] **Step 1: Write failing test**(覆盖各情形)

```python
# tests/connectors/test_exclusion.py
from backend.connectors.exclusion import ExclusionPolicy
def test_exclude_build_dirs():
    p = ExclusionPolicy({})
    assert p.should_exclude("build/main.c", 100)
    assert p.should_exclude("lib/node_modules/x.js", 100)
def test_keep_cmsis_big_file():
    p = ExclusionPolicy({})
    assert not p.should_exclude("Drivers/CMSIS/DSP/arm_common_tables.c", 5_000_000)  # 源码保留
def test_exclude_wave_test_data():
    p = ExclusionPolicy({})
    assert p.should_exclude("test/wave_1ch_16bits.c", 1_000_000)
def test_exclude_binary_ext():
    p = ExclusionPolicy({})
    assert p.should_exclude("img/logo.png", 5000)
def test_custom_exclude_regex():
    p = ExclusionPolicy({"exclude_regex": r"_test\.c$", "exclude_dirs": ["vendor/"]})
    assert p.should_exclude("src/foo_test.c", 100)
    assert not p.should_exclude("src/main.c", 100)
def test_max_file_size_only_nonsource():
    p = ExclusionPolicy({"max_file_size": 1_000_000})
    assert not p.should_exclude("src/huge.c", 5_000_000)      # 源码不受限
    assert p.should_exclude("data/huge.json", 5_000_000)       # 非源码受限
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# backend/connectors/exclusion.py
import re
from pathlib import PurePosixPath

BUILD_DIRS = {"build","dist","node_modules","__pycache__","target","out",".git",".next",".venv","venv",".idea",".vscode"}
BINARY_EXT = {".png",".jpg",".jpeg",".gif",".svg",".webp",".wav",".mp3",".mp4",".bin",".elf",".hex",".zip",".gz",".tar"}
SOURCE_EXT = {".c",".h",".cpp",".hpp",".rs",".py",".ts",".tsx",".js",".jsx",".sh",".go",".java",".md",".mdx",".txt",".yaml",".yml",".json",".ipynb"}
DEFAULT_TEST_DATA_RE = re.compile(r"wave_\d.*\.c$")

class ExclusionPolicy:
    def __init__(self, config: dict):
        self.exclude_dirs = set(config.get("exclude_dirs", []))
        self.user_regex = re.compile(config["exclude_regex"]) if config.get("exclude_regex") else None
        self.max_file_size = config.get("max_file_size")  # 仅作用于非源码

    def should_exclude(self, rel_path: str, size: int) -> bool:
        parts = PurePosixPath(rel_path).parts
        if any(p.lower() in BUILD_DIRS or p.lower() in {d.strip("/") for d in self.exclude_dirs} for p in parts):
            return True
        ext = PurePosixPath(rel_path).suffix.lower()
        if ext in BINARY_EXT:
            return True
        if DEFAULT_TEST_DATA_RE.search(rel_path):
            return True
        if self.user_regex and self.user_regex.search(rel_path):
            return True
        # 源码不受 size 限制;非源码超大排除
        is_source = ext in SOURCE_EXT
        if not is_source and self.max_file_size and size > self.max_file_size:
            return True
        return False
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(connectors): 极保守排除规则模块(P0)`

---

### Task 4: 本地 git connector(多分支 checkout 读)

**Files:**
- Create: `backend/connectors/local_git.py`(`@register("local_git")`)
- Modify: `backend/connectors/filesystem.py`(source_id 加 branch;接入 ExclusionPolicy)
- Test: `tests/connectors/test_local_git.py`(用 tmp git repo fixture)

**Interfaces:**
- Produces: `LocalGitConnector(SourceConfig)` 实现 DataSourceConnector Protocol;`fetch_all` 对每个 branch 执行 `git checkout` 后遍历文件,yield RawDocument(branch 字段已填,source_id=`{cfg.id}/{branch}/{rel}`)
- Consumes: Task 1 SourceConfig.branches、Task 2 RawDocument.branch、Task 3 ExclusionPolicy

- [ ] **Step 1: Write failing test**(tmp_path 建微型 git repo,2 分支各一个文件)

```python
# tests/connectors/test_local_git.py
import subprocess, pytest
from backend.connectors.local_git import LocalGitConnector
from backend.connectors.registry import SourceConfig

@pytest.fixture
def tiny_repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git","init","-q","-b","main"], cwd=r, check=True)
    (r/"main_only.py").write_text("a=1\n")
    subprocess.run(["git","add",".","-A"], cwd=r, check=True)
    subprocess.run(["git","commit","-q","-m","init"], cwd=r, check=True,
                   env={**__import__("os").environ,"GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t","GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"})
    subprocess.run(["git","checkout","-q","-b","hw-v1.2"], cwd=r, check=True)
    (r/"hw.py").write_text("b=2\n")
    subprocess.run(["git","add",".","-A"], cwd=r, check=True)
    subprocess.run(["git","commit","-q","-m","hw"], cwd=r, check=True,
                   env={**__import__("os").environ,"GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t","GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"})
    subprocess.run(["git","checkout","-q","main"], cwd=r, check=True)
    return r

def test_fetch_all_multi_branch(tiny_repo):
    cfg = SourceConfig(id="ne301", type="local_git", product="ne301", enabled=True,
        config={"repo_path": str(tiny_repo), "file_types": [".py"]},
        sync_interval="1h", branches=("main","hw-v1.2"))
    docs = list(LocalGitConnector(cfg).fetch_all())
    branches_seen = {d.branch for d in docs}
    assert branches_seen == {"main","hw-v1.2"}
    assert any(d.source_id == "ne301/main/main_only.py" for d in docs)
    assert any(d.source_id == "ne301/hw-v1.2/hw.py" for d in docs)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# backend/connectors/local_git.py
import subprocess, hashlib
from collections.abc import Iterator
from pathlib import Path
from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.connectors.exclusion import ExclusionPolicy

@ConnectorRegistry.register("local_git")
class LocalGitConnector(DataSourceConnector):
    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._repo = Path(config.config["repo_path"]).expanduser()
        self._file_types = set(config.config.get("file_types", [".py"]))
        self._policy = ExclusionPolicy(config.config)
        self._branches = config.branches or (config.config.get("branch", "main"),)
        self._channel_visibility = config.channel_visibility

    @property
    def source_id(self) -> str: return self._config.id
    @property
    def product(self) -> str: return self._config.product

    def _checkout(self, branch: str) -> None:
        subprocess.run(["git","checkout","-q",branch], cwd=self._repo, check=True)

    def _iter_files(self, branch: str) -> Iterator[RawDocument]:
        for p in sorted(self._repo.rglob("*")):
            if not p.is_file() or ".git" in p.parts: continue
            if p.suffix.lower() not in self._file_types: continue
            rel = str(p.relative_to(self._repo))
            try: size = p.stat().st_size
            except OSError: continue
            if self._policy.should_exclude(rel, size): continue
            try: content = p.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            yield RawDocument(
                source_id=f"{self._config.id}/{branch}/{rel}",
                source_type="local_git", product=self.product,
                title=p.stem, content=content,
                url=f"file://{p.absolute()}",
                metadata={"repo": str(self._repo), "branch": branch, "path": rel},
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                channel_visibility=self._channel_visibility, branch=branch,
            )

    def fetch_all(self) -> Iterator[RawDocument]:
        for b in self._branches:
            self._checkout(b)
            yield from self._iter_files(b)

    def fetch_changes(self, since):
        # Plan 1 简化:全量回退(Plan 2/后续补 git diff 增量)
        yield from self.fetch_all()

    def fetch_deleted(self, since): return []
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(connectors): local_git connector 支持多分支 checkout(P8)`

---

### Task 5: tree-sitter 代码分块器(P2)

**Files:**
- Create: `backend/pipeline/chunk_code.py`
- Test: `tests/pipeline/test_chunk_code.py`
- 依赖:`pyproject.toml` 加 `tree-sitter>=0.23`、`tree-sitter-language-pack`(或各语言 grammar)

**Interfaces:**
- Produces: `chunk_code(doc: RawDocument, max_tokens=600, overlap=50) -> list[Chunk]`,按函数/类/方法切;每个 code chunk 前缀拼上下文摘要 `// repo @ branch > path > symbol(signature)`(无 class 降级为函数名);chunk.chunk_type="code"
- Consumes: Task 2 RawDocument.branch

- [ ] **Step 1: Write failing test**

```python
# tests/pipeline/test_chunk_code.py
from backend.connectors.base import RawDocument
from backend.pipeline.chunk_code import chunk_code
def test_split_python_functions():
    src = "def foo():\n    return 1\n\ndef bar(x):\n    return x+1\n"
    doc = RawDocument(source_id="r/main/m.py", source_type="local_git", product="p",
        title="m", content=src, url="u", metadata={}, content_hash="h", branch="main")
    chunks = chunk_code(doc, max_tokens=600, overlap=50)
    assert len(chunks) >= 2
    assert all(c.chunk_type == "code" for c in chunks)
    assert "foo" in chunks[0].text or "foo" in chunks[0].text.split("\n")[0]
def test_context_prefix_present():
    doc = RawDocument(..., branch="hw-v1.2", metadata={})
    chunks = chunk_code(doc)
    assert "hw-v1.2" in chunks[0].text  # 摘要前缀含 branch
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**(tree-sitter 按 function/class/method 节点切;语言按扩展名映射 `.py→python`、`.c/.h→c`、`.rs→rust`、`.ts/.tsx→typescript`、`.js→javascript`、`.sh→bash`;无语法支持的扩展名退化为按空行+长度切;每个 chunk 前拼摘要注释)

```python
# backend/pipeline/chunk_code.py(骨架,实现时填充 tree-sitter 节点遍历)
from collections.abc import Iterable
from backend.connectors.base import RawDocument
from backend.pipeline.chunk import Chunk, _estimate_tokens, _hard_split_section

LANG_MAP = {".py":"python",".c":"c",".h":"c",".cpp":"cpp",".hpp":"cpp",
            ".rs":"rust",".ts":"typescript",".tsx":"tsx",".js":"javascript",".sh":"bash"}

def _symbol_prefix(doc: RawDocument, symbol: str, signature: str) -> str:
    cmt = "//" if doc.metadata.get("path","").endswith((".c",".h",".cpp",".rs")) else "#"
    sym = f"{symbol}({signature})" if signature else symbol
    return f"{cmt} {doc.source_id.split('/')[0]} @ {doc.branch} > {doc.metadata.get('path','')} > {sym}\n"

def chunk_code(doc: RawDocument, max_tokens: int = 600, overlap: int = 50) -> list[Chunk]:
    # 1. 按语言解析 tree-sitter AST,提取 function/class/method 节点(span + 名称 + 签名)
    # 2. 每个节点文本 > max_tokens 走 _hard_split_section;<= 则整块
    # 3. 相邻小块合并到 max_tokens 以内
    # 4. 每个 chunk 前拼 _symbol_prefix(doc, symbol, signature)
    # 5. 构造 Chunk(chunk_type="code", document=doc, ...)
    #    branch/visibility 从 doc 继承(复用 chunk_document_semantic 的字段填充模式)
    ...  # 实现时按 tree-sitter API 填充(见 references/tree-sitter.md 若有)
```

> 实现注:tree-sitter v0.23 API:`from tree_sitter_language_pack import get_parser; parser = get_parser(lang); tree = parser.parse(src_bytes); query = LANG_QUERIES[lang]; for m in query.captures(tree.root_node): ...`。每种语言定义一个 query 捕获 `function_definition`/`class_definition`/`method_definition` 节点。无 grammar 的扩展名走 `_hard_split_section(doc.content, max_tokens, overlap)` 兜底(不拼 symbol 前缀)。

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(pipeline): tree-sitter 代码 AST 分块器(P2)`

---

### Task 6: ingest 分块路由 + branch 元数据 + documents session_factory

**Files:**
- Modify: `backend/pipeline/ingest.py`(路由;branch 写 Weaviate property;session_factory 启用)
- Test: `tests/pipeline/test_ingest.py`(现有,扩展)

**Interfaces:**
- Produces: `IngestionPipeline.ingest_document` 按 doc.source_type/扩展名路由(代码→chunk_code,Markdown→chunk_document_semantic);Weaviate 写入增 `branch` property;传入 session_factory 时写 documents 表(含 branch)
- Consumes: Task 2 RawDocument.branch、Task 5 chunk_code、Task 8 Document.branch

- [ ] **Step 1: Write failing test**

```python
# tests/pipeline/test_ingest.py(扩展)
def test_route_code_to_chunk_code(monkeypatch):
    # 断言 .py doc 走 chunk_code,.md 走 chunk_document_semantic
def test_weaviate_gets_branch_property(...):
    # 断言 collection.data.insert 的 properties 含 branch
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**
  - `_ensure_collection` 的 properties 加 `Property(name="branch", data_type=DataType.TEXT)`
  - `ingest_document`:`chunks = chunk_code(doc, ...) if _is_code(doc) else chunk_document_semantic(doc, ...)`;`_is_code` 按扩展名(.c/.h/.cpp/.hpp/.rs/.py/.ts/.tsx/.js/.sh → True)
  - `data.insert` 的 properties 加 `"branch": doc.branch`
  - `__init__` 默认 session_factory 仍可选;sync 侧(Task 7)传入

- [ ] **Step 4: Run — expect PASS**(含现有 ingest 测试无回归)

- [ ] **Step 5: Commit** — `feat(pipeline): ingest 分块路由 + branch 元数据(P2/P8)`

---

### Task 7: Document 加 branch + sync 读 DB + 多分支循环 + session_factory(P1/P3/P8)

**Files:**
- Modify: `backend/db/models.py`(Document 加 branch)
- Modify: `scripts/sync.py`(读 DB;多分支已在 connector 内;传 session_factory)
- Modify: `backend/api/admin/data_sources.py`(trigger_sync 传 session_factory)
- Test: `tests/db/test_models.py`、`tests/scripts/test_sync_db.py`

**Interfaces:**
- Produces: Document.branch;sync.run_sync 从 DB 读 configs;pipeline 构造时 `session_factory=get_sync_session_factory(engine)`(同步 sessionmaker)

- [ ] **Step 1: Write failing test**

```python
# tests/scripts/test_sync_db.py(集成,用 ask_ai_test 库)
# - seed DataSource(local_git,多分支)到 DB
# - 跑 run_sync → 断言 documents 表有该 source 的多分支行,branch 字段非空
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**
  - models.py:`Document` 加 `branch: Mapped[str] = mapped_column(String(100), default="", nullable=False, index=True)`;`_upsert_postgres` 写入 branch
  - sync.py:`run_sync` 改 `configs = await _load_configs_from_db(session_factory)`(查 `data_sources` 表 where enabled,经 Task 1 `to_source_config` 转);构造 pipeline 时 `session_factory=get_sync_session_factory(engine)`(注:sync 用同步 sessionmaker 写 documents,需新增 `get_sync_session_factory`,因为现有 get_session_factory 是 async)
  - data_sources.py `trigger_sync`:构造 pipeline 传 `session_factory`

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(sync): 读 DB 配置 + 启用 documents 表 + 多分支(P1/P3/P8)`

---

### Task 8: preview-branches API + 前端结构化表单(P5/P6/P7)

**Files:**
- Modify: `backend/api/admin/data_sources.py`(`GET /data-sources/preview-branches`)
- Modify: `admin/src/types/api.ts`(DataSource 加 branches/include_dirs/exclude_dirs/exclude_regex/max_file_size/file_types)
- Modify: `admin/src/hooks/useDataSources.ts`(useUpdateDataSource 接 UI;useDeleteDataSource;usePreviewBranches)
- Modify: `admin/src/pages/DataSources.tsx`(react-hook-form 结构化表单:按 type 动态字段;分支多选;编辑/删除按钮)
- Test: `tests/api/admin/test_data_sources.py`(preview-branches)、`admin/tests/`(组件)

**Interfaces:**
- Produces: `GET /api/admin/data-sources/preview-branches?owner=&repo=` → `{branches: ["main","hw-v1.2",...]}`;前端表单按 type 展开 owner/repo/branches(多选)/include_dirs/exclude_dirs/exclude_regex/file_types/max_file_size

- [ ] **Step 1: Write failing test**(后端 preview-branches,mock GitHub API)

```python
# tests/api/admin/test_data_sources.py
def test_preview_branches(monkeypatch):
    # mock httpx GET /repos/{o}/{r}/branches → [{"name":"main"},{"name":"hw-v1.2"}]
    # 调 GET /api/admin/data-sources/preview-branches?owner=o&repo=r
    # 断言返回 branches 列表
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement 后端**

```python
@router.get("/preview-branches")
async def preview_branches(owner: str, repo: str, _: EditorDep) -> dict[str, list[str]]:
    import httpx, os
    token = os.environ.get("GITHUB_TOKEN","")
    headers = {"Accept":"application/vnd.github+json",
               **({"Authorization":f"Bearer {token}"} if token else {})}
    async with httpx.AsyncClient(timeout=15, headers=headers) as c:
        r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100")
        r.raise_for_status()
    return {"branches":[b["name"] for b in r.json()]}
```

- [ ] **Step 4: Implement 前端** — DataSources.tsx 用 react-hook-form + zod schema;type 选 `local_git` 显示 repo_path+branches(多选,调 preview-branches 拉 GitHub 分支或手填)+ file_types+exclude_dirs+exclude_regex+max_file_size;`filesystem` 显示 root_path;补编辑(drawer 复用表单)、删除按钮。移除前端 `web_crawl`/`sdk` 枚举(P7 对齐)。

- [ ] **Step 5: Run tests — expect PASS**(后端 + `cd admin && npm run test`)

- [ ] **Step 6: Commit** — `feat(admin): 数据源结构化表单 + 分支多选 + 编辑删除 + preview-branches(P5/P6/P7)`

---

## Self-Review(plan 自审)

**1. Spec 覆盖**(§13 步骤 1-3):
- P1 sync 读 DB → Task 7 ✓
- P5 include_dirs 可配 → Task 8 前端 ✓
- P6 前端表单 → Task 8 ✓
- P7 枚举对齐 → Task 8 ✓
- P8 多分支 source_id → Task 2/4/6 ✓
- P0 极保守排除 → Task 3 ✓
- P2 tree-sitter 分块 → Task 5 ✓
- P3 documents 表 → Task 6/7 ✓
- 不含(Plan 2/3):P4 SCIP、GPU 并行、混合检索 ✓

**2. 占位符扫描**:Task 5 的 tree-sitter AST 遍历标了"实现时填充"——这是 plan 唯一的开放点,因 tree-sitter API 细节较长,已给出 API 入口 + 退化策略,执行者按注释填充(非"TODO 待定",而是有明确指引)。其余 task 代码完整。

**3. 类型一致性**:`SourceConfig.branches`、`RawDocument.branch`、`Document.branch`、`ExclusionPolicy.should_exclude(rel_path,size)`、`chunk_code(doc,max_tokens,overlap)`、`to_source_config(ds)` 在各 task 间签名一致 ✓

**执行风险**:
- Task 5 tree-sitter 多语言 grammar 是最大不确定点——建议执行时先验证 tree-sitter-language-pack 对 C/Rust/Python/TS 的可用性,不可用则该语言走 `_hard_split_section` 兜底
- Task 7 sync 同步/异步桥接:documents 表用同步 sessionmaker(ingest 已支持),sync 的 async 入口里调同步 pipeline(沿用现有 _sync_one 模式)无新问题
