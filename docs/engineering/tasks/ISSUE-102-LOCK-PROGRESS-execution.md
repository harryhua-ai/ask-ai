# Issue #102 执行报告 — repair-all × init_db DDL 锁队列死锁消除

- Claim: `harryhua-ai-20260921T175752-693a4f6e`(mode=implement,authority=allowed)
- Branch: `agent/102/87ec48e6`(base = `47f33046` = main tip,#94 merge)
- Contract: #102 body `ght-contract` v1(AC1–AC6;design_refs #100/#101)
- 状态: **CANDIDATE READY — 待 Role A review**(STOP;不自行 merge)
- 生产 mutation: **0**

## 1. RCA → 修复映射(#100 生产实证)

| 生产事实(v1.6.3-r8,knowledge-support-cases 验证窗) | 机制 | 修复 |
| --- | --- | --- |
| repair-all 批级 `lock_session` 在同一长开事务里先 `FOR UPDATE` data_sources 再跑 documents 资格 SELECT;事务整批存活(实证 idle in transaction 56min+)并持有 documents ACCESS SHARE | 长开事务触碰的表成为锁队列枢纽 | AC2:guard 事务**只保留** data_sources 行锁语句(跨 worker 批互斥契约不变);documents 资格快照移入独立短事务(读完即释放) |
| sync-cron 每轮 `init_db → ensure_track_c_columns` 重跑 `ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type` —— 列已存在时 PG 仍先取 ACCESS EXCLUSIVE 再判 no-op | 稳态 no-op DDL 仍要全表排他锁 | AC3:`_table_column_exists`/`_index_exists` catalog 探测(只读 pg_catalog,零目标表锁);schema 已兼容 ⇒ **零 DDL 语句**;ensure_sync_delta_columns/ensure_sync_request_kind_column 同契约 |
| repair 后续 per-doc 查询按 PG 公平序排在等待中的 ALTER 之后 ⇒ 三方互等、零前进 | 排队级联 | AC1:guard 不再持 documents 锁 ⇒ DDL 无队列可入;稳态无 DDL ⇒ 队列源头消失;AC4:重叠有界完成,无需 terminate_backend/停 cron |

## 2. 有界性论证(真缺列路径,AC3 truthful)

稳态(列在)探测即返回,不产生任何锁请求。真缺列(升级/新装)时 DDL 仍真实执行,
但运行于 `SET LOCAL lock_timeout = '5s'`:与长事务重叠 ⇒ 55P03 → 包装为可执行
RuntimeError(指明竞争语境与"下一轮重试")—— 有界失败,绝非静默跳过,亦非无限
排队。探测与 DDL 间的窗口由 `IF NOT EXISTS` 语义兜底(重复执行安全)。catalog
探测本身不申请目标表锁,不可能排队。

## 3. repair-all 语义保持(AC5,#100 冻结面)

- 有界幂等键(`bulk-repair-v1/v2`)未动;
- 逐文档隔离(try/except per doc)未动;
- 聚合守恒(eligible == succeeded+rebuild_requested+failed,含 open-task 分支)未动;
- open-task lineage(`create_repair_task` 幂等/开放任务/#83 退役门)未动;
- 资格快照时序与原实现等价(原本也是先取行锁再读资格集;快照后漂移由
  `create_repair_task` 逐文档再校验兜底,既有行为);
- repair ≠ authoritative sync 边界零改动。

## 4. 测试(RED→GREEN)

新增 8 例,先因正确原因 RED,后全 GREEN:

| 文件 | 数 | 覆盖 |
| --- | --- | --- |
| tests/db/test_init_db_lock_safety.py | 5 | 稳态 ensure_track_c 零 DDL(持锁长事务下 20s 排队超时 → GREEN 即时);init_db 稳态轮零 DDL;其余 ensure_* 同契约;真缺列+无冲突 ⇒ 真实 DDL 完成;真缺列+锁竞争 ⇒ lock_timeout 内有界 actionable 失败 |
| tests/api/admin/test_repair_all_lock_progress.py | 3 | AC1 纯 PG 锁序本体复现(长读 → ALTER 排队 → 读饿死;释放后全部前进)+ 同重叠 GREEN 面;AC2 guard 会话语句审计(整批仅 data_sources FOR UPDATE;资格会话恰读一次);AC1 端到端(批中段注入外部 ALTER ⇒ DDL 与批都 bounded 完成 + AC5 守恒) |

RED 证据:稳态 ALTER 在持锁长事务后排队(20s 超时);guard 会话含 documents 语句
(structural 断言失败);端到端外部 DDL 5s 内完不成。测试线程纪律:psycopg2 阻塞
调用一律 `asyncio.to_thread` 后台任务(排队观察),不在事件循环上同步等待排队语句。

## 5. 回归

- #100 repair 语义 + Track C(U-8/U-14)+ tests/db:**81 passed / 0 failed**;
  (修复过程中曾发现全量套件下 guard 审计测试误报 —— 根因是测试插桩用 id()
  弱引用,短命 auth 会话 GC 后地址复用导致语句误归属;已改强引用,非实现缺陷)
- tests/scripts + tests/services + tests/pipeline:**1601 passed / 5 skipped / 0 failed**;
- broader backend 全量:**2967–2971 passed / 失败集 = 4 已知基线(gap_export×2 /
  gap_observation / tech_answer_gaps)+ recovery_semantics/sync_executor_loop
  时钟敏感族 —— 该族在纯净 base 47f33046 上同样失败(临时 worktree 实测 4F),
  与 #75 轮既分类的"宿主×DB 时钟竞态 flake"同族,与本 diff 零因果(两轮全量
  该族通过/失败翻转,进一步证实 flake 属性);admin 全目录 518P(含本候选
  新 3 例)仅余基线 4F。

## 6. 契约验收对照

| AC | 落点 |
| --- | --- |
| AC1 | test_ac1_production_lock_ordering_reproduced_then_bounded + 端到端重叠测试 |
| AC2 | guard 会话语句审计测试 + guard/资格会话拆分实现 |
| AC3 | init_db 稳态零 DDL 三例 + 真缺列完成/有界失败两例 |
| AC4 | 端到端重叠测试(无人工干预,两者 bounded 完成) |
| AC5 | 81 例 #100/TrackC 回归全绿 |
| AC6 | §5 套件 + §7 全量;零部署零生产触碰 |

## 7. 全量回归(补记)

见交付说明附表。

## 8. 边界自检

- 零生产 mutation;未部署;未动 #100/#94/#91/#83 语义;
- 未以停 cron / terminate_backend 作为产品修复(仅存在于测试的锁序构造中);
- 无 migration framework 改动(纯 session.py 内两函数级改 + 端点 guard 拆分);
- 单 ACTIVE claim,不自行 merge。

**STOP:等待 Role A review;不自行 merge。**
