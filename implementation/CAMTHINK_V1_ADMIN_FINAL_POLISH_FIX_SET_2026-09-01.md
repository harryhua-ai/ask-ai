# CAMTHINK V1 — Admin Final Polish Fix Set 执行报告

日期:2026-09-01
任务:CAMTHINK_V1_ADMIN_FINAL_POLISH_FIX_SET(P1 — V1 上线前)
BASELINE_COMMIT = 0dc0f43b8e77a1b5ee9083feac4a87eef878ee7b(WEB-01 候选;Planner 保留)
状态:**PASS(自评)——待 Planner 独立验收**

---

## 1. Executive Summary

按授权清单交付 6 项修复,未实现任何越权项(AFP-005/006/009/010/011 未动):

| 项 | 内容 | 结果 |
|----|------|------|
| AFP-001 | 删除数据源 ⇒ 独占知识退出检索(账本+向量+配置三清,失败可观察可重试) | ✓ |
| AFP-002 | viewer 不再被广告任何写控件;受限直达页显式无权限态 | ✓ |
| AFP-003 | 登录错误映射为中文文案,Pydantic 原文仅 console 留查 | ✓ |
| AFP-004 | 「总服务客户」→「服务对话数」(口径未动) | ✓ |
| AFP-007 | 移除「澄清漏斗(待接入)」占位面板 | ✓ |
| AFP-008 | 空结果语义:暂无数据 / 无匹配 区分;无权限态独立 | ✓ |

测试:后端删除生命周期 5/5 + 全仓 **704 passed**(4f/3e 为环境既有画像,与
基线一致,零回归);前端 **167 passed**(新增 FinalPolish 10 用例)+ tsc 干净 +
生产构建通过。浏览器验收 8 项全过(§8)。

**PRODUCTION_DEPLOYED = NO**

## 2. Baseline / Worktree / Branch

- BASELINE = 0dc0f43(WEB-01 候选;按合同要求保留其行为)
- WORKTREE = /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights(复用)
- BRANCH = worktree-exec/admin-final-polish(自 0dc0f43 切出)

## 3. Root Cause 与实现(逐项)

### AFP-001 数据源删除生命周期
- **根因**:旧 DELETE 仅删 `data_sources` 配置行;documents 账本行与 Weaviate
  向量原地留存且继续参与检索(P0 过滤按 channel_visibility,不感知源存活),
  且无界面可见——发现报告实锤(旧源 3,109 篇/57,912 chunks 孤儿)。
- **实现**(`data_sources.py`):DELETE 重排为
  ①枚举账本(source_id 前缀)→ ②`_purge_source_corpus_sync`(线程池):
  Weaviate 清理 = 账本 Equal 精确删(与 ingest.delete_document 同款安全模式,
  逐 source_id)+ 迭代器兜底收集前缀边界孤儿(`prefix+"/"`)逐 UUID 删 →
  ③同事务删账本行+配置行。
- **失败语义**:②失败 → HTTP 502 + 保留配置与账本(可重试,绝不假报成功);
  顺序保证「配置已消失 ⇒ 向量必已清」。
- **安全**:全程 Equal 精确匹配(Weaviate TEXT like 分词不可靠——一致性模块
  既有结论,本次浏览器验收再次实证);前缀边界 `prefix+"/"`,相似前缀
  (afp001-a vs afp001-ab)单测锁定互不波及。
- **幂等**:重复 DELETE 第二次 404;重建同名源再删同样干净(孤儿兜底验证)。

### AFP-002 viewer RBAC UI 真相
- 各页 `useAuth().user.role` → `canWrite = admin||editor`:
  - 数据源:隐藏 同步全部/新增数据源/同步/编辑/删除;
  - 模型配置:隐藏 供应商凭证/端点授权/应用变更/添加/链路编辑
    (ChainChip 新增 `editable` prop,viewer 隐藏编辑弹层与移出/排序);
  - 对话审查:隐藏 批量标注 Intent;答案覆盖:隐藏 新增覆盖/删除;
  - Users:非 admin 直达 → `<NoPermission/>`(显式「无访问权限」+联系管理员);
- 后端 RBAC 未动(仍权威 403);admin/editor 能力不变(既有测试+新增 G010 用例)。

### AFP-003 / AFP-004 / AFP-007 / AFP-008
- Login.tsx 新增 `formatLoginError`(导出):Pydantic 邮箱校验 →
  「邮箱格式不正确,请检查后重试」;后端中文(邮箱或密码错误)保留;其余 →
  「登录失败,请稍后再试」;原始 detail 仅 console.warn 留查(可观测性不丢)。
- BusinessOverview.tsx:label 总服务客户 → 服务对话数(计数逻辑零改动)。
- Analytics.tsx:删除澄清漏斗占位面板(知识缺口 tab 其余不动)。
- Conversations.tsx:空列表区分 `data.total===0` → 「暂无对话数据…」vs
  有筛选无匹配 → 「无匹配对话…请调整条件」(data-empty-state)。

## 4. Changed Files

- 后端:`backend/api/admin/data_sources.py`(purge 函数 + DELETE 重排;
  +Document/weaviate/Filter/run_in_threadpool/logging 导入)
- 前端:NoPermission.tsx(新);ChainChip.tsx(editable);DataSources.tsx /
  LLMProviders.tsx / Conversations.tsx / AnswerOverrides.tsx(角色门控);
  Users.tsx(角色守卫);Login.tsx(文案映射);BusinessOverview.tsx(改名);
  Analytics.tsx(移除占位)
- 测试:tests/api/admin/test_data_source_delete.py(新,5);admin/tests/
  FinalPolish.test.tsx(新,10);BusinessOverview/TechInsight 断言更新;
  ConversationsReview/LLMProviders/DataSources 测试补 useAuth mock
- 脚本:无新增(浏览器验收脚本为临时件,证据入库)

## 5. AFP-G001..G011 对照

| Golden | 结果 | 证据 |
|--------|------|------|
| G001 删除后源消失 | ✓ | 单测 delete_source_purges;真实 API delete=204 + source row=0 |
| G002 账本清理 | ✓ | 同单测 + 真实删除后 A docs=0 |
| G003 向量清理 | ✓ | 真实删除后 A chunks=0(Get 精查;§8 注) |
| G004 检索不可返回 | ✓ | 该前缀向量清零 ⇒ 无可召回对象 |
| G005 他源不波及 | ✓ | 单测(afp001-b 配置+账本幸存)+ 真实(afp001-acceptance-b chunk 幸存)+ 前缀边界单测 |
| G006 失败可观察 | ✓ | 单测:purge 抛错 → 502,配置/账本原样 |
| G007 重复删除安全 | ✓ | 单测:二次 404;真实:重建同名源再删同样干净(孤儿兜底) |
| G008 viewer 无写控件 | ✓ | FinalPolish 5 用例 + 浏览器 b5 |
| G009 受限直达显式无权限 | ✓ | FinalPolish + 浏览器 b6 |
| G010 admin/editor 能力保留 | ✓ | FinalPolish admin 两用例 + 全量前端/后端回归绿 |
| G011 后端仍 403 | ✓ | 后端 RBAC 代码未动;admin API 全量回归绿 |

## 6. TDD 证据

- 后端 RED:5 用例首跑 2 failed + 3 errors(purge 不存在/端点未清理);
  GREEN:实现后 5/5;
- 前端 RED→GREEN:FinalPolish 首跑 2 failed(答案覆盖/用户 mock 形状)→
  修正 mock 后 10/10;既有 3 个测试文件补 useAuth mock,2 处断言按新契约更新
  (澄清漏斗→断言不存在;总服务客户→服务对话数)。

## 7. Tests / Typecheck / Build

- 后端:删除生命周期 5/5;全仓(HF_HUB_OFFLINE=1,隔离库 ask_ai_polish)
  **704 passed / 4 failed / 3 errors / 5 skipped(59.5s)** —— 4f=embedder HF
  离线缓存竞态、3e=迁移测试 DSN 护栏,与基线运行完全一致(环境既有,
  WEB-01 报告已有主仓对照),零回归;
- 前端:vitest **167 passed(33 files)**;`tsc -b` 0 错误;`npm run build` ✓。

## 8. Browser Acceptance(隔离环境 8024/5177,真实数据)

| # | 项 | 结果 |
|---|----|------|
| 1 | viewer-数据源无写控件 | ✓ b5 截图 |
| 2 | admin-数据源写控件齐全 | ✓(走查 05 + 回归) |
| 3 | 数据源删除(隔离一次性源 afp001-acceptance) | ✓ b4:行消失;PG docs 2→0;向量清零;无关源 b 幸存 |
| 4 | viewer 直达 /users → 无权限态 | ✓ b6 |
| 5 | 空搜索/结果语义 | ✓ FinalPolish 用例 + 走查 10 |
| 6 | 登录非法输入 → 中文友好文案,无原文泄露 | ✓ b1 |
| 7 | 业务概览「服务对话数」 | ✓ b2(旧标签不存在) |
| 8 | 技术洞察澄清漏斗移除 | ✓ b3(知识缺口其余保留) |

删除生命周期实测数字:隔离源删除前 A=5 chunks(B=1)→ 删除后 A=0、B=1、
PG A docs=0、配置行=0;且经历「删除→重建同名源→再删除」两轮,清理幂等。
**验证方法学说明**:聚合 Like 校验查询自身受 TEXT 分词影响会把
afp001-acceptance-b 误计入 A(正是一致性模块既有结论),最终以 Get 精确查询
复核(仅剩 b1 对象)——该坑已写入报告防止复蹈。

截图/JSON:b1-b6 + acceptance-notes.json(docs 仓
`implementation/evidence/admin-final-polish-fix-20260901/`)。

## 9. Regression Evidence

- 全仓后端 704 passed(零新增失败);admin API 全量绿;
- 前端 167 passed(Technical Insights/DSH/LLM Providers/对话审查等全部既有
  契约测试通过);
- P0 信任边界/Citation/Generation Reliability:相关测试随全仓套绿;
- WEB-01 行为(sync 覆盖记账/自愈)未触碰 —— scripts/sync.py 本次零改动,
  其测试(test_sync_coverage/test_sync_gap_heal)全绿;
- Multi-Site Widget:widget/ 零改动。

## 10. Residual Risks / NOT_VERIFIED

- 大体量源(十万级 chunk)删除的耗时:Equal 逐 sid + 迭代器全扫为 O(库),
  实测隔离源秒级;超大源在 HTTP 同步等待内可能超时,残留可重试收敛
  (FOLLOW-UP:可改后台任务+进度轮询);
- 后端宕机时删除请求 → 502 可观察(路径已测),但前端未加专用重试引导;
- editor 角色页面差异未走查(仅 admin/viewer 两端);
- Safari/Firefox 未验证(仅 Chromium);
- 批准范围外维持现状:AFP-005/006/009/010/011。

## 11. Production Status

未部署生产;未触碰 T4/生产库/共享配置;Weaviate 仅插入/删除**一次性隔离
前缀**(afp001-acceptance*)的验收对象,真实源(ne101/website)零触碰。

**PRODUCTION_DEPLOYED = NO**

## 12. Final Commit

- FINAL_COMMIT = 6b9f9c438bad85a9829b09d37022365712cbf8e3
- BRANCH = worktree-exec/admin-final-polish(已推 origin)
- REPORT_PATH = docs/implementation/CAMTHINK_V1_ADMIN_FINAL_POLISH_FIX_SET_2026-09-01.md
- REPORT_COMMIT = 见 docs 仓提交记录

Executor PASS 不构成 Final Acceptance,Planner 独立验收为准。

---

## 13. Acceptance Cleanup 附记(2026-09-01,Planner FINAL REVIEW = PARTIAL 后)

按验收清理指令完成三项,历史证据(§1-§12)未改写:

### AC-FIX-01 literal 前缀所有权
- **原始缺陷**:DELETE 路径账本枚举/清理使用 `Document.source_id.like(f"{source_id}/%")`,
  而源 ID 允许含 `%`/`_` —— 通配符越界可吸走他源账本与向量(违反合同
  「不得删除另一个源的知识」)。
- **修复**:`startswith(f"{source_id}/", autoescape=True)`(SQLAlchemy 自动
  转义 %/_ 与转义符,ID 视为字面标识符;前缀边界与可索引性不变)。
  两处:账本枚举 + documents 清理;向量段本为 Equal 精确匹配,未动。
- **回归测试**(`test_data_source_delete_wildcards.py`,3 组全绿):
  1. 前缀重叠 source-a vs source-ab;
  2. 下划线 afp_src_a vs afpXsrcXa(未修复时 purge 账本吸入他源文档,RED 实证);
  3. 百分号 afp%pct vs afp-x-pct(同上 RED 实证)。
  每组断言:删 A → A 配置/账本/向量清零;B 配置/文档原样;purge 账本
  精确等于 A 自己的文档清单。
- 测试辅助 _doc_count 同步改字面语义(测试自身也曾犯同款 LIKE 毛病,
  修复前后差异正是缺陷实证)。

### AC-FIX-02 仓库卫生
- `admin/node_modules`、`widget/node_modules`(worktree 依赖复用软链,
  mode 120000 symlink)已移出 git 跟踪;
- 根因:原 .gitignore 规则 `node_modules/`(带斜杠)只匹配目录,不匹配
  symlink 文件 → 已追加显式条目 `admin/node_modules`、`widget/node_modules`;
- 本地依赖复用软链保留在文件系统,仅不可再提交。

### AC-FIX-03 交付元数据
- 原始实现提交:6b9f9c438bad85a9829b09d37022365712cbf8e3
- 验收清理提交:262c1fc(仅 data_sources.py + .gitignore + 新回归测试)
- **清理后 FINAL_COMMIT**:见下(HEAD of worktree-exec/admin-final-polish)
- REPORT_COMMIT:本文件所在 docs 提交(见提交记录)

### 清理验证
- 删除生命周期测试:8/8(原 5 + 通配符 3);
- admin 后端全量:156 passed;FinalPolish 前端:10 passed;
- `git diff 0dc0f43...HEAD --name-only`:20 个文件,0 个 node_modules,
  无授权范围外内容;`git ls-tree -r HEAD | grep -c node_modules` = 0;
- worktree 工作区干净(node_modules 软链为 gitignore 防护下的本地复用件)。
