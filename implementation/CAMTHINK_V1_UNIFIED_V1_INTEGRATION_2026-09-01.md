# CAMTHINK V1 — Unified V1 Integration Gate 执行报告

- 任务:CAMTHINK V1 UNIFIED V1 INTEGRATION(INTEGRATION + COMBINATION VERIFICATION)
- 日期:2026-09-01
- Executor:Engineering Executor / Integration Engineer(ZCode)
- 报告仓:docs 本地仓(分支 main)
- 执行仓:主仓 ask-ai,worktree `.worktrees/technical-insights`

---

## 1. Executive Result

**Executor 自评:PASS。**(Executor PASS ≠ Planner Final Acceptance)

两条已验收产品线(主产品线 262c1fc、Multi-Site 线 2d27dd8)经一次真实 merge 组合为
Unified V1 候选,merge 零冲突(唯一重叠文件 .gitignore 双方规则自动并集保留)。
组合验证全绿:

- 新增 5 个 INT-V1 组合门用例全过(G001/G002/G003/G004/G008),其余 5 门引用既有专项测试;
- 迁移/Schema 兼容:旧库升级路径模拟 + 幂等 + NULL site_id 保留全过;
- 全量回归:后端 763 passed(4 失败为主仓对照复现的环境性 HF-cache 类)/ admin 167 passed + tsc + build / widget 57 passed + tsc + build;
- 运行时冒烟:隔离后端站点门禁 curl 矩阵全过,Admin 五页面真实浏览器渲染全过,
  Widget 三路径(legacy / 已知站体验生效 / 未知站 fail-safe)真实浏览器全过。

本门产出的是**统一开发基线(unified development baseline)**,不是 Release Candidate,
不是生产部署。

## 2. Inputs / Accepted Commits

| 输入 | Commit | 内容 |
| --- | --- | --- |
| BASE_INTEGRATION_COMMIT | `e945f59cb7aa2aaed432bebd4cb42328caa115af` | P0 信任边界/生成可靠性/引用完整性/LLM 供应商/空 key 追加/数据源健康/checkpoint 契约 |
| CURRENT_PRIMARY_HEAD | `262c1fc859ad3203337f77eb5b5c60e40d66929c` | 技术洞察 + API-keyless 回归保护(692a862/1003504)+ WEB-01 覆盖/一致性 + Admin Final Polish + AC 清理 |
| MULTI_SITE_FINAL | `2d27dd8925bb9d9f1f5c8e2ffd85184c2e2a3f63` | Multi-Site Widget(MSW T1–T7b + 验收清理)9 提交 |

merge-base(262c1fc, 2d27dd8) = e945f59,与合同拓扑图完全一致。

## 3. Worktree / Branch

- Worktree:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights`(复用,未新建)
- 起始 HEAD 核验 = 262c1fc(branch worktree-exec/admin-final-polish,与 origin 一致,树干净)
- 集成分支:`integration/camthink-v1-unified-2026-09-01`(自 262c1fc 创建,已推 origin)
- venv 复用主仓 `/Users/harryhua/Documents/GitHub/ask-ai/.venv`;`PYTHONPATH=$PWD` 下
  `python -c "import backend"` 解析到 worktree 内 `.../technical-insights/backend/__init__.py` ✓
- models 软链复用,未重下模型;main 分支未改动。

## 4. Git Composition Method

`git merge --no-ff 2d27dd8`(单 merge commit **9fffa0e**,双亲 262c1fc + 2d27dd8,
两条验收谱系均可审计,无 squash、无改写)。随后提交门用例 **ec76beb**(仅新增 2 个测试文件)。

## 5. Conflict Analysis

两线 25+38 个变更文件中**唯一重叠 = `.gitignore`**,git 自动合并成功;
人工核验合并结果同时含主产品线规则(`node_modules/` + AC-FIX-02 三行,
L13–16)与 Multi-Site 规则(`.playwright-cli/`,L36)。语义冲突:**0**;
需要产品裁决的分歧:**0**(CONFLICT_COUNT = 0)。

## 6. Final Commit Graph

```
e945f59 (BASE_INTEGRATION_COMMIT)
   ├──────────────────────────────┐
   ▼                              ▼
262c1fc (主产品线)          2d27dd8 (Multi-Site)
6b9f9c4 Admin Polish        441f22d/824bcaf/4e6c650/7eebe66
0dc0f43 WEB-01              f90742a/a6fea20/2fd4247/877a953
024e55b 技术洞察            2d27dd8 验收清理
692a862/1003504 API-keyless
   │                              │
   └──────────────┬───────────────┘
                  ▼
        9fffa0e merge(INT-V1 门,零冲突)
                  ▼
        ec76beb test: INT-V1 组合门用例  ← FINAL_COMMIT
```

- 分支已推送:`origin/integration/camthink-v1-unified-2026-09-01`(9fffa0e..ec76beb)
- worktree 干净,与 origin 同步。

## 7. INT-V1-001..010 结果

| # | 契约 | 结果 | 依据 |
| --- | --- | --- | --- |
| 001 | 信任边界 × Multi-Site | PASS | site_id/Origin/page_context 不进入授权链(routes.py 注释+实现:resolve_site 仅裁门禁;channel 恒 widget;P0 guard 独立)。G001 用例证明站点上下文在场时内部/幽灵源仍被拦 |
| 002 | 引用 × Page Context | PASS | page_hint 仅追加 user 消息非信任标签段;boost 软加分不增删候选;G002 用例证明引用编号仍只映射可见公开源,页面背景不是引用成员 |
| 003 | 可靠性 × Multi-Site 流式 | PASS | G003 用例:已授权站点 + 零内容生成 → sources→兜底token→error(empty_generation)→done;is_answered=False;Trace=generation_error;site_id 如实落库 |
| 004 | 网站覆盖 × 删除生命周期 | PASS | G008 用例:删除后配置行即同步宇宙权威,WEB-01 校验/自愈路径无法触及已删源;伴随源完好 |
| 005 | Multi-Site Schema × Admin | PASS | site_experiences 表 + Conversation.site_id(nullable)共存;G004 用例:NULL legacy 行与站点行同窗可见、技术洞察出数 |
| 006 | 站点身份/Origin 安全 | PASS | resolve_site:enabled + Origin 归一化精确命中;未知/禁用/无 Origin/不匹配 → SiteDenied → 403 统一文案防枚举;无通配信任 |
| 007 | Legacy Widget 兼容 | PASS | 无 site_id → resolve_site 直接返回 None 不校验;G010:后端 legacy 用例 + widget legacy 冒烟(0 次 site-config 请求,默认体验) |
| 008 | Admin Final Polish 回归 | PASS | FinalPolish 10 用例全过;冒烟中 viewer 无误导写控件语义未被 Multi-Site 触碰(admin/ 与 MSW 零文件交集) |
| 009 | 仓库卫生 | PASS | `git ls-files` 0 条 node_modules/.playwright-cli/.db/.env;diff 审计 = 两分支精确并集 + 2 个授权新增测试文件 |
| 010 | 能力无损 | PASS | 见 §15 清单;10 族能力全部在场且各有活跃测试 |

## 8. INT-V1-G001..010 证据

**新增组合用例**(commit ec76beb;全 mock,零 Weaviate;`tests/api/test_unified_v1_gate.py`
与 `tests/api/admin/test_unified_v1_admin_gate.py`,5 用例全绿):

| 门 | 用例 | 断言要点 |
| --- | --- | --- |
| G001 | `test_int_v1_g001_site_context_cannot_unlock_internal_sources` | site_id 已授权 + page_context 在场:restricted/ghost 候选仍被拦;内部值(ICCID/价格)不进生成上下文也不外发 token;可见 sources 仅公开源 |
| G002 | `test_int_v1_g002_page_context_hints_but_never_cites` | 引用编号仍只映射可见公开源(sources[0].url == 公开源);页面 URL/标题非引用成员;背景段仅进 user 消息且 system 消息零污染 |
| G003 | `test_int_v1_g003_authorized_site_zero_generation_fails_explicitly` | 事件序列 sources→token(兜底)→error(empty_generation)→done;site_name/page_context 贯通 rag;conv.site_id 落值 + is_answered=False + Trace=generation_error |
| G004 | `test_int_v1_g004_legacy_null_site_rows_survive_in_admin` | NULL site_id legacy 对话与站点对话在 /admin/conversations 同窗可见;Tech KPI(trace_total)正常出数 |
| G008 | `test_int_v1_g008_deleted_source_not_resurrected_by_sync` | DELETE 204 后:同步宇宙(配置表)不含被删源;幸存源 `_sync_one` 照常;被删源配置/账本/SyncLog 三者保持不存在 |

**引用既有测试**(不重复建设,契约 §6):

| 门 | 既有证据 |
| --- | --- |
| G002(辅) | `tests/pipeline/test_rag_page_context.py`(背景段仅限 user 区/站点上下文不改检索渠道)+ `test_page_context_boost.py`(软加分不增删候选) |
| G005 | `tests/api/test_site_routes.py::test_ask_authorized_site_persists_site_id_and_threads_context`、`::test_site_config_returns_experience_for_authorized_origin`;冒烟:curl Origin=store → 200 + 体验字段 |
| G006 | `::test_ask_spoofed_origin_denied_403_and_no_side_effects`(rag 未调用、对话不落库)、`::test_site_config_mismatched_origin_denied`;冒烟 curl 403 |
| G007 | `::test_ask_unknown_site_denied_403`、`::test_ask_site_without_origin_denied_403`、`::test_ask_disabled_site_denied_403`、`::test_site_config_unknown_site_denied`、`::test_site_config_missing_origin_denied`;冒烟 curl 403 ×2 |
| G009 | `admin/tests/FinalPolish.test.tsx`(10 用例)+ `tests/api/admin/test_analytics.py::test_viewer_can_read`/`::test_viewer_cannot_refresh` + 删除生命周期 8 用例 |
| G010 | `tests/api/test_site_routes.py::test_ask_legacy_without_site_id_skips_site_validation`(session.get 未被调用,site_id NULL)+ widget `bootstrapSite.test.ts`(4)/`useSSE.payload.test.ts`(5);冒烟:legacy.html 0 次 site-config 请求 |

## 9. Migration / Schema Compatibility

机制 = 仓库既有惯例(startup `init_db` create_all + 专用迁移脚本),未发明新迁移系统。

模拟真实升级路径(隔离库 ask_ai_mig,先造**旧 schema**:conversations 已存在、含 1 行存量数据、无 site_id 列):

- RUN1:`scripts/migrate_add_site_experiences.py` → `ADD COLUMN IF NOT EXISTS site_id` 成功;
  **存量行保留且 site_id = NULL**;site_experiences 建表 + YAML 3 站点(website/wiki/store)upsert;
- RUN2:重复执行 → 无错误、结果不变(**幂等** ✓);
- lifespan seed 路径:冒烟用全新空库启动,应用启动即自动建表 + seed 3 站点(后端日志「站点体验配置已同步(3 个站点)」)✓;
- Conversation.site_id NULL 合法性:G004 用例 + 升级模拟双重证明 ✓;
- 既有 Admin 查询在含 NULL site_id 数据上全部工作(全量回归 + G004)✓;
- 未触碰生产库/共享库(全部隔离库,用后 DROP)。

## 10. Backend Regression

- 环境:worktree + 主仓 venv,`HF_HUB_OFFLINE=1`,隔离测试库(全新重建 ask_ai_test),
  `TEST_DATABASE_URL` 指向该库。
- 结果:**763 passed / 5 skipped / 4 failed**(58.7s)。
- 4 个失败全部为 `tests/embedder/test_bge.py`(OSError,HF 离线缓存类)。
  **环境性对照**:主仓 76b2199(不含本门任何改动)同环境复现**完全相同的 4 个失败**
  → 判定为基线/环境类,非本集成引入;除此之外 **0 产品失败**。
- 过程更正(如实记录):首轮流跑时误用了非 `ask_ai_test` 命名的隔离 DSN,3 个迁移脚本
  测试按其内置防护(「迁移脚本测试必须在 ask_ai_test 库上运行」)拒绝——系执行侧 DSN
  选择问题而非代码缺陷;改用全新重建的 ask_ai_test 后消失。
- 专项族全部在内:P0 可见性(test_checkpoint_gate 等)、引用完整性、可靠性、web_crawl/同步覆盖、
  删除生命周期+通配符边界、站点体验/Origin/page_context、技术洞察、Final Polish。

## 11. Admin Regression

- vitest:**33 文件 / 167 用例全过**(含 FinalPolish 10、TechInsight 16);
- `tsc --noEmit`:0 错误;
- 生产 build:成功(chunk >500kB 提示为既有咨询性告警,非本门引入)。

## 12. Widget Regression

- vitest:**7 文件 / 57 用例全过**(含 bootstrapSite 4、useSSE.payload 5、pageContext/siteConfig);
- `tsc --noEmit`:0 错误;
- 生产 build:成功(dist/widget.js 251.21 kB / gzip 88.38 kB)。

## 13. Runtime Smoke(集成冒烟,非最终上线验收)

隔离栈:worktree 后端 `127.0.0.1:8031`(全新空库 ask_ai_uv1 + 独立 Weaviate class
`DocumentUV1Smoke`,与主后端 :8000/共享语料零接触,主后端冒烟前后 health 200)。

**后端站点门禁(curl 矩阵)**

| 场景 | 结果 |
| --- | --- |
| 已知站 + 合法 Origin → site-config | 200,仅体验字段(无 allowed_origins 泄漏) |
| 已知站 + 不匹配 Origin | 403 |
| 未知站点 | 403 |
| 无 Origin | 403 |
| legacy /ask(无 site_id) | 200(全管道走通) |
| 已知站 + 合法 Origin /ask | 200(门禁通过进 RAG) |
| 未知站 /ask | 403 「站点未授权或来源不受信任」 |

**Admin(真实浏览器)**:登录(admin@camthink.ai)→ 业务概览 → 数据源管理 →
技术洞察 → 对话审查 → 模型配置,五页面全部正常渲染且共存:
数据源行健康态「样本不足」、技术洞察「证据不足」横幅 + 真实失败/诊断异常/降级恢复三 KPI
(样本即冒烟产生的 2 条 trace)、对话审查显示 2 条冒烟对话(拒答徽标)、模型配置五环齐全。
证据:`evidence/CAMTHINK_V1_UNIFIED_V1_INTEGRATION_2026-09-01/smoke-admin-*.png`(4 张)。

**Widget(真实浏览器,三路径)**

1. 已知站(smoke-local,Origin=http://localhost:8099 命中 allowed_origins):
   site-config 200 → **站点体验生效**(welcome「Hello from smoke local!」+ starters
   「Smoke starter one/two」,证据 `smoke-widget-site-experience.png`);
2. 未知站(ghost-smoke):site-config **403**(服务端日志为证)→ widget fail-safe 回退默认体验照常可用;
3. legacy(无 data-site-id):正常启动默认体验,**全程 0 次 site-config 请求**。

冒烟注记:隔离栈曾出现「server 200 但站点体验未生效」,定位为宿主浏览器 CORS
(harness 源 :8099 不在冒烟栈 CORS 白名单)——属测试装置配置,非产品缺陷;
为完成浏览器级证明,冒烟栈将该测试源加入 CORS 白名单后重验通过。
**生产三站的真实 Origin/CORS 配置属 Production Activation 门,本门不验(见 §17)。**

冒烟栈已全部拆除:隔离后端/静态服务停止,ask_ai_uv1 DROP,DocumentUV1Smoke 未产生
(共享 Weaviate 仅原 Document class),.playwright-cli 本地产物清除。

## 14. Scope / Repository Hygiene Audit

- `git diff e945f59..HEAD --name-only` 与两验收分支文件清单并集做集合比对:
  **不多不少**(HEAD 侧额外项仅 ec76beb 的 2 个新测试文件,系合同 §6 授权的组合用例;
  验收侧 0 文件缺失);
- `git ls-files | grep -E 'node_modules|.playwright-cli|.db$|.env$'` → **0 条**;
- main 分支 0 改动;主后端 :8000 全程未受影响;
- 冒烟/测试隔离资源全部回收(§13)。

## 15. Accepted Capability Inventory(统一候选内全部在场)

- **Core**:P0 信任边界(SourceVisibilityGuard + channel_visibility)、生成可靠性
  (零内容显式失败/错误事件/PC-06 持久化)、引用完整性(CIT 权威编号+确定性校验);
- **Operations**:LLM 供应商管理(+端点授权 llm_allowed_hosts)、API-keyless 供应商
  兼容回归(692a862/1003504)、数据源健康(五态)、技术洞察(决策化重构语义)、
  网站覆盖/一致性(web_crawl 覆盖记账+自愈)、数据源删除生命周期(字面前缀边界);
- **Experience**:Multi-Site Core(site_experiences/身份授权/Origin 校验/page_context
  软加分+非信任背景/站点体验/Conversation.site_id)。

## 16. Residual Risks(不阻断本门,移交后续门)

1. **生产发布红线(既有)**:上线必须打 internal 标记 + 跑 channel_visibility 迁移,
   否则存量隔离不生效(P0 交付时已知,非本门新增);
2. F-1 deepseek 重试仅日志不可观测(技术洞察已按真相语义退役该指标,插桩属后续);
3. F-6 JS 渲染页面 headless 抓取为 low_content(官网覆盖盲区,跟进项);
4. 生产三站 Origin/CORS 白名单配置与验证属 Production Activation;
5. 并行窗口如再启,ask_ai_test 共享扰动风险照旧(本门已用「全新重建」规避)。

## 17. NOT_VERIFIED(合同 §10 全单,本门不做声明)

生产部署/生产库迁移/生产官网语料修复/www.camthink.ai 嵌入/wiki 嵌入/store 生产嵌入/
生产 Origin+CORS 验证/真实三站 Natural Acceptance/Final Launch Acceptance —— 全部
**未验证**,归 Production Activation / Multi-Site Production Integration / Final Launch 门。

## 18. Production Status

**PRODUCTION_DEPLOYED = NO。** 本门未触碰生产 T4、生产库、共享配置、共享 Weaviate 语料;
无破坏性测试施于真实源。

## 19. Final Commit / Delivery

| 字段 | 值 |
| --- | --- |
| STATUS | PASS(Executor 自评,非 Planner Final Acceptance) |
| BASE_PRIMARY | 262c1fc859ad3203337f77eb5b5c60e40d66929c |
| MULTI_SITE_INPUT | 2d27dd8925bb9d9f1f5c8e2ffd85184c2e2a3f63 |
| BASE_INTEGRATION_COMMIT | e945f59cb7aa2aaed432bebd4cb42328caa115af |
| FINAL_COMMIT | ec76beb6a4bb88dddc2e203272d0472eb26ad49b(9fffa0e merge + 门用例;分支 tip,已推 origin 主仓) |
| BRANCH | integration/camthink-v1-unified-2026-09-01(已推 origin) |
| WORKTREE | /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights(干净) |
| CONFLICT_COUNT | 0 |
| BACKEND_RESULT | 763 passed / 5 skipped / 4 environmental(对照仓复现) |
| ADMIN_RESULT | 167 passed + tsc 0 错 + build 成功 |
| WIDGET_RESULT | 57 passed + tsc 0 错 + build 成功 |
| INT_V1_G001_G010 | 5 新增全绿 + 5 门既有测试/冒烟引用,全过 |
| REPORT_PATH | docs/implementation/CAMTHINK_V1_UNIFIED_V1_INTEGRATION_2026-09-01.md |
| REPORT_COMMIT | 由下一提交回填(本报告全文+精确 FINAL_COMMIT 随该上游提交可检索) |
| WORKTREE_CLEAN | YES |
| PRODUCTION_DEPLOYED | NO |

按合同停在统一集成报告与交接;**不自动开始 Production Activation**,
由 Planner 独立审查 commit graph、diff、测试与本报告。
