# 数据源统一收尾(#17 合并 + #18 表格 + #19 可读性)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 main 上落地 #17(github 统一,基于前序 PR #3 cherry-pick)+ #18(admin 表格移除 ID 列、调整列顺序)+ #19(类型中文显示 + product 前端常量字典),不 reindex(最后单独授权)。

**Architecture:** cherry-pick 前 序 PR #3 的 5 个核心 commit 到 main,解决 5 个冲突文件(Docker/CI/sync 让位于 main 版本);admin DataSources 表格改造(前端纯改);product 用前端常量字典 PRODUCT_LABELS(不建表)。

**Tech Stack:** Python 3.12 / React + zod / pytest。

**Spec:**
- 前序:`docs/superpowers/specs/2026-08-04-github-source-unify-brainstorm.md`(双路审核收敛)
- 前序 plan:`docs/superpowers/plans/2026-08-04-github-source-unify.md`(PR #3 已实现)

## Global Constraints

- **冲突解决原则**:5 个冲突文件(Dockerfile / .dockerignore / build-image.yml / docker-compose.yml / sync.py)全部取 main 版本(已生产验证),PR #3 旧版本丢弃
- **id 保留语义化**:**不改 UUID**(评审 H3:source_id 里嵌 id,UUID 破坏可读性;#18「移除 ID」指前端不展示,不是改后端主键生成)
- **product 不建表**(评审 M3:8 个固定值建表过度工程),用前端常量字典
- **类型显示中文**(决策 B):`{github:"代码仓库", filesystem:"文件目录", woocommerce:"商城"}`
- **local_git.py 删除**(决策 D=a):逻辑搬进 github.py
- 测试:`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest`
- **不动生产数据**(reindex 最后单独授权)

## Terminal Target: implementation(测过,不 integrate 不 reindex)

---

## Task 1: Cherry-pick PR #3 核心改动到 main

**Files:**
- 基于前序 5 commit:`d910037`(github 重构) `49bdeb2`(local_git 降级) `af70262`(admin 表单) `07809dc`(config yaml) `931b390`(迁移脚本)
- 冲突文件:`Dockerfile` `.dockerignore` `.github/workflows/build-image.yml` `deploy/tesla-t4/docker-compose.yml` `scripts/sync.py`

**Interfaces:**
- Consumes: 前序 PR #3 分支 `feat/github-unify` 上的 5 个 commit
- Produces: main 分支上有 github 统一的完整实现(connector + admin + config + 迁移脚本)

- [x] **Step 1: 在 worktree 上 cherry-pick 5 个 commit**

```bash
# worktree 已在 main 上,从 origin/feat/github-unify cherry-pick
git cherry-pick d910037  # github 重构(可能跟 main 的 sync.py 冲突)
# 冲突解决原则:sync.py 取 main 版本(git checkout --ours),github.py 取 PR 版本
```

逐个 cherry-pick:d910037 → 49bdeb2 → af70262 → 07809dc → 931b390。每个冲突按下面原则解决。

- [x] **Step 2: 冲突解决原则(逐文件)**

| 冲突文件 | 解决 |
|---|---|
| `Dockerfile` | 取 **main**(已含 git safe.directory + cu128 + admin COPY) |
| `.dockerignore` | 取 **main** |
| `.github/workflows/build-image.yml` | 取 **main**(已含 admin build in Actions) |
| `deploy/tesla-t4/docker-compose.yml` | 取 **main**(已含端口 18000 + POSTGRES_HOST 覆盖) |
| `scripts/sync.py` | 取 **main** 版本;但确认 PR #3 删的那行 `import backend.connectors.local_git` 是否还在(若 local_git 不再 @register,这个 import 是为了让 sync 触发 local_git 注册——现在 local_git 降级了,import 保留无害,但若 PR 删了且 main 保留,以 main 为准) |

**关键**:cherry-pick `49bdeb2`(local_git 降级)时,它会改 `scripts/sync.py` 删 1 行 import。若冲突,核对:main 的 sync.py 是否还 import local_git?是则保留 import(无害,local_git 类还在只是不 @register),或按 PR 删除——**以 main 现状为准,只确保 sync.py 能跑**。

- [x] **Step 3: 跑 connector 测试验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/ -q
```

Expected: PASS(github 新测试绿、local_git 降级测试绿)

- [x] **Step 4: Commit(cherry-pick 自动 commit,冲突解决后 git cherry-pick --continue)**

---

## Task 2: admin DataSources 表格 #18 改造

**Files:**
- Modify: `admin/src/pages/DataSources.tsx`(Task 1 cherry-pick 后的版本,已是 PR #3 的 repo_url+clone_path 表单)

**Interfaces:**
- Consumes: Task 1 的 admin 表单(github repo_url 模式)
- Produces: 表格无 ID 列、列顺序为 产品线→类型→状态→同步间隔→操作

- [x] **Step 1: 表格列顺序调整 + 移除 ID 列**

找到 `<TableHeader>` 区块(约 L389),改:

```tsx
<TableHeader>
  <TableRow>
    <TableHead>产品线</TableHead>
    <TableHead>类型</TableHead>
    <TableHead>状态</TableHead>
    <TableHead>同步间隔</TableHead>
    <TableHead>操作</TableHead>
  </TableRow>
</TableHeader>
```

对应 `<TableBody>` 的 `<TableRow>`(约 L408+),删掉 ID 单元格(`<TableCell className="font-mono text-sm">{ds.id}</TableCell>`),按新顺序排列。

- [x] **Step 2: 移除新建表单的 ID 输入框**

表单里找 ID 的 `<Label>ID</Label>` + 对应 `<Input {...register("id")}>`(约 L236),**整段删除**。

后端 create API 仍需 id——保留前端 formSchema 的 id 字段为 optional,提交时若无 id 则后端用 `ds.product` + 时间戳/slug 生成(或前端默认生成 `product-<timestamp>`)。

**决策**:前端提交时,若用户没填 id(现在表单没这字段了),用 `product` 值 + 短 hash 生成,如 `${product}-${Date.now().toString(36)}`。改 formSchema 的 id 默认值 + onSubmit 逻辑。

- [x] **Step 3: 后端 create API 接受空 id 时生成**

`backend/api/admin/schemas.py:55`:`DataSourceCreate.id: str = Field(..., min_length=1)` 改为 `id: str | None = Field(None)`(可选)。`backend/api/routes` 里 create data source 逻辑:若 id 为 None,生成 `${product}-${uuid4().hex[:8]}`。

- [x] **Step 4: admin build 验证**

```bash
cd admin && npm run build
```

Expected: 无 TS 错误

- [x] **Step 5: Commit**

```bash
git add admin/src/pages/DataSources.tsx backend/api/
git commit -m "feat(admin): 数据源表格移除 ID 列 + 调整列顺序(#18)"
```

---

## Task 3: #19 类型中文显示 + product 前端常量字典

**Files:**
- Modify: `admin/src/pages/DataSources.tsx`(加常量字典 + 显示映射)

**Interfaces:**
- Consumes: Task 1-2 的 DataSources
- Produces: 类型列显示中文、产品线列显示中文 label

- [x] **Step 1: 加 TYPE_LABELS + PRODUCT_LABELS 常量**

文件顶部(SOURCE_TYPES 附近)加:

```tsx
const TYPE_LABELS: Record<string, string> = {
  github: "代码仓库",
  filesystem: "文件目录",
  woocommerce: "商城",
};

const PRODUCT_LABELS: Record<string, string> = {
  ne301: "NE301 边缘相机",
  ne101: "NE101 低功耗相机",
  ne503: "NE503 AI 相机",
  ng4500: "NG4500 边缘网关",
  neomind: "NeoMind 平台",
  wiki: "官方文档",
  aitoolstack: "AI Tool Stack",
  knowledge: "支持案例",
  commercial: "商城",
};
```

- [x] **Step 2: 表格类型列显示中文**

`<TableCell>{ds.type}</TableCell>` 改 `<TableCell>{TYPE_LABELS[ds.type] ?? ds.type}</TableCell>`

- [x] **Step 3: 表格产品线列显示中文 label + hover 显示原始 key**

```tsx
<TableCell title={ds.product}>{PRODUCT_LABELS[ds.product] ?? ds.product}</TableCell>
```

未知 product 降级显示原始 key。

- [x] **Step 4: build 验证**

```bash
cd admin && npm run build
```

- [x] **Step 5: Commit**

```bash
git add admin/src/pages/DataSources.tsx
git commit -m "feat(admin): 类型中文显示 + product 可读名映射(#19)"
```

---

## Task 4: woocommerce 进 SOURCE_TYPES 枚举

**Files:**
- Modify: `admin/src/pages/DataSources.tsx`

- [x] **Step 1: SOURCE_TYPES 加 woocommerce**

```tsx
const SOURCE_TYPES = ["github", "filesystem", "woocommerce"] as const;
```

formSchema 的 type enum 同步加。`buildConfig` 加 woocommerce 分支(store_url / consumer_key / consumer_secret)。表单 UI 加 woocommerce 条件渲染。

- [x] **Step 2: build 验证 + Commit**

```bash
git add admin/src/pages/DataSources.tsx
git commit -m "feat(admin): woocommerce 进数据源类型枚举(#19)"
```

---

## Task 5: 全量回归 + Real-Run Gate

- [x] **Step 1: 后端全量测试**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/ tests/pipeline/ tests/api/ -q
```

- [x] **Step 2: admin build**

```bash
cd admin && npm run build
```

- [x] **Step 3: sync.py 冒烟(import 不报错)**

```bash
.venv/bin/python -c "import scripts.sync" 2>&1 | head -5
```

- [x] **Step 4: 记录结果,不 reindex 不 integrate**

---

## Self-Review Checklist

- [x] github 统一:local_git 降级、github clone/fetch/reset、admin repo_url 表单
- [x] 冲突解决:5 文件取 main 版本
- [x] 表格:无 ID 列、列顺序 产品线→类型→状态→同步间隔→操作
- [x] 类型中文、product 可读名(未知降级原始 key)
- [x] woocommerce 进枚举
- [x] 后端 create API id 可选(空时生成)
- [x] 所有测试绿 + admin build 绿
- [x] 不动生产数据(不 reindex)

## 不在本 plan

- reindex(用户单独授权后执行)
- product_mappings 表(评审 M3 否决,用前端常量)
- id 改 UUID(评审 H3 否决,保留语义 id)
- Issues/PR/Releases 索引(独立)
