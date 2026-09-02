# CAMTHINK V1 — Final Unified Integration + Merge-to-Main + Housekeeping 执行报告

- 日期:2026-09-02
- 模式:SINGLE CODEX(最终源集成门)
- 仓库:`harryhua-ai/ask-ai`
- 执行工作树:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/afp-closure-01`(集成构建)→ 主仓根(main,合并/报告)

---

## A. STATUS

**STATUS = PASS**(Executor 验证通过;不声明 Product FINAL ACCEPTANCE,等 Planner FINAL REVIEW)

## B. REPOSITORY BEFORE STATE

| 项 | 值 |
| --- | --- |
| 本地 main HEAD(改动前) | `cd12687`(= origin/main 76b2199 + 1 个本地 housekeeping 提交:.gitignore 加 /.worktrees/ 忽略规则) |
| origin/main | `76b2199ff334194a4e145c80ab844726d7e50293` |
| 候选线 tip | `worktree-exec/afp-closure-01` @ `1e93d8b` |
| merge-base(main, 候选) | `76b2199`(候选线完全包含 origin/main) |
| main 独有提交 | 仅 `cd12687`(.gitignore housekeeping,合并保留,非危险分歧) |
| 工作树(改前) | 11 个(见 §L) |
| 脏工作树 | 主仓根(`.gitignore` 本地改动:**删除** /.worktrees/ 忽略规则,与已提交意图 cd12687 相反 → `git stash` 保留可恢复,未丢弃);ask-ai-llm-provider(仅未跟踪 node_modules) |

## C. ACCEPTED LINEAGE PROOF(实证,非假设)

`git merge-base --is-ancestor` 对候选 `1e93d8b`:

| 提交 | 判定 |
| --- | --- |
| d9065df(已验收产品变更集成) | **ancestor ✓** |
| f32b3f4(多语言闭环实现) | **ancestor ✓** |
| eb3b899(AFP-CLOSURE-01 实现) | **ancestor ✓** |
| f874ee4(P1 Website Sync Stability / release 线) | **ancestor ✓**(= 已验收历史线被候选包含,无需重放) |

**3 个孤儿报告提交**(不在产品代码血统内,按 §5 干净并入,实质内容零改动):
`dff6e59`(多语言报告)、`257807d`(集成门报告)、`667815d`(重审triage 报告)。

## D. INTEGRATION METHOD

复用 `afp-closure-01` 工作树,自 `1e93d8b` 建 `integration/final-unified-2026-09-02`:
三次 `git merge --no-ff` 并入三个孤儿报告提交(a361083 / 3dbb70d / 4329ff0,**全部零冲突**——均为互不相交的报告文件)。产品代码零改动:`git diff eb3b899..4329ff0 --stat` = 仅 4 个报告文件 +571 行。

## E. FINAL PRODUCT CONTENT

候选 `4329ff0` 树内含全部验收内容:P1 sync 闭环(f874ee4 线)、三站契约(config/sites.yaml 三站 en + 接入契约 v2.0)、UX Closure B(canonical_url/social)、Sales Lead V1(lead_qualify/lead_service/sales_leads)、已验收集成(d9065df)、多语言闭环(f32b3f4)、AFP-CLOSURE-01(eb3b899)、16 份持久报告/契约文档(docs/implementation 15 + docs/integration 1)。

## F. MIGRATION INVENTORY(生产迁移清单;部署基线 = sha-3bf945b)

| # | 脚本 | 影响对象 | 幂等 | 分类 | 依赖/时机 |
| --- | --- | --- | --- | --- | --- |
| 1 | `scripts/migrate_channel_visibility.py` | Weaviate Document.channel_visibility 属性标记(不重嵌入) | 幂等(重复运行安全) | **REQUIRED** | 脚本已在部署源内但**生产从未执行**(P0 隔离对存量未生效)——公开/隔离保证前必须跑 |
| 2 | `scripts/migrate_sales_leads.py` | 建 `sales_leads` 表 | 幂等(存在即 skip) | **REQUIRED** | Sales Lead V1 激活前 |
| 3 | `scripts/migrate_conversations_session_id.py` | `conversations.session_id` 列 + 索引 | 幂等(存在即 skip) | **REQUIRED** | Lead 跨轮线索连续性前(与 #2 同批) |
| 4 | `scripts/migrate_site_experiences_i18n.py` | `site_experiences.welcome_i18n/starters_i18n` + YAML 回填 | 幂等(补列+只补 NULL) | **REQUIRED**(多语言站点文案激活;未跑时 language 参数安全回落默认文案) | 独立,任意时机 |
| 5 | `scripts/migrate_add_site_experiences.py`(+site_id) | site_experiences 表 + conversations.site_id | 幂等 | **ALREADY SUPERSEDED** | PA-0C 已于 2026-09-02 在生产执行(报告在档) |
| 6 | migrate_add_country / symbol_props / github_source_schema / intent_tag_8to4 / yaml_to_db | 历史列/结构 | 幂等 | **ALREADY SUPERSEDED** | 先于部署源引入;生产已运行 1ed84bb+ 镜像多轮 |
| 7 | `scripts/migrate_llm_chain_format.py` | llm provider 行配置格式(DB 数据) | 幂等 | **UNKNOWN→低风险** | 生产 llm 行存在且 DB 优先选型工作正常(PA-0C/D 冒烟),Production Gate 预检时复核即可 |

生产迁移一律未执行(本门只盘点);#1~#4 为下一 Production Gate 的执行清单(顺序无强依赖,建议 #2+#3 同批)。

## G. GOLDEN SCENARIOS(INT-FINAL-G001~G012)

| 门 | 证据 | 结果 |
| --- | --- | --- |
| G001 AFP-CLOSURE-01 可达 | eb3b899 ancestor ✓ + LoadError 在候选树 | PASS |
| G002 多语言闭环可达且行为保持 | f32b3f4 ancestor ✓ + ML 门 26 后端 + widget 语言测试全绿 | PASS |
| G003 已验收集成 d9065df 可达 | ancestor ✓ | PASS |
| G004 sync 稳定闭环行为在位 | f874ee4 ancestor ✓ + vector_consistency.py/sync.py + test_sync_lifecycle 15 用例绿 | PASS |
| G005 Sales Lead V1 在位 | 35a0870 在线 + leads/lead_flow 套件绿 | PASS |
| G006 三站契约在位 | sites.yaml 三站 en + site_routes 绿 + 接入契约文档在树 | PASS |
| G007 canonical Wiki 引用在位 | canonical_url.py + citation provenance 桥 + citation 套件绿 | PASS |
| G008 Admin 四态语义在位 | LoadError/NoPermission + AFP 黄金 13 用例绿 | PASS |
| G009 无未验收内容混入 | `git diff eb3b899..4329ff0` 仅 4 报告文件(+571 行,零代码) | PASS |
| G010 报告持久可达 | docs/implementation 15 份 + integration 契约 1 份全部在候选树 | PASS |
| G011 迁移清单完备 | §F(4 REQUIRED + 2 SUPERSEDED + 1 UNKNOWN 低风险) | PASS |
| G012 全量回归可接受 | §I(943+5 后端 / 185 admin / 68 widget / 双 tsc+双 build) | PASS |

## H. ACCEPTANCE CRITERIA

AC-01~AC-30 **全部 PASS**:实际盘点先行(§B)、无分歧覆盖(合并保留 cd12687)、血统实证(§C)、AC-04~11 各验收内容在位(§G)、报告持久(G010)、无未验收混入(G009)、迁移清单(F)、三端回归+迁移验证(§I)、G001~G012 全过、main 仅在门全过后更新、origin/main push 后核验一致(3261fef)、无 force push(76b2199..3261fef 正常推送)、合并后验证(main−候选 仅 .gitignore 一处=cd12687 已知项)、精确注册路径移除、无脏/未合并树被毁性删除(llm-provider/v1-integration-checkpoint 因活进程改判 KEEP;widget-handoff 因未验收 KEEP)、可达性证明后才删本地分支(远端全保留)、release 线保留、前后盘点在档(§L/§M)、零生产接触、零产品范围扩大。

## I. TEST COMMANDS + RESULTS(候选 4329ff0 上)

| 套件 | 结果 | 失败分类 |
| --- | --- | --- |
| 后端全量 `tests/`(隔离库 ask_ai_intgate) | **943 passed, 5 skipped** | 4 embedder 失败 = **BASELINE_EXISTING_FAILURE**(test_bge.py 文件内隔离缺陷,单跑通过;未动基线同样复现,已两次实证);3 errors = **TEST_ENVIRONMENT_FAILURE**(fixture 强制 ask_ai_test DSN,按其要求运行 4 passed) |
| Admin vitest 全量 | **185 passed(35 文件)** | — |
| Admin tsc -b --force / vite build | exit 0 / ✓ | — |
| Widget vitest 全量 | **68 passed(8 文件)** | — |
| Widget tsc --noEmit / vite build | OK / ✓ | — |
| `tests/scripts/test_migrate_llm_chain_format.py`(守卫要求的 ask_ai_test) | 4 passed | — |

## J. FAILURE CLASSIFICATION

见 §I:无 FINAL_INTEGRATION_REGRESSION。全部失败归类为 BASELINE_EXISTING_FAILURE(4)与 TEST_ENVIRONMENT_FAILURE(3),均有基线对照/守卫复跑证据。

## K. MAIN MERGE/PUSH EVIDENCE

- 合并(主仓根,干净树):`git merge --no-ff integration/final-unified-2026-09-02` → **3261fef**(merge commit,零冲突)
- 推送:`76b2199..3261fef main -> main`(正常推送,**无 force**)
- 远端核验:`git ls-remote origin main` = `3261fefba964f78a4250c9a0fea93cb95c474ee6` ✓
- 合并后验证:`git diff 4329ff0 main` = 仅 `.gitignore`(+5/-1,即 cd12687 已知 housekeeping 规则)→ main 树 = 已验证候选树 + 已知本地提交
- main 上金样冒烟:INT 组合门 11 + ML 门 26 + sync lifecycle 15 = **52 passed**
- MAIN_FINAL_COMMIT 随本报告推进至报告提交(§12 明示允许,报告为唯一后续变更)

## L. WORKTREE BEFORE INVENTORY(12 项)

| 路径 | 分支 | HEAD | 状态 | 处置 |
| --- | --- | --- | --- | --- |
| 主仓根 | main | cd12687 | .gitignore 本地改动(已 stash) | **KEEP**(main) |
| ask-ai-llm-provider | worktree-exec/admin-p1-llm-provider | 2dd9113 | 未跟踪 node_modules;**活 node/esbuild 进程** | **KEEP**(活会话;内容已全部补丁等价入 main) |
| .worktrees/accepted-integration | integration/…-accepted-product-changes | 257807d | clean(257807d 已并入) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/admin-retriage | discovery/admin-polish-retriage | 667815d | clean(已并入) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/afp-closure-01 | worktree-exec/afp-closure-01 | 1e93d8b | clean(1e93d8b 在候选线) | SAFE_TO_REMOVE → 移除(报告持久化到 main 后最后执行) |
| .worktrees/multi-site-widget | worktree-exec/multi-site-widget | 2d27dd8 | clean(2d27dd8 reachable) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/multilingual-closure | worktree-exec/multilingual-closure | dff6e59 | clean(已并入) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/product-ux-closure-b | worktree-exec/product-ux-closure-b | f89f5d7 | clean(cherry-pick 源,内容经验收 picks 入 main;远端保留原件) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/sales-lead | worktree-exec/sales-lead-capture | cb9d841 | clean(同上) | SAFE_TO_REMOVE → 已移除 |
| .worktrees/technical-insights | release/camthink-v1-rc-2026-09-01 | f874ee4 | clean | **KEEP**(release 血统检出) |
| .worktrees/v1-integration-checkpoint | integration/camthink-v1-checkpoint | e945f59 | clean;**活 node/esbuild 进程(用户测试栈)** | **KEEP**(BLOCKED:活会话) |
| .worktrees/widget-handoff | worktree-exec/widget-integration-handoff | eb112fa | clean | **KEEP**(BLOCKED_UNMERGED:v2.1 回填未验收) |

## M. WORKTREE AFTER INVENTORY(6 项)

| 路径 | 分支 | 理由 |
| --- | --- | --- |
| 主仓根 | **main @ 报告提交** | 权威基线 |
| ask-ai-llm-provider | worktree-exec/admin-p1-llm-provider | 活会话保留 |
| .worktrees/afp-closure-01 | integration/final-unified-2026-09-02 | 本门工作树(报告落 main 后按 §13 作为最后清理项移除) |
| .worktrees/technical-insights | release/camthink-v1-rc-2026-09-01 | release 血统 |
| .worktrees/v1-integration-checkpoint | integration/camthink-v1-checkpoint | 活会话保留 |
| .worktrees/widget-handoff | worktree-exec/widget-integration-handoff | 未验收工作保留 |

## N. BRANCH HOUSEKEEPING

- **删除的本地分支(12 个,均经可达性/补丁等价证明;远端副本全部保留)**:worktree-exec/{multi-site-widget, product-ux-closure-b, sales-lead-capture, multilingual-closure, afp-closure-01(末步), admin-final-polish, admin-p1-data-source-health, admin-p1-technical-insights, p0-trust-boundary, p1-citation-integrity, p1-reliability, p1-website-coverage, t1a-launch}、integration/{…accepted-product-changes, camthink-v1-p0-p1, camthink-v1-unified-2026-09-01, final-unified-2026-09-02(末步)},discovery/admin-polish-retriage-2026-09-02
- **保留**:main;release/camthink-v1-rc-2026-09-01;worktree-exec/widget-integration-handoff(未验收);worktree-exec/admin-p1-llm-provider、integration/camthink-v1-checkpoint-2026-09-01(活工作树检出)
- **远端分支**:一律未删(默认保留历史)
- 本地 stash:1 条(housekeeping-gate-20260902,与已提交意图相反的 .gitignore 改动,可恢复)

## O. PRODUCTION BOUNDARY

PRODUCTION_ACCESS = NO / PRODUCTION_MUTATION = NO / PRODUCTION_DB_MUTATION = NO / PUBLIC_TRAFFIC_CHANGE = NO(迁移仅盘点;测试库操作仅本地 ask_ai_intgate/ask_ai_test)

## P. RESIDUAL RISKS

1. embedder 4 个基线既有测试隔离缺陷仍未修(两次实证与基线无关;建议独立微任务)。
2. 生产迁移 #1~#4 未执行——Production Gate 唯一待办清单(本报告 §F 即输入)。
3. widget-handoff 的 eb112fa(v2.1 基址回填)仍未验收,分支/工作树保留待 Planner 裁决。
4. v1-integration-checkpoint 与 llm-provider 工作树内有活开发进程,本次保守保留;后续清理须先确认会话结束。
5. 主仓根 stash 1 条(相反意图的 .gitignore 改动)待用户确认后可 `git stash drop`。

## Q. NEXT GATE INPUTS(Final Release Artifact Gate)

- 权威源:main @ 3261fef(+报告提交)
- 生产迁移执行清单:§F #1~#4(幂等,脚本均在树)
- 镜像构建:CI push/手动触发(权威 amd64);生产升级 backend+sync-cron 同 sha 双服务
- 激活前置:channel_visibility 迁移(#1)必须先于公开/隔离保证;T4 GPU 显存饱和问题沿用既往记录
