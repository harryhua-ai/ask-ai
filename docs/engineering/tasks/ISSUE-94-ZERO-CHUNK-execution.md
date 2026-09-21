# Issue #94 执行报告 — 零语义分块确定性分类(RECONCILABLE AUTHORITY 第三分区)

- Claim: `harryhua-ai-20260918T135924-627de129`(mode=implement,authority=allowed)
- Branch: `agent/94/e64b331f`(Candidate 1 base = `14735859`;**REVIEW_1 续轨已同步 main `1093c93`** = #100 merge)
- Contract: #94 body `ght-contract` v1(AC1–AC6,depends_on #91 已 CLOSED)
- 状态: **CANDIDATE READY(REVIEW_1 R2)— 待 Role A review**(STOP;不自行 merge)

## 0. REVIEW_1 R2 修正(2026-09-21,同 lineage)

Role A REVIEW_1(REQUEST_CHANGES)blocker:零分块被计入 `permanent_excluded`
且从 `eligible_count` 扣除 —— 违反「零分块 ≠ #91 永久安全排除;零分块仍是
eligible authoritative content」。

**修正**(`scripts/sync.py::_exclusion_delta`,最小 diff):
- `permanent_excluded` = **仅** #91 safety exclusion(`excluded_docs − zero_chunk_docs`);
- `zero_semantic_chunk` 独立分列(与 permanent_excluded **不相交**);
- `eligible_count` = 参与判定总数 − safety(零分块**保留在 eligible 侧**);
- 守恒算术:`eligible_count + permanent_excluded == new+updated+unchanged
  +metadata+safety+zero_chunk`;
- 零值键省略(「不制造无信息键」风格保持);全空批次返回空 dict。

RED→GREEN(4 新例,`test_issue94_zero_chunk_builder.py::test_review1_*`):
1. only-zero-chunk:permanent_excluded 缺席(0)、zero_semantic_chunk=2、
   eligible 含零分块(=3)—— RED 实证旧实现把零分块计入 permanent 并扣 eligible;
2. mixed(safety+zero):permanent=1/zero=1 不相交,eligible=total−safety,
   守恒 `3+1==4`;
3. pure-safety:既有 #91 行为零回归(permanent=N、eligible 扣除、无 zero 键);
4. 全分区组合算术:eligible+permanent == 全部参与判定数(7+5=12)。

同步 main 说明:merge `origin/main`(1093c93,#100)零冲突;#100 的
`SourceRootUnavailable` fail-closed seams 与 #94 分区逻辑共存,
`tests/scripts/test_source_unavailable_failclosed.py` 等 #100 回归全绿
(见 §7 R2)。

## 1. 基线审计(缺陷确认,与生产只读取证一致)

`generation_builder` Phase 1 中,合格权威文档经安全判定/物化后,
`chunk_document_semantic` 确定性产出 `[]` 的分支仅 `logger.info("切分为空")
+ continue`(`backend/pipeline/generation_builder.py:281`):不入账本、无
分类、无核算 ⇒ membership 每轮如实上报为 actionable missing ⇒ 永恒 missing
债(生产残留:ne301-local=5、lowpower-camera-local=18)。行为有界(零嵌入、
不毒化生成代),但账目不真 —— 正是本契约要修的面。

## 2. 设计(与 #91 同构的第三分区;单一事实源原则)

新表 **`zero_semantic_chunks`**(与 `ingestion_exclusions` 严格分表):

| 列 | 语义 |
| --- | --- |
| source_id (PK, VARCHAR(500)) | 每身份恰一行 = 对其当前权威内容的判定 |
| content_fingerprint (SHA-256) | 判定所针对的内容指纹(`doc.content_hash`) |
| chunker_policy_fingerprint (SHA-256) | chunker 策略确定性版本身份:`sha256("chunk-policy:v1|kind|max_tokens|overlap|max_chars")` |
| detail / times_confirmed / first_seen_at / last_confirmed_at | 审计与确认计数 |

核心不变式(与 #91 REVIEW_2/3 修正后的哲学一致):
- **本表只是记账,绝不是判定门**:builder 对到达它的内容每代永远重跑现行
  chunker(零分块文档每代重分块 = 纯 CPU 重评估,零嵌入零索引);
- **指纹双轴失效(AC3)**:内容或策略任一指纹变化 ⇒ 原位换判定;
- **有界压制**:membership 对账只在窗口内
  (`ZERO_CHUNK_REEVALUATION_DAYS=7`,自 last_confirmed_at)且内容指纹一致
  (连接器 `membership_content_fingerprints` 可得时,同 #91 R3 机制)把身份
  移入 `zero_chunk_ids`;过期/漂移 ⇒ 重回 actionable missing ⇒ 补灌重判;
- **失败类隔离(AC4)**:仅 chunker 正常返回 `[]` 登记分类;异常/超时/
  embed/index 失败走既有 failed(fail-closed),结构上不可能写本表(embed
  在 chunk 之后,零分块无 embed)。

## 3. 实现 delta

1. `backend/db/models.py`:`ZeroSemanticChunk` 模型(语义契约全文注释);
2. `backend/services/zero_semantic_chunks.py`(新):`record_zero_semantic_chunk`
   (upsert:同指纹确认+1 / 指纹漂移原位换判定,first_seen 保留审计)、
   `chunker_policy_fingerprint`、`suppression_cutoff`、
   `purge_expired_out_of_authority`(窗口过期 ∘ 越权枚举卫生,幂等)、
   `delete_for_identities`(激活清除);
3. `backend/pipeline/generation_builder.py`:
   - 零分块分支:登记 + `excluded.append(DocFailure(error_class=
     "zero_semantic_chunk", stage=STAGE_CHUNK, retryable=False))`(分区,非
     failed;沿用 #91 的 excluded 通道,不毒化生成代);
   - `BuildAccounting.zero_chunk_docs` 分列字段(AC5);
   - 激活事务:与 #91 的排除清除同点追加零分块分类清除(AC3 后半);
   - `_chunker_policy_fingerprint` 模块函数;
4. `backend/services/membership_currency.py`:`MembershipReconciliation.
   zero_chunk_ids` 分列;对账压制(窗口+内容指纹一致)/漂移失效/过期重开;
   卫生 purge;`truth_detail_of` 增 `zero_chunk_sample`;
5. `scripts/sync.py`:`_exclusion_delta` 增加性键
   `zero_semantic_chunk(+_unit)`(仅非零时输出;既有键不变;
   **R2 修正:三桶不相交,permanent_excluded 仅 #91,eligible 含零分块**);
6. `scripts/migrate_add_zero_semantic_chunks.py`(幂等,CREATE TABLE IF NOT
   EXISTS + 窗口过滤索引)+ 登记进 `deploy/prod/migrations.json`(第 14 条);
   `tests/api/admin/conftest.py` 迁移链同步。

## 4. 测试(RED→GREEN)

新增 17 例,先确认因正确原因红(`ZeroSemanticChunk` 缺失 ImportError /
`zero_chunk_ids` 属性缺失),后全绿:

| 文件 | 数 | 覆盖 |
| --- | --- | --- |
| tests/services/test_issue94_zero_chunk_service.py | 7 | AC2 全字段持久化;确认计数/时间戳;内容与策略指纹原位换判定;删除(幂等);窗口有界;越权过期卫生 |
| tests/pipeline/test_issue94_zero_chunk_builder.py | 5 | AC1/AC2 登记+分区+零账本+零嵌入;AC1 下轮确认幂等;AC3 内容变更换判定;AC3 激活清除(内容变更走 updated 重建代);AC4 chunker 异常保持 failed 且零登记 |
| tests/services/test_issue94_membership_zero_chunk.py | 5 | AC3/AC5 窗口+指纹一致压制且 `zero_chunk_ids` 单列;指纹漂移重开 missing;窗口过期重开;与 #91 安全排除同轮分列(excluded_ids ≠ zero_chunk_ids,missing 双扣);truth detail 采样 |

## 5. 回归

- **#91 不变量**(分区/收敛/陈旧重评/membership 压制)4 套件 + #92 + #68 迁移
  + P1 lifecycle:**38/38 绿**;
- 后端全量:见 §7(预期 #91/#25 既有失败分类不变);
- 关键回归面论证:#91 安全排除路径未动(仅在 missing 计算/激活清理处**追加**
  零分块集合);#25 退休语义未动(reconcile 的 stale/tombstone 流程原样);
  合成「零分块 → 有效分块」内容变更由 builder 测试第 4/5 例覆盖。

## 6. 契约验收对照

| AC | 落点 |
| --- | --- |
| AC1 | builder 测试 1/2(登记+分区+幂等确认+非 actionable) |
| AC2 | 表结构五要素 + 独立表(非 #91 复用)+ 零 dummy 文档/向量 |
| AC3 | 指纹双轴原位换判定 + 激活清除 + 7 天有界重评估 |
| AC4 | 异常路径测试 + 结构隔离(embed 在 chunk 后) |
| AC5 | `zero_chunk_ids` 分列 + `zero_semantic_chunk` 核算键 + 幂等确认零嵌入 |
| AC6 | #91 4 套件 38/38 + #25 reconcile 原样 + 合成变更用例 |

## 7. 全量回归结果(最终)

- **backend 全量:3002 passed / 0 failed / 8 skipped**(37 分钟);
- `test_gap_export` 2 例按基线预告**主动 deselect**(种子日期 2026-09-11 的
  7d 窗口时间炸弹;当日干净 worktree 已复现同 2 failed,与 #68/#87 轮分类
  一致),本轮单独复跑仍为既定 2 failed(非本候选引入);
- 零回归:#91 分区/收敛/重评 4 套件、#25 reconcile、#92 容量、#68/#91 迁移、
  P1 lifecycle 全绿(38/38);admin conftest 迁移链 additive。

## 8. Candidate

- Branch: `agent/94/e64b331f`;本报告随代码同 commit force-add。
- **STOP:等待 Role A review;不自行 merge。**

## 9. REVIEW_1 R2 验证记录(2026-09-21)

- Targeted #91/#94 accounting/lifecycle:tests/pipeline/test_issue91_convergence +
  test_issue94_zero_chunk_builder + tests/services/test_issue91_membership_exclusion
  + test_issue94_membership_zero_chunk + test_issue94_zero_chunk_service =
  **28 passed / 0 failed**;
- #100 sync/source-unavailable 回归(不回归门):test_source_unavailable_failclosed
  + test_filesystem_unavailable_root + test_bulk_repair_bounded_idempotency
  + test_shared_uploads_volume + test_upload_connector_visibility + tests/scripts 全目录 =
  **393 passed / 5 skipped / 0 failed**;
- Broader backend 全量(R2 合并 main 1093c93 后):**2964 passed / 4 failed / 6 skipped** —
  4 失败 = 既定基线既有(gap_export×2 / gap_observation / tech_answer_gaps,#100 轮
  已在纯净 base 逐一复现分类),与本 diff 零因果;#100 面 393 用例全绿 = 不回归门 PASS;
- Membership 侧既有正确行为零改动:excluded_ids/zero_chunk_ids 分列、指纹失效、
  fail-closed、激活清除、无 dummy serving truth(既有 17 例全绿背书)。
