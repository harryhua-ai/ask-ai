# CAMTHINK V1 — Admin P1 Technical Insights / Observability 执行报告

日期:2026-09-01
任务:CAMTHINK_V1_ADMIN_P1_TECHNICAL_INSIGHTS(OBS-01/02/03,P1 — V1 上线前)
状态:**PASS(自评)——待 Planner 独立验收,不称 FINAL ACCEPTANCE**

---

## 1. Executive Result

技术洞察「技术性能」tab 已从**指标堆砌页**重构为**事件分诊决策页**,并在后端完成
一组关键语义修正。核心成果:

1. **修复了失败率恒 0 的可观测性缺陷**:生产 trace 写入路径从不写 stage 级
   `error` 字段,旧 `fail_rate` 在真实失败发生时仍显示 0%。真实失败现在按
   `Trace.type == "generation_error"`(P1 生成可靠性 PC-06 的唯一失败持久化路径)
   判定,可被看见、被计数、被深链排查。
2. **「重试率」双重虚构指标退役**:调查证明 `retry_count` 与 stage `error` 字段
   在生产代码中**从未被写入**,旧 retry_rate 恒为 0 且语义名不副实;deepseek 客户端
   确有 max_attempts=2 重试但仅落日志不落 trace。按合同 §9「不为此兼容性保留误导
   标签」裁决:KPI 改为**降级恢复**(唯一可观测恢复证据 `rerank.fallback` +
   容错 `error+recovered`)。
3. **OBS-03 语义纠正落地**:诊断异常明示为「超性能阈值或含错误;属诊断信号,
   不等同服务失败」,UI 全链路无裸百分比(分子/分母/窗口齐备)。
4. **信息架构按 OBS-01/02 重排**:PRIMARY 服务健康横幅(后端确定性五态推导 +
   证据理由 + 行动深链)→ SECONDARY 三卡 → DIAGNOSTIC(瓶颈主导阶段高亮、异常
   语义着色)→ REFERENCE(DSH 摘要,DSH-02 边界未动)。
5. **基线诚实化**:`baseline_source` 区分「上一周期 P95(历史对比)」与「本窗
   P50(诊断参考,非历史对比)」;上一窗无数据时环比 delta 置 null,不再假装环比。
6. **附赠缺陷修复**:无 retrieve 阶段的失败/拒答 trace 曾被误判为「单路检索」
   降级(EVIDENCE-02 初版中 3 条失败被计入降级面板),已修(缺失证据≠降级证据)。

测试:后端聚焦 24 绿 + admin API 全量 142 绿;前端 vitest 157 绿、`tsc -b` 干净、
生产构建通过。全仓后端回归结果见 §21/§24。证据包:4 张必备真实渲染截图 + 1 张
深链证据 + 各场景 API 响应 JSON(§23)。

**PRODUCTION_DEPLOYED = NO**(§28)。

## 2. Baseline / Worktree / Branch

- BASELINE_COMMIT = `e945f59cb7aa2aaed432bebd4cb42328caa115af`(独立验收的
  unified checkpoint,未从 main/76b2199/84a68b9/旧任务分支起步)
- Worktree = `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights`
- Branch = `worktree-exec/admin-p1-technical-insights`
- 冻结的 `.worktrees/v1-integration-checkpoint` 未被触碰(仍指向 e945f59)
- 回归测试搬运见 §3;最终 commit 见 §28

## 3. Regression Test Housekeeping(6c03c80 / 2dd9113)

按合同 §4,先检查后搬运:

- `git show --stat 6c03c80` → 仅 `tests/llm/test_deepseek.py` +60 行
  (FOLLOW-G005 stream 空 key 回归),提交信息明示「零实现改动」;
- `git show --stat 2dd9113` → 仅 `tests/llm/test_deepseek.py` +26 行
  (FOLLOW-G004 generate Bearer 头锁定),零实现改动;
- 确认 test-only 后按序 cherry-pick,均干净套用:
  - `1003504` ← 6c03c80
  - `692a862` ← 2dd9113
- 未从旧 LLM 分支带入任何生产变更。

## 4. Investigation Findings(调查发现,全部有源码实证)

调查范围:Analytics.tsx / techInsight.ts / tech.py / TechInsight.test.tsx /
test_tech_perf.py / Trace 模型(backend/db/models.py:107)/ 生产 trace 写入路径
(backend/pipeline/rag.py、backend/api/routes.py)/ deepseek 客户端 /
conversations.py / Conversations.tsx。

关键实证(源码行号以 baseline e945f59 为准):

| # | 发现 | 证据 |
|---|------|------|
| F1 | stage 级 `error` 字段生产从不写入;唯一错误写入是 routes.py 229-239 的 `stages={"error":{"kind":...}}`(KEY 叫 error,内部字段是 kind) | rag.py 各 trace_payload 组装点(435/462/536/589/648/680/746/897)均无 error/retry_count/recovered 字段 |
| F2 | `retry_count` 生产从未写入 | 全仓 grep:仅 tech.py/conversations.py 读取,无写入点 |
| F3 | `recovered` 生产从未写入 | 同上,仅 tech.py 读取 |
| F4 | 因此基线上 retry_rate 与 fail_rate **恒 0**,即便发生真实失败;且失败 trace(type=generation_error)的 error KEY 不在 STAGE_NAMES 里,连异常率都不计入 | tech.py 主循环 + _count_flags 与 F1 组合推理;测试实证(基线实现跑 G002 场景 fail_count=0) |
| F5 | deepseek 客户端存在 literal 重试(max_attempts=2,仅首 chunk 前),**仅 logger.warning,不落 trace**;重试耗尽 → 异常 → generation_error | backend/llm/deepseek.py:104-119,160-175 |
| F6 | 唯一可观测「遇问题恢复」证据 = `stages.rerank.fallback=true`(重排滤光→降级用 fused top-N→用户仍获答案) | rag.py:525-551,734- |
| F7 | 基线比较语义:baseline=上一窗 P95,缺失时回退本窗 P50;API 无字段区分,UI 统一显示「基线 Xms」+ 环比箭头 | tech.py:238-247;Analytics.tsx:85-93 |
| F8 | anomaly 分布的彩色圆点纯按计数(count>5 红 / >2 黄) | Analytics.tsx:218-219 |
| F9 | Conversations API 已有 has_retry/has_clarify/has_feedback/is_answered 等过滤;页面已读 URL 参数(intent/channel/feedback/answered/q);**无失败过滤** | conversations.py:44-133;Conversations.tsx:67-78 |
| F10 | KpiCard 与 BusinessOverview 共享;retry_* 字段仅 Analytics.tsx 消费(可安全改名) | grep 证明 |

## 5. Current Semantics(基线语义精确定义)

- **anomaly**:6 个具名阶段(intent/rewrite/retrieve/rerank/generate/output)任一
  `ms > NORMAL_MAX` 或 stage dict 含 `error` 字段 → 因 F1,实际等价于纯延迟超限;
- **retry**:`error or retry_count` 任一 → 因 F1/F2,恒 0;
- **fail**:`error and not recovered` → 因 F1/F3,恒 0;
- **baseline**:上一等长窗 P95,否则本窗 P50 回退,UI 不区分(=G007 违规态);
- **degradations**:type∈{reject_short,override,clarify} 或 retrieve.path_counts
  symbol/boost 全 0 —— 后者存在「无 retrieve 阶段也判单路」的缺陷(见 §6/D2)。

## 6. Root Product Problems

- **P1(=OBS-03 根因)**:管理员看到的三率里两个恒 0、一个实为延迟超限率——
  真实失败(用户收到失败文案)在页面上完全不可见;
- **P2(=OBS-01 根因)**:页面是 8 个平权面板的指标陈列,不回答「服务健康吗→
  什么问题→慢在哪→看哪些对话」;
- **P3(=OBS-02 根因)**:色彩按计数/装饰分配,alarm 阈值散落前端(p95>5000、
  anomaly>0.1、fail>0.05)而非服务级结论;
- **D2(调查新发现)**:降级面板把无 retrieve 阶段的 trace 误计为「单路检索」
  (`stages.get("retrieve", {})` 的 `{}` 默认值对缺失阶段也判 0/0)。

## 7. Final Implemented Semantics(实现后语义,与 tech.py `_classify_trace` 同源)

- **真实失败(fail)**:`type == "generation_error"` OR(任一 stage `error` 且未
  `recovered`——容错未来写入);失败类别 `failure_kind` ∈ {empty_generation,
  provider_error, stream_interrupted, unknown},从 config_snapshot → stage error.kind
  逐级提取;
- **诊断异常(anomaly)**:任一具名阶段 `ms > NORMAL_MAX` OR 任一 stage `error`
  OR 真实失败 ⇒ 保证「异常 ⊃ 失败」包含关系;**慢成功≠失败,诊断异常≠失败**;
- **降级恢复(recovered)**:非失败 且(rerank `fallback` OR `error+recovered`);
  独立信号,不并入异常/失败;
- **重试**:仅承认显式 `retry_count` 字段(literal)。生产暂无写入方 → 不设 KPI,
  conversations marker 重试语义同步收窄(与 has_retry SQL 过滤字面语义对齐);
- **降级(degradations 面板)**:仅当 retrieve 阶段真实存在且带非空 path_counts
  且 symbol/boost 全 0。

## 8. OBS-01 Result(产品目的:事件分诊)

页面按「服务健康 → 什么问题 → 慢在哪 → 看哪些对话」重排:
1. PRIMARY:`ServiceHealthBanner`(后端推导状态+证据理由+样本/窗口+行动区);
2. SECONDARY:真实失败/诊断异常/降级恢复三卡(分子/分母+一句话语义);
3. DIAGNOSTIC:瓶颈在哪(P95+基线+主导瓶颈高亮)/ 什么异常(语义着色)/
   降级到什么;P50/P95 趋势 + 信号关系(异常⊃失败;降级恢复独立);
4. ACTION:横幅内「查看失败对话 →」(失败>0 时)与「在对话审查中排查 →」;
5. REFERENCE:数据源健康摘要 + 跳转(DSH-02 边界,§15)。

## 9. OBS-02 Result(视觉层级)

- 色彩仅表达状态语义:healthy=绿 / degraded=琥珀 / critical=红 /
  insufficient_data·no_data=灰;失败卡>0 才红,诊断异常>10% 才琥珀;
- 异常列表按 severity(error=红点/slow=琥珀点)而非计数着色(F8 废除);
- 无报警卡堆叠:三卡默认中性色,仅语义触发时着色;页面整体观感更平静;
- 未引入新设计系统,复用既有 tokens(var(--err)/var(--warn)/var(--ok)/panel/bd)
  与组件(Button/Badge/Table/KpiCard 增量扩展 tone/footnote)。

## 10. OBS-03 Result(异常语义纠正)

- UI 全部百分比带分子/分母/窗口(「9 / 12 条 · 超性能阈值或含错误,≠服务失败」);
- 「78% 异常率」场景(OBS-G001)呈现为:诊断异常 75%(9/12)琥珀 + 横幅理由
  「诊断异常率 75% 偏高(…属诊断信号,不等同服务失败)」+ 失败卡 0%(0/12);
  不再可能被读成「78% 服务失败」;
- 异常列表人类可读标签(生成缓慢/重排错误/生成失败·供应商异常…),
  机器类型 `type` 原样保留(title 属性 + data-anomaly-item)。

## 11. Retry Semantic Investigation(§9 专项裁决)

**裁决:基线 retry_rate 不可称为「Retry Rate」,标签退役。** 论证链:
1. 字面重试机制唯一存在于 deepseek 客户端(F5),max_attempts=2、仅首 chunk 前、
   恢复成功无任何持久化痕迹(仅日志)——「重试率」从 trace 层不可计算;
2. 旧检测式 `error or retry_count` 与「重试发生」无对应关系:error 字段本身生产
   从不写入(F1),retry_count 亦无写入方(F2)→ 该指标在生产**恒 0**;
3. 若坚持字面口径(仅 retry_count),结果同样是恒 0 的死指标;
4. 合同允许方向中,「rename/reframe 到真实证据」最小且不撒谎:改用 F6 的
   rerank.fallback(+容错 error+recovered)呈现「降级恢复」;
5. conversations 侧:marker retry 收窄为 literal retry_count(与 has_retry SQL
   的 `'%"retry_count":%'` 字面口径对齐),失败信号另立 failure marker;
6. FOLLOW_UP(§26):deepseek 重试次数透传到 LLMResponse/stages 属生产管线
   插桩,本任务不做(§14 限制:非必要不改管线);若未来写入 `retry_count`,
   conversations 过滤与 marker 将自动开始工作,无需再改。

## 12. Failure Semantic Verification

- 失败=用户可见失败:generation_error trace 只在 PC-06 路径写入,此刻用户必然
  收到 SERVICE_UNAVAILABLE 文案、`Conversation.is_answered=False`;不存在
  「已恢复的 generation_error」(无重试落盘)→ 单条 generation_error 即未恢复失败;
- 慢成功(43s 但 answered)只进诊断异常;降级恢复(fallback)三态都不是;
- OBS-G004 场景实证:rerank fallback + error-recovered 两 trace → fail_count=0、
  recovered_count=2、健康度 degraded(理由只谈诊断信号,无「真实失败」字样)。

## 13. Service Health Derivation(§11 五态推导,确定性)

阈值全部复用重构前 UI 既有告警线(anomaly>10%、fail>5%、P95>5000ms),
仅收拢为服务级判定,无新产品阈值:

```
n == 0                                        → no_data
fail_count>0 且 (fail_rate≥5% 或 fail_count≥5) → critical
fail_count>0 或 anomaly_rate>10% 或 P95>5000  → degraded
其余 且 n<10                                   → insufficient_data
其余                                           → healthy(reasons 附正常说明)
```

- reasons[] 为证据文字(哪条证据触发、数值多少),前端零二次推断;
- 失败与诊断异常严格分级:高异常率单独最多 degraded,绝不判 critical;
- n<10 的 degraded 附「样本过少,结论需谨慎」;n<10 的「健康」直接判
  insufficient_data(§19:不假装自信结论);
- 样本量阈值 10 为工程 HOW(比例指标在小样本下方差不可接受),已在理由文字中
  向管理员如实披露。

## 14. Comparison/Baseline Semantics(§13)

- API 新增 `kpi.baseline_source`: `previous_window` | `current_window_p50_fallback`;
- 上一窗无 trace 时:三个环比 delta 置 **null**(旧实现 prev_n=1 会把当前率伪装
  成「环比变化」);comparison 保留数值但 UI 依 baseline_source 决定呈现;
- UI 文案:历史对比=「基线 4,950ms(上一周期 P95)」;回退=「无上一周期数据,
  基线 3,700ms = 本窗 P50(诊断参考,非历史对比)」,且回退态不渲染环比箭头;
- OBS-G007 前后端测试均锁定该行为。

## 15. Conversation Actionability(§16/G009)

- 后端新增 `GET /api/admin/conversations?has_failure=true`
  (EXISTS Trace.type='generation_error',真实证据过滤,非发明参数);
- Conversations 页新增 `failure=true` URL 参数 + 「失败」toggle chip +
  markers.failure 红点(生成失败);
- 技术洞察横幅失败>0 时给「查看失败对话 →」深链(EVIDENCE-05 实证:3 条失败
  精确过滤,失败 toggle 激活);
- **如实限制**:异常类型(如 generate_slow)无法在 Conversations 真实过滤
  (延迟阈值存于 JSONB 数值,SQL 级不可靠)→ 不发明假过滤器;页面提供通用
  「在对话审查中排查 →」并明示「异常类型过滤暂不支持,可按时间窗检索」;
  Conversations 页无日期过滤 UI,窗口深链不可行,一并如实标注。

## 16. DSH-02 Preservation(§17 边界)

- SourceHealthSummary 组件原样保留(一行计数+跳转),未加任何逐源表格/同步
  run 细节/操作控件;
- 原 DSH 测试两条原样通过(摘要呈现 + 无竞争表格);
- source-health API 调用参数未变(days=30)。

## 17. OBS-G001..G009 逐条对照

| 场景 | 后端测试 | 前端测试 | 真实渲染证据 |
|------|---------|---------|--------------|
| G001 高异常零失败 | test_g001…(fail=0,degraded,理由无「真实失败」) | OBS-G001(横幅 degraded,≠服务失败标注) | EVIDENCE-01(degraded,75% vs 0%) |
| G002 真实失败 | test_g002/g002b(critical 阈值/孤立失败 degraded) | OBS-G002(critical+深链 href) | EVIDENCE-02(critical,20%,深链按钮) |
| G003 慢主导阶段 | test_g003(over_count 3/1/0) | OBS-G003(主导瓶颈高亮) | EVIDENCE-01(生成 9 条超阈值高亮) |
| G004 恢复非失败 | test_g004(recovered=2,fail=0) | OBS-G004(独立卡+信号关系) | EVIDENCE-02(降级恢复 13%) |
| G005 健康周期 | test_g005(healthy) | OBS-G005(healthy,无色卡) | EVIDENCE-03(healthy) |
| G006 无/小数据 | test_g006(no_data/insufficient) | OBS-G006(两态) | EVIDENCE-04(no_data,—%) |
| G007 对比不可用 | test_g007(baseline_source+null delta) | OBS-G007(两态文案) | EVIDENCE-02(本窗 P50 明示) |
| G008 DSH 边界 | —(无后端改动) | DSH 两条原样+通过 | 各截图底部摘要条 |
| G009 排查行动 | test_list_conversations_has_failure_filter | OBS-G009(入口+限制说明) | EVIDENCE-05(深链过滤态) |

## 18. Negative Acceptance Review(§24 逐条自检)

- 「异常率≠失败率」✓(UI 语义标注+测试);retry 标签未超证据 ✓(已退役);
- 慢成功未呈现为失败 ✓;恢复未呈现为未恢复失败 ✓(G004 锁定);
- 无裸百分比 ✓(三卡 footnote 均带 n/N);P50 回退未冒充历史基线 ✓(G007);
- 高异常单独不得 critical ✓(test_g001 显式断言 status≠critical);
- 装饰色不再是主层级 ✓(severity/语义色);DSH 明细面板未回归 ✓(G008 测试);
- 未发明对话过滤参数 ✓(has_failure 基于真实 trace type;限制如实标注);
- RAG/LLM/检索行为零改动 ✓(diff 审计:仅 admin API 层+前端);DSH 公式未动 ✓;
- 端点授权未动 ✓;无无关 Admin 重构 ✓(改动文件清单 §19)。

## 19. Changed Files / Diff Audit

后端:
- `backend/api/admin/tech.py`(重写:分类/健康度/基线/异常标签/降级修复;
  NORMAL_MAX 六阶段阈值未动,无新配置)
- `backend/api/admin/conversations.py`(_infer_markers 语义收窄+failure marker;
  has_failure 过滤;has_retry 描述诚实化)

前端:
- `admin/src/pages/Analytics.tsx`(技术性能 tab 重构;知识缺口 tab 未动)
- `admin/src/pages/Conversations.tsx`(failure URL 参数/toggle/marker;
  「异常重试」chip 更名「重试」)
- `admin/src/lib/api/techInsight.ts`(类型);`admin/src/types/api.ts`(markers+failure)
- `admin/src/hooks/useConversations.ts`(has_failure)
- `admin/src/components/observability/ServiceHealthBanner.tsx`(新)
- `admin/src/components/observability/KpiCard.tsx`(增量 tone/footnote,
  BusinessOverview 兼容)
- `admin/src/components/observability/ContainmentDiagram.tsx`(两层包含+独立恢复)

测试/脚本:
- `tests/api/admin/test_tech_semantics.py`(新,11 用例);
  `tests/api/admin/test_tech_perf.py`(断言迁移);
  `tests/api/admin/test_conversations.py`(has_failure+markers 语义+降级回归)
- `admin/tests/TechInsight.test.tsx`(重写,16 用例);ContainmentDiagram/KpiCard
  组件测试重写;ConversationsReview toggle 数 4→5
- `scripts/evidence_seed_tech_insights.py`(证据 seed 脚本,入库可复现)

不在范围:rag.py/deepseek.py/检索/引用/P0 信任边界/DSH 公式/端点授权 —— 零改动。

## 20. TDD RED → GREEN Evidence

- RED:新建 test_tech_semantics.py 后对基线实现首跑
  **10 failed**(G001-G007+label+denominator 全红),证实旧实现不满足新语义;
- GREEN:重写 tech.py 后 **10/10 通过**;conversations RED(has_failure/
  markers 用例先失败)→ 实现后通过;
- 过程修正:①跨测试时间窗污染 → autouse fixture 按 question 标记清理;
  ②G004 预期依合同 §11「恢复信号也需关注」修正为 degraded+无失败表述;
  ③EVIDENCE 验证中发现单路检索误判缺陷 → 先加回归测试再修(tdd);

## 21. Backend Tests

- 聚焦语义+性能+trace:`test_tech_semantics.py`(11)+ `test_tech_perf.py`(4)
  + `test_traces.py` + `test_models_trace.py` → **18 passed**;
- Admin API 全量 `tests/api/admin/` → **142 passed**(含新语义用例);
- 降级缺陷修复后复跑三文件 → **24 passed**;
- 全仓 `tests/`(隔离库 ask_ai_obs_sem,`HF_HUB_OFFLINE=1`)→
  **686 passed / 4 failed / 3 errors / 5 skipped(53.9s)**,失败归因见 §24;
- 环境:隔离库 ask_ai_obs_sem(dockerized Postgres,用后 DROP),
  `TEST_DATABASE_URL` 注入;未触碰共享 ask_ai_test 与生产库。

## 22. Admin Tests / Typecheck / Build

- `npx vitest run` → **157 passed**(含 TechInsight 16 用例:G001-G009 全覆盖);
- `npx tsc -b` → 0 错误(修复:未用变量、TraceMarkers+failure、widget 依赖软链);
- `npm run build` → ✓ built(生产构建);
- Worktree 无 node_modules,按既有惯例软链主仓 admin/widget node_modules
  (package.json 与主仓同 SHA,依赖一致)。

## 23. Product Evidence Pack(§27,真实渲染非 mockup)

环境:隔离后端 127.0.0.1:8024(worktree 代码,独立库 ask_ai_obs_evidence,
 lifespan seed admin)+ 隔离 admin dev 5177(`VITE_API_TARGET=http://localhost:8024`)。
数据:`scripts/evidence_seed_tech_insights.py` 四场景(源码入库);截图经真实
登录(Playwright+chromium)导航 /admin/analytics 全页截取。

| 文件 | 状态断言 | 场景要点 |
|------|---------|----------|
| evidence-01-high-anomaly-zero-failure.png | degraded | 9/12 生成超 30s 阈值,失败 0%(0/12);主导瓶颈:生成(9 条超阈值);基线=上一周期 P95 |
| evidence-02-real-failures.png | critical | 3/15 失败(供应商异常/空生成/流中断各 1),查看失败对话按钮;基线=本窗 P50 明示;降级面板=无降级 |
| evidence-03-healthy.png | healthy | 12 条正常,无告警色 |
| evidence-04-no-data.png | no_data | 0 trace,—% 卡片,不假装结论 |
| evidence-05-failure-deeplink.png | — | 深链落点 /admin/conversations?failure=true,失败 toggle 激活,精确 3 条 |

API 响应 JSON(resp-*.json,5 份)与截图同目录;汇总:
critical|fail 3|anomaly 3|recovered 2|total 15;degraded|fail 0|anomaly 9|total 12;
healthy|0/0/0|12;no_data|total 0。

证据目录(docs 仓):`docs/implementation/evidence/technical-insights-20260901/`。

## 24. Regression Evidence

- DSH:`admin/tests` 中两条 DSH-02 边界用例原样通过(vitest 157 内);
- LLM Provider / Empty API Key follow-up:cherry-pick 的 6c03c80+2dd9113 在线
  lineage,`tests/llm/test_deepseek.py` 随全仓套执行(§23);
- P0/P1/Citation:`tests/api/admin/` 142 绿含集成相关 admin 面;组合契约门
  (e945f59 的 INT-CHK-001/002)随全仓套执行;
- 全仓后端回归(686 passed / 4 failed / 3 errors / 5 skipped)失败归因:
  - 4 failed 全部为 `tests/embedder/test_bge.py` 的 `OSError: 无法连接
    huggingface.co`(HF_HUB_OFFLINE×共享模型缓存竞态,两次运行失败集合不同,
    单测复跑即通过)——**对照实验:主仓 76b2199(无本任务改动)同环境同命令
    复现同样 4 failed**,证实为环境既有问题,非本任务回归;
  - 3 errors 为 `test_migrate_llm_chain_format.py` 的 DSN 护栏断言
    (「迁移脚本测试必须在 ask_ai_test 库上运行」),隔离库名 ask_ai_obs_sem
    按设计触发,非回归;
  - 本任务改动面(admin API + 前端)与上述文件零交集。

## 25. Residual Risks

1. 降级恢复的覆盖面目前仅 rerank.fallback 一类证据(生产可观测恢复信号唯一);
   未来管线若新增降级路径需同步纳入;
2. 健康度阈值为工程收拢(复用旧 UI 告警线),上线后可能需按真实流量分布校准
   (尤其 P95>5000ms 对 generate 慢场景偏敏感——本地 CPU 数据≠T4 GPU);
3. anomaly 深链受限于 Conversations 无日期过滤 UI,当前仅通用入口+限制说明;
4. generation_error 的 failure_kind=unknown 兜底分支尚无生产写入方(防御性),
   若出现说明存在未登记写入路径,值得排查;
5. trace 级 stage error 字段(容错分支)无生产写入方,测试覆盖为契约性防未来。

## 26. NOT_VERIFIED / FOLLOW_UP_FINDINGS

NOT_VERIFIED:
- T4 GPU 环境下阈值合理性(无 T4 实验,合同 §28 禁产线操作);

FOLLOW_UP_FINDINGS:
- F-0:环境发现 —— `HF_HUB_OFFLINE=1` 下全仓套的 embedder 测试存在共享缓存
  竞态抖动(主仓同环境复现),建议 CI/本地全量跑统一 `HF_HUB_OFFLINE=1` +
  每进程独立 HF 缓存或预热策略,否则会有 4 条左右噪声性失败;
- F-1:deepseek 重试计数透传(stages.generate.retry_attempts)可让「重试(已恢复)」
  成为真指标 —— 需管线插桩,建议单独立项;
- F-2:Conversations 页日期过滤 UI 补齐后,技术洞察可提供窗口深链;
- F-3:Conversations 标记的 degraded 判定在 retrieve 缺 path_counts 的旧格式
  trace 上保守返回 False(宁缺勿谎),如需覆盖旧数据需数据迁移;
- F-4:`marker retry` 与 `has_retry` 现均为字面口径,生产恒空,待 F-1 落地后
  自然激活;
- F-5:本任务发现并修复「无 retrieve 阶段被判单路检索」缺陷(D2),该缺陷在
  baseline 上同样影响旧降级面板口径。

## 27. Production Status

- 未部署生产;未触碰 T4/生产库/共享配置/共享 Weaviate/主仓 :8000 后端;
- 隔离面:worktree + 独立库 ask_ai_obs_sem(测试)/ask_ai_obs_evidence(证据,
  均用后 DROP)+ 独立端口 8024(后端)/5177(admin dev);
- **PRODUCTION_DEPLOYED = NO**

## 28. Final Commit

- FINAL_COMMIT = `024e55bd437cbec98f5de4dc2bb1f139cf0bb359`
  (worktree-exec/admin-p1-technical-insights;父提交 692a862←2dd9113、
  1003504←6c03c80、e945f59=baseline)
- REPORT_COMMIT = docs 仓本报告提交 SHA(见提交记录)
- BASELINE_COMMIT = e945f59cb7aa2aaed432bebd4cb42328caa115af

---

交付摘要(STATUS/BASELINE/FINAL_COMMIT/BRANCH/REPORT_PATH)见执行会话最终输出;
本报告不构成 FINAL ACCEPTANCE,Planner 独立验收为准。
