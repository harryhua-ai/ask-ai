# V1.6.3 Wave 1 — Track D 执行报告:Gap Reason Taxonomy(U-14 扩展原因词表 + 证据规则)

- **执行 agent**:Track D(taxonomy)
- **日期**:2026-09-13
- **Worktree**:`/Users/harryhua/Documents/GitHub/ask-ai-v163-wd`(仅追加 commits,未新建 worktree)
- **Branch**:`track/v163-d-taxonomy`
- **基线**:PREP_BASE_SHA = `d613e6aab787110e6c7839f92dbc28611b79ee7e`(FINAL_PREP_BASE,Wave 0B FINAL OWNERSHIP ISOLATION 勘误 tip)
- **Verdict**:**CANDIDATE READY**

---

## 1. 实现范围(仅冻结项)

### 1.1 U-14 六新类 + 每类后端证据规则(IF-2 冻结稿)

词表扩展挂载点 = `backend/services/gap_taxonomy.py`(其头注声明的 Wave 1 Track D 专属扩展权)。
参考词表 = TI-09 / 参考 PNG 逐词核对(知识缺失/服务知识不完整/内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失)。
新增权威机器值 6 个(字面 = 参考词,即参考要求的扩展原因类):

| 新类 | 证据规则(可从真实证据确定性复现;非 keyword 猜测、非 label-only) |
|---|---|
| **生成异常** | generation failure 真相:最新 Trace.type=`generation_error`(PC-06 结构化失败持久化;`config_snapshot.failure_kind` ∈ empty_generation/provider_error/stream_interrupted)。失败会话 NA-05 强制 is_answered=False,故本规则优先于 reject,否则该真相永不可见;无此 trace 证据的未回答会话仍判 reject |
| **内容缺失** | 知识缺失变体:is_answered=False + sources 空 + 最新 rag trace `stages.retrieve.hybrid_count==0`(知识库对该内容零候选;召回空 answered 空间不变) |
| **引用异常** | 引用一致性违例:answered + sources 非空 + 答案含 `[N]` 引用标记且 N 越界(N=0 或 N>len(sources);标记形状契约同 backend.pipeline.citation:1-3 位数字、非 Markdown 链接形态) |
| **内容冲突** | 多源冲突真相:同一会话同时引用 superseded 文档与其接替者(`documents.superseded_by` 链两端均出现在 sources 的 source_id 集) |
| **内容过期** | 内容时间真相:所引文档(第一方 source_id→documents)内容最后更新时间早于会话时间超过 `GAP_STALE_CONTENT_DAYS=180` 天 |
| **检索异常** | 检索异常证据:answered + sources 非空 + 最新 trace 检索阶段未达最低有效召回(`stages.retrieve.min_results_met=False`,或 `hybrid_count<effective_min`) |

**优先级(IF-2 冻结)**:生成异常 > 内容缺失 > reject;引用异常 > 内容冲突 > 内容过期 > 检索异常 > low/召回不足。新类=更具体的确定性证据,优先于置信度代理;召回空(answered+零来源)冻结空间不侵入(六新类中仅生成异常/内容缺失落未回答侧)。

**旧 4 类保全**:reject/low/召回空/召回不足 谓词语义逐字保持(0.6 阈值收编为常量 `GAP_MISS_LOW_CONFIDENCE`,零语义变化);无新类证据的既有证据形态分类不变(专项回归测试钉死);既有测试 `test_coverage_gaps_miss_type_four_types`、`test_answer_gaps_*` 全部原样通过。

### 1.2 分类判定仍在后端

- 单会话规则纯函数 `classify_conversation_miss_type` = `backend/services/gap_taxonomy.py`(IF-2 挂载点);
- 批量分类器 `classify_gap_miss_types` = `backend/api/admin/analytics.py`(证据 IO:conversations+traces+documents 三查询;聚类主导归并逻辑不变);
- `tech_answer_gaps.py` **零 diff**(cause 参数与 miss_type 投影经既有 D-owned 区域透传,同源消费)。

### 1.3 前端呈现(全部消费后端权威值)

- `admin/src/lib/gapCause.ts`(词表单一真相源,cause 面=D):GAP_CAUSE_LABELS/TONES/CONCLUSIONS/OPTIONS 扩展六新类;新 tone `violet`(参考 PNG 淡彩紫,检索/生成/引用异常);内容过期/内容冲突=warning(琥珀)、内容缺失=critical(红系)——与参考 PNG 徽章色族逐类一致;**status 面(E)零改动**;
- `admin/src/pages/analytics/CauseBadge.tsx`:CAUSE_TONE_STYLE 增加 violet 淡彩语法条目(`color-mix(in srgb, #7c3aed 12%, transparent)`;主题 token 无紫色,唯一字面量即参考词表语义色);data-gap-type 机器值恒存机制不变;
- `GapCauseFilter.tsx` / `DiagnosisConclusion.tsx`:**零 diff**——选项与结论经 gapCause 单一词表源自动获得新类(IF-6 设计的实现路径即如此);
- **零 frontend keyword 猜测/label-only 扩展**:前端只映射展示,分类判定全部在后端。

### 1.4 与 E 的观察流零耦合

词表模块稳定导出常量 + 版本注释清晰(模块 docstring = IF-2 冻结稿全文);零 observing 语义、零 E 文件触碰。E 可直接依赖 IF-2 词表常量与 `classify_gap_miss_types` 实际实现联测。

## 2. Changed Files(7;scope audit 全 D-owned)

| 文件 | 归属 | 变更 |
|---|---|---|
| `backend/services/gap_taxonomy.py` | D(IF-2 挂载点) | +六新类词表/证据规则常量/纯函数分类器/模块 docstring 冻结稿 |
| `backend/api/admin/analytics.py` | D(classify 区) | classify_gap_miss_types 证据 IO 扩展 + 纯函数调用 + docstring |
| `admin/src/lib/gapCause.ts` | D(cause 面) | labels/tones/conclusions/options 扩展六新类;status 面零改动 |
| `admin/src/pages/analytics/CauseBadge.tsx` | D | violet tone 淡彩条目 |
| `admin/src/lib/gapCause.test.ts` | D(cause 测试) | 选项全集断言随 U-14 冻结更新(旧断言「新词不得进入」已被 U-14 冻结合同取代) |
| `tests/api/admin/test_gap_taxonomy_causes.py` | **新增**(D 测试) | 纯规则 10 用例 + 真实 DB→API 回放 13 用例 |
| `admin/tests/GapCauseTaxonomy.test.tsx` | **新增**(D 测试) | 词表/选项/徽章/诊断结论 18 用例 |

未触碰(禁改清单核验):AnswerGapsTab/GapPanel 壳、GapStatusFilter/StatusBadge/PanelHistory(E)、PanelStats/GapTopicCell(F)、tech_observation/tech_export/tech_evidence、gap_status.py、tech.py、data_sources/DataSourceDetail(C)、Sidebar/Layout(A)——`git status` 零命中。

## 3. Tests(RED→GREEN)

### 后端(新 23)
- **RED**:新常量 ImportError(收集失败)确认;
- **纯规则单元**(`TestConversationClassifierPure`,10):六新类各 1 + 引用在界反例 + 优先级 2(生成>内容缺失、冲突>过期)+ 旧 4 类无新证据逐字保持 1;
- **真实 DB→API 回放**(`@integration`,13):六新类 × `/tech/answer-gaps`(parametrize,断言 miss_type+breakdown)+ `/analytics/coverage-gaps` 六类同源+summary + cause=生成异常 权威行集 E2E(total 真值/无混入/行集全为该分类)+ 旧 4 类不被侵入(parametrize 4:reject_plain/recall_empty_plain/low_plain/insufficient_plain)+ 内容过期边界(新鲜文档回落召回不足);
- 每个新类 ≥1 行确定性真实证据(fixture 构造经真实 DB→API),满足合同验收「每个新词至少 1 行真实分类证据」。

### 门(全部绿)
| 门 | 结果 |
|---|---|
| pytest 全量(串行,TEST_DATABASE_URL=…ask_ai_test_d,HF_HUB_OFFLINE=1) | **2524 passed / 0 failed / 7 skipped**(收集 2531 = 基线 2508 + 新 23;基线组 flaky 规则下 0 失败,无复跑) |
| PA 套件 tests/project_automation | **114/114 passed** |
| vitest 全量 | **471 passed**(基线 453 + 新 18;含修复 widget node_modules 缺失后的环境恢复) |
| tsc -b / build | **0 error / ✓ built**(admin `npm run build` 内含 tsc -b) |
| ruff(3 个改动 py 文件) | **All checks passed!**(全仓 303 条 pre-existing 与基线双树一致,零新增;format 门不适用——基线 analytics.py 本身非 format-clean,已实测证实) |
| 相关回归子集(analytics/tech/gap_taxonomy/PA) | 175 passed |

## 4. 真实运行时验收(本地栈 8124/5224;三角核对)

- **seed**(WD- 标记,仅本地 ask_ai@5432,SQL 全文=交付物):6 gap cluster + 6 conversation + 6 trace + 3 documents,六新类各 1 行代表性真实证据(`fixture-seed-wd-d-taxonomy.sql`);
- **分类→API**:`GET /tech/answer-gaps?q=WD-` → 六行 miss_type = 生成异常/内容缺失/引用异常/内容冲突/内容过期/检索异常(逐行与证据规则预期一致);`GET /analytics/coverage-gaps` 同源同值 + miss_type_summary 含六新类各 1;
- **API 过滤**:`cause=生成异常` → total=1、行集=该分类权威行集(其余类不混入);
- **API→UI**:`[data-filter-cause]` 选项 DOM 取证 = 全部原因 + 参考词表 8 词 + 拒答/低相关 + 未分类(12 项,`filter-options-dom.txt`);六新类逐一 `select_option` → 行集=1 行且徽章 data-gap-type=该类(E2E:按新原因过滤→行集=该分类权威行集);点开行 → 诊断结论 `data-conclusion-kind=authoritative`,徽章=生成异常(紫),结论=证据规则忠实转述「回答生成失败(供应商错误/空生成/流中断)…」;
- 诊断详情 Tab 原因分类分布与队列分布一致(breakdown)。

## 5. 视觉证据(1536×1024 @1x)

目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave1-d-20260913/`
- `01-cause-filter-all-options.png` / `02-cause-column-new-classes.png`:队列原因列全词表(六新类徽章:生成异常/引用异常/检索异常=淡彩紫,内容过期/内容冲突=琥珀,内容缺失=红系;与参考 PNG 色族一致);
- `03-cause-column-legacy-classes.png`:旧类徽章页(知识缺失/服务知识不完整/低相关/拒答/未分类);
- `04-filter-{六新类}-rowset.png` ×6:按新原因过滤 → 权威行集;
- `05-diagnosis-conclusion-生成异常.png` / `07-diagnosis-conclusion-内容过期.png`:诊断结论新类权威形态;
- `06-diagnosis-detail-breakdown-生成异常.png`:诊断详情分布一致性;
- `filter-options-dom.txt`:筛选器全词表 DOM 取证;`fixture-seed-wd-d-taxonomy.sql`:fixture SQL 全文。

## 6. Ownership / Interface / Blockers

- **Ownership violations**:无(7 changed 文件全 D-owned;禁改清单零命中);
- **Interface expansions**:无(未新增任何跨轨需求;E 依赖的 IF-2 词表合同已按实际实现交付);
- **Blockers**:无;
- **备注**:worktree 首建导致 `widget/node_modules` 缺失(环境,非代码),`npm ci` 恢复后 vitest 全量 471 绿;登录/筛选/徽章/结论全部为后端权威值消费,无前端自造分类。

## 7. Issue 映射

- **#59**(原因词表/分布部分):六新类+证据规则+filter 全集+分布一致性——本 candidate 落地后可关闭词表部分;
- **#54**(banner 部分):贡献 cause 分类面(引用异常=「引用需要重新验证」类真相;DataSourceDetail banner 若合同冻结给 D 的呈现面本次未收到移交,未触碰 C-owned 文件)。

## 8. 移交与 STOP

- Candidate=`track/v163-d-taxonomy` 分支 tip,及时移交 **Track E joined runtime FINAL PASS 联测**(D→E 依赖合同 §3.6:E 对 D 实际词表实现联测);
- 本 agent 未 merge/deploy/关 issue;**STOP**。
