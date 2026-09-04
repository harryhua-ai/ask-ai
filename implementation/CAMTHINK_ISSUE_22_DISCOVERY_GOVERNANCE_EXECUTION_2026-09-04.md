# Issue #22 — Source Center 统一发现治理 执行报告

- **日期**:2026-09-04
- **执行身份**:Engineering Executor(契约:ASK-AI v1.1 — Issue #22 Execution Contract,AUTHORIZED FOR ENGINEERING EXECUTION)
- **SoT**:docs/implementation/CAMTHINK_V1_1_SOURCE_CENTER_SHARED_DISCOVERY_2026-09-04.md(origin/docs/v11-shared-discovery-20260904 @ 20ac091,含 Planner Review REV 1;PD-1 APPROVED WITH MODIFICATION / PD-2/3/4 APPROVED)
- **STATUS**:CANDIDATE READY(Executor 不宣告 FINAL PASS,等 Planner 独立评审)

## 1. BASELINE_COMMIT / FINAL_COMMIT

```
BASELINE_COMMIT = ba904501bd171ed318c637ae07109174d65505ef(= v1.0.1 已验收工程 RC = 生产运行版)
WORKTREE        = .worktrees/v11-issue22-discovery-governance(专用单 worktree,未复用任何 v1.0.1 worktree)
BRANCH          = v1.1/issue22-discovery-governance
FINAL_COMMIT    = 2ba83d69fd4327889d3d1beaac3eacc2f806f66f(已推 origin,远端核验一致)
DIFF            = 13 files, +1511/−73
```

## 2. CHANGED_FILES(授权矩阵内核验)

| 文件 | 处置(契约 §20) | 内容 |
|---|---|---|
| `backend/services/source_discovery.py` | OWN | §9.3 聚合规则、rules 解析/匹配/继承、member_in_scope、annotate_scope、决策印章、wire 语义 |
| `backend/services/repo_discovery.py` | HUNK | compile 第二参、L1 producer 印章、接 rules、scope 确认 |
| `backend/services/website_discovery.py` | HUNK | 族群证据分类、规则排除并入编译、L1 印章预置、scope 确认 |
| `backend/api/admin/source_center_schemas.py` | HUNK | GroupOut += admin_decision/scope_confirmed/member_excluded;CandidateOut += decision_origin;reason 印章文案 |
| `backend/api/admin/data_sources.py` | HUNK | 两端点接规则只读查找(`_load_source_discovery_rules`) |
| `admin/src/components/dataSources/RepoDiscoveryPanel.tsx` | OWN | 组决策控件、治理徽章、applyRepoDecisions 纯函数 |
| `admin/src/pages/DataSources.tsx` | HUNK | discovery_rules 表单承载、双源决策 handler、网站分组行控件 |
| `admin/src/types/api.ts` / `admin/src/hooks/useDataSources.ts` | HUNK | wire 类型增量 |
| `tests/services/test_issue22_governance.py`(新)等 4 个测试文件 | OWN/HUNK | 验收矩阵 + 既有断言有意更新 |

**SCOPE_AUDIT**:`git diff --name-only ba90450` 全集 = 上表;grep 审计 `connectors/|scripts/sync|pipeline/|db/models|migration|source_lifecycle|source_deletion|sync_runs` → **零命中**(CLEAN)。连接器运行时、ingest、safety.py、sync 三表、lifecycle、#23 性能逻辑、生产配置/数据全部零触碰。

## 3. IMPLEMENTATION(与冻结契约逐一映射)

| 契约条款 | 实现 |
|---|---|
| §9.2 决策三层 | L1:producer 印章(`l1:binary`/`l1:exclude`,repo 侧 unsafe/二进制/无扩展名→确定性排除;web 侧 URL 排除清单+二进制后缀)——规则永不翻转 L1;L2:角色词表映射 + 规则继承 + 族群一致证据(印章 `rule:*`/`family:*`,frozen 文案);L3:兜底 review、平票、族群冲突(`family_conflict`)、尺寸/密钥类(PD-2 维持人工,未被自动化触碰) |
| §5(执行契约)unknown path ≠ include/review 理由 | `classify_url` 兜底 `(technical_doc, review)` 原样保留(REV1 修正);unknown path 只能经族群一致票 / 规则继承证据化改写;无证据 → review;冲突 → review + `family_conflict` 印章 |
| §9.3 分组聚合 | `summarize_candidates` 按冻结规则重写:混合组多数决(不再整组 review)、include==exclude 平票 → review、review-only → review;`member_excluded` 如实呈现少数派 |
| §9.4 discovery_rules | `data_sources.config` JSONB 新键;`parse_discovery_rules` 防御式解析(畸形跳过);github=首段目录前缀 / web=路径子串前缀,先匹配先胜;`apply_discovery_rules` 为双连接器共用 producer 级纯函数;规则是治理记忆,**不是第二摄取权威**——编译桥仍是唯一通道 |
| §9.5 wire 增量 | GroupOut += `admin_decision`/`scope_confirmed`/`member_excluded`;target += `inherited_rules`;CandidateOut += `decision_origin`;请求 schema、端点集合、错误语义零变化(旧前端可忽略) |
| §11 Apply 契约 | 采用推荐策略上送「基线编译 ⊕ 会话决策」;L3 未决组不被吞(不进白名单也不进排除,组级保持待确认);规则继承组的决策已随分类进编译(`.ts` 进白名单 / 规则排除目录进 exclude_dirs / web 规则排除进 exclude_patterns) |
| §12/§13 scope_confirmed | `member_in_scope(path, compiled_config, kind)` 按**连接器同视野**逐成员判定(github:扩展名∈file_types ∧ 目录∉exclude_dirs ∧ 不中 exclude_regex;web:不中排除清单 ∪ 用户 patterns ∧ 非二进制后缀);任一 include 成员出范围 → 组 `scope_confirmed=false` + preview 显式告警。「显示纳入却不进范围」成为不可通过测试的缺陷(测试锁定) |
| §14 Human Review | 评审以组为单位;面板提供纳入/排除/恢复推荐控件;决定写入 `discovery_rules`(§10 授权持久化),后续发现自动继承并带「已按策略」徽章,同一歧义不再反复询问(测试 W7/R8 锁定) |
| REV1 §2 族群证据 | `apply_family_evidence`(仅网站):投票源=规则成员+hint 命中成员(L1 不投票);全族一致→L2 继承;冲突→L3;无票→兜底 review |
| 兼容(§16) | 无 discovery_rules 的源零行为变化(测试锁定);既有 include/exclude 配置语义不变;零迁移、零新表、零新端点 |

**components 案件机理修正(实现期发现)**:v1.0.0 中 BINARY 角色(如 png)在路径层 `recommendation=review` 且部分技术不安全工件(.bin/.iso)也呈现 review——与 §9.1 冻结审计「unsafe → exclude」不符。producer 层 L1 印章(§9.2 冻结的 L1 清单:技术安全全部结论/二进制资产后缀/白名单不可能形态)落地为确定性排除;`KnowledgeRole` 13 值与 `RECOMMENDED_*_ROLES` 词表零改动(connectors/** 禁触碰纪律保持)。这是 components 组落「建议纳入」的直接机理。

## 4. REPOSITORY_ACCEPTANCE(tests/services/test_issue22_governance.py)

- **R1** 纯 include 组 → include ✅
- **R2** 纯 exclude 组 → exclude ✅
- **R3** 混合组(13 include + 1 L1 排除)→ include + member_excluded=1;少数派由编译白名单机械不进范围 ✅;**R3b** exclude 多数 → exclude ✅
- **R4** 平票组 → review;全 review 组 → review ✅
- **R5** components 案件(13×.tsx + preview.png)→ 组直呈「建议纳入」,member_excluded=1,scope_confirmed=true ✅
- **R6** 采用推荐策略 → `.tsx` 进 file_types、components 不进 exclude_dirs、逐成员 member_in_scope 全真 ✅
- **R7** L3 平票组不被静默吞:组级保持 review、目录不进排除;成员级安全决策保持强(逐项 include 进白名单,v1.0.0 同语义)✅
- **R8** 持久规则 → 二次发现继承:admin_decision=include/排除目录生效/inherited_rules=1;API 级端到端(端点按 repo_url 归一化匹配既有源,含 .git 差异归一)✅
- L1 压过规则:规则说 include、id_rsa unsafe → 仍 exclude,且规则不盖章 ✅
- compile 第二参:缺省 None 向后兼容逐位相等;组决策覆盖生效;unsafe 成员即使决策 include 也不进白名单 ✅

## 5. WEBSITE_ACCEPTANCE

- **W1** 确定性排除(/login、/cart)→ exclude + `l1:exclude` 印章 ✅
- **W2** hint 命中(/docs/quickstart)→ include ✅
- **W3** unknown path + 族群一致证据 → include(盖 `family:include`,hint 成员自身无印章)✅
- **W4** unknown path + 强无关证据(L1 清单命中)→ exclude ✅
- **W5** unknown path + 族群冲突票 → review + `family_conflict` 印章;组内规则决策不一致 → admin_decision 不呈现 ✅
- **W6** unknown path 本身永远不是 include/review 理由:无证据兜底 review(既有 `test_classify_url_unknown_is_review_not_silent_include` 保持绿)✅
- **W7** 持久决议:/blog/ 一次决定 → 二次 preview 组继承 include + 已按策略 + inherited_rules=1 ✅
- 规则排除并入编译 exclude_patterns(预览=同步视野)✅;scope_confirmed=true/None 分支锁定 ✅

## 6. POLICY_ACCEPTANCE

- **P1** `discovery_rules` 持久于 config JSONB(表单承载 + buildConfig 写回 github/web_crawl 分支;dsToForm 编辑回填)✅
- **P2** 既有源无此键 → 零行为变化(专用测试);既有 include/exclude 配置语义不变 ✅
- **P3** 零迁移(无新表/无新列;`git diff` 无 models.py/迁移脚本)✅
- **P4** 编译产物 = 真实生效策略(连接器消费语义实证:github `_should_include_path` 中 exclude_dirs 胜过白名单——排除组成员机械不进范围)✅
- **P5** 生效策略 UI 如实呈现:chips 即表单字段即 sync 唯一消费源;include 组 scope_confirmed 徽章 + 出范围显式告警 ✅
- **P6** 规则不绕过技术安全:L1 压过规则(unsafe→exclude 红线测试);compile 白名单仍要求 technical_safe(admin 决策 include 也不能白名单化 unsafe 成员)✅
- **P7** 摄取继续走既有 source policy 路径:连接器/sync/ingest 零 diff(scope 审计 CLEAN)✅

## 7. UI_ACCEPTANCE

- 三桶语义分明:建议纳入 / 建议排除·自动排除 / 待人工确认(仅 L3);待确认组就地提供「纳入/排除」,已决定组显示「已决定 + 恢复推荐」✅
- 「已按策略」徽章(规则继承组)+ 「已继承 N 条策略」提示 + 「无待确认组(推荐可直接采用)」合法终态文案 ✅
- include 组范围徽章:✓ 范围已确认 / ⚠ 范围未确认(机械判定,非 UI 推断)✅
- 网站分组行:同套控件 + 组决定实时写入高级选项排除清单(即生效采集策略)+ 保存后策略记忆生效 ✅
- 不暴露内部置信机制:印章只呈现为 frozen 人读文案与徽章 ✅
- 前端证据:`tsc -b && vite build` 绿;vitest **255/255**(含 5 个新 #22 决策合成/UI 交互用例;1 条旧文案断言按 §22.1 有意更新,注释注明理由)

## 8. REGRESSION_RESULTS

| 层 | 结果 |
|---|---|
| focused(services discovery ×4 + admin discovery) | 86 passed ✅ |
| 全量离线(`HF_HUB_OFFLINE=1` + 隔离 `TEST_DATABASE_URL`) | **1598 passed / 6 skipped / 0 failed**(41.7s;较 ba90450 基线 1568 净增 30 = 新增验收用例) |
| admin build | tsc -b + vite build 绿 ✅ |
| admin vitest | 255/255 ✅ |

既有测试变更(§22.1 有意更新,逐条注释理由):① `test_repo_discovery`/`test_data_sources_discovery` 各 1 处 target 严格相等断言加入 `inherited_rules` wire 字段;② `RepoDiscoveryPanel.test` 1 条旧「待确认项默认不纳入」文案断言替换为新冻结文案。零断言弱化;S0 冻结面(reason 枚举、FileAdmission 结构、URL_EXCLUDE 词表、Yoast/零发现/128 页确定性、`/store/` 对齐)全部保持绿。

## 9. KNOWN_LIMITATIONS / DEFERRED(与 Discovery §23 对齐)

1. 规则 GC/失配规则清理 UI 不在本轮(失配规则无害滞留,零副作用);
2. 会话内决策(创建流、尚未保存的新源)不参与服务端规则继承——保存后下一次发现即继承;编辑流决策保存即记忆;
3. 网站预览仍为 sitemap 结构证据,不做正文嗅探(能力注记如实声明;正文质量由 sync 期薄内容阈值兜底);
4. 分组 slice(0,10) 之外的完整翻页 UI 维持现状(文案已声明「其余同规则处理」);
5. `.example/.sample` 模板在本基线的路径层为 include 分类(S0 §5.4 的 review 带未在 discovery 层生效)——本报告如实记录为基线事实,未新增行为;若 Planner 认定应属 L3,建议另立小契约(PD-2 语境),本门未自行扩大。

## 10. PRODUCTION_MUTATIONS

**NONE**。本任务零生产接触:无生产 DB 写、无生产配置变更、无生产发现 apply、无 sync 触发、无部署。全部验证在本地隔离环境(离线全量 + 注入式 IO + 隔离测试库)。

## 11. 交付锚点

```
BRANCH        = v1.1/issue22-discovery-governance
FINAL_COMMIT  = 2ba83d69fd4327889d3d1beaac3eacc2f806f66f(origin 已核验)
REPORT_PATH   = docs/implementation/CAMTHINK_ISSUE_22_DISCOVERY_GOVERNANCE_EXECUTION_2026-09-04.md
REPORT_COMMIT = 见 docs 本地仓(本文件所在提交)
```
