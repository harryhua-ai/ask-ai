# Spec:GitHub 数据源统一 + API 增量感知

- **日期**:2026-08-04
- **状态**:spec(双路审核 2 轮收敛,用户确认决策 1A/2A/3A/4A;本文档同时作 brainstorm + spec,直接进 plan)
- **触发**:admin 测试发现"数据源同时有 github 和 local_git 两种类型"(用户提出)
- **关联**:`2026-07-27-ask-ai-design.md` §6(数据接入框架,Connector 类型表);`2026-08-04-intent-routing-design.md`(§1.2 source_type 实测 + §3.2.3 路由表,**尚未实现**)

---

## 1. 问题陈述(现状)

admin 数据源页同时显示 `github` 和 `local_git` 两种类型,DB 有 23 个数据源(10 github 全 disabled + 10 local_git 全 enabled + 3 filesystem,1 enabled)。用户困惑:配置数据源时该选哪个?

**根因**:历史迁移遗留。总体设计 §6 原是 `GitHubConnector`(REST API 逐文件拉),Phase 1.5 转为 `LocalGitConnector`(本地 git clone 读副本,更快无限制)。但迁移没清理:
- `github.py`(REST API 逐文件拉)代码保留 + 仍注册 "github" 类型
- DB 留下 10 个废弃 disabled github 配置(从 `migrate_yaml_to_db.py` 迁来时 `enabled` 从 YAML 继承=true,后被 local_git 取代、在 admin 手动禁用)
- `local_git` 作为独立用户类型暴露(但它只是 GitHub 仓库的实现方式)

**YAML 与 DB 的差异**:`config/data_sources.yaml` 里 10 个代码源全是 `type: "github"`(旧 schema,字段 `{owner, repo, branch, include_dirs, exclude_regex}`),enabled;但生产 sync 读 DB(`_load_configs_from_db`),DB 里这 10 个 github 被 disabled,另建了 10 个 `local_git` 源(schema `{repo_path, branches}`)实际在跑。YAML 仅作 seed/参考。

**客观事实**(用户澄清):所有数据最终来自 GitHub(git clone)。所谓"本地拉取"是从"已 clone 的本地副本"读 —— 副本本身也从 GitHub clone 来。没有"凭空的本地数据源"。

## 2. 用户视角的目标状态

**只有一种"GitHub 仓库"数据源类型**。用户配置时:
- GitHub 仓库地址(`repo_url`,完整 HTTPS URL,如 `https://github.com/camthink-ai/ne301.git`)
- 分支(可多选)
- 文件类型白名单
- (可选)本地 clone 路径(显示用,默认系统缓存到 corpus)

**底层实现用户不感知**:
- 系统自动 `git clone`(HTTPS + `GITHUB_TOKEN` 鉴权;首次 clone 失败 → 报错,不静默)到本地
- sync 用本地副本读文件(快、无 API 限制、完整)
- `local_git` 不作为独立用户类型(它是 GitHub 源的实现细节)

## 3. GitHub API 的正确增值位置(用户洞察)

当前 `github.py` 用 API 拉取文件:`fetch_all` 用 tree API 递归列举、`fetch_changes` 用 commits API 增量列举,再 base64 拉内容 —— 这是 API 的**劣势**(5000/h 限制、慢),且和本地 clone 重复。

**API 真正增值是"元数据/事件查询",不是文件拉取**:

### 3.1 增量感知(用户设计,核心 —— 同时修一个数据陈旧 bug)

> **现状核实**(Round 1 审核 CRITICAL 修正):`local_git.py` 全文**只有 `git checkout` + `git log --since`**,无 `git fetch` / `git pull`。意味着:**本地 clone 停留在首次 clone 时刻,远端 GitHub 的新 commit 永远进不来 → 已索引数据随时间陈旧**。这是一个真实的**数据陈旧 bug**,不是"无谓 fetch 成本"的优化问题。方案的核心价值是"补上缺失的 fetch",API SHA 感知是"智能触发 fetch"的手段(避免每仓库每次都 fetch)。

> **进一步核实**(Round 2 审核 N3):整个代码库**全无 `git clone`/`git fetch`/`git pull`/`git reset`**。`local_git.py` 也无 clone 逻辑(只 checkout+log,**假设 clone 已存在**)——corpus 是带外手动 clone 的。故新 GitHubConnector 的 **git clone + fetch + reset 都是全新实现**,非"复用 local_git 的 clone 逻辑"。这对工作量评估有直接影响(见 §6)。

```
sync 触发(cron)
  ↓
对每个 github 数据源,每个分支:
  GitHub API: GET /repos/{owner}/{repo}/commits/{branch}  ← 1 个轻量调用,拿远端最新 SHA
    (owner/repo 从 repo_url 解析)
  ↓
比对本地 HEAD SHA(git rev-parse)
  ├─ 相同 → 跳过该分支 git log(无更新,仅 1 个 API 调用)
  └─ 不同 → git fetch origin {branch} + git reset --hard origin/{branch}
            (更新 remote-tracking ref + 工作区到远端最新;clone 只读副本,reset 安全无本地改动)
            → git log --since 拿变更文件 → 索引
```

> **技术注**(Round 2 审核 N1):normal path 用 `git fetch + git reset --hard origin/{branch}`(而非 `git checkout`)—— `git fetch` 只更新 `origin/<branch>` remote-tracking ref,**不更新本地工作区/本地分支**;`git checkout <已存在分支>` 是 no-op(不 fast-forward)。只有 `reset --hard`(或 `git pull --ff-only`)才把远端新 commit 带入工作区,修 staleness bug。与 force-push 边界(§4.2)统一用 reset。

**解决什么**:
- **主**:补上 local_git 缺失的 `git fetch`(+ reset),修复数据陈旧 bug(远端更新进入索引)
- **辅**:用 API SHA 比对智能触发 fetch —— 无更新时 1 个轻量 API 调用即跳过(不付出 fetch 网络/IO),有更新才 fetch

**验收标准**(因现状修正而调整):
- ✅ 远端 GitHub 新 commit 能在下次 sync 后进入索引(**数据不再陈旧**;前提:sync 正常运行,sync_interval < sync.py 的 since=24h 窗口 —— 见已知局限)
- ✅ 无更新仓库不付出 git fetch 成本(API SHA 比对跳过)

**已知局限**:sync.py:176 `since = now - 24h`,若 sync 停摆 >24h,`git log --since=24h` 仍漏 24h 前的 commit(即使 fetch 成功)。spec 阶段可改用 `HEAD...origin/branch` 范围替代 `--since`,或保证 cron 间隔 <24h。

**速率限制评估**(细化):
- 认证 token(GITHUB_TOKEN,已配置):5000 req/h
- 10 仓库 × 平均 1.5 分支 × 每 sync = 15 调用/sync;按 sync_interval=1h → **15 调用/h ≪ 5000 req/h**(认证)✓
- 匿名场景(无 token):60/h,15 调用/sync 仍可,但生产用 token
- 多分支倍增:ne301 等多分支仓库放大调用数,但总量仍小

### 3.2 GitHub 独有数据(未来增强,可选)

API 能拉取 **git clone 没有的数据**(用户提问可能涉及):
- **Issues**(bug 报告/功能请求/常见问题)→ support 意图高价值
- **Pull Requests**(代码变更讨论/设计决策)→ support 意图中价值
- **Releases / Release Notes**(版本变更日志)→ product 意图高价值
- ~~Discussions~~(社区问答)→ 暂缓(camthink 仓库未启用 Discussions)

**当前 github.py 没拉这些** —— 只拉了文件(和 clone 重复)。这是 API 的未开发价值。

## 4. 设计方案

### 4.1 用户层:统一 `github` 类型

`SourceConfig.type = "github"`(唯一)。配置 schema(**与现状 github 字段不同,需迁移**):

```yaml
- id: "ne301"                    # 不含 "local" 字样(避免 local_git 概念残留)
  type: "github"
  product: "ne301"
  enabled: true
  config:
    repo_url: "https://github.com/camthink-ai/ne301.git"  # 完整 URL(旧 schema 是 owner+repo 分填)
    branches: ["main"]                                     # 复数(旧是单数 branch)
    file_types: [".py", ".c", ".h", ".md", ".rst"]
    clone_path: "~/ask-ai-corpus/ne301"                   # 可选,默认系统缓存
    # include_dirs / exclude_regex: 可选过滤(沿用现状,此处省略)
  sync_interval: "1h"
  channel_visibility: ["widget", "api"]
```

**字段迁移**(现状 github `{owner, repo, branch, include_dirs, exclude_regex}` → 新 `{repo_url, branches, clone_path, file_types}`):
- `owner` + `repo` → 合并为 `repo_url`(`https://github.com/{owner}/{repo}.git`)
- `branch`(单) → `branches`(复,支持多分支)
- `include_dirs` / `exclude_regex` → 保留为可选过滤(本 brainstorm 未改,沿用现状)

**移除 `local_git` 用户类型**(合并进 github 内部实现)。

### 4.2 实现层:GitHubConnector 重构

`github.py` 重构为(吸收 local_git 的 clone 逻辑 + API 增量感知):

```python
@ConnectorRegistry.register("github")
class GitHubConnector:
    """GitHub 仓库数据源。

    实现(均为全新代码,见 §3.1 N3 核实:代码库原无 git clone/fetch/reset):
    - 文件读取:遍历本地 clone 副本(原 local_git 的 checkout+遍历逻辑)
    - 增量感知:GitHub API 查最新 SHA,有更新才 git fetch+reset(修复 local_git 从不 fetch 的陈旧 bug)
    - 降级:API 故障 → 直接 git fetch(保底)
    - 可选增强:API 拉 Issues/PR/Releases(独立 RawDocument,未来)
    """

    def fetch_changes(self, since):
        for branch in self._branches:
            if self._remote_has_updates(branch):  # API 查 SHA(轻量)
                self._git_sync_branch(branch)       # fetch + reset --hard(重)— 修复陈旧 bug
                yield from self._read_local_changes(branch, since)  # git log --since
            # SHA 相同:跳过该分支(SHA 一致时 git log --since 也不执行)

    def _git_sync_branch(self, branch) -> None:
        """fetch + reset 工作区到远端最新(与 force-push 边界统一)。

        git fetch 只更 origin/<branch> ref;reset --hard 把工作区/本地分支指到远端。
        clone 只读副本(无本地改动),reset --hard 安全。
        """
        subprocess.run(["git", "fetch", "origin", branch], ...)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], ...)

    def _remote_has_updates(self, branch) -> bool:
        """GitHub API 查最新 SHA,比对本地 HEAD。API 故障时返回 True(降级,触发 fetch)。"""
        try:
            remote_sha = self._api_get_latest_sha(branch)  # 1 个 API 调用
            local_sha = self._git_local_sha(branch)
            return remote_sha != local_sha
        except Exception:
            logger.warning("API 感知失败,降级直接 fetch: %s", branch)
            return True  # 降级:触发 fetch(保底,不依赖 API)
```

**边界处置**(Round 1 审核补充):
- **force push / 历史 rewrite**:远端 SHA 本地无 → `_git_sync_branch` 的 `fetch + reset --hard origin/{branch}` 已覆盖(与 normal path 统一);记录 warning
- **本地工作区脏**:local_git.py:73 `git checkout` 会 `CalledProcessError`;新 connector 用 reset --hard 会覆盖本地改动 → sync 前确保 clone 只读(不本地 commit);脏时报错不静默
- **私有仓库**:用 `GITHUB_TOKEN` 走 HTTPS clone(`https://x-access-token:{token}@github.com/...`)
- **首次 clone 不存在**(clone_path 空):自动 `git clone` 到默认缓存路径(**全新代码**,代码库原无 git clone);失败(磁盘满/无权限/网络)报错,不降级到逐文件 API(见决策 4)
- **`local_git.py` 文件保留**(内部 checkout+遍历逻辑被 github.py 复用),但**移除 `@register("local_git")`**(不再作为用户类型)。注意 local_git **无 clone/fetch 逻辑**,这些是新 connector 全新实现

### 4.3 source_type 统一(迁移与 reindex 顺序)

当前已索引 580k chunk 的 `source_type = "local_git"`(Weaviate property)。重构后 connector 写 `source_type = "github"`。

**两条互斥路径**(Round 1 审核 HIGH 修正,二选一):

| 路径 | 做法 | 适用 |
|---|---|---|
| **A(推荐)** | merge 新 connector(写 `source_type="github"`)→ 跑 `sync.py --reindex`(删 collection 重建,新数据天然 github) | reindex 已是 P0#2 在跑,顺带统一,**免 Weaviate `update_many` 迁移**(DB `data_sources` schema 迁移两路径都要做,见 §6) |
| **B** | merge 新 connector + `update_many` 迁移脚本(UPDATE source_type property,不重索引) | 不想再 reindex 时 |

**路径 A 的顺序约束**:必须等 P0#2 当前 reindex 完成 → merge 本重构 → 再跑一次 `--reindex`(因为当前 reindex 跑的是旧 connector,写 local_git)。**不能并行**(reindex 删 collection,迁移脚本 update 会扑空)。

**路径 B 开销评估**(若选 B):580k 对象 `update_many`,需分批(每批 ~1000,约 580 批),经 SSH tunnel 到 mac Weaviate,预估 30-60min;期间查询受影响(Weaviate update 有锁)。**故推荐路径 A**(reindex 本就要跑,顺带统一零成本)。

**影响 P0#1 意图路由**(引用 `2026-08-04-intent-routing-design.md` §3.2.3,**尚未实现**):设计上路由表用 `source_type=["filesystem"]`(support 桶),不涉及 github;product 桶用 `chunk_type`(不涉及 source_type)。方向上无影响 ✓。**但 intent-routing spec §1.2 的实测数字(`local_git 579,688`)会在 source_type 统一后过时,需同步更新**。

## 5. 决策点(需用户确认)

### 5.1 决策 1:Issues/PR/Releases 增强是否纳入本次重构?

- **选项 A**(推荐):本次只做"统一类型 + API 增量感知",Issues/PR 留作后续独立增强(各自走 spec)
- **选项 B**:本次一起做(范围扩大,但 GitHub API 价值一次到位)

### 5.2 决策 2:source_type 统一方式

- **选项 A(推荐)**:merge 新 connector 后,顺下次 `--reindex` 自然统一(免迁移脚本;但需在 P0#2 当前 reindex 完成后,再跑一次 reindex)
- **选项 B**:merge 后跑 `update_many` 迁移脚本(不 reindex,但 580k 对象 30-60min + 查询影响)

### 5.3 决策 3:clone_path 策略

- **选项 A**(推荐):默认系统缓存到 `~/ask-ai-corpus/<repo-name>`(与现状一致),用户可覆盖
- **选项 B**:强制用户填(clone_path 必填)

### 5.4 决策 4:废弃 github.py(REST API 逐文件拉)的逻辑

- **选项 A**(推荐):移除逐文件拉取的**默认路径**(慢 + 与 clone 重复),github.py 改为"增量感知 + clone 管理"
- **选项 B**:保留逐文件拉取作为**显式降级**(clone 不可用时)

> Round 1 审核 MEDIUM 修正:决策 4 不能简单"clone 不可用 = clone 坏了应修"。clone 不可用还包括:首次 clone 失败(磁盘满,corpus 几 GB)、生产机无 GitHub 访问、clone_path 权限。**推荐 4A,但需在 spec 明确这些场景的处置**(报错告警 vs 降级到 API),而非默认假设 clone 总可修。

## 6. 影响范围(预估)

| 层 | 改动 | 风险 |
|---|---|---|
| `backend/connectors/github.py` | 重构:**全新实现** git clone + fetch + reset(代码库原无,见 §3.1 N3)+ API SHA 感知 + 边界处置;吸收 local_git 的 checkout+遍历 | **高**(全新 git 操作能力 + 核心 connector) |
| `backend/connectors/local_git.py` | 移除 `@register`(其 checkout+遍历逻辑被 github.py 复用;**无 clone/fetch 逻辑**需新写) | 中 |
| **admin UI**(`DataSources.tsx`) | **github 表单字段 schema 大变**:github 现状 `{owner, repo, branches, file_types}` → 新 `{repo_url, clone_path, branches, file_types}`;`SOURCE_TYPES` 移除 `local_git`(当前 `["github","filesystem","local_git"]` → `["github","filesystem"]`);`zod` formSchema + `types/api.ts` DataSourceType + `buildConfig`/`dsToForm` 适配。**woocommerce 不在本次**(P1#5 未 implement,admin 未注册) | 中(表单重构,admin 侧最大工作量) |
| DB data_sources | 10 个 local_git → type 改 "github" + config schema 迁移(repo_path→repo_url 等);删 10 个废弃 disabled github | 低(SQL 迁移) |
| config/data_sources.yaml | **github config schema 全量重写**(owner/repo/branch → repo_url/branches/clone_path),非仅"改 type"(YAML 本就是 github) | 低 |
| Weaviate | source_type property 统一 local_git → github(路径 A:顺下次 reindex;路径 B:update_many 迁移) | 中(路径 B 580k 对象 30-60min) |
| `intent-routing-design.md` §1.2 | 实测数字 `local_git 579,688` 过时,source_type 统一后改 `github 579,688` | 低 |
| 测试 | github/local_git connector 测试重组 | 中 |

## 7. 我的推荐(整合用户设计)

1. **范围**:统一 `github` 类型 + API 增量感知(修数据陈旧 bug)+ source_type 统一(决策 1A、2A、3A、4A + 边界处置)
2. **Issues/PR/Releases 增强**:记为独立 backlog(各自 spec,高价值但可单独做)
3. **时机**:P0#2 当前 reindex 完成 → merge 本重构(走 spec/plan)→ 再跑一次 `--reindex` 统一 source_type(决策 2A)
4. **流程**:brainstorm(本文档)→ 用户审 → spec → dual-review → plan → orchestrator worktree 实现
5. **DB 废弃配置清理**:可立即做(删 10 个 disabled github,不阻塞,减 admin 混淆)

## 8. 非目标(本次不做)

- GitHub Issues/PR/Releases 索引(独立增强,决策 1A)
- Discussions(camthink 仓库未启用)
- git clone 的并发/性能优化(现状够用)
- 非 GitHub 的 git 源(GitLab 等)—— 当前所有源都在 GitHub

---

## 待用户确认

- 决策 1-4 的选择(我推荐全 A)
- 是否现在清理 DB 废弃配置(10 个 disabled github)
- brainstorm 是否进 spec(通过则走 spec → plan 队列,reindex 完成后实施)

<!-- 以上为文档正文,以下为双路审核修复记录 -->

---

## 🔍 Dual Review Log

### Round 1 — 2026-08-04 · 双路并行

| # | 级别 | 来源 | 位置 | 问题 | 修复动作 |
|---|------|------|------|------|---------|
| 1 | CRITICAL | 内容 | §3.1 | 现状描述反了:local_git.py **无 git fetch/pull**(只 checkout + git log --since),是从不 fetch 的**数据陈久 bug**,非"无谓 fetch 成本" | §3.1 重写:主 agent 亲验属实(local_git.py:73/173/213 无 fetch);补"> 现状核实"段;方案价值改为"补 fetch 修 bug",API SHA 是智能触发手段;验收标准改"数据不再陈旧" |
| 2 | HIGH | 内容 | §6 admin 行 | (a) woocommerce 未实现(admin SOURCE_TYPES 无,后端未注册)却列;(b) 漏 github 表单字段 schema 大变(owner/repo → repo_url+clone_path) | §6 admin 行重写:删 woocommerce;补 github 表单 schema 变更 + zod/types/buildConfig 适配(标注 admin 最大工作量) |
| 3 | HIGH | 内容 | §6 YAML 行 | 非"改 type",YAML 本就 github;是 config schema 全量重写(owner/repo/branch → repo_url/branches/clone_path) | §6 YAML 行改"config schema 全量重写";§4.1 补字段迁移说明 |
| 4 | HIGH | 内容 | §4.3/§7 | source_type 迁移与 reindex(删 collection 重建)顺序未厘清,可能扑空/再脏 | §4.3 重写:两条互斥路径(A reindex 自然统一 / B update_many 迁移)+ 顺序约束 + 路径 B 开销评估;决策 2 改为方式选择 |
| 5 | MEDIUM | 内容 | §4.3 | 引用未实现的 P0#1 spec,误导 | 标注"引用 2026-08-04-intent-routing-design.md §3.2.3,**尚未实现**";§6 补"§1.2 实测数字会过时" |
| 6 | MEDIUM | 内容 | §3.1 | 速率评估粗糙(匿名 60/h、多分支倍增未提) | §3.1 速率细化:认证/匿名/多分支三档 |
| 7 | MEDIUM | 内容 | §4.2 | 边界不全(force push/脏工作区/私有/首次 clone) | §4.2 补"边界处置"段(reset/只读/token/首 clone 报错) |
| 8 | MEDIUM | 内容 | §4.3 | "快"对 580k 对象乐观 | §4.3 路径 B 改"分批 580 批 30-60min + 查询影响" |
| 9 | MEDIUM | 内容 | §5 决策4 | "clone 不可用=clone 坏了"理由狭隘(首 clone 失败/磁盘满/无 GitHub 访问) | 决策 4 补注:4A 但 spec 须明示这些场景处置 |
| 10 | MEDIUM | 结构 | L13/L129 | "§6"外部引用未注明出处,本文 §6 是影响范围 | 改"总体设计 §6";加"关联"元数据字段 |
| 11 | MEDIUM | 结构 | §3.1 vs §4.2 | 流程图"相同→跳过"vs 代码 yield from 在 if 外(SHA 一致仍执行),矛盾 | §4.2 代码 yield from 移入 if 块(SHA 一致跳过 git log);流程图与代码一致 |
| 12 | LOW | 内容 | §1 | DB disabled vs YAML enabled 来源未释 | §1 补"migrate_yaml_to_db 迁来设 disabled 被 local_git 取代"+ YAML/DB 差异段 |
| 13 | LOW | 内容 | §3 | fetch_all(tree)与 fetch_changes(commits)混为一谈 | §3 拆分两者描述 |
| 14 | LOW | 内容 | §4.2 | since 窗口短 + 仓库多日未 sync 会漏中间 commit | 留 spec 阶段(fetch 后改 HEAD...origin/branch 或说明窗口) |
| 15 | LOW | 结构 | §5 | 决策节"### 决策 N:"与 §3/§4 "### N.M"两套命名 | 统一为"### 5.N 决策 N" |
| 16 | LOW | 结构 | §4.1 | yaml id "ne301-local" 含 local 与主旨悖 | 改 "ne301" |
| 17 | LOW | 结构 | §2 vs §4.1 | owner/repo vs repo_url 格式不对齐 | §2 统一为 repo_url 完整 URL |
| 18 | LOW | 结构 | §4.2/§7 | Discussions 时有时无(§3.2 有,§4.2/§7 无) | §3.2 标注 Discussions 暂缓;全文统一 3 项(Issues/PR/Releases) |

**本轮修复**:18 个 | **累计修复**:18 个

---

### Round 2 — 2026-08-04 · 双路并行

| # | 级别 | 来源 | 位置 | 问题 | 修复动作 |
|---|------|------|------|------|---------|
| N1 | HIGH | 内容 | §3.1 流程图/§4.2 | normal path `git fetch + git checkout` 不更新工作区,staleness 修不了;与 force-push 边界(reset --hard)矛盾 | 主 agent 亲验属实;§3.1 流程图改 `git fetch + git reset --hard origin/{branch}` + 技术注;§4.2 `_git_fetch` 重命名 `_git_sync_branch`,补 fetch+reset 实现;边界 force-push 与 normal 统一 |
| N2 | MEDIUM | 内容 | §6 admin 行 | 现状字段误含 `repo_path`(属 local_git) | 亲验 admin github 实际字段 `{owner,repo,branches,file_types}`;§6 改正 |
| N3 | MEDIUM | 内容 | §4.2/§6 | "复用 local_git clone 逻辑"不成立(代码库全无 git clone) | 亲验 `grep -rn "git clone"` 全空;§3.1 加 N3 核实段;§4.2 docstring/边界标注全新实现;§6 github.py 风险上调高 + 标注全新 git 能力 |
| N4 | LOW | 内容 | §3.1 验收 | "数据不再陈旧"过强,未 reconcile 24h since 窗口 | §3.1 验收加"前提 sync_interval<24h"+ 补"已知局限"段(since 窗口) |
| N5 | LOW | 内容 | §1 | "migrate 脚本设 disabled"不实 | 亲验脚本 `enabled=prov.get("enabled",True)`;§1 改"YAML 继承 true,后手动 admin 禁用" |
| N6 | LOW | 内容 | §4.1 示例 | YAML 示例省略 include_dirs/exclude_regex 未标注 | §4.1 示例补注释"# 省略 include_dirs/exclude_regex" |
| N7 | LOW | 内容 | §3.1 速率 | "360/天 vs 5000/h"跨量纲 | 改"15 调用/h ≪ 5000 req/h" |
| N8 | LOW | 内容 | §4.3 路径A | "免迁移脚本"未限定范围 | 改"免 Weaviate update_many(DB schema 迁移两路径都要)" |
| R2-S1 | LOW | 结构 | 全文 | "陈久"vs"陈旧"不一致(4 处) | 正文统一"陈旧";日志保留原样 |
| R2-S2 | LOW | 结构 | §3.1 流程图 | {owner}/{repo} 未示从 repo_url 解析 | 流程图加"(owner/repo 从 repo_url 解析)" |
| R2-S3 | LOW | 结构 | §4.2 | `_git_fetch` 与流程图 fetch+checkout 粒度缝隙 | 随 N1 一并修(`_git_sync_branch` 含 fetch+reset 明示) |
| R2-S4 | LOW | 结构 | §6 admin 行 | 旧 schema 字段集不精确 | 随 N2 一并修(列 github 实际字段) |

**本轮修复**:12 个 | **累计修复**:30 个

---

### 汇总

- **收敛轮次**:2
- **累计修复**:30 个问题(CRITICAL: 1, HIGH: 4, MEDIUM: 10, LOW: 15)
- **审核模式**:双路并行(内容 + 结构)
- **内容视角**:Round 1 不通过 → Round 2 发现 N1 HIGH + 7 MEDIUM/LOW → 全修 → **收敛**
- **结构视角**:Round 1 不通过 → Round 2 **通过**(仅 LOW,已顺修)→ **收敛**
- **完成时间**:2026-08-04

> Round 2 两路均无残留 CRITICAL/HIGH;N1(核心机制技术错误)已修正(normal path 与 force-push 统一用 fetch + reset --hard)。结构仅 LOW 已清扫。按 dual-review 收敛规则,brainstorm 进入 spec 队列。spec 起草时注意:R2-S2/S3 的 owner/repo 解析与 fetch+reset 粒度已在 brainstorm 标注。
