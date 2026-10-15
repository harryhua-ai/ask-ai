# Issue #164｜已删知识残留向量：精确身份账本、GC 覆盖差异与受控清理预检（公开脱敏版）

- 日期：2026-10-15 ｜ 执行：Role B（Claim `harryhua-ai-20261015T093039-9986714b`）
- 分支：`agent/164/8f8beae2`（base `16d01b89` = main @ #162/PR #163 修复合入点）
- **全程零生产写入声明**：本 Task 对生产 PostgreSQL 与 Weaviate 仅执行 SELECT / GraphQL Get / Aggregate 只读取证；未运行 GC `--apply`、未开启 `LIFECYCLE_GC_APPLY`、未变更任何配置/索引/缓存、未触发 `/api/ask`。同步容器日志仅 `docker logs --since` 只读查看。
- 生产基线：`v1.6.4-r2`（三容器同镜像，Weaviate 1.28.0，PostgreSQL 16）；**#162 修复未部署**（见 §6 约束）。

---

## 1. 结论摘要（对 Issue 前提的一次实质性修正）

1. **17,479 无法在现场复现**。2026-10-15 对 Weaviate `Document` collection 做全量 cursor 精确扫描（532,783 对象，逐对象含 `source_id`），按 820 条已删文档的 `source_id` **精确匹配**清点，残留对象 = **10,512**（distinct UUID，无重复）。既有调查报告的 17,479 / 7,148 跨代叠积**按精确身份口径不可复现**，其逐项查询工件未随报告保存、无法审计——按契约如实记 **UNKNOWN**，不填造。可以精确复现的是：820（docs）、10,331（PG 终版 chunk 合计）、479+80+261（墓碑构成）、532,783（collection 全量）。
2. **整数守恒成立（今日冻结工件）**：10,512（目标残留）= **10,512 可被现有 GC 精确覆盖** + **0 不可覆盖 orphan**。残留对象按 `generation_ordinal` 分桶与 PG `DocumentVersion` 行逐桶精确一致——每一个残留对象都能由当前 PG 版本行经确定性 UUID 路径推导。
3. **现有 GC（#162 语义 + 显式 `tombstone_days`）足以覆盖 820 条文档的全部今日残留**；**不需要**为这 820 条新写 cleanup 工具。#162 修复落地的必要性不变（资格语义收紧 + 墓碑 opt-in 分层），生产部署版本仍缺该修复。
4. **真正结构性的 GC 不可覆盖孤儿在目标之外**：2,370 个对象属于 **active** 的 wiki 文档，位于三个卡在 `processing` 状态、永不退休的旧代（ordinal 43/51/59，各 790 个）。它们被在服代过滤排除、不构成检索面，但任何现有 GC 路径都不会清理它们（代状态非 retired，且版本行已迁移）。本 Task **不将其纳入清理目标**（属 active 身份，触碰即越权），单列风险移交。
5. **全局 `tombstone_days` 当前外溢面 = 0**：生产全部 lifecycle=deleted 文档就是这 820 条（active 27,685、missing_candidate 0、superseded 0）。但该配置是**常驻语义**：配置后未来任何墓碑满 T 天都会自动入选，且发现确认退休行走 7 天自动窗——外溢面是时间函数，必须以冻结 allowlist + fail-closed 预检守门（§5）。

## 2. 口径对照表（AC1）

| 数字 | 权威口径 | 现场重核（2026-10-15 09:42Z 冻结工件） | 判定 |
|---|---|---|---|
| **820** | `documents.lifecycle='deleted'` 行数 | 820（构成：479 membership 墓碑 + 80 fetch_deleted + 261 早于退休落笔机制的无记录行；`retirement.gc_eligible_at` 非空者 **0** 条） | ✅ 精确复现 |
| **10,331** | 820 条文档 **current** `DocumentVersion` 行 `chunk_count` 合计 | 10,331（820 行） | ✅ 精确复现 |
| **10,512** | 820 条文档**全部**版本行（825 行=820 current + 5 旧行）`chunk_count` 合计 | 10,512 = Weaviate 残留精确清点 | ✅ 新账本（旧报告无此数） |
| **17,479** | 既有私有调查报告的残留清点（方法记录为"Equal 全路径精确清点"，查询文本与逐项结果未保存） | 全量扫描下按精确 source_id 匹配 = **10,512**，差 6,967 无法归因 | ❌ **UNKNOWN**（两种可能：采样时点差异——当日有代构建活动；或该清点实际匹配面宽于精确 source_id。无原始工件可裁决） |
| **7,148** | 报告自述 17,479 − 10,331 的推导值（跨代叠积） | 实际跨代对象 = 10,512 − 10,331 = **181**（恰为 5 条旧版本行的 chunk 合计） | ❌ 不可复现（随 17,479 一并 UNKNOWN） |
| **532,783** | collection 全量 cursor 扫描对象数（逻辑存活权威口径） | 本次全量 cursor 扫描逐对象计数 = 532,783，UUID 全 distinct | ✅ 精确复现 |
| **532,733** | 仅出现于 Issue 文本转述，任何工件（含原始报告）均无此数 | 与 532,783 差 50，无独立测量支撑 | ❌ 判定为转写漂移，非独立口径 |
| **1,962,489** | `id NotEqual` 过滤计数（倒排补集伪计数） | 方法性不可用（分片级补集近似），不作为任何账本口径 | ✅ 维持"不可用"结论 |

**采样/对照方法**：PG 侧 `COPY (SELECT …) TO STDOUT` 导出三张身份表（`documents` 仅身份列、`document_versions`、`index_generations`，**不含任何正文/title/url/props**）；Weaviate 侧经 backend 容器 GraphQL Get cursor 分页导出 `(uuid, source_id, generation_id, generation_ordinal)` 四元组。PG 身份 ↔ 实际对象对照 = 在本地离线用 `backend.pipeline.ingest.chunk_uuids_for_version`（与 main 完全相同的确定性 UUID 路径：`ordinal=0 → uuid5(NS_URL, source_id#i)`；否则 `uuid5(NS_URL, source_id#generation_id#i)`）推导全集，与清单做集合运算。collection = `Document`，未启用 tenant 分区（单租户默认空间）。

**工件哈希（私有逐项明细不入库，仅记录哈希与受控保存位置）**：

| 工件 | sha256（前 16 位） | 保存位置 |
|---|---|---|
| `documents-20261015.csv`（28,505 行） | `0ba3dfd314d7fcb9…` | 操作员本地 `/tmp/issue164-private/`（易失）；交付后仅哈希存证 |
| `document_versions-20261015.csv`（29,956 行） | `80314ca50bb03624…` | 同上 |
| `index_generations-20261015.csv`（235 行） | `0b2266481c1882f6…` | 同上 |
| `weaviate-inventory-20261015.jsonl`（532,783 行，92 MB） | `a333d25aecbe4646…` | 同上；生产主机 `/tmp/inv164.jsonl` 有同字节副本 |
| 既有私有调查报告 `issue-residual-vectors-investigation-20261015.md` | （本地 main repo untracked；未纳入本 PR） | 保留在操作员本地，公开渠道仅本脱敏版 |

## 3. 差异账本与整数守恒（AC2）

资格判定离线**逐条复用 main 的 `lifecycle_gc.sweep` 规则**（#162 语义：普通墓碑仅在显式 `tombstone_days` 下入选；发现确认退休锚行走 7 天自动窗；退役代需 `gc_eligible_at` 成熟且未 purge），UUID 全部经 `chunk_uuids_for_version` 推导。

**3.1 目标残留守恒（820 条已删文档，2026-10-15 冻结工件）**

```
残留对象（精确 source_id 匹配，distinct）   = 10,512
  = 可被现有 GC 推导覆盖（在场）           = 10,512
  + 不可覆盖 orphan（无任何 PG 行可推导）   =      0
```

按 `generation_ordinal` 分桶，残留对象与 PG 可推导集合**逐桶相等**（0:4,427 / 19:251 / 35:6 / 62:208 / 63:4,877 / 127:46 / 131:5 / 132:417 / 178:149 / 203:110 / 204:16）。目标内当前版本对象缺席 = 0。

**3.2 GC 窗口覆盖表（同族语义，`--tombstone-days=T`）**

| T | doomed docs | 可推导 UUID（全部在场） | 其中目标内（820 条） | 目标外（披露，见下） |
|---|---|---|---|---|
| 30 | 241 | 2,431 | 2,380 | 51 |
| 7 | 768 | 9,673 | 9,622 | 51 |
| 1 | 820 | 10,563 | **10,512** | 51 |

**3.3 目标外触达面披露（GC 语义自带，必须知情）**
- "目标外 51" = 退役代 ordinal 143（`retired_at` 09-30，锚 10-07 已成熟）中仍被 2 条 **active** 文档旧版本行引用的对象。它们不在任何在服 current 集合（现势撤出已完成），被 GC part1 删除属设计内行为，但**不是**本 820 目标的一部分，提案中作为已披露副作用（§6 步骤 5 只读回读会如实记录）。
- 退役代 ordinal 22（锚 10-18）与 83（锚 10-20）尚未成熟（合计 6 行 / 22 chunks，同样属 active 文档旧版本），T 执行日晚于锚点会被一并卷入——**执行前必须重新预检**。
- **全局墓碑窗外溢**：当前 doomed ⊆ allowlist（820），外溢 0。但配置常驻后，未来新墓碑满 T 天自动入选；发现确认退休行（`gc_eligible_at` 锚）走 7 天自动窗不受墓碑窗控制。当前锚行数 = 0。

**3.4 全局守恒（对照面）**：532,783 = 530,413（全库版本行可推导且在场）+ **2,370 true orphan**；另有 2,695 个可推导 UUID 无对象（缺席，与清理无关，见 §8）。**2,370 个孤儿全部属于 active 的 wiki 文档**，对象代 ordinal = 43/51/59（各 790），对应三个卡在 `processing` 状态的失败/中断构建代（`index_generations` 中 status=`processing`、chunk_count=0、无锚点、永不满足 part1 资格）。它们被在服代过滤（`active_generation_ordinals_sync` = 在服 current 版本代序集合）排除在检索面外，属惰性存储残留。**本 Task 不清理它们**；如需处理须另行授权（方向：代状态修复或显式 UUID 清单操作，均超出本契约）。

**3.5 安全交集证明**：清理清单 ∩ 在服（active/missing_candidate）current 可推导 UUID = **0**（结构保证：UUID 空间含 `source_id`，且 doomed 文档整体退出在服对照面；预检含防御纵深断言）。另实证：与 820 条已删文档**同 (repo,path) 但不同 source_id**（如不同分支）的对象有 **3,245** 个，属在服文档——这是 TEXT Like/prefix/token 匹配绝不可用于删除的直接量化证据。

## 4. 只读预检程序与离线回归（AC3）

**新增**：`scripts/gc_preflight.py`（只读预检）+ `tests/scripts/test_gc_preflight.py`（20 项 fixture 回归，零网络/零 PG/零 Weaviate）。

- **零写构造**：Weaviate 句柄经 `ReadOnlyCollection` 代理（`delete*/insert*/replace*/update*/purge*` 属性即抛 `NotReadOnly`，先于 `getattr` 拦截）；账本构造为纯函数（不接任何写入句柄）；PG 仅 SELECT。
- **外溢 fail-closed**：`--allowlist-json`（冻结 820 source_id 清点 + sha256 自校验，哈希不符即 exit 2）；doomed ⊄ allowlist → violations + exit 2，外溢文档 UUID 绝不入清单。
- **精确身份**：清单只能由 `chunk_uuids_for_version` 推导；测试与 main 路径做 parity 断言（含 legacy ordinal-0 命名空间）。
- **attempts≠success**：`GCReport.objects_deleted` 在 main 代码中 = `len(uuids)` 尝试数、忽略 `delete_many` 返回（`backend/services/lifecycle_gc.py` `_delete_version_objects`）——预检以只读在场探针区分 `present/missing/orphan`，并在守恒式中单列；apply 后验收必须以逐 UUID 读回为准（§6）。
- **orphan 单列**：任何不可推导残留对象只进 `orphan_uuids_*` 计数与违规项，绝不并入清理清单；目标内出现 orphan 即 exit 2（本次实测为 0）。
- **资格漂移检测**：liveness 模式下同时跑真实 `lifecycle_gc.sweep(apply=False)`（A-5 dry-run 默认）与本地重算，二者不一致 exit 3。
- **可复用现有命令**：`python scripts/gc_lifecycle.py --report-json out.json`（dry-run 默认 + `LIFECYCLE_GC_APPLY` config gate）——`--apply` 缺 config 门时显式拒绝，仍是安全可复用的资格报告工具。
- **离线复现**：本报告 §3 全部数字可用冻结工件离线复现：
  `python scripts/gc_preflight.py --tombstone-days 30 --allowlist-json <allowlist> --inventory-jsonl <inv.jsonl> --docs-csv <d.csv> --versions-csv <v.csv> --gens-csv <g.csv> --now-iso 2026-10-15T09:42:00+00:00`

测试结果：`pytest tests/scripts/test_gc_preflight.py` → **20 passed**；`pytest tests/scripts -k "gc or lifecycle or preflight"` → 27 passed（含既有生命周期脚本回归）。

## 5. AC5 安全门（清理前必须 PASS）

- **守卫链在位**（main + 生产镜像双重确认）：`backend/main.py` `_build_withdrawn_identity_provider` → `withdrawn_document_source_ids_sync`（权威 = `lifecycle NOT IN (active, missing_candidate)`，**当前恰好覆盖这 820 条**）→ `CachedSourceExclusions`（TTL 30s，查询失败异常向上传播 **fail-closed**，绝不空集回落）→ `HybridSearcher(withdrawn_identity_provider=…)`。生产镜像 v1.6.4-r2 容器内 grep 验证 wiring 与函数均在（#84 修复 r6 之上）。
- **在服代过滤**：`active_generation_ordinals_sync`（在服 current 代序集合，全局 allowlist）。820 条残留中 legacy ordinal-0 的 4,427 个对象因 ordinal 0 仍在服集合而被该过滤放行——即 Weaviate 侧过滤对部分残留**无效**，身份排除完全依赖 #84 单点（与既有调查结论一致）。
- **历史消费事实（不绝对化）**：历史 ≥3 轮 LLM context 接触为已确认事实（#84 追溯，09-15/16 窗口）；当前版本零新消费为"机制+无观察"证据，非绝对零消费声明。
- 清理完成后该守卫对 820 条身份自然失效（PG 行被 GC 删除后退出 withdrawn 集合）——**仅在对象确已物理删除后才是安全的**；这决定了 §6 的操作顺序（先删对象、后删 PG 行，同批次逐文档提交）。

## 6. 受控清理提案（供 A/User 审批；本 Task 未执行）

**结论：既有 GC 足够，无需新增清理工具或工程补丁**（目标内 orphan=0）。前提约束与操作设计如下：

1. **在服版本约束（硬性）**：生产 v1.6.4-r2 的 sweep 含 #162 修复前的回退语义。执行必须满足其一：① 部署含 #162 的版本后执行；② 经 User 明确授权以 main 构建的一次性 GC 运行（镜像/脚本 SHA 冻结入审计，版本偏差知情）。**禁止**在 v1.6.4-r2 原生语义下执行。
2. **全量可恢复备份**：PG `documents/document_versions/document_version_chunks/index_generations` 逻辑备份 + Weaviate 目标 UUID 清单快照（本报告工件已具备清单基础，执行日重导）；恢复验证 = 备份恢复到临时库并通过行数/哈希抽查后才可进入执行窗。Weaviate 对象向量本身不可再生的部分由 `document_version_chunks` 持久副本+重嵌入覆盖（重建判据=结构等价）。
3. **操作前集合冻结 + 审计哈希**：执行窗开始时重跑 `scripts/gc_preflight.py`（live 模式，含 sweep 对账），归档 `--report-json`；manifest sha256 与 allowlist sha256 双哈希入审批记录。预检 exit ≠ 0 即中止。
4. **精确 UUID 范围**：仅 GC 自身确定性推导（等价于 manifest）；绝无 TEXT 过滤。**不使用**任何一次性 Weaviate 批删脚本（本 Task 已证明 GC 覆盖完备，无需第二工具面）。
5. **批次/中断/重试/幂等**：GC 为逐文档事务（每文档：对象点删 → chunk 行删 → 版本行删 → 文档行删，commit）。中断恢复 = 重跑 sweep（幂等：已删 PG 行不再入选；Weaviate 缺席 UUID 点删匹配零、无副作用）。批次节奏 = 单轮 sweep（10,563 尝试 ≈ 数分钟级），如需限速可分窗口（按 deleted_at 周切，窗口间预检）。
6. **每批后 PG+Weaviate 逐 UUID 读回对照**：sweep 结束后立即以只读清单重扫：目标内残留应为 0；`GCReport.objects_deleted`（尝试数）与读回的实际消失数对账，差额单列调查（预期 0）。
7. **zero residual 验收**：48h 后（跨一个同步周期+TTL 窗口）复扫一次确认无回填；#84 检索面回归（widget/api 各一轮只读探针不新增生成）确认无 withdrawn 身份召回。
8. **失败恢复路线**：GC 中断 → 重跑 sweep 补齐（幂等）；PG 行已删但对象残留（不可能顺序，防御性记录）→ 以冻结清单二次点删；误删 active 对象（预检证明为 0 概率）→ 从 `document_version_chunks` 持久副本走 repair 重物化。
9. **配置卫生**：一次性受控窗后评估是否保留常驻 `LIFECYCLE_GC_TOMBSTONE_DAYS`（保留=未来墓碑自动清理；不保留=恢复 opt-in 关闭态）。两个方向均需 User 意图，不默认。

## 7. 范围与 UNKNOWN 边界

- 未执行任何生产写入/删除/purge；未把 820/17,479 当已验证事实（820 已现场重核，17,479 判 UNKNOWN）。
- **UNKNOWN 清单**：①17,479/7,148 的测量口径与采样时点（原始逐项工件缺失）；②2,695 个可推导但缺席的对象分布成因（不构成清理风险，存储/审计事实，未逐项归因）；③2,370 个 active-wiki 旧代孤儿的处置路径（超出本契约）；④历史 LLM 正文采纳与否（无请求日志，永久 UNKNOWN）。
- 采样时点差异风险：本账本冻结于 2026-10-15 09:42Z；执行窗必须重新预检（当日已观测到代构建活动会使数字漂移）。
