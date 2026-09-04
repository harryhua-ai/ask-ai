# v1.0.1 Track A — Issue #19 Comparison Answer Correctness 执行报告

- baseline:0e6a8a3(v1.0.0,= origin/main,实查未前进)
- branch/worktree:`v1.0.1/track-a-issue19` @ `.worktrees/v101-track-a-issue19`(独立 .env/models 物理拷贝,无软链)
- authority:Discovery 报告 fa0c192(READY),未重做 Discovery、未采信旧 issue body
- **STATUS:CANDIDATE READY**;commit:**9bc7ea2**(已推 origin)

## 工程根因(继承 Discovery,实码复证)
RC1 comparison 无 per-target 证据获取;RC2 woo 类别映射列表序先命中先胜致设备页误标;RC3 PC-01 把 B/C/D 型混同 service_unavailable。

## 实现(变更文件)
1. `backend/pipeline/rag.py`:comparison 分支 = 每 target 以自身资格标签集独立跑既有三路融合管线 → `_merge_per_target_candidates` 轮转配额合并(quota=max(1,top_k//n),rest_cap 回填共享/平台,(source_id,chunk_index) 跨路去重)→ rerank/prune/纵深过滤后 **D-preflight 终检**:任一 target 缺自身标注证据 → `_comparison_insufficient_reply`(冻结键 `comparison_evidence_insufficient`,占位 {products}/{missing})+ `complete(is_answered=false,result_key=…)`,lead 邀请收敛同拒答纪律。PC-01 分型:C 型(citation_filter 三计数>0 且零内容)→ 产品/比较不足语义(complete is_answered=False);B 型(零剔除零内容)维持 EmptyGenerationError。
2. `backend/api/routes.py`:error 事件对 empty_generation 附 `reason="model_empty_stream"`(加性字段,旧客户端可忽略)。
3. `backend/utils/user_messages.py`:新冻结键 `comparison_evidence_insufficient`(zh/en,MESSAGE_KEYS 入表)。
4. `backend/connectors/woocommerce.py`:设备身份优先由 name+slug 经 taxonomy 别名扫描派生(仅认 kind=product,platform 桶不认领,失败不猜);类别映射拆 `_DEVICE_CATEGORY_MAP`(含 ne302/ng4500)先查、`_BROAD_CATEGORY_MAP` 后查;`accessories` 归一 canonical `commercial`(消除 ingest 与 #5 迁移后存量的标签漂移)。
5. `scripts/migrate_store_device_metadata.py`(新):商店设备页元数据迁移,dry-run 默认、--apply 原位属性更新、零 re-embed,与 ingest 共用 `_device_identity_from_text`。
6. citation.py:**零变更**(Discovery 预判成立,stats 已供 C 检测)。schema:**零变更**。

## 测试(实跑)
- 新增 `tests/pipeline/test_issue19_comparison.py`:配额结构保证(饥饿侧必入候选)、缺失侧上报、共享证据不计 target、跨路去重、不足语义键/文案、F1 查询 resolver 重放、商店派生正例/平台负例、类别映射设备优先、_product_to_document 端到端。
- 按新合约更新 4 处旧预期:CIT-G010 与 INT-CHK-002b(C 型→不足语义 complete,安全不变量「绝不伪装成功」保持)、Scenario-H 与 comparison-scope(per-target 调用形态);woo accessories 断言→commercial。
- 实跑结果:pipeline+connectors+retrieval+taxonomy **781 passed,0 failed**;focused 24/24;ruff(自有文件)clean;black(新文件)clean。

## Scope audit / 生产影响
仅触及 Discovery 授权边界内文件;#5 exact 路径零触碰(其回归全绿);无 schema/无 re-embed;上线后需一次商店元数据迁移(dry-run→人工核对→--apply,≤40 chunk 量级)与代码发布同窗或先后皆可(向后兼容)。

## 未决风险
- D-preflight 文案对「检索有但 prune 剔净」的极小概率场景表述为「暂未找到」(与最终上下文一致,可接受);
- B 型 provider 侧机制(v4-flash 零内容)开放,本 track 只保证可观测与语义分型;
- per-target 检索使 comparison 查询检索成本 ×n(正确性优先;如需优化回 #23 通道)。
