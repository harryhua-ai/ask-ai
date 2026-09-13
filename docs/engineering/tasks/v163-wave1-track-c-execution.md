# V1.6.3 Wave 1 Track C 执行报告 — Data Source Product Completion(U-6..U-13)

- **分支**:`track/v163-c-b1-product`(worktree ask-ai-v163-wc;唯一实现树,未建新 worktree)
- **基线**:PREP_BASE_SHA = `d613e6a`(FINAL_PREP_BASE;父链 7e3e71c→c016d50→acc6756→f83740c→d613e6a;merge-base(HEAD,7e3e71c)=7e3e71c 复核 PASS)
- **Candidate SHA**:`a4e21cc`(本报告冻结后 tip 以 push 为准)
- **verdict 建议**:**CANDIDATE READY**(八项全部实现+运行时验收;三项 contract 内接口触点见 §6)

## 1. 范围与语义闭环(八项)

| 项 | 参考需求 | 后端真值 | 前端呈现 | 状态 |
|---|---|---|---|---|
| U-6 品牌内建映射 | DS-P2-02 | —(呈现层) | `lib/sourceBrand.ts`:类型→色块/字形内建映射(woo 紫 #7F54B3「W」/github「G」/web_crawl/filesystem/local_git;未知回退首字母);**零远程 logo_url** | ✅ |
| U-7 逐文档 content_type | DS-P2-16/20 | `documents.content_type` 加性列 + `content_taxonomy.py` 结构化推导;连接器写入点(woocommerce=product/web_crawl=按 URL 后缀 page\|document/filesystem+github+local_git=document);`ingest._upsert_postgres` 持久化;API items 列+`content_type` 过滤(`none`=不可用行)+`content_type_counts` 账本聚合 | 类型列=后端真值(product→商品/page→页面/document→文档;null=「—」title 存量不可用,禁推断);类型过滤 select=账本聚合词表 | ✅ |
| U-8 行级修复 | DS-P2-25/26、P3-07/08/09 | `document_repair_tasks` 表;POST `/{id}/documents/repair`(RBAC=EditorDep);幂等=(doc,idempotency_key)+开放任务唯一+健康文档 no-op 复验;审计=events 追加;进度=stage(plan/repair/verify);语义=持久 chunk 副本回放(corpus_repair/gap-heal 同源:确定性 uuid、零源抓取);向量库不可用→503 | 需处理行「处理」+每行「⋯」(重新处理/查看真相);验证卡(vN/chunks 4/4/一致性 ✓通过=任务 result 真值);修复中文案态 | ✅ |
| U-9 chunk serving | DS-P3-05 | `chunk_serving.py`:verify_source_vectors 同口径(迭代器全扫+客户端 source_id 精确匹配);单文档投影 serving/total/missing/stale;truth 端点注入;向量库不可用→null(不伪造) | 展开行「X / Y 在服/不完整」=后端投影 | ✅ |
| U-10 恢复计数 | DS-P3-06(P4-10 带内) | `document_recovery_events` 表;写点=sync.py 无变更跳过分支 gap-heal refill 逐文档记账(尽力而为,零行为变更);truth 端点权威计数 | 「系统已自动尝试恢复 N 次,未成功。」=recovery_attempts_failed | ✅ |
| U-11 next_run_at | DS-P4-03 | `data_sources.next_run_at` 持久列 + `schedule_truth.py` reconcile(禁用→paused/进行中→syncing/从未同步→waiting_first/删除流程→deleting,均 NULL;否则 last finished+interval,过期持久真实时点);schedule 端点+列表读面 reconcile+PUT 配置变更即刷新 | SyncActivityPanel「下次同步」=权威值(未来 X小时后;过去「已到期待调度」;NULL→状态词);**零纯派生** | ✅ |
| U-12 知识设置 | DS-P6-01..05 | `knowledge_role/freshness_hours` 政策层加性列(叠加 lifecycle,零 lifecycle 列改动);GET/PUT settings;新鲜度真值(后端权威 overdue 判定,超期态 Admin 可见);**检索资格消费**=HybridSearcher `knowledge_exclusion_provider`(HISTORICAL 源 chunk 过滤;fail-closed;TTL 缓存) | KnowledgeSettingsDrawer:时态角色(CURRENT/HISTORICAL+参考说明)/新鲜度要求(6/12/24/72/168h+参考说明)/超期提醒/详情页超期 banner | ✅ |
| U-13 高风险预览 | DS-P7-01..06 | `knowledge_settings_previews` 快照;preview 端点(compute_policy_impact 服务端权威:affected=账本全域/current_eligibility_change/historical_eligibility_change);确认校验=token 有效+pending 策略与请求一致+ledger_fingerprint 一致,drift→409 失效(stale);确认后重验快照回写 | RiskPreviewModal:before→after(红)/三行计数(=预览端点)/不会删除持久知识/变更后重新验证说明/取消+确认变更(红,带 token);drift 提示重新预览 | ✅ |

## 2. 契约附录 IF-3(修复命令契约冻结稿,Track C 交付)

- `POST /api/admin/data-sources/{source_id}/documents/repair`(admin/editor;viewer 403)
  - 请求:`{doc_source_id: "<source_id>/<branch>/<rel_path>", idempotency_key?: string(≤100)}`
  - 响应 200:`DocumentRepairTaskOut {id, source_id, doc_source_id, status(pending/running/succeeded/failed), stage(plan/repair/verify), requested_by, idempotency_key, result{version_seq,chunks_serving,chunks_total,consistency(passed/failed),repaired_indices,repair_mode}, error, events[{at,event,...}], created_at, finished_at}`
  - 幂等:①同 (doc,idempotency_key) 已有任务→原任务;②同文档存在 pending/running→原任务;③健康文档重复→真实复验 no-op(0 repaired,复验通过)
  - 向量库/嵌入不可用→503(诚实降级,不受理不伪造);404=后端无此记录(文档不存在/跨源)
- `GET /api/admin/data-sources/{source_id}/documents/repair/{task_id}`(viewer+;进度/结果/审计)
- 修复语义:仅触碰计划内对象(缺失 index 的确定性 uuid 点写;无整表操作/无 TEXT 属性过滤删除)
- 修复后验证:重算 chunk serving 投影;serving==total 且无 stale→consistency=passed(验证卡唯一数据源)

## 3. 契约附录 IF-4(知识设置+预览契约冻结稿,Track C 交付)

- `GET /{id}/knowledge-settings`(viewer+)→`{role(current/historical 生效值), explicit_role, freshness_hours(生效值), explicit_freshness_hours, freshness{freshness_hours,last_success_at,overdue,overdue_hours_ago,basis}, updated_at}`;NULL 列=默认 current/24h(后端权威展开)
- `POST /{id}/knowledge-settings/preview`(editor+)→`{preview_token, current_policy, pending_policy, impact{affected_documents,current_eligibility_change,historical_eligibility_change}, expires_at(30min)}`
  - 计数规则(服务端权威,预览/确认同函数):affected=源账本全域;role 变化时 current_eligibility_change=current_count(active∧现行版本可解析)、historical_eligibility_change=ledger−current;role 等值→两 change=0
- `PUT /{id}/knowledge-settings`(editor+)`{role, freshness_hours?, preview_token?}`
  - 时态角色变化=高风险:必须带 token;校验 token 有效/未消费/未过期、pending_policy 与请求逐键一致、ledger_fingerprint 与预览一致;任一不满足→409(「预览已失效/不一致/drift,请重新预览」);确认施加 mutation=pending_policy 快照;确认后重验(账本聚合+新鲜度+调度 reconcile)快照回写 revalidation
  - 新鲜度单独调整非高风险(无角色变化)可直接 PUT
- 检索资格消费(U-12 硬性):`data_sources.knowledge_role='historical'` 的源前缀集合经 `excluded_source_prefixes(_sync)` 供给 HybridSearcher;其 chunk 从检索候选过滤(仅历史/溯源/证据链,不支撑当前事实型断言);provider 未 wiring=行为不变;读取失败=fail-closed(与在服代 provider 同语义)

## 4. 测试数字(三门)

| 门 | 结果 |
|---|---|
| pytest 全量(串行,TEST_DATABASE_URL=ask_ai_test_c,HF_HUB_OFFLINE=1) | run1 2516/5/7(失败=recovery_semantics×3+sync_executor_loop×1 等 flaky 族)→ **run2 2520 passed / 0 failed / 8 skipped**(2500 基线+20 新增,精确收敛;失败集单跑 32/32 PASS 证实非行为漂移) |
| 新增后端用例 | `tests/api/admin/test_data_sources_track_c.py` 20 用例(U-7×3/U-8×5/U-9×2/U-10×1/U-11×4/U-12×3/U-13×2 含真实 stub 注入) |
| vitest 全量 | **466/466**(453 基线+13 新增 TrackC;含既有 detail/convergence 按冻结语义更新) |
| tsc -b | 0 errors |
| build | ✓ built(2.08s) |
| ruff | 新增/修改文件零新增告警(web_crawl 2 条=基线既有) |
| PA | tests/project_automation 114/114(收尾复核 134 passed 含 workspace 20) |

TDD 纪律说明:按「每项 RED 先行」执行,实际节奏为批量实现后同会话内写测试并以红→绿循环收敛(test_data_sources_track_c 首轮 7 failed→逐项修正至 20/20;前端 TrackC 首轮 7 failed→13/13);无跳过验证环节。

## 5. Runtime acceptance(本地真实栈 8123+5223,ask_ai 库+真实 Weaviate 8080+CPU BGE)

**seed(WC_ 标记,仅本地;操作全文)**:
- 迁移:`python scripts/migrate_add_track_c_product.py` → 加性列/三表 + U-7 存量行推导回填 **1228 行**(woocommerce→product 8/web_crawl→page 1208/filesystem+github→document 12;零 NULL 残留;零文本语义推断)
- `WC_SEED_1`(向量精确点删,uuid5 寻址):`coll.data.delete_by_id(uuid5("store-woo/main/legacy-pricing#2"/"#3"))` → True/True(制造 0/4 serving 缺口)
- `WC_SEED_2`(SQL 全文):`INSERT INTO document_recovery_events (id,source_id,doc_source_id,outcome,detail) VALUES (<uuid4>,'store-woo','store-woo/main/legacy-pricing','failed','{"mode":"gap_heal_refill","seed":"WC_SEED_2"}');`

**八项动作链(UI→API→DB 三角)**:
1. **U-8 修复链**:UI Legacy Pricing 行(需处理)「处理」在位 → POST repair(WC_REPAIR_E2E_4)→ 任务 succeeded:`result={version_seq:1,chunks_serving:4,chunks_total:4,consistency:passed,repaired_indices:[0..3],repair_mode:persisted_chunk_replay}` → 真实 BGE CPU 嵌入回放 4 chunks 入 Weaviate → DB 任务行+events 审计在库 → 展开行验证卡「v1 · 4/4 · ✓通过」(截图 07)。幂等复跑(WC_REPAIR_E2E_5)→ no-op `repaired_indices:[]` passed。失败诚实性:E2E_2(CUDA 缺失)/E2E_3(float32)如实 failed+error 在案
2. **U-12/U-13 知识设置-预览-确认链**:Drawer 改 HISTORICAL+12h → 保存 → POST preview `impact={affected:8,current_change:5,historical_change:3}`(=服务端账本真值:current_count=5)→ Modal 呈现 → 确认(PUT+token)→ DB `knowledge_role='historical',freshness_hours=12` → **检索资格实时变化**:重开设置读=historical;`excluded_source_prefixes=['store-woo']`;真实 HybridSearcher(真 Weaviate+真 provider)query "shipping" 20 结果 0 条 store-woo → 恢复链二次预览-确认回 CURRENT(截图 08/09)
3. **新鲜度链**:设置 GET `overdue:true(37.88h/50.2h,basis=last_success/never_synced)`;详情页琥珀 banner「已超过新鲜度要求(12 小时)…」+ Drawer 超期提醒实时呈现(截图 01/08)
4. **U-11 倒计时链**:partner-portal 真实同步(CLI,manual)完成后 schedule=`{next_run_at:finished+24h,state:scheduled}` → UI「下次同步: 23小时后」(截图 05);存量 pending request 期间 UI=「同步进行中」(05b);禁用/从未同步→NULL 状态词(pytest 覆盖)
5. **U-7 类型链**:store-woo documents `content_type_counts={product:8}`;类型列=商品;filter=product→8 行/none→0 行存量不可用;partner-portal(真实 filesystem 同步写入链)6 行=document(截图 02/02b/02c)
6. **U-9 分数链**:seed 缺口后 truth `0/4,missing[0..3],consistent:false` → 修复后 `4/4 consistent:true`;UI 比例=后端值(截图 03)
7. **U-10 注记链**:WC_SEED_2 事件 → UI「系统已自动尝试恢复 1 次,未成功。」;**真实写点实证**:partner-portal 真实同步 gap-heal 3 篇未修复 → 3 条 failed 事件由 sync.py 写点自动落库(非种子)
8. **U-13 drift 链**:preview(token)→ 账本插入 WC 探针行 → confirm → **409「账本已变化(影响计数 drift),预览失效;请重新预览后确认」**+预览行标 stale → 探针行删除;策略不一致(预览无 freshness/提交 6h)→409;无效 token→409(pytest+双实测)

**fixture 清理**:漂移探针行已删;存量 pending sync_requests(ids 3/4/5,前轨残留+本次触发 1 条)已清;修复任务/恢复事件行保留(本地审计证据,idempotency_key=WC_REPAIR_E2E_*、detail.seed=WC_SEED_2 标记);Weaviate legacy-pricing 4 对象=修复产物(真实在服内容)

**截图(1536×1024 @1x,ask-ai-acceptance/v163-wave1-c-20260913/)**:01 品牌头(U-6)/02 类型列+过滤(U-7)/02b filter=product/02c filter=none/03 serving 4/4(U-9)/04 恢复注记(U-10)/05 next_run_at 23小时后(U-11)/05b 同步进行中/06 处理+行 ⋯(U-8)/06b 菜单重新处理/07 验证卡 v1·4/4·通过(U-8)/08 知识设置 Drawer(U-12)/09 预览 Modal 8/5/3(U-13)+ `capture.mjs`/`ui-action-log.txt`

## 6. Scope audit(零检索/排序/引用语义漂移)

- 35 文件(30 代码+3 测试+2 报告待提交);**他轨禁触面零改动**:Analytics 面/tech*.py/gap_*.py/SourceEditorDrawer/Sidebar/Layout/AnswerGapsTab/GapPanel/DataSources.tsx 全部零 diff(git 实证)
- 检索/排序/引用语义审计:检索=只加 HISTORICAL 排除(provider 未 wiring 行为不变;无排序/评分改动);documents 排序/order 参数零改动;引用/citation 面零接触;既有 2520 测试零改基线(仅 C-owned detail/convergence 测试按 U-7/U-8/U-12 冻结语义更新,Forbidden 守卫改为授权呈现锁定,更新点均在报告 §1 语义内)
- **接口触点(3,合同内授权,非 EXPANSION)**:①`backend/main.py` lifespan 注入 knowledge_exclusion_provider(~20 行加性块;U-12「资格判定贯通检索服务」硬性要求);②`backend/retrieval/search.py` HybridSearcher 加性 provider+候选过滤(U-12 检索挂钩本体;None=行为不变);③`scripts/sync.py` gap-heal 后逐文档恢复事件记账(~30 行加性,尽力而为;U-10「恢复事件记录」写点;DS-P4-10 恢复事件权威化归 U-10)。另:`SyncActivityPanel.tsx`(DS-P4 面板,他轨未认领,D 的 banner 文案面在 DataSourceDetail 侧)+`dataSourceOps.ts`(新增纯函数 untilRelativeTime,既有函数零改动)
- 禁止捷径核对:无 frontend-only fake state/无 fake counts(影响/恢复/serving 全后端)/无 fake next_run_at/无 UI-only repair/资格语义已消费/确认=预览一致 mutation/无任意远程 logo/无前端 content_type 推断/未关 issue/未 merge/未 deploy/未新增豁免

## 7. Issue 映射(落地完成,待 Integration 统一关闭;本轨未操作)

- #54(详情:品牌/类型/修复/知识设置/预览)、#55(检查器:serving 分数/恢复计数/验证卡)、#56(历史:下次同步)—— 实现与验收证据齐备

## 8. STOP 确认

未 merge/未 deploy/未关 issue/未建新 worktree/未触他轨禁改文件/本地库 mutation 均按 §5 记录且限本地。**Track C verdict:CANDIDATE READY**
