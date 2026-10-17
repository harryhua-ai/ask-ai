# Issue #164｜已删知识残留向量：精确身份账本、GC 覆盖差异与受控清理预检（公开脱敏版）

- 日期：2026-10-15 ｜ 执行：Role B（Claim `harryhua-ai-20261015T093039-9986714b`）
- 分支：`agent/164/8f8beae2`（base `16d01b89` = main @ #162/PR #163 修复合入点）
- **R2（2026-10-17，对 A 复审 REQUEST_CHANGES 的逐项修正）**：delta 见 §0。核心变化——**§6 由「既有 GC 足够」改为 HARD NO-GO**（删除回执/元数据排序被证明前禁用既有 GC apply）；预检新增 **820-only 范围门**与清单守恒代码门；证据工件归类为 **B-REPORTED、非持久**。
- **R3（2026-10-17，对 A 02:26Z REQUEST_CHANGES 三项阻塞的逐项修正）**：delta 见 §0b。空 allowlist 清单恒为空集；空白 source_id 一致 fail-closed；live parity 不可静默旁路（skip/混合输入 → `unverified` + exit 4）。HARD NO-GO 结论与 820-only 范围门不变。
- **全程零生产写入声明**：本 Task 对生产 PostgreSQL 与 Weaviate 仅执行 SELECT / GraphQL Get / Aggregate 只读取证；未运行 GC `--apply`、未开启 `LIFECYCLE_GC_APPLY`、未变更任何配置/索引/缓存、未触发 `/api/ask`。同步容器日志仅 `docker logs --since` 只读查看。
- 生产基线：`v1.6.4-r2`（三容器同镜像，Weaviate 1.28.0，PostgreSQL 16）；**#162 修复未部署**（见 §6 约束）。

---

## 0. R2 修正说明（对 A 复审五项阻塞的逐项处置）

1. **GC 删除回执/不可逆身份丢失（P1）→ §6 改判 HARD NO-GO**。A 指出正确：`_delete_version_objects` 忽略 `delete_many` 的 successful/failed 计数并返回 `len(uuids)` 尝试数；`sweep(apply=True)` 在 Weaviate 零/部分删除且不抛错时**仍提交** chunk/版本/文档行删除与 `purged_at`——§6(8) 原断言「PG 已删但对象残留（不可能顺序）」**不成立，予以撤销**。R2 以离线 fake 会话/假回执的**特征钉死测试**固化该危险事实（`tests/scripts/test_gc_preflight.py::TestGCApplyHardNoGo`）；预检输出恒带 `gc_apply_hard_no_go=true` 及理由清单（`HARD_NO_GO_REASONS`）。**本只读预检 Candidate 不改生产 GC 本体**；解禁条件（回执消费、验证后元数据排序、manifest 驱动可恢复身份）单列为需另行授权的独立工程任务（§6 裁决与 §6.2 解禁前置工程）。
2. **实际爆炸半径 >820 → 预检新增 fail-closed 820-only 范围门**。T=1 manifest 确为 10,563，其中 51 个属两个 active 文档的退役代（ordinal 143）版本；既有 GC part 1 独立于 `tombstone_days` 触碰它们——**如实现状 GC 无法做到 820-only，在此直说：做不到**。R2 后 `compute_ledger` 把合格退役代触及的目标外文档 UUID 单列 `out_of_scope_generation_uuids`（需另行授权）并产生 violation（exit 2），**绝不并入清理清单**；外溢文档的退役代路径同样被封死。§3 各表格数字不变（范围门只改清单边界，不改账本观测值）。
3. **预检 fail-closed 证明补全**：a) `--allowlist-json` 的 `sha256` **缺失/为空/不匹配一律 exit 2**（`load_allowlist` 强制）；b) live `_sweep_crosscheck` 现在**同时比对文档与代两个资格面**，任一漂移即 exit 3 并在报告写明漂移面与两侧集合；c) 修正 `as_dict()` 先于 drift violation 追加的顺序颠倒——报告 violations 与 exit code 现在一致；d) 清单守恒升级为**代码门**：distinct UUID、非空 `source_id` 绑定、源↔UUID 绑定与 PG 可推导集合一致性，破坏即 fail-closed。以上均有负向 fixture 证明非零退出与真实审计输出；live parity 未被压制（无漂移路径由真实 `lifecycle_gc.sweep` 契约测试覆盖）。
4. **审计证据边界 → 快照归类 B-REPORTED、非持久**。532,783 对象 UUID 清单与 PG 身份 CSV 仅存于操作员本地易失 `/tmp`，公开报告哈希仅前 16 位（**非校验级**）——不存在可独立访问的持久受限证据通道。R2 如实降级：§2 工件为 **B-REPORTED（报告方陈述），不可独立复核**；**任何执行窗的 preflight 必须重新做同快照全审计采集**（全新三表导出 + 全量清单，完整长度校验和入受限通道），不得引用本报告数字作为执行依据。
5. **SessionFactory 错配修正**：R1 的 `main()` 把 `async_sessionmaker[AsyncSession]` 传给同步用法的 `_load_live_rows`、把同步 sessionmaker 传给内部 `async with`/`await` 的 `_sweep_crosscheck`→`lifecycle_gc.sweep`——live 路径进入即 TypeError 崩溃（离线复算路径不受影响，故 R1 未暴露）。R2 按各函数调用约定配置正确工厂（生产访问保持全只读），并新增离线 fake SessionFactory 契约测试（`TestSessionFactoryContracts`：sync/async 各自契约 + 拒错配 + main() 双路径接线断言）。


---

## 0b. R3 修正说明（对 A 2026-10-17T02:26Z REQUEST_CHANGES 三项阻塞的逐项处置）

1. **空 allowlist 泄漏全量清单（安全边界错误）→ 清单恒为空集**。`load_allowlist` 本就容许合法的 `{"sources":[],"sha256":<空集哈希>}`，但 `compute_ledger` 的 `in_scope = doomed_set & (allowed_deleted_sources or doomed_set)` 用 falsy `or` 把空 set 替换成全量 doomed——违规路径的清单与 `manifest_sha256` 会包含未授权 UUID，违背「目标外 UUID 绝不进入清单」强边界。R3 显式区分 `None`（未提供 allowlist，仅内部路径，语义不变）与空 set（**授权 0 篇**）：空 allowlist 下 `derived_deletable_uuids` 恒为 `[]`、manifest 对应空集（`sha256(b"")`）。负例 fixture：空 allowlist + 非空 doomed → exit 2 **且** 清单为空（`TestR3EmptyAllowlistNeverLeaksManifest`，单元级 + CLI 级）。
2. **source_id 空串绕过守恒门 → 一致按无有效身份 fail-closed**。修复前守恒门只认 `sid is None`；`_load_live_inventory`（Weaviate 属性）与离线 JSONL 均可携带 `""`/纯空白，无身份对象在其他条件正常时 `violations` 保持空并以 exit 0 计入审计总数。R3 将 None、空串、纯空白一致计为 `null_binding` violation（源↔UUID 绑定校验同步用同一身份谓词），负例 fixture 复现「修复前 exit 0」并证明修复后非零退出 + 报告真实列示（`TestR3BlankSourceIdFailClosed`，单元级参数化 + CLI 级）。
3. **live 资格双面 parity 可被静默旁路 → 强制 parity，旁路通道 unverified + exit 4**。修复前：`--skip-sweep-crosscheck` 可在 live 模式跳过真实 `lifecycle_gc.sweep(apply=False)` 对账；`--inventory-jsonl` 未配齐三件冻结 CSV 时会读当前 live PG（混合不同时点数据）并直接 `drift=None`——两种情况都可能 EXIT_OK 且报告不标 unverified。R3 起可供授权判断的 live preflight **强制**双面 parity；仅存的显式 debug 通道（`--skip-sweep-crosscheck`、冻结清单 × live PG 混合输入）必须输出 `unverified=true` + 原因，并以 `EXIT_UNVERIFIED=4` 退出（violations/漂移存在时仍取更强的 exit 2/3），不可作为安全门 PASS；CSV 三件不成组同给 → 直接 exit 2（不再静默忽略）。负例 fixture：潜伏漂移 + skip 参数（对账确实未跑、非 PASS）、混合输入（修复前 EXIT_OK → 修复后 exit 4）、部分 CSV 参数（exit 2）、未跳过时 parity 仍强制（漂移走 exit 3 通道）（`TestR3ParityNotSilentlyBypassable`）。

**不变项**：HARD NO-GO 结论、820-only 范围门、§3 表格观测数字、零生产写入边界、生产 `lifecycle_gc.py` 只读——R3 均未触碰（#164 之外，#138 继续 NO-GO）。


---

## 1. 结论摘要（对 Issue 前提的一次实质性修正）

1. **17,479 无法在现场复现**。2026-10-15 对 Weaviate `Document` collection 做全量 cursor 精确扫描（532,783 对象，逐对象含 `source_id`），按 820 条已删文档的 `source_id` **精确匹配**清点，残留对象 = **10,512**（distinct UUID，无重复）。既有调查报告的 17,479 / 7,148 跨代叠积**按精确身份口径不可复现**，其逐项查询工件未随报告保存、无法审计——按契约如实记 **UNKNOWN**，不填造。可以精确复现的是：820（docs）、10,331（PG 终版 chunk 合计）、479+80+261（墓碑构成）、532,783（collection 全量）。
2. **整数守恒成立（今日冻结工件）**：10,512（目标残留）= **10,512 可被现有 GC 精确覆盖** + **0 不可覆盖 orphan**。残留对象按 `generation_ordinal` 分桶与 PG `DocumentVersion` 行逐桶精确一致——每一个残留对象都能由当前 PG 版本行经确定性 UUID 路径推导。
3. **〔R2 改判〕账本推导意义上，现有 GC（#162 语义 + 显式 `tombstone_days`）的资格判定可精确覆盖 820 条文档的全部今日残留（10,512 = 10,512 + 0）**；但 **R1 的「既有 GC 足够、无需工程补丁」结论已撤回**：其 apply 路径的删除回执与元数据排序未被证明安全（§0.1），且 GC part 1 **不是 820-only**（§3.3）。在独立工程任务完成回执验证与安全排序并另行授权前，**任何生产删除执行均为 HARD NO-GO**。#162 修复落地的必要性不变（资格语义收紧 + 墓碑 opt-in 分层），生产部署版本仍缺该修复。
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

**工件哈希与证据边界（R2 重新归类：B-REPORTED、非持久）**：

> **R2 证据边界声明（对 A 复审阻塞 4 的处置）**：下表工件仅存于操作员本地易失 `/tmp/issue164-private/`（及生产主机 `/tmp/inv164.jsonl` 同字节副本），**不存在可独立访问的持久受限证据通道**；本报告公开哈希仅取前 16 位，**非校验级，不能作为完整校验锚**。故本节全部快照按 **B-REPORTED（报告方陈述）**归类：**不可独立复核、非持久**，不构成冻结证据。§1/§3 的数字在 R2 后只能作为「2026-10-15 09:42Z 时点的报告方账本」引用；**任何执行窗的 preflight 必须重新做同快照全审计采集**（全新 PG 三表只读导出 + Weaviate 全量 cursor 清单 + 完整长度 sha256 入受限持久通道），不得引用本报告数字作为执行依据。

| 工件 | sha256（前 16 位，非校验级） | 保存位置（非持久） |
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

> R2 注记：表中「可推导 UUID」为 GC 资格语义的完整触达面（观测值，保持 R1 数字不变）；R2 起预检的**清理清单**只含目标内列（820-only 范围门），目标外列进入 `out_of_scope_generation_uuids` 单列授权面并 fail-closed。

**3.3 目标外触达面披露（GC 语义自带，必须知情；R2 起预检 fail-closed）**
- "目标外 51" = 退役代 ordinal 143（`retired_at` 09-30，锚 10-07 已成熟）中仍被 2 条 **active** 文档旧版本行引用的对象。它们不在任何在服 current 集合（现势撤出已完成），被 GC part1 删除属设计内行为，但**不是**本 820 目标的一部分——**如实现状 GC 无法做到 820-only，在此直说：做不到**（part1 独立于 `tombstone_days` 清扫全部合格退役代）。R2 后预检把这部分单列为 `out_of_scope_generation_uuids`（**需另行授权的退役代范围**）并产生 violation（exit 2），绝不并入 820-only 清单；外溢文档的退役代路径同样被封死。R1 提案中「作为已披露副作用接受」的说法不再成立——在回执/排序解禁前不存在可接受的执行。
- 退役代 ordinal 22（锚 10-18）与 83（锚 10-20）尚未成熟（合计 6 行 / 22 chunks，同样属 active 文档旧版本），T 执行日晚于锚点会被一并卷入——**执行前必须重新预检**（范围门会把它们一并单列）。
- **全局墓碑窗外溢**：当前 doomed ⊆ allowlist（820），外溢 0。但配置常驻后，未来新墓碑满 T 天自动入选；发现确认退休行（`gc_eligible_at` 锚）走 7 天自动窗不受墓碑窗控制。当前锚行数 = 0。

**3.4 全局守恒（对照面）**：532,783 = 530,413（全库版本行可推导且在场）+ **2,370 true orphan**；另有 2,695 个可推导 UUID 无对象（缺席，与清理无关，见 §8）。**2,370 个孤儿全部属于 active 的 wiki 文档**，对象代 ordinal = 43/51/59（各 790），对应三个卡在 `processing` 状态的失败/中断构建代（`index_generations` 中 status=`processing`、chunk_count=0、无锚点、永不满足 part1 资格）。它们被在服代过滤（`active_generation_ordinals_sync` = 在服 current 版本代序集合）排除在检索面外，属惰性存储残留。**本 Task 不清理它们**；如需处理须另行授权（方向：代状态修复或显式 UUID 清单操作，均超出本契约）。

**3.5 安全交集证明**：清理清单 ∩ 在服（active/missing_candidate）current 可推导 UUID = **0**（结构保证：UUID 空间含 `source_id`，且 doomed 文档整体退出在服对照面；预检含防御纵深断言）。另实证：与 820 条已删文档**同 (repo,path) 但不同 source_id**（如不同分支）的对象有 **3,245** 个，属在服文档——这是 TEXT Like/prefix/token 匹配绝不可用于删除的直接量化证据。

## 4. 只读预检程序与离线回归（AC3）

**新增**：`scripts/gc_preflight.py`（只读预检）+ `tests/scripts/test_gc_preflight.py`（60 项 fixture 回归，零网络/零 PG/零 Weaviate）。

- **零写构造**：Weaviate 句柄经 `ReadOnlyCollection` 代理（`delete*/insert*/replace*/update*/purge*` 属性即抛 `NotReadOnly`，先于 `getattr` 拦截）；账本构造为纯函数（不接任何写入句柄）；PG 仅 SELECT。
- **外溢 fail-closed**：`--allowlist-json`（冻结 820 source_id 清点）；**R2：`sha256` 自描述强制**——缺失/为空/与 sources 全集不匹配一律 exit 2（`load_allowlist`/`AllowlistRejected`）；doomed ⊄ allowlist → violations + exit 2，外溢文档 UUID 绝不入清单（含退役代路径，R2 范围门）。**R3：空 allowlist（`sources: []` + 合法哈希）=授权 0 篇**，与「未提供」显式区分——违规路径的清单/manifest 恒为空集，绝不回退全量。
- **820-only 范围门（R2）**：合格退役代触及的目标外文档 UUID 单列 `out_of_scope_generation_uuids`（需另行授权）+ violation exit 2，绝不并入清理清单；该触达面由可推导集合决定、与对象在场无关。
- **精确身份**：清单只能由 `chunk_uuids_for_version` 推导；测试与 main 路径做 parity 断言（含 legacy ordinal-0 命名空间）。
- **attempts≠success**：`GCReport.objects_deleted` 在 main 代码中 = `len(uuids)` 尝试数、忽略 `delete_many` 返回（`backend/services/lifecycle_gc.py` `_delete_version_objects`）——预检以只读在场探针区分 `present/missing/orphan`，并在守恒式中单列；**R2：该回执缺陷连同元数据排序缺陷构成 §6 HARD NO-GO**，预检输出恒带 `gc_apply_hard_no_go=true`（特征钉死测试固化危险事实，生产 GC 本体不在本 Candidate 改动）。
- **orphan 单列**：任何不可推导残留对象只进 `orphan_uuids_*` 计数与违规项，绝不并入清理清单；目标内出现 orphan 即 exit 2（本次实测为 0）。
- **清单守恒代码门（R2；R3 收紧身份谓词）**：distinct UUID、非空 `source_id` 绑定、源↔UUID 绑定与 PG 可推导集合一致性由 `compute_ledger` 强制（负向 fixture 证明各自独立触发 violation），守恒不再是假设。**R3：None/空串/纯空白 source_id 一致按无有效身份 fail-closed**（修复前空串可静默以 exit 0 计入审计）。
- **资格漂移检测（R2 加固；R3 强制）**：liveness 模式下同时跑真实 `lifecycle_gc.sweep(apply=False)`（A-5 dry-run 默认）与本地重算，**文档与代两个资格面都比对**，任一不一致 exit 3；漂移 violation 先于报告序列化追加（修复 R1 的 `as_dict()` 顺序颠倒——报告 violations 与 exit code 现已一致）。**R3：可供授权判断的 live preflight 强制该对账**——`--skip-sweep-crosscheck` 与「冻结清单 JSONL × 当前 live PG 混合输入」只能得到 `unverified=true` + `EXIT_UNVERIFIED=4`（不可作为安全门 PASS）；CSV 冻结工件三件不成组同给 → exit 2。
- **SessionFactory 契约（R2）**：`_load_live_rows` 只接受同步会话工厂（sync 上下文 + 同步 execute），`_sweep_crosscheck` 只接受异步会话工厂（async 上下文 + await execute）；错配显式 TypeError。R1 的 main() 错配（live 路径进入即崩）已修正，契约由离线 fake 工厂测试钉死（生产访问保持全只读 SELECT）。
- **可复用现有命令**：`python scripts/gc_lifecycle.py --report-json out.json`（dry-run 默认 + `LIFECYCLE_GC_APPLY` config gate）——`--apply` 缺 config 门时显式拒绝，仍是安全可复用的资格报告工具（**注意：R2 后其 dry-run 资格输出仅供观察，不代表可安全 apply**，见 §6）。
- **离线复现**：本报告 §3 全部数字可用冻结工件离线复现（工件为 B-REPORTED、非持久，见 §2——复现需操作员本地仍保留工件或重新采集）：
  `python scripts/gc_preflight.py --tombstone-days 30 --allowlist-json <allowlist> --inventory-jsonl <inv.jsonl> --docs-csv <d.csv> --versions-csv <v.csv> --gens-csv <g.csv> --now-iso 2026-10-15T09:42:00+00:00`

测试结果：`pytest tests/scripts/test_gc_preflight.py` → **60 passed**（R1 20 项 + R2 新增 27 项 + R3 新增 13 项：空 allowlist 清单空集负例×4、空白 source_id 负例×5、parity 不可静默旁路负例×4——各自先 RED 复现错误 PASS/错误清单/exit-0 旁路，再 GREEN）；`pytest tests/scripts` → 439 passed, 5 skipped；`pytest tests/ -k "lifecycle or gc or preflight"` → 209 passed。

## 5. AC5 安全门（清理前必须 PASS）

- **守卫链在位**（main + 生产镜像双重确认）：`backend/main.py` `_build_withdrawn_identity_provider` → `withdrawn_document_source_ids_sync`（权威 = `lifecycle NOT IN (active, missing_candidate)`，**当前恰好覆盖这 820 条**）→ `CachedSourceExclusions`（TTL 30s，查询失败异常向上传播 **fail-closed**，绝不空集回落）→ `HybridSearcher(withdrawn_identity_provider=…)`。生产镜像 v1.6.4-r2 容器内 grep 验证 wiring 与函数均在（#84 修复 r6 之上）。
- **在服代过滤**：`active_generation_ordinals_sync`（在服 current 代序集合，全局 allowlist）。820 条残留中 legacy ordinal-0 的 4,427 个对象因 ordinal 0 仍在服集合而被该过滤放行——即 Weaviate 侧过滤对部分残留**无效**，身份排除完全依赖 #84 单点（与既有调查结论一致）。
- **历史消费事实（不绝对化）**：历史 ≥3 轮 LLM context 接触为已确认事实（#84 追溯，09-15/16 窗口）；当前版本零新消费为"机制+无观察"证据，非绝对零消费声明。
- 清理完成后该守卫对 820 条身份自然失效（PG 行被 GC 删除后退出 withdrawn 集合）——**仅在对象确已物理删除并验证后才是安全的**。R1 曾据此推定「先删对象、后删 PG 行」的操作顺序即可；R2 撤回该推定：现状 GC 虽按该顺序书写，但**不验证删除回执**（零/部分删除仍提交行删除），安全顺序必须以「回执验证 + 只读读回确认后才动元数据」的实现为前提——这是 §6 HARD NO-GO 的组成部分，不是既有代码已具备的性质。

## 6. 受控清理提案（R2 改判：**HARD NO-GO**；本 Task 未执行、亦未改生产 GC）

> **裁决（R2, AC4）**：**在「实际删除结果验证」与「安全 DB 元数据排序」被独立实现证明并另行授权之前，禁止用现有 GC 对生产执行任何删除（`apply=True`）**。R1 的「既有 GC 足够，无需新增清理工具或工程补丁」结论**撤回**。理由（与预检输出 `gc_apply_hard_no_go_reasons` 一致）：
>
> 1. **删除回执未验证**：`_delete_version_objects` 忽略 `delete_many` 返回的 successful/failed 计数，返回 `len(uuids)` 尝试数；Weaviate **零删除或部分删除且不抛错**时，`sweep(apply=True)` 仍按成功记账。
> 2. **元数据排序不安全**：`purged_at`/chunk 行/版本行/文档行删除在「已验证的对象删除」之前提交 → 部分成功或零成功场景下，PG 身份行被删除而对象残留，**该文档版本身份永久不可再推导**。§6 旧文第 8 条「PG 行已删但对象残留（不可能顺序）」**断言错误，正式撤销**——这正是当前实现可产生的顺序。
> 3. **「重跑 sweep」不是恢复路径**：幂等性只在元数据未提交前成立；一旦行删除被提交，重跑 sweep 对残留对象**不可见**。部分成功/中断场景必须由**冻结精确 manifest** 驱动身份恢复，而非事后重跑。
> 4. **既有 GC 不是 820-only**：part1 独立于 `tombstone_days` 清扫全部合格退役代（已证明触及 51 个目标外 UUID；代 22/83 成熟后扩大）。任何「只清 820」的操作都无法用现状 GC 达成——要么把退役代范围作为**另行授权的共范围**明示并入，要么需要独立的 manifest 驱动范围机制（新工具面 = 独立授权决策）。
>
> 账本层面的事实保持不变且已被 R2 强化：820 条目标残留 100% 可由 PG 版本行经确定性 UUID 路径推导（10,512 = 10,512 + 0，orphan=0），**推导面完备**；缺的是**执行面的删除回执验证与安全排序**，属生产 GC 本体的工程改动——**本只读预检 Candidate 不做该改动**。

以下操作设计**降级为解禁后的框架草案**，逐条以 R2 事实重写：

1. **在服版本约束（硬性，不变）**：生产 v1.6.4-r2 的 sweep 含 #162 修复前的回退语义。任何未来执行必须满足其一：① 部署含 #162 的版本后执行；② 经 User 明确授权以 main 构建的一次性 GC 运行（镜像/脚本 SHA 冻结入审计，版本偏差知情）。**禁止**在 v1.6.4-r2 原生语义下执行。
2. **解禁前置工程（新增，独立授权）**：修改 GC apply 使其——a) 消费 `delete_many` 回执（逐批次 successful/failed），任一批次 `failed>0` 或验证删除数 < 期望即**中止且绝不提交任何 DB 元数据变更**；b) 元数据变更（`purged_at`/行删除）只在**逐批次对象删除回执验证 + 只读读回确认**之后提交；c) 中断/部分成功后，残留身份由执行前冻结的精确 manifest（预检 `derived_deletable_uuids`，sha256 锚定）驱动恢复，**不依赖重跑 sweep**；d) 该任务的 AC 必须含：回执部分失败 fake → 零提交；回执失败 → `purged_at` 不变、行完整；kill-restart → 从 manifest 恢复且零身份丢失；逐 UUID 读回验收。
3. **全量可恢复备份（不变）**：PG `documents/document_versions/document_version_chunks/index_generations` 逻辑备份 + Weaviate 目标 UUID 清单快照；恢复验证 = 备份恢复到临时库并通过行数/哈希抽查后才可进入执行窗。Weaviate 对象向量本身不可再生的部分由 `document_version_chunks` 持久副本+重嵌入覆盖（重建判据=结构等价）。
4. **操作前集合冻结 + 审计哈希（R2 加严）**：执行窗开始时**重新做同快照全审计采集**（§2 证据边界声明：R1 工件为 B-REPORTED、非持久，不得引用）——全新 PG 三表只读导出 + Weaviate 全量 cursor 清单，完整长度 sha256 入受限持久通道；重跑 `scripts/gc_preflight.py`（live 模式，含文档+代双面对账与 820-only 范围门），归档 `--report-json`；manifest sha256 与 allowlist sha256 双哈希入审批记录。预检 exit ≠ 0 即中止（**范围门 violation = 退役代范围未获单独授权**）。
5. **精确 UUID 范围（不变 + R2 边界）**：仅 GC 自身确定性推导（等价于 manifest）；绝无 TEXT 过滤。**不使用**任何一次性 Weaviate 批删脚本。R2 明示：GC 推导面包含退役代目标外 UUID（§3.3），清单级 820-only 由预检范围门表达；GC 执行面的 820-only 只能通过解禁前置工程（第 2 条）的 manifest 驱动实现。
6. **批次/中断/重试（重写）**：批次节奏与限速（按 deleted_at 周切，窗口间预检）保持 R1 设想；但**中断恢复不再宣称「重跑 sweep 补齐」**——解禁前该说法不成立（见裁决 3）。恢复语义以第 2 条 c) 为准。
7. **每批后 PG+Weaviate 逐 UUID 读回对照（保留，地位提升为执行内门）**：每批次后立即以只读清单重扫：`GCReport.objects_deleted`（尝试数）与读回的实际消失数**逐批次对账**，差额 > 0 即停止后续批次并进入 manifest 驱动恢复（R1 将其仅作验收，R2 后是元数据提交的前置条件之一——由第 2 条实现承载）。
8. **zero residual 验收（不变）**：48h 后（跨一个同步周期+TTL 窗口）复扫一次确认无回填；#84 检索面回归（widget/api 各一轮只读探针不新增生成）确认无 withdrawn 身份召回。
9. **失败恢复路线（重写）**：~~PG 行已删但对象残留（不可能顺序）~~ → **该顺序可发生**：以执行前冻结清单 + `document_version_chunks` 持久副本重建身份映射后二次点删/重物化（解禁前置工程必须使其不可能产生，此处仅为纵深兜底）；误删 active 对象（预检证明为 0 概率）→ 从 `document_version_chunks` 持久副本走 repair 重物化。
10. **配置卫生（不变）**：一次性受控窗后评估是否保留常驻 `LIFECYCLE_GC_TOMBSTONE_DAYS`（保留=未来墓碑自动清理；不保留=恢复 opt-in 关闭态）。两个方向均需 User 意图，不默认。

## 7. 范围与 UNKNOWN 边界

- 未执行任何生产写入/删除/purge；未把 820/17,479 当已验证事实（820 已现场重核，17,479 判 UNKNOWN）。
- **R2 新增边界**：①生产 GC apply 对生产删除**HARD NO-GO**（§6 裁决），本 Task 未改生产 GC 本体，解禁需独立授权的工程任务（§6.2）；②§2 工件为 B-REPORTED、非持久（不可独立复核），执行窗 preflight 必须全新采集（§2 声明）；③预检的 820-only 范围门把退役代目标外触达（51 + 未来成熟的代 22/83）显式划出本授权范围（§3.3）。
- **UNKNOWN 清单**：①17,479/7,148 的测量口径与采样时点（原始逐项工件缺失）；②2,695 个可推导但缺席的对象分布成因（不构成清理风险，存储/审计事实，未逐项归因）；③2,370 个 active-wiki 旧代孤儿的处置路径（超出本契约）；④历史 LLM 正文采纳与否（无请求日志，永久 UNKNOWN）。
- 采样时点差异风险：本账本冻结于 2026-10-15 09:42Z；执行窗必须重新预检（当日已观测到代构建活动会使数字漂移）。
