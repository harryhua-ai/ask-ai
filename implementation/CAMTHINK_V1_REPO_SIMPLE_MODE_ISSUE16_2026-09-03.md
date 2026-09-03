# CamThink V1 — Issue #16 Code Repository Source Simple Mode 实现报告

- **日期**: 2026-09-03
- **执行角色**: Executor #1(PARALLEL;#17 Website Discovery / #18 Async Delete 由并行窗口承担,本任务零触碰)
- **基线**: `ce52af4`(S0 Source Center Shared Foundation 集成基线;S0 契约由 Planner PASS)
- **分支**: `worktree-exec/issue16-repo-simple-mode-20260903`
- **Worktree**: `.worktrees/issue16-repo-simple-mode`
- **状态**: **CANDIDATE_READY(待 Planner FINAL REVIEW)**

---

## 1. 任务与冻结契约

把代码仓库数据源配置从"用户手工维护 clone_path / file_types / excludes"升级为
V1 Simple Mode:**Repo URL → Discover → 推荐纳入/排除策略 Preview → 用户确认 → 保存/同步**。

八条冻结产品契约逐条落实情况:

| # | 契约 | 落实 |
|---|------|------|
| 1 | Simple Mode 默认只要 Repository URL | 发现请求 `GitHubDiscoveryRequest(S0)` 只有 repo_url + 可选 branch;branch 缺省由远端 default_branch 解析 |
| 2 | 自动发现推荐策略,不要求理解 file_types/excludes/clone_path | `POST /data-sources/discover-repo` + RepoDiscoveryPanel;clone_path 降级为只读提示行 |
| 3 | 复用 S0 Discovery + Technical Safety + FileAdmission + KnowledgeRole | 逐候选即 `FileAdmission`;envelope/聚合/文案 = `source_discovery.build_discovery_result`,零新合同 |
| 4 | secrets/credentials 属 Technical Safety,Admin allowlist 不可绕过 | 发现层 `check_path`→`secret_file` 即 unsafe;推荐产物永不纳入;`compile` 单测 + connector 语义等价单测锁定 |
| 5 | 同步前可见 include/exclude/review + reason/evidence | 面板三段分组直呈,reason 为后端冻结文案原文(前端零重判);告警/能力边界逐条可见 |
| 6 | Advanced Mode 保留 clone_path/file_types/excludes 等 | 高级选项 = Clone 路径 + 文件类型 + 排除目录 + 排除正则 + 最大文件大小 |
| 7 | Simple Mode 编译为现有 config/source policy,无第二套 authority | `recommended_config = {file_types, exclude_dirs}` 既有 JSONB 词表;保存走既有 POST/PATCH;同步零改动 |
| 8 | 不改同步语义,不做无关重构 | connectors/safety/exclusion/github 零改动;backend 变更仅新增 service 文件 + data_sources.py 一个端点 |

## 2. 关键设计决策(冻结)

1. **发现 = 保存前远程 tree scan(最低风险路径)**:GitHub trees API
   `recursive=1` 只读枚举——不 clone、不落盘、不触发同步、零配置写入。
   真实抓取仍由既有 connector clone 流程执行(issue "Discovery Required"
   三选一中的低风险选项)。树截断(`truncated`)/超量(>20000)显式告警,
   绝不把"没扫到"当"没内容"。
2. **发现层 = path+size 廉价层**:无内容,故内容层私钥嗅探(`check_content`)
   仍发生在同步灌入——发现层不替代也不放宽;该边界写入 capability_notes
   向管理员如实声明。
3. **编译规则(纯函数,单测锁定)**:
   - `file_types` = **technical_safe ∧ recommendation==include** 候选的扩展名
     (排序去重)。review(图片等 binary)/exclude/unsafe 类型一律不进白名单;
   - `exclude_dirs` = 与 envelope 同一 `summarize_candidates` 规则下分组推荐
     为 exclude 的**目录**组(根文件组除外)。connector 侧语义为"任意层级
     同名目录排除",tests/ 嵌套场景自然覆盖;
   - 编译产物与既有 connector 三层准入等价性有专项验收测试
     (`test_compiled_config_executes_via_existing_connector_semantics`)。
4. **前端只呈现不重判**:推荐/理由/能力边界全部为后端冻结产物;chips 仅做
   增删(与高级原始输入同源,表单唯一事实源);「采用推荐策略」把
   `recommended_config` 原样写入既有 config 字段。
5. **废除"全量后缀预填"**:旧"拉取分支"把仓库全部后缀塞进 file_types
   (检测到什么就纳入什么)——与 issue 方向直接冲突,已废除;后缀预览端点
   保留(API 兼容)。#16 测试断言 `fetchPreviewFileTypes` 不再被调用。
6. **事件循环纪律(504 事故防线)**:发现为同步 httpx,route 经
   `run_in_threadpool` 执行,绝不阻塞 backend 事件循环。
7. **并行安全**:S0 已把 API domain schemas 独立于 `schemas.py`
   (`source_center_schemas.py`);本任务复用之,backend 唯一既有文件改动是
   `data_sources.py` 追加一个端点(hunk 最小),与 #17/#18 冲突面最小化。

## 3. 交付物

### 后端(新增 2 文件 + 1 端点)
- `backend/services/repo_discovery.py`:producer + 编译器。`parse_repo_url` /
  `top_level_group`(根文件组 `(根目录)`)/ `admission_from_tree_entry` /
  `compile_recommended_config` / `discover_repository`(api_get 注入,离线可测)
  / `default_api_get`(GITHUB_TOKEN 可选,404/403/429 → 脱敏中文错误)。
- `backend/api/admin/data_sources.py`:`POST /data-sources/discover-repo`
  (editor+;S0 `GitHubDiscoveryRequest` / `DiscoveryResultOut` 原样 wire)。
- 测试:`tests/services/test_repo_discovery.py`(18)+ `tests/api/admin/test_data_sources_discovery.py`(5)。

### Admin(新增 1 组件 + 表单重构)
- `components/dataSources/RepoDiscoveryPanel.tsx`:预览面板(三段分组 + 冻结
  理由原文 + 技术安全计数 + 告警 + 能力边界可展开 + 推荐策略 chips + 采用按钮)
  与 `PolicyChips`(已采用策略可视化增删;空态不渲染)。
- `pages/DataSources.tsx`:github 表单 = 仓库 URL + 分支(拉取分支 + **扫描并
  推荐策略**双按钮)+ 发现面板 + 策略 chips;clone_path 降级为
  "本地缓存路径:自动管理(…高级选项可修改)"只读行;文件类型/排除目录/
  clone_path 移入高级选项(语义标签诚实化:"留空将不纳入任何文件"取代错误的
  "留空=全部")。
- `types/api.ts` + `hooks/useDataSources.ts`:`RepoDiscovery*` 类型(与
  DiscoveryResultOut 1:1)+ `fetchRepoDiscovery`。
- 测试:`tests/RepoDiscoveryPanel.test.tsx`(9)+ `DataSources.test.tsx` 重写
  1 例(预填废除)+ 新增 4 例(#16 Simple Mode 场景)。

## 4. 安全边界(非可绕过性论证)

- 推荐产物**构造性排除** secrets(unsafe → 永不进 include)、模型工件/超大
  (unsafe)、图片等(review → 不进白名单);单测逐类锁定;
- 即便管理员在 chips/高级选项手动增补 `.png`/`.key`,同步时既有
  `TechnicalSafetyPolicy.check_path` + `ExclusionPolicy.BINARY_EXT` +
  ingest 内容层嗅探仍然生效——**三层准入 `TECHNICALLY_SAFE ∧
  KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED` 的第 1 层不因 UI 而变**;
- UI 文案明示:"技术安全边界不因白名单放宽而失效"。

## 5. 测试与验证证据

| 项 | 结果 |
|----|------|
| 后端全量(隔离库 ask_ai_test,HF_HUB_OFFLINE=1,权重物理副本) | **1236 passed / 6 skipped / 0 failed**(基线 1213 + 新增 23,严格吻合) |
| admin vitest 全量 | **37 files / 203 passed / 0 failed**(基线 36 files 零丢失 + 新增 1 文件) |
| admin build(`tsc -b && vite build`) | PASS(仅既有 chunk 体积警告) |
| `git diff --check` | PASS |
| 模型 offline 加载预验 | bge-m3 + bge-reranker-v2-m3 自 worktree 物理副本加载 OK(HF_HUB_OFFLINE=1,零网络) |
| 真实仓库只读冒烟 | octocat/Hello-World:default branch 解析 master ✓;README 无扩展名 → include 推荐但**不进白名单** + 无扩展名 capability note(诚实边界实证) |

## 6. 环境引导(本 worktree 复现实操)

```bash
git worktree add .worktrees/issue16-repo-simple-mode \
  -b worktree-exec/issue16-repo-simple-mode-20260903 ce52af4
cp -c /path/main/.env .env                 # 物理复制(禁软链)
rm -rf models && cp -Rc /path/main/models models   # APFS clonefile 物理复制,禁 symlink
(cd widget && npm install); (cd admin && npm install)  # admin tsconfig 引用 ../widget/src
# 测试:
HF_HUB_OFFLINE=1 HF_HUB_CACHE=$PWD/models/hub PYTHONPATH=$PWD \
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test \
  /path/main/.venv/bin/python -m pytest -q
```

## 7. Known Limitations(诚实边界,非缺陷)

1. **发现层无内容证据**:私钥内容伪装(如 cert.pem 藏私钥)在发现层不可见
   (路径层仅给推荐排除),内容层由同步灌入时的 `check_content` 强制拦;
   capability_notes 已向管理员声明该分层。
2. **exclude_dirs 粒度 = 目录名(任意层级)**:既有 ExclusionPolicy 语义;
   嵌套混合目录(如 `docs/generated`)在分组为 review 时不会自动排除,需
   管理员在 chips/高级选项手动补充。UI 已给 review 默认不纳入提示。
3. **无扩展名文件**(LICENSE/Makefile)无法被扩展名白名单匹配,即使推荐
   include 也默认不纳入;capability_notes 明示。
4. **超大树截断**:>20000 候选截断 + 告警;`truncated=true` 同样告警;
   统计完整性以告警为准,不静默。
5. **私有仓库依赖 GITHUB_TOKEN**(环境变量,既有机制);匿名受速率限制,
   403/429 映射为可操作中文错误。
6. **已存在的 github 源 config 完全不迁移**:编辑旧源仍显示其原始
   file_types/exclude_dirs(chips 呈现),可用「扫描并推荐策略」重新生成——
   不因 UI 升级静默扩大任何既有源的 ingestion scope(验收 9)。

## 8. 边界遵守声明

- PRODUCTION_MUTATIONS: **NONE**(无部署、无生产配置/DB/Weaviate 触碰、
  无 sync 触发;发现端点只读远端 trees API)
- 未实现 #17 / #18;未放宽 Technical Safety;connectors 层零改动;
  W0/W2/W3 文件零触碰;无产品特定 hardcode(producer 全部数据驱动)。

## 9. 最终回复块

```
STATUS: CANDIDATE_READY(待 Planner FINAL REVIEW)
BASELINE: ce52af4(S0 Source Center 集成基线)
FINAL_COMMIT: 见分支 tip(worktree-exec/issue16-repo-simple-mode-20260903,已推 origin)
BRANCH: worktree-exec/issue16-repo-simple-mode-20260903
WORKTREE: .worktrees/issue16-repo-simple-mode
SIMPLE_MODE_FLOW: Repo URL(+可选分支)→ POST /data-sources/discover-repo
  (S0 trees-only 只读远程扫描,不 clone 不落盘)→ DiscoveryResultOut 预览
  (include/exclude/review 三段 + 冻结理由 + 告警 + 能力边界)→ 用户
  「采用推荐策略」(chips 可增删微调)→ 既有 POST/PATCH 保存既有 config 词表
  → 同步语义不变
SAFETY_BOUNDARY: secrets/工件/超大 = Layer1 unsafe 永不推荐纳入;图片等 =
  review 默认不纳入;手动增补仍被同步侧 TechnicalSafetyPolicy + ExclusionPolicy
  + 内容嗅探三层强制;发现层无内容证据的分层边界已向 UI 如实声明
TESTS: 后端 1236/6/0(全量,隔离库+离线);admin 37 files / 203 passed;
  新增后端 23 例 + admin 13 例
BUILD: admin tsc -b && vite build PASS;git diff --check PASS
REGRESSIONS: 零(基线 1213 严格吻合;既有 admin 测试仅 1 例按 issue 方向
  重写=全量后缀预填废除,其余全绿)
KNOWN_LIMITATIONS: 见 §7(六项,均为诚实边界非缺陷)
REPORT_PATH: docs/implementation/CAMTHINK_V1_REPO_SIMPLE_MODE_ISSUE16_2026-09-03.md
PRODUCTION_MUTATIONS: NONE
```
