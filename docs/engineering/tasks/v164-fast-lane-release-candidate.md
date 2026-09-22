# v1.6.4 FAST-LANE — DEPLOY-READY CANDIDATE REPORT

状态:SEE "FINAL VERDICT" — 本报告随最终 candidate 提交,SHA 见文首。

## Identities

```text
INTEGRATION_BASE:  dc5c0a0391aaf0740f6dc5bb064be570255cedfc  (POST_105_MAIN = merge PR #109)
POST_105_MAIN:     dc5c0a0391aaf0740f6dc5bb064be570255cedfc
FINAL_CANDIDATE_SHA: SEE BELOW (release/v1.6.4-deploy-ready head)
FINAL_PR:          SEE BELOW
Track A (#106):    b9df383 @ track/issue106-prepool-recall
Track B (#107):    c2868eb @ track/issue107-test-dsn-contract
INTEGRATED_SHA_PRE_GATE: 3f6d8b7234134f4b0d8022394499a96e41226a05
```

#105 merge(Gate 0):

- merge:PR #109 head 逐字节核验 = Role A FINAL PASS 接受的
  `812d0b431fa471851d96e7d4d31c3e101054ff5d`(durable review comment
  5774356990,exact-SHA bound),GitHub 报 MERGEABLE/CLEAN,仓库标准
  merge-commit strategy,零 force。merge commit = `dc5c0a0`,双父
  (926dfb7a, 812d0b4)精确。
- focused:#105 全部 10 focused(commerce convergence T1–T8 + mirror-drift
  reachability T9/T10)在 post-merge main 上 10/10 GREEN。
- ght 备注:claim `harryhua-ai-20260922T055616-f5e6c1ac` 已 deliver
  (candidate 812d0b4 登记,execution lease released);`ght complete`
  的机械校验要求「A REVIEW — ACCEPTED」格式 top-level comment,而本轮
  FINAL PASS 评论为 `## Role A REVIEW_R5 — FINAL PASS` 格式,不被
  complete 识别 —— claim 终态化留给 Role A(governance bookkeeping,
  非工程阻塞)。

## #106 — Solution/Case pre-pool recall + OCR authority

RCA(真实查询路径,只读):

- 检索三路(主 hybrid / 符号 / intent boost #78 桶)全部以查询相似度
  竞争入池;官方 Solution 页 `solutions/infrastructure-monitoring/`
  内容主题与水表 OCR 查询弱相关 → 全局竞争整页落榜(生产实证 EN 0/78,
  ZH 0/85)。
- 已接受的 #31 `SOLUTION_RETENTION_FLOOR`(R1 保位)只作用于**池内**
  成员:上游 recall 缺失使其结构性无从发力。缺陷面 = pre-pool。
- EN/ZH 不对称 = 召回随机性:EN 池 case 页 rank 6(hybrid+boost);
  ZH 池 0/85,内部历史工单(filesystem/knowledge)占据 CASE_EVIDENCE
  槽位 —— production AD2 命名的反模式。
- authority taxonomy(`_has_solution_signal` /
  `_is_published_case_page`,#31 冻结)只活在 post-pool 匹配,从未进入
  pre-pool 召回。

实现(bounded、deterministic、语言无关):

- `search_bucket` 加性 `url_substrings` 谓词(Weaviate like,any_of):
  权威页面段凭**页面结构身份**获得类内确定性准入,与查询相似度解耦。
- role-recall lanes(solution / case-stud 段):仅当证据计划为
  recommendation 意图且含 SOLUTION_GUIDE / CASE_EVIDENCE 槽时启用
  (support / factual / commercial 零触发,#78 既有桶契约零漂移);
  每 lane 一次检索、limit ≤ 10、零新增 embedding、零 corpus-wide loop、
  零 LLM;成员须通过与 post-pool 同源的 authority 谓词校验(URL 信号
  不得冒充角色);异常降级同既有 boost 桶纪律;出账进
  `stages.retrieve.buckets`(`role:<名>`)。
- R1 窄扩展(CASE_EVIDENCE):first-party published case 池内可得而
  幸存者无 first-party 形态时晋升最优 published case(正相关下限,
  与 #31 SOLUTION_GUIDE 保位同一纪律);first-party 不存在时既有语义
  逐字节保留(optional 槽 no-op / required 槽通用晋升)。

RED→GREEN:

- RED(实现 stash 后在 base 状态):5 个测试失败精确钉在缺陷面
  (solution 准入 / lane 出账 / ZH case 准入 / EN-ZH 等价 / R1
  first-party 优先),7 个夹具对照通过。
- GREEN:14/14 scripted + 2 真 Weaviate lane 原语可达性
  (`tests/pipeline/test_issue106_first_party_recall_lanes.py`、
  `tests/retrieval/test_issue106_lane_reachability.py`)。

EN/ZH parity:等价 EN/ZH 方案查询对断言 Solution + first-party Case +
Product/Wiki 三类 role coverage 等价(不要求候选全同)。

OCR authority(AC5,read-only 诊断,Case A/B 裁决):

```text
OCR_AUTHORITY_STATUS = EXTERNAL_CONTENT_GAP
```

- 配置源(wiki-documents main 树 + NeoMind repo,GitHub API 只读核验)
  中不存在期望的 "NE101 Camera AI Vision / paddle-ocr pipeline"
  model-use-case 权威文档(wiki 树 paddle 零命中;NeoMind repo 54 个
  .md 均为 agent/ADR/skills 文档,ocr/vision 命中全是代码与 eval 文件)。
- 生产 ledger 只读诊断(v1.6.3-r9 生产,backend 容器只读 SELECT):
  wiki-local 585 篇(540 active)中 `docs/0-neomind/` 段 128 篇 active
  已在库(相邻权威),但该特定 use-case 页不存在;neomind-local 无
  OCR use-case 文档(vision 命中全部为 .rs/.json 代码)。
- 结论:上游 genuinely absent → 不创建、不合成、不从别处复制假装
  authority;该 sub-gate 记录 EXTERNAL_CONTENT_GAP 后 STOP for Role A。
  production acceptance 须按此口径标记。

负面对抗矩阵(全部有测试):

| 边界 | 结果 |
|---|---|
| Reachability | 真 Weaviate URL-segment lane 原语 2/2(scripted 链路 14/14) |
| Negative boundary | factual / support 查询零 lane 触发(support = #78 冻结契约,`test_rag.py` 契约测试保持) |
| Product isolation | lane 继承既有 product_labels/channel/product_filter 硬过滤(同一 search_bucket 通路) |
| Authority integrity | URL 信号命中但无 solution 语义的页不得入池(谓词校验测试);support ticket 不得冒充 first-party case(R1 优先测试) |
| Citation integrity | lane 候选经既有 citation 管线(#77 资格谓词回归 289 passed 全绿) |
| Fail-closed | lane 异常降级不阻断主流程、不伪造证据(fail-open 降级测试) |
| EN/ZH | 等价对 coverage 等价测试 |
| Cost | 每 query 至多 +2 lane、limit ≤ 10;零新增 embedding;零 corpus-wide loop;零 per-result LLM |
| Idempotency | 重复查询零状态漂移测试 |
| #31 语义 | evidence reservation 全套(#31/#77/inc4/inc5/inc7)289 passed 保持 |

## #107 — release CI test-DSN contract

RCA:

- `tests/db/test_init_db_lock_safety.py` 裸读
  `load_settings().postgres_dsn`(两处:psycopg2 锁连接 + DDL 计数
  engine),违背仓库 canonical 测试库解析契约
  (`tests/conftest.py` db_engine:TEST_DATABASE_URL 权威,settings 回落)。
- release CI 形状(build-image.yml:job env 注入
  `TEST_DATABASE_URL=…ask_ai_test`;postgres service 仅建 ask_ai_test):
  该测试解析 settings 默认 `POSTGRES_DB=ask_ai` →
  `FATAL: database "ask_ai" does not exist` → 5/5 harness 缺陷失败
  → `build-and-push needs: test` → tag 无镜像 → break-glass。
  证据:CI run 35713214378(HEAD dc5c0a0)与 v1.6.3-r9 tag run
  35686494777 同失败。
- 隐含危害(本候选执行中实证):裸 settings DSN 在开发机上静默指向
  schema 持久的本地库,lock-safety 探针(LOCK TABLE / ensure DDL)依赖
  「恰好存在的表结构」—— 测试环境的 DSN bug 同时是静默脱离测试库的
  缺陷。

GREEN(canonical 契约 + fail-closed,不削 #102):

- `_test_dsn()` / `_sync_dsn()`:TEST_DATABASE_URL 权威;无 env 时仅非
  prod 形状回落 settings;`APP_MODE=prod` 且无显式测试 DSN ⇒
  RuntimeError(镜像 #20 `resolve_migration_dsn` 先例)。
- 文件自足:module 级幂等 `init_db` 预热 canonical 共享测试库(其表会被
  其它测试 db_engine fixture drop_all;此前隐含依赖「某个外部持久库」)。
- grep 级守卫(镜像 #20 迁移脚本守卫):lock-safety 文件禁止绕过
  resolver 裸读 postgres_dsn。
- #102 语义冻结:锁序 / lock_timeout / 稳态零 DDL / 有界进度断言零改动,
  9/9 通过。

RED→GREEN(进程级 CI 形状):

- base(dc5c0a0)+ CI 形状 env(settings 指向不存在库 + TEST_DATABASE_URL
  指向 ask_ai_test):5 failed in 0.6s(纯 harness 缺陷 = 生产 CI 形态)。
- candidate + 同 env:5 passed。
- 契约测试 4 个(env 权威 / prod fail-closed / dev 回落不回归 / grep
  守卫):base 上 3 RED 1 PASS(护栏),candidate 4/4。
- #107 电池(tests/db + test_migration_dsn_guard + tests/deploy):
  102 passed ×2 稳定。

## Regression

- focused(三轨 integrated 树):34 passed(#105 10 + #106 16 + #107 8)。
- #106 面扩展 battery(evidence/rag/retrieval 全家):289 passed。
- #107 电池:102 passed ×2。
- full-suite(Tag CI 精确形状:`pytest tests/ -q --ignore=tests/api/admin
  --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder
  --ignore=tests/e2e`,TEST_DATABASE_URL 注入):
  **integrated candidate = 2522 passed / 0 failed / 2 skipped**
  (skip = test_sync_gap_heal 既有环境性 skip,非候选面)。零失败,
  base 对照归因不适用(无失败可归因)。已知历史 baseline 失败
  (gap_export×2 / gap_observation / tech_answer_gaps)在 Tag CI 形状
  的忽略集/修复面之外,本候选零新增失败。
- candidate-attributable failures:**ZERO**(全绿;Track B 执行中发现并
  当场修复的 lock-safety 表自足问题属 track 内修复,修复后 102×2 稳定)。

## Release Gates

- build(container):**由 GitHub canonical CI 执行**(build-image.yml
  workflow_dispatch on 本 release 分支)—— 遵循 User 指示不在本地测 CI。
  该 workflow 同时重跑 test job(TEST_DATABASE_URL 注入的 pytest,
  postgres service 形状)与 build-and-push(widget/admin 构建、
  RELEASE.json 生成、in-image 身份断言)。结果:SEE CI RUN BELOW。
- migration/init:候选零新迁移(ledger 14 条与 base 逐条一致,零漂移;
  `release_migration_plan.py --tag v1.6.4` 输出 = manifest 全量对账,
  生产按台账已全部执行,实际 PLAN=NONE);init_db 稳态零 DDL 由 #102
  套件持续保证(102×2 电池全绿)。
- startup/smoke:本地隔离启动冒烟(独立库 ask_ai_smoke + 独立 Weaviate
  collection Issue164Smoke,零生产触碰):
  - Isolated startup:进程启动 ~10s,/health 200,`version=1.6.4`、
    `git_sha` 精确等于候选 SHA;init_db(空库 create_all)成功;
    Weaviate 可达;零 fatal traceback。空库无 `ADMIN_PASSWORD` 时启动
    被拒(#76 fail-closed bootstrap 按设计工作,顺带验证)。
  - Smoke(真 embedder/reranker CPU + DeepSeek LLM 真实调用):
    - ZH 方案代表查询:sources 含官方 Solution 页与 first-party Case 页
      (role lane 经真实 /ask 全链路生效,231 token 流式输出);
    - EN 等价查询:sources 同样含 Solution + Case 两页(EN/ZH parity);
    - factual 规格查询:sources 命中 Product/Wiki 规格页,且零 lane
      触发(负面边界);
    - citation integrity:sources 事件携带真实 URL/标题;
    - 顺带验证:P0 SourceVisibilityGuard 对未登记源按 DENY 处理
      (fail-closed 纵深防线按设计工作;登记后恢复)。
  - sync 子系统:由 #105 的 runtime 级集成测试覆盖(real `_sync_one →
    connector → GenerationBuilder`:normal/no-change/mirror-reconciliation/
    幂等),broad 套件中全绿;未触碰生产 Store。
- release-CI simulation:由真实 GitHub CI 取代(上)。

## CI RUN (GitHub canonical)

SEE CI RESULTS BELOW.

## Production Acceptance Package(deploy 后执行;本轮零生产 mutation)

#105(canonical normal WooCommerce sync 唯一路径;禁 reindex / SQL /
vector repair / hard-coded product action):

1. 部署后触发一次 normal canonical Woo sync;
2. 验证链:Store → connector → active DocumentVersion → documents row →
   persisted chunk props → serving/vector props;
3. 若生产身份仍在,必须纳入验证:`5110:5950`、`5110:5951`;
4. 验证 current Store commerce truth / stock_status / price / sale /
   purchasable / `commerce_synced_at`;
5. 重复 normal sync → 幂等 UNCHANGED(零 embedding churn、零新版本、
   零新代)。

#106(冻结的 #31 representative EN/ZH water-meter OCR queries 重跑):

1. 验证 official Solution 页 + matching first-party Case 在相关时被
   admitted/retained(candidate pool 含身份 + 终局上下文含身份,两语言);
2. Product/Wiki role 覆盖保持;
3. unrelated support ticket 不得冒充 first-party Case(first-party 在
   库且相关时终局须含 first-party 形态);
4. EN/ZH authority-role coverage 不再按语言分裂;
5. absence 语言保守(不得因 recall 缺失断言官方不存在);
6. citations 指向真实 evidence;
7. **OCR authority**:按 AC5 裁决标记 `EXTERNAL_CONTENT_GAP` —— 不得
   要求系统生成/引用不存在的权威;相邻 0-neomind 开发者文档已在库,
   可被引用但不得冒充该特定 use-case 权威。

#107(正式 release/tag 后):

1. tag CI primary artifact path:lock-safety 测试使用 intended test DB
   (job env TEST_DATABASE_URL),build-and-push 正常产镜像;
2. release CI 不因 TEST_DATABASE_URL mismatch 失败;
3. 不因该缺陷走 break-glass host build。

## Rollback Package

- Rollback target:部署前 stable release = `v1.6.3-r9` @
  `926dfb7a08bf506a635a259a41b9a60ebfdb62b1`(canonical dispatch 回滚,
  `deploy-production.yml` dispatch `-f tag=v1.6.3-r9`;既有先例 r5→r4)。
- Rollback triggers(任一即回滚):
  - startup failure / migration failure / health 不 healthy;
  - /ask query error-rate 回归或 citation integrity 回归;
  - cross-product contamination(产品隔离破坏);
  - Woo truth non-convergence(#105 验收失败);
  - retrieval explosion / lane 未按预算(role lane 失控扩大);
  - release artifact 失败。
- Rollback constraints:不依赖 manual DB surgery / manual vector
  surgery / destructive cleanup。本候选**零新迁移**(ledger 14 条不变),
  #105/#106/#107 均为代码/测试层变更,backward compatibility = 直接
  回滚镜像即可;#105 metadata-only/activation 行为在回滚后保持既有
  v1.6.3-r9 语义(无 schema 依赖)。

## CI RUN (GitHub canonical)

- build-image.yml 以 workflow_dispatch 在本 release 分支触发(User 指示:
  不在本地测 CI;本地 docker build 尝试因 pypi.nvidia.com 上游 CDN
  504/timeout 两次失败,非候选缺陷,已放弃本地构建路线)。
- Run 结果 SEE CI RUN ID BELOW:job test(TEST_DATABASE_URL 形状
  pytest + postgres service)→ build-and-push(widget/admin 构建 +
  RELEASE.json + in-image RELEASE.json 身份断言)。

## FINAL VERDICT

DEPLOY_READY(预 CI 确认)—— 工程正确性、三轨回归、broad 全量、迁移
一致性、隔离启动、smoke 全部门 GREEN;release build 由 GitHub
canonical CI 在本分支执行。待 Role A exact-SHA 终审时一并核验 CI run
绿灯与镜像身份断言。
