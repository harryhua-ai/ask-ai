# CAMTHINK V1 — Sales Lead Capture & Handoff 执行报告

- 日期:2026-09-02
- 执行:Senior Engineering Executor(PARALLEL CODEX C)
- 任务:Sales Lead Capture & Handoff V1(仅此一项,未触其他 Roadmap 任务)
- 报告仓库:docs 仓(仅本地,无 remote)

## 1. Baseline

| 项 | 值 |
| --- | --- |
| BASELINE_COMMIT | `76b2199`(main,五任务批 FINAL PASS 合入点,CI 双绿) |
| WORKTREE | `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/sales-lead`(新建,与其他并行 Codex 完全隔离;4 个既有 worktree 均被其他任务占用,无可复用闲置树) |
| BRANCH | `worktree-exec/sales-lead-capture` |
| FINAL_COMMIT | `d01a2a7`(已推 origin) |

## 2. Existing Architecture(勘察结论)

- 无 alembic;`backend/db/models.py` 单文件 SQLAlchemy 2.0 async;`init_db`(create_all)启动时自动建**新表**,不给已有表加列 → 已有表变更走 `scripts/migrate_*.py` 幂等脚本(仓库既有惯例,如 country 列)。
- `Conversation` = **单轮**问答(question/answer);多轮上下文由客户端 `AskRequest.conversation_history` 提供;widget 端 `session_id`(localStorage UUID)已在 `useSSE.ts` 上报但此前未持久化。
- 意图 4 分类(`backend/pipeline/intent.py`,fail-open 为 product);`stream_answer` 顺序:override → intent → extract/rewrite → 检索融合 → rerank → 生成;SSE 事件 `sources/token/done/declined`。
- 业务概览(`backend/api/admin/business.py`)旧口径:`leads.valid = commercial 且 answered`、`leads.potential = commercial 总数` —— 即本任务要消除的「商业对话 = 有效线索」混淆。
- 语料入库唯一路径 = `scripts/sync.py` → `IngestionPipeline`(仅连接器文档);对话内容从不进 Weaviate → PII 边界有天然结构,本任务以运行时+源码级测试实证(§8)。
- PII 掩码 `mask_pii`(邮箱+中国手机号)在 `/api/ask` 顶部应用于用户消息。

## 3. Engineering Design

状态模型(契约 §4/§10 的最小实现,不建 0-100 分):

```
LEAD_NONE / LEAD_POTENTIAL / LEAD_QUALIFIED        (资格级别,qualifier LLM 输出)
potential → qualified → contact_captured → handed_off   (线索状态,只升不降)
```

- LEAD_NONE = 无 sales_leads 行;potential(初步商业意向,如选型评估)即建行(支撑概览「潜在线索」口径);qualified(强信号)升级;任何状态获得联系方式 → contact_captured;admin 手动移交 → handed_off(终态,自动流程不可降级)。
- **资格判定门**(成本控制):仅 `commercial/product` 意图、或会话已有线索、或本轮检出联系方式、或命中「要求销售联系」确定性短语时,才调 qualifier LLM(`task=lead_qualification`,路由缺省回退 generation 链)。
- **零延迟增加**:qualifier 与 rewrite/检索 `asyncio` 并发,生成前收敛。
- **One-Proactive-Ask**(契约 §7):`decide_invite` — 已有联系方式不邀请;explicit_sales_request(LLM 或确定性短语)可邀请(含再邀请);首次 qualified 邀请一次;已邀请过则仅「实质更强信号」且 `prompt_count < 2`(MAX_PROACTIVE_ASKS 有界化)再邀请一次;之后不再骚扰。
- **先答后邀**(LEAD-G003):邀请以指令内嵌 system prompt,明确要求「先完整回答当前问题,回答结束后另起一行追加一句自然邀请」。
- **Capture 模式**(LEAD-G004):原始消息(脱敏前)经确定性正则检出联系方式(邮箱/电话/WhatsApp/微信,一种即 capture)→ 本轮绕过 off_topic 拒答、`effective_min=0`(空检索也生成)、内嵌确认指令。
- **Contact Promise Boundary**(契约 §8):确认/邀请指令均明文禁止承诺「销售会联系/24 小时内」;handoff 接口只表达人工接管,不触发任何自动通知。widget 零改动(纯对话式捕获,无新 SSE 事件)。

## 4. DB / Data Model

新表 `sales_leads`(仅新增,不改既有行;`init_db` 自动建,生产门另备显式脚本):
`id, session_id(线程键,index), status(index), contact_type/value/masked/captured_at, name, company, region, product_interest, quantity, use_case, purchase_intent, timeline, ai_summary, prompt_count, last_prompted_at, source_conversation_id, last_conversation_id, channel, language, country, handoff_at, handoff_by, created_at/updated_at`。

- `contact_value` 原文**仅存本表**(RFC 邮箱 320 上限);列表视图只回 `contact_masked`。
- 不设到 conversations 的外键:线索生命周期独立于对话保留策略。
- `conversations` 增列 `session_id`(String64 + index):新对话写入,支撑「查看完整对话」按会话聚合全部轮次;旧行 NULL → 线程回退「创建轮 + 最近轮」锚点。
- `idx_sales_leads_status_created(status, created_at desc)`、`idx_conversations_session_id`。

## 5. Qualification / Contact Capture Behavior

- qualifier prompt 冻结契约语义:none=普通产品/技术/单次询价(「NE503 多少钱」判 none/potential,绝不邀请);qualified=明确采购/报价请求/数量/项目需求/经销合作/批量/规模/时间表/要销售联系;`stronger_signal` 与已记录字段对比;fields 仅提取用户明示信息;summary 一两句中文供销售速判。
- 解析 fail-open:非 JSON/非法级别 → LEAD_NONE,绝不阻断问答。
- 联系方式检测(脱敏前原文,确定性):邮箱 > 微信号 > 号码形状(9-15 位数字,滤日期/编号噪声)+ 关键词定型(whatsapp/wechat/phone);`mask_contact_value` 生成展示值(`j***@example.com`/`138******78`)。
- 落库(apply_turn):qualifier 未运行且无联系方式 → 不产生行;level=none 且无既有线索 → 不产生行(G001 防灌爆);字段合并「新值非空才覆盖」;已有联系方式不覆盖;invited → `prompt_count+1`。

## 6. Admin UX(信息架构)

- 侧边栏「运营」组新顺序:业务概览 → **销售线索**(`Target` 图标)→ 对话审查 → 技术洞察。Lead 是独立一等对象,不是 Conversation Review 的 filter。
- `/admin/leads` 页:状态 tab(全部/潜在/合格/已留联系方式/已移交)+「可联系」开关 + 搜索(公司/摘要/masked 联系方式);列表列=状态徽标/联系方式(icon+masked/未提供)/公司/产品/数量/地区/需求摘要/创建时间。
- 详情侧板:状态、联系方式原文(销售跟进必需)、姓名/公司/地区/产品/数量/用途/采购意向/时间表、AI 摘要、邀请次数、创建时间;**「查看完整对话」**按 session_id 聚合全部轮次(气泡渲染);**「移交销售」**(admin/editor,幂等,写 `handoff_by/handoff_at`);面板固定文案声明「系统不会自动联系客户」。
- 业务概览:`leads` 块改为 `commercial_conversations / potential / qualified / contactable / handed_off`(移除 `valid`);卡片区分商业对话量与各级线索;下钻链接改指 `/leads`。API 兼容性:同仓前端同步更新,无外部消费者。

## 7. PII Isolation(HARD 实证)

三层证据(tests/api/admin/test_ask_lead_flow.py + test_rag_lead.py):

1. **运行时全表面扫描**:真实 orchestrator + 脚本 LLM 走完整 `/api/ask` 三轮流程,断言原文邮箱不出现在 conversations(question/answer)、traces.stages、检索查询(searcher 录取)、全部 LLM prompt(qualifier/generation 录取);脱敏占位 `[邮箱已脱敏]` 确在管线流转;原文唯一落点 = `sales_leads.contact_value`。
2. **trace PII 安全**:lead 阶段只含 `contact:{type, masked}`。
3. **源码级不变量**:`backend/pipeline/ingest.py`、`scripts/sync.py`、`backend/connectors/*.py` 不含任何 lead 域符号引用(`SalesLead/lead_service/lead_qualify/apply_lead_turn`)。
4. **暴露面收缩**:列表 API 不回原文(仅 masked);原文仅详情/移交响应返回且需授权角色;无任何公开(/api)端点接触 lead 数据。

## 8. Modified Files

新增(13):`backend/pipeline/lead_qualify.py`、`backend/services/lead_service.py`、`backend/api/admin/leads.py`、`scripts/migrate_sales_leads.py`、`scripts/migrate_conversations_session_id.py`、`admin/src/lib/api/salesLeads.ts`、`admin/src/pages/SalesLeads.tsx`、`tests/pipeline/test_lead_qualify.py`、`tests/pipeline/test_rag_lead.py`、`tests/services/test_lead_service.py`、`tests/api/admin/test_leads.py`、`tests/api/admin/test_ask_lead_flow.py`、`admin/tests/SalesLeads.test.tsx`。

修改(12):`backend/db/models.py`(SalesLead + conversations.session_id + 2 索引)、`backend/pipeline/rag.py`(lead 步骤/指令内嵌/capture 门)、`backend/api/routes.py`(lead 上下文/落库/session_id 持久化)、`backend/api/admin/{router,business}.py`、`config/llm_providers.yaml`(lead_qualification 路由种子)、`admin/src/{App.tsx,components/Sidebar.tsx,lib/api/businessOverview.ts,pages/BusinessOverview.tsx}`、`tests/api/admin/test_analytics_business.py`、`admin/tests/BusinessOverview.test.tsx`。

## 9. Migration(仅测试/本地验证)

| 脚本 | 验证 |
| --- | --- |
| `scripts/migrate_sales_leads.py` | dry-run → 创建 → 二次幂等 skip,全过 |
| `scripts/migrate_conversations_session_id.py` | dry-run → 加列+索引 → 二次幂等 skip,全过 |

验证库:一次性隔离库 `ask_ai_lead_test` / `ask_ai_test_lead`(本机 Docker PG,用后即弃,可 DROP)。另:脚本经 `.env` DSN 在**本地开发库 ask_ai** 同步执行过(加法变更、幂等、零数据触碰;本地 dev 后端下次重启 create_all 亦会自动建 sales_leads)。

## 10. Tests(全部实际运行,非代码阅读断言)

| 套件 | 结果 |
| --- | --- |
| 新增 lead 用例(qualify 37 + service 12 + 管线 11 + admin/flow 11) | 71 passed |
| CI 同口径 `pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e` | **506 passed**(0 failed/error) |
| DB 型 admin API 目录(CI 无 PG 故排除;本地带隔离库实跑) | 108 passed |
| 其余目录分片(db/pipeline/retrieval/services/auth/utils/llm/connectors) | 全绿 |
| admin vitest 全量 | **136 passed** |
| `npm run build`(tsc -b 类型检查 + vite) | 绿 |

注:曾复现一次全量单进程运行挂起,定位为环境型网络等待(tests/embedder 路径,CI 亦排除该目录);按 CI 同口径命令与分目录运行均稳定全绿。

## 11. Acceptance Matrix(LEAD-G001..G015)

| Gate | 结论 | 证据 |
| --- | --- | --- |
| G001 普通产品/价格咨询不索要联系方式 | PASS | `test_invite_no_invite_for_price_inquiry`、`test_potential_no_invite`、`test_plain_inquiry_creates_no_lead`(询价判 none 不建行) |
| G002 报价/批量/项目/经销强信号 → Qualified | PASS | `test_qualified_appends_invite_after_full_answer`、qualifier prompt 规则、`test_apply_creates_lead_on_qualified` |
| G003 先答当前问题再自然邀请 | PASS | `LEAD_INVITE_INSTRUCTION` 要求 1)+管线断言指令内嵌且生成正常完成 |
| G004 一种联系方式即可 capture | PASS | `test_contact_only_turn_without_prior_lead`(裸邮箱)、`test_contact_capture_upgrades_status`、`test_capture_mode_bypasses_off_topic_and_acks` |
| G005 拒绝/忽略后不重复询问 | PASS | `test_one_proactive_ask_second_turn_no_reinvite`、`test_invite_capped_at_two_proactive_asks`、E2E 第三轮 `prompt_count==1` |
| G006 Contact Captured ≠ Sales Contacted | PASS | 指令禁承诺断言、详情面板固定文案、handoff 仅人工接管语义 |
| G007 Lead 独立存储并关联 Conversation | PASS | `test_full_lead_flow_and_pii_isolation`(source_conversation_id/session_id 断言)、`test_second_turn_same_session_updates_and_prompt_bookkeeping` |
| G008 独立「销售线索」入口与列表 | PASS | Sidebar/App 路由、`test_leads.py` 列表/过滤/鉴权 |
| G009 Lead Detail 商业信息 + 原始 Conversation | PASS | `test_detail_contains_contact_value`、`test_thread_aggregates_session_turns`、`SalesLeads.test.tsx` 详情/线程交互 |
| G010 概览不再混淆商业对话=有效线索 | PASS | `valid` 键移除断言、`test_business_overview_new_leads_semantics`、五口径卡片 |
| G011 Conversation Review 不被破坏 | PASS | `tests/api/admin/test_conversations.py` 全绿;对话审查代码零触碰 |
| G012 Intent 主流程无 regression | PASS | `test_no_lead_ctx_baseline_unchanged`(无 lead_ctx 行为与基线一致)、intent 全套绿、506 回归 |
| G013 Lead PII 不进 Weaviate/RAG corpus | PASS | §7 四层实证(运行时扫描+源码不变量) |
| G014 跨会话/客户不泄漏 Lead PII | PASS | 原文不进任何 LLM prompt/存储表面;无公开 API 暴露;admin 鉴权矩阵(401/403) |
| G015 中英文基本体验 | PASS | 中文全流程 E2E + `test_english_lead_flow_invite`(英文强信号)+ `test_hint_en`(英文销售请求短语) |

## 12. Remaining Risks

1. qualifier 质量=LLM 质量:fail-open 下 qualifier 失败时,无确定性短语加持的潜在 qualified 轮会漏判(宁漏勿扰,符合契约取向);上生产后建议用真实对话回看调 prompt。
2. 号码形状检测(9-15 位)理论上可能误捕长数字编号(概率低;销售人工复核兜底;邮箱/微信路径精确)。
3. `conversations.session_id` 仅新对话写入;历史行 NULL → 线程视图回退 2 锚点轮次(不完整但不报错)。
4. 邀请为纯文本指令驱动,非确定性 UI 控件;LLM 偶发不遵循指令时不展示邀请(不影响数据正确性,`invited` 以指令是否内嵌为准)。
5. 业务概览 `leads.valid` 键移除:同仓前端已同步;若有外部报表直读该键需同步(仓库内无)。

## 13. Production Activation Requirements(未执行,留 Production Gate)

1. 生产库执行 `python scripts/migrate_sales_leads.py`(幂等;即便不跑,后端启动 create_all 也会建表,但显式执行可控可验证)。
2. **必跑** `python scripts/migrate_conversations_session_id.py`(create_all 不会给既有 conversations 加列;不跑则新对话不落 session_id,线程视图退化为锚点模式,lead 线程聚合失效)。
3. LLM 路由:`lead_qualification` 任务自动回退 generation 链,零配置可用;可选在 llm_routing 表显式 seed 该任务。
4. 发布含 `config/llm_providers.yaml` 变更;无新环境变量;无 Weaviate schema 变更。
5. 生产验证建议:埋一条英文+一条中文强信号真实对话,核对 sales_leads 行、邀请文案、概览口径。

## 14. Final Commit

- `d01a2a7` @ `origin/worktree-exec/sales-lead-capture`(25 files, +3406/−31)
- Baseline:`76b2199`(main)
- 本报告:docs 仓 `docs/implementation/CAMTHINK_V1_SALES_LEAD_CAPTURE_HANDOFF_2026-09-02.md`
