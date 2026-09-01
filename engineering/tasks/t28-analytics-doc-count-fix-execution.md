# T28-ANALYTICS-DOC-COUNT-FIX Execution Report

- **Task / Initiative**:t28-analytics-doc-count-fix / 数据源健康度(D-9 归属体系)
- **Worktree / Branch**:`/Users/harryhua/Documents/GitHub/ask-ai-t28-doc-count` / `worktree-exec/t28-analytics-doc-count-fix`
- **Baseline → Final Commit**:`bbfaa6a` → `cc09cce`
- **Status**:**CANDIDATE READY**(不 push,等 A Review)

## Files Changed

| 文件 | 变更 |
|---|---|
| `backend/api/admin/analytics.py` | `source_health` 的 `doc_q` 聚合键从完整 `Document.source_id` 改为 `func.split_part(Document.source_id, "/", 1)`(复合键首段;无斜杠时 split_part 整串返回=整串即 id),`doc_map` 键随之对齐 sync_log 纯 id 口径 |
| `tests/api/admin/test_analytics.py` | 新增 `TestSourceHealth` 5 用例 + `_seed`/`_cleanup` 精准夹具工具;模型 import 扩展 |

响应字段集合、其余字段语义、sync_log 聚合口径、30 天窗口、写入链路:零改动(Frozen #2/#3 满足)。

## Implementation

单点修正:documents.source_id 是复合键 `{数据源id}/{路径}`(五 connector 一致),旧代码按完整键 GROUP BY 后用 sync_log 纯 id `doc_map.get(row.source_id)` → 永不命中 → 恒 (0,0)。现按首段聚合对齐口径。聚合仍在 SQL 侧(`GROUP BY split_part`),表规模增长时无全表拉取;项目全栈为 Postgres(JSONB 依赖),split_part 无方言风险,CI service 亦为 postgres:16。

## Verification actually executed

1. **TDD 红**:新增用例先行,`test_composite_key_multi_source_counts` / `test_chunk_count_summed_across_docs` **2 failed**(计数恒 0 缺陷复现),`test_source_without_documents_is_zero` / `test_no_slash_source_id_is_own_prefix` / `test_response_field_set_unchanged` 3 passed(其中无斜杠用例旧实现本就命中,是回归锁)。
2. **TDD 绿**:实现后 `tests/api/admin/test_analytics.py` **16 passed**(5 新 + 11 既有)。
3. **口径一**(tests/ 全量含 tests/api/admin,TEST_DATABASE_URL + ENCRYPTION_KEY):**540 passed**。
4. **口径二**(CI 确切口径 `pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e`):**447 passed**。
5. **AC1 本地真实库对账**(契约允许"测试内直连调端点"):以 `PYTHONPATH=worktree` 直调端点(ASGITransport,临时 admin 用户精准建删),对本地 ask_ai 库 11 个 sync 窗口内源逐行比对 SQL 前缀聚合(`split_part(source_id,'/',1)`,全量 SQL 见下)——**11/11 行一致**,其中契约点名的 website-camthink / local-db326229 / knowledge-* 三族全部命中:

   ```
   source_id            ep_docs sql_docs ep_chunks sql_chunks  match
   knowledge-0aa5b846         0        0         0          0  OK
   knowledge-1db4e151        67       67        67         67  OK
   website-camthink          40       40       606        606  OK
   ne101-84d914e4             0        0         0          0  OK
   wiki-47909975              0        0         0          0  OK
   review-c9w23-09c8e28e      4        4         4          4  OK
   local-db326229             0        0         0          0  OK
   c9-e2e                     0        0         0          0  OK
   local-47ece942           174      174       532        532  OK
   knowledge-d341da15         0        0         0          0  OK
   review-c9w23-2f37af50      0        0         0          0  OK
   ```

   对账 SQL(端点侧逐源与其比对):
   ```sql
   SELECT split_part(source_id,'/',1) AS sid, count(*) AS docs,
          COALESCE(sum(chunk_count),0) AS chunks
   FROM documents GROUP BY 1;
   ```
   对账脚本:`/tmp/t28_recon.py`(口径:端点 items 仅含 30d sync 窗口内源,无 sync 记录不入表=现语义维持;本次 SQL 侧无端点外孤儿源)。注意 documents 现总量 285 行,与契约 E3 撰写时 371 行不同=期间网站源再同步与 C9 清理所至,不影响"端点 vs SQL 同时刻对账"的结论。
6. **black**:analytics.py 全文件 clean;测试文件基线区(未触碰的业务 miss 测试)本就不 black-clean,遵守"black 只植增量"纪律仅手工对齐**本人新增行**(6 处),复验新增区无 black 诉求。

## Runtime / Real-World Self-Check

对账即真实库运行时自检:修复后端点在真实数据上 doc_count/chunk_count 非零且与 SQL 独立口径一致;无文档源(0/0)按 Frozen #1 语义返回。

## Deviations / Risks

1. **环境发现(记入,非缺陷)**:主仓 `.venv` 是 ask_ai **editable 安装指向主仓**——任何"直调 backend 代码"的脚本从任意 cwd 启动都会 import 到主仓代码,必须 `PYTHONPATH=<worktree>` 压前。首轮对账因此跑到旧代码(输出全 0),PYTHONPATH 修正后结论成立。起后端/写脚本时需注意。
2. 本地 documents 计数与契约 E3(371)不同(285),为契约撰写后的正常数据演进(见上),非本修复相关。
3. T4 生产同病(E6)随下次发布一并修复,本任务未触碰生产。

## Parallel/依赖状态

与 C8B/T26/T27 文件域互斥;T25A(健康度 UI 迁移)依赖本修复的数字,建议同批发布。
