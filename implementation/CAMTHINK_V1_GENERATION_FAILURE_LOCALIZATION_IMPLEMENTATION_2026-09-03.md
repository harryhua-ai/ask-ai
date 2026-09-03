# CAMTHINK V1 — ⑯ 生成失败/本地化 实现报告(2026-09-03)

- 角色:Engineering Implementation Agent(WINDOW B)
- 基线:`269cadb0ce6a3ce47059e0f4b074f356e41612eb`(= origin/main,已 fetch 核验)
- 分支:`worktree-exec/generation-localization-20260903`(独立 worktree `.worktrees/generation-localization`,物理拷贝 .env,未提交任何凭据/模型/运行时资产)
- 实现提交:**7912ccc**(基线之上单提交,线性,零 merge)
- PRODUCTION_ACCESS:NONE;未合并 main;未部署
- Discovery 依据:本文档仓 `CAMTHINK_V1_GENERATION_FAILURE_LOCALIZATION_DISCOVERY_2026-09-03.md`(e6b249b,FINAL PASS),实现前在 baseline 上重新读取全部真实实现

## 1. 交付概览

| 任务要求 | 落地 |
|---|---|
| 冻结语言规则(单一 authority) | routes 在 SSE generator **之前**调用同一 `resolve_answer_language(masked_message, req.language or site.language)`,与 rag 入口同函数同输入(纯函数确定性等值),零算法复制 |
| 用户消息语言归一 | 新增 `conversation_language()`(language.py):新写入 Conversation.language 仅 zh/en(中文→zh,其余→en);无历史迁移 |
| 冻结文案 | 新模块 `backend/utils/user_messages.py`:service_unavailable / budget_declined / no_evidence 三键,文案逐字取任务契约;zh→中文,其余→英文;未知键 fail-safe 回落 |
| 失败分类 | empty_generation / provider_error(保留原名,语义=首 token 前管线失败)/ stream_interrupted 逻辑不动,仅文案本地化 + error 事件增 `message_key` |
| Budget Declined | 真实 Conversation(id=真实 uuid、question、answer=本地化繁忙文案、language 归一、is_answered=False)+ Trace(type=`budget_declined`,config_snapshot.outcome=declined);declined/done 事件下发真实 conversation_id + reason 本地化 + message_key;不进 generation_error taxonomy |
| Admin 分类 | 列表 trace_summary 增 `failure_kind`(additive);详情端点增 `trace_type`/`failure_kind`;新纯函数 `admin/src/utils/outcome.ts` deriveOutcome:已回答/拒答(reject_short)/生成失败(generation_error)/服务繁忙(budget_declined),列表+详情徽章均接入;筛选项「拒答」改为「未回答(拒答/失败/繁忙)」 |
| SSE 兼容 | error/declined 增可选 `message_key`;`message`/`reason` **恒保留且已本地化**;事件序列/形状零变化;widget useSSE 兜底常量可注入双语(缺省保持旧中文常量),messageKey 透传进 meta |
| no_evidence | rag 拒答文案函数化 `_reject_answer(language)`(answer 同步路径 + stream 路径),zh/en 冻结文案;off_topic/social 既有双语不动 |

## 2. 变更文件(18)

后端:`backend/utils/user_messages.py`(新)、`backend/utils/language.py`(+conversation_language)、`backend/api/routes.py`、`backend/pipeline/rag.py`、`backend/api/admin/conversations.py`;
Admin:`admin/src/utils/outcome.ts`+`.test.ts`(新)、`admin/src/pages/Conversations.tsx`、`admin/src/hooks/useConversations.ts`、`admin/src/types/api.ts`;
Widget:`widget/src/i18n.ts`(+serviceBusy)、`widget/src/hooks/useSSE.ts`、`widget/src/App.tsx`、`widget/src/hooks/__tests__/useSSE.test.ts`;
测试:`tests/api/test_failure_localization.py`(新 13 例)、`tests/api/test_reliability.py`(mock complete 语言真实性修正 + EN 用例断言)、`tests/pipeline/test_rag.py`(2 处 EN 拒答期望)、`tests/api/test_unified_v1_gate.py`(EN 失败期望)。

## 3. 验收对照(AC1-AC12 全过)

- AC1/AC2:`test_en_provider_error_gives_en_fallback` / `test_zh_provider_error_gives_zh_fallback`(EN query 失败→英文文案、ZH→中文,DB/answer/事件三面断言)
- AC3:routes 与 rag 均调 `resolve_answer_language`,无第二套算法(代码审查 + 确定性论证:同输入纯函数)
- AC4:`conversation_language` 二值归一 + `test_zh_query_without_hint_language_normalized_zh`(zh-cn→zh)
- AC5/AC6:`test_budget_declined_en_persists_real_conversation`(真实 id=done id=Conversation.id、DECLINED trace、独立于 generation_error)
- AC7:Admin deriveOutcome 三分类 + API trace_type/failure_kind 下发(`outcome.test.ts` 5 例)
- AC8:三类失败 kind 与 trace failure_kind 断言保持原语义,名称未改
- AC9:no_evidence EN/ZH(`localized_message` 矩阵测试 + rag EN/ZH 路径)
- AC10/AC11:旧客户端 message 恒保留;widget 72 测试全绿(含旧契约用例);message_key 仅 additive
- AC12:SITE_DENIED_MSG/site_denied 零触碰(测试矩阵断言未知键 fail-safe,未引入 site_denied 文案)

## 4. Negative Acceptance(逐项证明)

| 必须不出现 | 证明 |
|---|---|
| EN 失败→中文兜底 | `test_en_provider_error_gives_en_fallback` + unified_v1_gate EN 用例(英文断言) |
| ZH 失败→英文兜底 | `test_zh_provider_error_gives_zh_fallback` / `test_zh_stream_interrupted_...` |
| Budget Declined 幽灵 UUID | declined/done id 一致性断言 + Conversation.id==id 断言 |
| 失败被 Admin 显示为拒答 | deriveOutcome(generation_error)→「生成失败」;旧数据无 trace 才兜底「拒答」 |
| budget_declined 计入 generation error | trace type 断言 + `_infer_markers`(type≠generation_error 且 stages 空 → failure=False) |
| 旧客户端因 message_key 破坏 | message 恒在;widget 旧用例逐字断言中文兜底路径仍绿 |
| Conversation.language 写入非 zh/en | `conversation_language` 二值 + 13 例新测全经该函数 |

## 5. 测试与回归证据

| 套件 | 结果 |
|---|---|
| 新增 backend(test_failure_localization) | 13 passed |
| targeted(reliability/routes/multilingual×2/admin conversations/rag/unified gate/integration gate/trust boundary/attachments) | 全绿(30+86) |
| **全量 backend** | **1079 passed / 6 skipped / 0 failed,85.39s**(基线 1058+21 新增,零回归;暖缓存 offline 环境) |
| widget vitest | 72 passed(67 旧+5 新/改) |
| admin vitest | 190 passed(含新 outcome 5 例) |
| widget/admin `tsc --noEmit` + `npm run build` | 全过 |
| ruff/black | 本轮文件 clean;conversations.py/test_rag.py 的 black 漂移与 2 处 ruff 项(F841/B008)经 git stash 对照确认为**基线既有**,按「black 只植增量」纪律未动 |

测试基建修正说明:新测试文件含 autouse `limiter.reset()`(先例 test_unified_v1_gate),因新用例密频调用 /api/ask 会耗尽 20/min 共享限流计数——非产品代码改动。REL-G001 的 mock complete.language 由 "en" 改 "zh-cn" 是让 mock 与中文 query 自洽(真实 rag 经 resolver 返回检测原值),非放松断言。

## 6. Known Limitations(诚实边界)

1. 旧 widget(缓存滞后)忽略 error 事件时,兜底 token 文本会以普通气泡呈现——服务端文案已本地化,呈现层级差异为文档化降级(discovery §3.4 既有结论)。
2. `provider_error` 名称保留(兼容),字面仍含检索/重排崩溃(首 token 前管线失败),语义已注释+报告声明(PD-5)。
3. 非 en/zh 语言(ja/ko/fr)失败/繁忙/拒答文案回落英文(冻结规则:非 zh 即 en);off_topic/social 既有同构语义。
4. intent/rewrite 供应商故障仍 fail-open 静默降级(MF-9,discovery 声明的既有边界,本轮不扩)。
5. Conversation.language 仅约束新写入;存量 zh-cn/en 混落行按契约不做迁移。
6. site_denied 403 detail、全局 500、429、附件错误文案维持现状(任务 OUT OF SCOPE / PD-6)。

## 7. Self-Check

- CODE_MUTATION 范围:仅上述 18 文件;无 acceptance 改动让测试通过(改的 4 处既有断言全部是「EN query 期望中文」的过时期望,替换为契约冻结英文文案,语义强化而非放松);
- 无生产接触、未合并 main、未部署;.env 为物理拷贝且未入库;node_modules 为软链(便于前端测试)不入库;
- 最终状态:**CANDIDATE READY**(待 Planner FINAL REVIEW)。

---

## 8. FINAL_REVIEW_CORRECTION(2026-09-03,Planner PARTIAL → 修正)

- CORRECTION_BASELINE:7912ccc(原实现提交,未 squash,线性追加)
- **CORRECTION_COMMIT:65e57eb**(已推 origin 同分支)
- 范围纪律:仅修两个 Blocker,零重构、零扩项,Stage⑯ 全部既有行为(EN/ZH 六类、Admin 分类、SSE 兼容、message_key、site_denied OUT、无历史迁移)保持。

### BLOCKER_A_RESOLUTION(Budget Declined 幽灵 conversation_id)

- 根因:原实现持久化失败仅记日志,仍以该 UUID 下发 declined/done → 客户端拿到未持久化的身份。
- 修法(routes.py):引入 `declined_persisted` 成功标志——**仅当 Conversation+Trace commit 成功才把 conversation_id 放入 declined/done payload**;持久化失败 → declined/done **完全不含 conversation_id 键**(诚实缺省,绝不伪造已持久化身份),本地化繁忙文案 + message_key 照常,declined→done 事件序列与「无 error 事件」不变(DECLINED ≠ FAILURE 不破)。
- 契约不变量:「凡下发的 declined Conversation 身份必对应一次成功持久化」由测试强制(见下);widget 对 done 缺 id 的行为 = conversationId 置空 → feedback 静默 no-op,与旧幽灵 id 的实际效果等价但语义诚实。

### BLOCKER_B_RESOLUTION(complete 缺 language 覆写权威语言)

- 根因:`language = data.get("language", "en")` 在 complete 缺 language 时把前置权威解析值重置为硬编码 en。
- 修法(routes.py):`language = data.get("language") or language`——前置 `resolve_answer_language` 结果保持为唯一回退真相;complete 有值时与前置值恒等(同一 resolver 同输入),语言算法仍单一,无第二套实现。
- 兼容:complete.language 若有值,经既有 `conversation_language()` 归一后落库,冻结 zh/en 规则不受影响。

### NEW_REGRESSION_TESTS(tests/api/test_failure_localization.py,+4,TDD 先红后绿)

1. `test_budget_declined_persistence_failure_emits_no_ghost_identity` — commit 强制抛错 → declined/done 均无 conversation_id,reason/message_key 保留,无 error 事件,且持久化尝试确实发生(语义不弱化);
2. `test_budget_declined_success_still_emits_real_id` — 成功路径护栏:真实 id 照常下发(防修过头);
3. `test_complete_without_language_keeps_authoritative_zh` — 中文 query + complete 缺 language + 零内容 → 兜底 token/error 文案仍中文 + Conversation.language=zh;
4. `test_complete_without_language_keeps_authoritative_en` — 英文等价(兜底英文 + language=en)。

### FINAL_TEST_RESULTS

| 套件 | 结果 |
|---|---|
| test_failure_localization.py | **17 passed**(13+4) |
| targeted(reliability/routes/admin conversations) | 全绿 |
| **全量 backend** | **1083 passed / 6 skipped / 0 failed,82.78s** |
| widget vitest | 72 passed |
| admin vitest | 190 passed |
| black/ruff(本轮文件) | clean(routes.py 剩余 B008 为基线既有、未触碰代码) |

### REGRESSIONS

零失败;修正未触碰 rag/admin UI/widget/Admin 分类,SSE 旧客户端兼容与全部既有断言保持。

### CORRECTION_COMMIT

`65e57eb`(`fix(stage16-correction)`,origin/worktree-exec/generation-localization-20260903)

**最终状态:CANDIDATE READY。**
