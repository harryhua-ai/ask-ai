# TB-P1 — PRODUCTION MIGRATION CORRECTIVE 执行报告

Status: **CANDIDATE READY**(待独立 Role A 评审;未部署;未触碰生产;v1.6.0 未动)

- 分支:`trace-b/p1-migration-corrective-20260911`(自 main `7f5acf6` 切出)
- 前情:`TB-P1 PRODUCTION = PARTIAL`(报告
  `docs/engineering/tasks/tb-p1-production-migration-runtime-acceptance.md`;
  迁移 fail-closed 于 NUL;rollout 未执行;生产仍 v1.5.0 健康)
- 本矫正只覆盖任务授权的三项阻断修复;**不含**生产迁移续跑/部署(属下一任务)

---

## 1. Current main baseline

`7f5acf6`(= 2d7e416 P1 接受树 + 并发治理线 05b8a9d/2b9e7db + PARTIAL 报告;
全部与 P1 代码面正交)。

## 2. RED 证据(实现前,10/10 全红)

`tests/db/test_migration_p1_corrective.py` 首跑(实现前):

| # | 用例 | RED 表现 |
| --- | --- | --- |
| 1 | NUL chunk text 剥离+chunk 保全 | `KeyError: 'nul_chunks'`(stats 键不存在)+ NUL 文本原样入库会崩 |
| 2 | 嵌套属性 NUL 剥离 | 同上 |
| 3 | 多 NUL 精确统计 | `KeyError: 'nul_chars_removed'` |
| 4 | 常规文本零改动 | `KeyError`(stats 键) |
| 5 | 重跑幂等 | `KeyError` |
| 6 | 混批结构 1:1 | `KeyError` |
| 7 | clean legacy verify-only | `AttributeError: inspect_pg_migration_state` 不存在 |
| 8 | partial 态 fail-closed | `AttributeError` |
| 9 | migrated 态全量验证 | `AttributeError` |
| 10 | manifest 登记 P1 迁移 | `assert "scripts/migrate_p1_lifecycle_foundation.py" in entries` 失败 |

## 3. FIX-1 — NUL 安全真值迁移(冻结口径的精确实现)

**精确规则**:对写入 PG 真值的每个值(`document_version_chunks.text` 与
`props` JSONB 的全部字符串值,含 list/dict 嵌套递归)执行
`value.replace("\x00", "")` —— **仅移除 NUL 字符,零其他 Unicode/内容归一化**;
`props` 单遍递归(text 含于 props,自然去重,不移除计数)。Weaviate 侧原对象
**零改动**(text 原样、向量原样、不删除);source_id/chunk_index/版本
chunk_count 全不变(结构 1:1);不跳过任何 chunk。

**统计语义** = 真实持久化时的清理量(exists-skip 的重跑路径不计入,保证
幂等重跑统计不膨胀):`nul_objects`(按对象去重)/ `nul_chunks` /
`nul_chars_removed`;连同 scanned/chunks_inserted/props_backfilled/
ghost_objects 一起入返回值与迁移日志(日志行显式含 NUL 三元组)。

实现:`_strip_nul_value()` 递归剥离助手 + `backfill_content_from_weaviate`
在 pending_chunks 组装处单点净化、`_flush` 真实插入处计账。
结构守卫同步收紧:零重嵌红线测试原断言 `".replace(" not in source` 会误伤
`str.replace`;改为精确红线 `assert "data.replace" not in source` + 
`assert "vector=" not in source`(Weaviate 对象替换写/向量传输),零重嵌
语义不变。

## 4. FIX-2 — Legacy-safe --verify-only(三态状态机)

- `inspect_pg_migration_state(sf)`(只读,information_schema 探测八结构:
  5 documents 列 + 3 表):全缺 → `legacy`;全在 → `migrated`;其间 →
  `partial`(缺列/缺表明细随结果返回);
- `migration_gate(state)`:legacy → `("LEGACY / MIGRATION REQUIRED /
  ELIGIBLE", True)`;migrated → `("MIGRATED / RUN FULL VERIFICATION", True)`;
  partial → `("PARTIAL / INVALID MIGRATION STATE - FAIL CLOSED", False)`;
- `run_verify_only_gate(sf, client, class_name)`:legacy → 显式 ELIGIBLE
  结果(零变更退出);migrated → 走既有全量 `verify()`(PG 不变量 +
  Weaviate 校验,fail-closed);partial → `RuntimeError`(fail-closed);
- CLI `--verify-only` 接线至 gate。**--verify-only 全程只读**(不建表、
  不补列、不写数据)。

生产对应态(本矫正前):PARTIAL(实际)——正是该状态机会拦截的情形;
v1.6.0 部署桥若在该态误走 verify 会显式失败而非静默。

## 5. FIX-3 — 部署迁移清单登记

`deploy/prod/migrations.json` 追加
`scripts/migrate_p1_lifecycle_foundation.py`(排在既有
launcher_presentation 之后;清单契约:条目幂等/加性,冻结树内存在)。
效果:任何 ≥ 本矫正树的 release 经部署编排时,P1 迁移在 rollout 前由桥
自动执行——**不再可能被静默跳过**;已手工部分迁移的生产库上重跑安全
(§7 幂等)。验证:`release_migration_plan.py` 白名单正则 + 树内存在性
校验覆盖于新测试(RED-10)。

## 6. 定向测试(GREEN)

`tests/db/test_migration_p1_corrective.py` **10/10 PASS**(真实 PG 一次性库
+ 真实 Weaviate):

1. NUL chunk text → `"before\x00after"` 持久化为 `"beforeafter"`,chunk 保全,
   Weaviate 对象 text 原样(含 NUL)、向量不动;
2. 嵌套数组属性 `["widget\x00","api"]` → props JSONB 内 `["widget","api"]`;
3. 多 NUL 精确统计:文本 5 + 属性 1 = `nul_chars_removed==6`,
   `nul_chunks==2`,`nul_objects==1`(同对象双 chunk 去重);
4. 常规文本(含中文/emoji)逐字节不变,三项 NUL 统计全零;
5. 重跑幂等:`chunks_inserted==0 / props_backfilled==0 / nul_chunks==0`,
   行内容不变;
6. 混批(1 NUL+3 常规 chunk)结构 1:1:插入 6、版本 chunk_count 2/3/1 逐文档
   符合;
7. 纯净 legacy → `state=legacy` + 门 `ELIGIBLE/放行`;
8. 缺一列的部分态 → `state=partial` + `FAIL CLOSED` + `run_verify_only_gate`
   raise;
9. 全迁移态 → `state=migrated` + 走全量验证 PASS;
10. manifest 含 P1 条目;全部条目过白名单正则且树内存在。

回归:`tests/db/test_migration_p1_lifecycle.py` 7/7(含收紧后的零重嵌守卫)。

## 7. 幂等证据

- 用例 5(NUL 文档在场重跑):二跑 0 插入/0 补属性/0 NUL 统计/行不变;
- 既有 idempotency 测试套件全绿(test_migration_p1_lifecycle:补列二跑、
  版本回填二跑 0、内容回填二跑 0/0);
- 生产场景推演:已手工落地的 schema+12,000 版本为同一工具同一序的产物,
  续跑 = 版本回填 0 新建 + 内容回填按 exists-skip 续传 + NUL 5 文档正常
  持久化(剥离后)。

## 8. 全量回归

`2399 passed / 8 skipped / 0 failed`(组合树,含治理线增量);
`ruff check` 改动文件 **0 error**。

## 9. 变更文件 / Scope Audit

| 文件 | 分类 |
| --- | --- |
| scripts/migrate_p1_lifecycle_foundation.py | EXPECTED(FIX-1 净化+统计;FIX-2 状态机;CLI 接线) |
| deploy/prod/migrations.json | EXPECTED(FIX-3 清单登记) |
| tests/db/test_migration_p1_corrective.py | REQUIRED SUPPORTING(10 门测试) |
| tests/db/test_migration_p1_lifecycle.py | REQUIRED SUPPORTING(零重嵌红线精确化) |
| 本报告 | REQUIRED SUPPORTING |

**未触碰**:检索/排序/reranker/引用、lifecycle schema 语义(仅迁移工具)、
GC、tombstone 策略、Admin、P2+;生产零触碰(无 SSH 变更、无迁移重跑、
v1.6.0 未部署、5 篇 NUL 文档原样、无 GC);v1.6.0 tag/Release 原样未动。
迁移工具改动 = 授权冻结口径的精确落地,不改任何已接受 P1 产品语义;
`_strip_nul_value`/状态机为迁移脚本内部新增,零模块间耦合。

## 10. 候选

- 分支:`trace-b/p1-migration-corrective-20260911`
- 候选 commit:见分支 HEAD(本报告提交为最新提交)
- 后续(授权后):独立评审通过 → 并 main → 新 tag **v1.6.1** →
  部署桥自动执行 P1 迁移(含 NUL 矫正)→ 生产迁移/运行时验收续跑

---

TB-P1-PRODUCTION-MIGRATION-CORRECTIVE = CANDIDATE READY
