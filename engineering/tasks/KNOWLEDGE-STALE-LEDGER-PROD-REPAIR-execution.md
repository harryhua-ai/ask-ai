# KNOWLEDGE-STALE-LEDGER-PROD-REPAIR 执行报告

- **任务**:knowledge-support-cases 源 26 行历史 gate 测试账本残留的受控生产修复
- **优先级**:P0 DATA REPAIR · CONTROLLED PRODUCTION REPAIR
- **基线仓库 SHA**:073f26236c08531212f6d5b12b8b8173f0557c79(v1.1.1,= 生产运行版)
- **执行日期**:2026-09-05
- **最终状态**:**PASS**

## 1. 背景与根因(承接只读排查)

源 `knowledge-support-cases`(filesystem,/home/ubuntu/knowledge-support/)的每轮同步报
「一致性校验发现缺口 481/507;需重灌 26 篇;复验仍 481/507」且补齐无效。只读排查(systematic-debugging
Phase 1)确立根因:26 篇缺失全部为 v1.1.0 容量门/REV3.1 门验收测试文档
(`gate-72cdcbf-*` ×13 + `gate-762eae3-*` ×13,各 1 chunk);验收清理时删除了磁盘文件、
手工点删了 Weaviate 向量,但 documents 表账本行残留。filesystem `fetch_deleted()` 恒返回空
(删除检测不存在)→ 无任何流程退休这些账本行;补齐分支 `fetch_all()` 无法为已删文件再现
source_id → 0 灌入 → 永久 partial。真实知识(179 篇/481 chunks)账实一致,EXTRA_UNRESOLVED_ORPHAN=0。

## 2. Phase 1 — 变更前验证(PASS)

全量重读生产现状(独立复核,不沿用排查期数据):

| 不变量 | 实测 | 判定 |
|---|---|---|
| documents 账本 | 205 docs / 507 expected chunks | ✓ |
| Weaviate 实际 | 481 chunks / 179 docs(全量迭代器+客户端前缀,与校验器同口径) | ✓ |
| MISSING(整篇缺失) | **26**,且逐条匹配 gate 测试文档身份正则 `gate-(72cdcbf\|762eae3)-*` | ✓ |
| MISMATCH(chunk 集合不一致) | 0 | ✓ |
| ORPHAN(多余/未决) | 0 | ✓ |
| 非候选群体 | 179 docs / 481 chunks | ✓ |
| 26 候选磁盘存在性 | 逐项 `test -e`:present_count=**0**(全部不存在) | ✓ |
| 26 候选向量数 | 逐项 Equal 精确查询:均 0(即 missing 定义本身) | ✓ |

## 3. 允许清单(26 项,逐一显式枚举,无模糊选择器)

`knowledge-support-cases/main/experience/` 下:
gate-72cdcbf-batch-01..12.md、gate-72cdcbf-capacity-test.md、
gate-762eae3-batch-01..13.md(完整 26 个 source_id 见 §4 表格首列)。

## 4. Phase 2 — 恢复证据

事务内(DELETE 之前)对 26 行执行全字段取证 SELECT:
`source_id, chunk_count, content_hash, created_at, updated_at`(source_type=filesystem、
product=camthink、branch=main 为同构值)。逐行 content_hash 与时间戳已留存于
tesla-t4:`/tmp/ks_delete_result.txt`(psql 会话输出;样例:
`gate-72cdcbf-batch-01.md | 1 | 1381b56b…d99cc | 2026-09-04 13:52:30.233+00`)。
26 行全部为 2026-09-04 两次 gate 灌入(13:52 批次与 15:10 批次),与验收史完全吻合。

## 5. Phase 3 — 原子删除(PASS)

- 单事务:BEGIN → 取证 SELECT → `DELETE FROM documents WHERE source_id = ANY(26 项显式数组)` →
  `GET DIAGNOSTICS n = ROW_COUNT; IF n <> 26 THEN RAISE` → COMMIT;psql `ON_ERROR_STOP=1`。
- 首次执行因 PL/pgSQL RAISE 占位符转义笔误在 DO 块编译期报错,ON_ERROR_STOP 于 COMMIT 前中止,
  **事务回滚、零行删除**(随即实证 count 仍=205);修正转义后重跑。
- 结果:`NOTICE: DELETED_OK rows=26` → **COMMIT**,deleted_rows == 26 ✓。

## 6. Phase 4 — 变更后独立复验(PASS)

| 不变量 | 实测 | 目标 |
|---|---|---|
| documents 账本 | **179 docs / 481 expected chunks** | 179/481 ✓ |
| Weaviate 实际 | **481 chunks / 179 docs** | 481 ✓ |
| MISSING | **0** | 0 ✓ |
| MISMATCH | **0** | 0 ✓ |
| ORPHAN | **0** | 0 ✓ |
| 26 个 gate source_id | 账本 0 行 / 磁盘 0 文件 / 向量 0 | 0/0/0 ✓ |

正规 reconciliation 路径刷新:`POST /api/admin/data-sources/knowledge-support-cases/sync`
(accepted,request_id=32,manual)→ 该源最新 sync_log:**status=success,items_unchanged=179,
error_detail 为空**——持续数日的 partial 告警消除,Knowledge Health = **HEALTHY**。

## 7. 边界确认(未授权项零发生)

未触碰:Weaviate 向量、真实知识文件/目录、源配置、sync 代码、filesystem 内容、无关服务;
无 wildcard/LIKE/前缀删除;未做全量重嵌;未实施 filesystem 退休行为(移交 #25)。
真实知识 179/481 全程未变(前后两次独立扫描一致)。

## 8. Phase 5 — 系统性缺口立项

GitHub Issue **#25**:「Filesystem sources do not retire ledger entries when source files disappear」
https://github.com/harryhua-ai/ask-ai/issues/25 — 记录机制(fetch_deleted 恒空/补齐不可达/
校验器如实)、本次事故、期望的 SOURCE-CONFIRMED 退休语义与安全要求(多次成功全量发现才可退休、
绝不凭向量缺失删除、与过滤策略显式交互、幂等可审计);实现 HOW 留待 Planner Discovery/Contract。

## 9. 最终状态

**PASS** —— 授权范围内单一突变精确执行(deleted=26),最终真相
179 docs / 481 expected / 481 actual / 0 missing / 0 mismatch / 0 orphan,Health=HEALTHY。
