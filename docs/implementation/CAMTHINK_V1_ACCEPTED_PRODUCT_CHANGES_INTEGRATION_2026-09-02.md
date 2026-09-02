# CAMTHINK V1 — Accepted Product Changes Integration Gate 执行报告

- 日期:2026-09-02
- 执行:Engineering Executor(Integration Gate)
- 分支:`integration/camthink-v1-accepted-product-changes-2026-09-02`
- 工作树:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/accepted-integration`
- 仓库:`harryhua-ai/ask-ai`(主仓;docs/ 目录文件按既有惯例 force-add 入主仓)

---

## 1. STATUS

**STATUS = PASS**

三项已 FINAL PASS 的验收输入(A. Product UX Closure B / B. Sales Lead Capture & Handoff V1 / C. Three-site Integration Contract)已在同一集成候选上共存,行为级证明 INT-G001~G010 全过,后端/Admin/Widget 回归全绿,迁移幂等本地实证,零生产接触。

## 2. 基线判定(不猜目录名,按 git 实证)

| 项 | 值 |
| --- | --- |
| BASELINE_COMMIT | `f874ee45a6df2368ef8c5f55078ab3e35ddd4a8f` |
| 基线分支 | `release/camthink-v1-rc-2026-09-01`(tip,与 origin 同步) |
| 判定依据 | 任务书指认的 P0/P1 sync 线基点 81312df 之后,该线已追加 P1 sync 生命周期闭环(7599e8a)与 Planner 修正(9bbf587),均为**已提交已推送**工作;`.worktrees/technical-insights`(该线唯一工作树)`git status` 干净,无任何未提交 Sync Codex 工作可被"消费"。故按任务书"latest safe release-line commit that does NOT consume uncommitted work"规则取 tip f874ee4 |

## 3. 集成输入与产出提交

集成策略:cherry-pick(最低风险——三个输入分支基点各异,且 widget-handoff 分支 tip eb112fa **未验收**,不可整支合并)。

| 验收输入 | 原提交 | 集成分支上的提交 |
| --- | --- | --- |
| C. 三站契约(多语言+Headless) | `a26f1a418b7c371ae657b9abbfa2a8a5f11f4492` | `10751978aad559f17bcdc0693d17dd33539070e9` |
| C. 报告 §10 Multilingual/Headless | `657338b09092aa5a63d3ab3320dd527f462bc824` | `721d16fd8287bf6fb127906b248d932d9fc61567` |
| A. UX Closure B 实现 | `0420703cafd0d44139a3714869083f7e3c563621` | `040324802a4706589e490be81e58ad3d3903e8e3` |
| A. UX Closure B 报告 | `f89f5d773d01162f16bda8dc748b0816d2847846` | `4b3e4b53e2de53ea927d99d6d916214affccfb69` |
| B. Sales Lead V1 实现 | `d01a2a7960fa5ea4e457b99f9c28950f1dfbf9e7` | `35a0870cce91d09780d0382166d27fca1ae74d6b` |
| B. Sales Lead V1 报告 | `cb9d841cc63ce3ed35fc1b1efe9c1dbb828cce88` | `4b1b3830c2ca7e09b7e7d25eeedeeb24e2c48b33` |
| (本门新增)INT-G001~G010 门用例 + lint 修复 | — | `d9065df315e70c9c4a7a5233238f8f20e25d2832`(**FINAL_COMMIT**) |

未纳入:eb112fa(widget-handoff tip,基址回填,**未验收**);cd12687(main 的 .gitignore chore,与 release 线无关)。657338b 的报告载体文件在本基线不存在(由未纳入的 2fb1a86 创建),按"取验收提交当时的文件完整版本"重建,实证其中 **0 处** eb112fa 内容(`wiki-data.camthink.ai` 计数为 0)。

## 4. 冲突解决(CONFLICTS_RESOLVED)

全部冲突集中在任务书预警的关键区(`rag.py`)及其邻接面,逐处语义裁决:

1. **rag.py(0420703 pick,4 处)**:P1 引用完整性已把 `_build_context`/`SOURCE_LABELS`/`_normalize_source_path` 迁入 `citation.py`。裁决:canonical 化改在 `_extract_sources` 内做(`wiki_canonical_url` → `normalize_source_path` 去重),`_build_context` 不再恢复;`SOURCE_LABELS` 以 citation.py 为唯一定义点;imports 两侧并存。
2. **citation.py(集成改编,+12 行)**:`build_citation_context` 增加 `provenance_url → 同编号`映射桥。原因:sources[].url canonical 化后,rerank 候选仍带原始 GitHub blob URL,不补桥则 wiki chunk 全部落入 `dropped_public_chunks`、CIT-01 权威编号断裂(INT-G008 会失败)。无 provenance_url 时行为与基线逐字节一致(`test_citation_integrity.py` 539 行全绿)。
3. **rag.py(d01a2a7 pick,9 处)**:`_social_answer`(UX B)与 `_run_qualifier`/`_lead_decide`/`_lead_stage`(Lead)并存;`answer()`/`stream_answer()` 签名同时保留 `page_context`/`site_name`(MSW)与 `lead_ctx`;`_build_messages` 单次调用合入 `cite_ctx.context` + `page_hint` + `lead_instruction`;trace 同时含 `citation_integrity` 与 `lead` 阶段;拒答路径保留 Lead payload 收敛逻辑。
4. **routes.py(7 处)**:ask() 同时保留 site 授权(`site_id` 持久化)、生成可靠性(`EmptyGenerationError` 失败分类/error 事件)与 lead 上下文/落库三套状态机;`Conversation(site_id=…, session_id=…)` 双列并存。
5. **models.py(1 处)**:`idx_conversations_site` 与 `idx_conversations_session_id` 两索引并存。
6. **657338b(1 处)**:报告载体文件缺失,按验收时点内容重建(见 §3)。
7. **lint**:合并引入的 SIM102 嵌套 if 合并为单条件(语义不变,行为由门用例复验);基线既有 F841(`rerank_fallback`,f874ee4 上已存在)**不修改基线代码**。

冻结语义零妥协:无测试弱化、无产品行为重设计、无未验收内容搭车。

## 5. INT-G001~G010 行为实证

测试文件:`tests/pipeline/test_accepted_changes_integration_gate.py`(11 用例,全过)。设计原则:只 mock LLM 与检索,`match_social`/`wiki_canonical_url`/`detect_contact`/`decide_invite`/邀请决策全部走**真实实现**;断言的是编排行为(事件序列/messages 内容/trace/payload),不是代码形状。

| 门 | 场景 | 证明 | 结果 |
| --- | --- | --- | --- |
| INT-G001 | "你好"/"hello"(且会话已有 qualified 线索的最不利前提) | 单 complete 事件 intent=smalltalk;searcher 未调用;qualifier 未运行;complete 无 `lead` 键(routes 因而不落库);answer/stream 双路径 | PASS |
| INT-G002 | "请给我写一首关于量子宇宙的诗" | 友好边界话术(非旧生硬拒绝);不进 RAG;off_topic+无线索 → qualifier 不运行,零 lead | PASS |
| INT-G003 | "NE301 是什么产品?"(potential) | 正常 RAG 作答;`invited=False`;生成 system prompt 无邀请/确认指令(商业意图≠lead) | PASS |
| INT-G004 | "你好,NE301 支持什么功能?" | 真实 `match_social` 整串语义不命中;走完整 RAG(trace type=rag),未被 smalltalk 吞 | PASS |
| INT-G005 | "We need 500 NE503 units for a project and need a quotation." | 正常有用的商业回答先生成;`invited=True`/`level=qualified`/fields 正确;邀请指令内嵌于回答的同一 system prompt(答后邀请机制载体) | PASS |
| INT-G006 | 捕获轮(最不利:intent 判 off_topic + 检索为空) | 不被拒答吞掉;`ack=True`/`invited=False`;**PII HARD**:邮箱原文不出现在任何 LLM 消息、generate 调用、trace、SSE 事件;trace 只带 `{type, masked}` | PASS |
| INT-G007 | 纯联系方式轮("john.acme@example-corp.com") | `match_social` 不命中;off_topic 判定下仍走捕获;ack 确认,无边界拒绝 | PASS |
| INT-G008 | qualified 商业问题 × Wiki 证据 | sources:Wiki → canonical `wiki.camthink.ai` + `provenance_url` 留 GitHub blob(可溯源);非 Wiki URL 零变化;LLM 上下文呈现 canonical 不呈现 blob;lead 同轮 `invited=True`;citation_integrity 与 lead 阶段共存于同一 trace | PASS |
| INT-G009 | answer() vs stream_answer() 同场景 | is_answered/intent/sources(canonical)一致;lead 决策一致(stream 经 complete payload,answer 经 trace stages) | PASS |
| INT-G010 | Website/WooCommerce/非 wiki GitHub 源 | URL 全部原样,无 `provenance_url` 键 | PASS |

## 6. 回归验证(TESTS)

环境:主仓 venv(PYTHONPATH 指向集成工作树);**一次性隔离库 `ask_ai_intgate`**(避免共享 ask_ai_test 被并行任务重建干扰);models 软链主仓缓存 + `HF_HUB_OFFLINE=1`(全程零网络下载,本地已下载权重直接加载)。

| 套件 | 结果 |
| --- | --- |
| 后端全量 `tests/`(隔离库) | **906 passed, 5 skipped** |
| UX B 聚焦(social/canonical_url/rag_citation_source) | 39 passed |
| Sales Lead 聚焦(qualify/rag_lead/lead_service/leads API/ask_lead_flow/business) | 116 passed |
| `tests/pipeline` + `tests/api` 终态复跑(含门用例) | 585 passed |
| `tests/api/test_site_routes.py` + widget hosting(三站契约面) | 15 passed |
| Admin `tsc -b --force` | exit 0,零错误 |
| Admin vitest | **172 passed(34 文件)** |
| Widget vitest | **57 passed** |
| 迁移 `migrate_sales_leads.py` | DROP 后创建路径 [ok] + 幂等重跑 [skip],双路径实证 |
| 迁移 `migrate_conversations_session_id.py` | 创建 [ok] + 幂等重跑 [skip];schema 实证 `session_id`/`site_id` 两列、两索引并存,冻结 schema 未被意外改动 |

已知非集成失败(基线对照实证):

- `tests/embedder/test_bge.py` 4 个失败:**在未改动的基线 f874ee4 工作树上完全复现同 4 个**;根因是该文件内单测对模型缓存路径的环境泄漏(测试隔离缺陷),单独运行即通过(本地权重可正常加载)。非本集成引入,不在本门修复范围。
- `tests/scripts/test_migrate_llm_chain_format.py` 3 个 error:该文件 fixture 强制要求 DSN 为 `ask_ai_test` 库(防误伤保护),对隔离库拒绝运行;按其要求在 `ask_ai_test` 上运行 → **4 passed**。

## 7. 三站配置契约(§7 required verification)

- `config/sites.yaml`:camthink-website / camthink-wiki / camthink-store 三站齐全,**默认语言全 `en`**(含 a26f1a4 的 wiki zh→en 对齐及宿主页面语言优先注释);
- 站点身份语义未变(Origin 授权/site 门禁/display_name);
- Headless browser-direct API 行为:契约文档(CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md v2.0)在位,后端站点路由/site-config/ask 门禁用例全绿(15 passed);
- 多语言 Gap G-L1~L5 未在本门处理(按任务书);生产 API base 未激活。

## 8. 生产边界(Production Boundary)

- PRODUCTION_ACCESS = **NO**:未 SSH、未读写生产 DB/Weaviate、未触发同步、未部署、未改 DNS/CORS/路由;
- PRODUCTION_MUTATION = **NO**:迁移仅在本地一次性隔离库 `ask_ai_intgate` 上验证(用后 DROP);
- 生产激活前置(channel_visibility 迁移、sales_leads/session_id 迁移、store CORS 补齐、ask 冒烟)全部留给各自授权 Gate。

## 9. UNRESOLVED_RISKS

1. **citation.py 集成桥需 Planner 知悉**:为使 canonical 化与 CIT-01 权威编号共存,`build_citation_context` 新增 provenance_url→同编号映射(+12 行)。无 provenance 时行为与基线一致(citation 完整性套件全绿),但这是本门唯一触及 P1 已验收模块的改编点。
2. **embedder 测试隔离缺陷为基线既有**(见 §6),建议另立微小任务修复该测试文件的环境泄漏,与本门无关。
3. 三个输入的报告/契约文档以主仓 force-add 文件为准;docs/ 独立本地仓与主仓互不可见的既有约定未改变。
4. 生产侧既有未解事项不受本门影响:channel_visibility 迁移未跑、store 站 CORS 未放行、T4 GPU 显存饱和——均在相应发布/运维 Gate 职责内。

## 10. 交付物

- 集成分支(7 提交,线性):`integration/camthink-v1-accepted-product-changes-2026-09-02` → 已推 origin
- 门用例:`tests/pipeline/test_accepted_changes_integration_gate.py`
- 本报告:`docs/implementation/CAMTHINK_V1_ACCEPTED_PRODUCT_CHANGES_INTEGRATION_2026-09-02.md`
