# CamThink V1 — Data Source Center
# S0 Shared Foundation 实施报告

- **日期**:2026-09-03
- **执行模式**:SINGLE EXECUTOR — FOUNDATION ONLY(#16/#17/#18 完整功能未开始)
- **实现仓**:harryhua-ai/ask-ai;分支 `worktree-exec/s0-source-center-foundation-20260903`;worktree `.worktrees/s0-source-center`
- **FINAL_COMMIT**: `2a6edce`(11 文件,+1576/-1;未合 main)
- **基线**:1d6f6b5(= origin/main;开始前 git status/HEAD/log/worktree 四项已核;W0 波 w2-sync-truth / w3 分支当时 0 commits ahead,无可消费实现——按指令只建低冲突 foundation,未重构 shared sync APIs)
- **上游契约**:《DATA_SOURCE_CENTER_SHARED_DISCOVERY_2026-09-03》(docs 072f895)+ Planner 四项 PD 拍板

---

## 1. Executive Summary

**STATUS: CANDIDATE_READY。** 六项必需工作全部交付(Seaways Safety / Discovery Contract / Website 原语 / Lifecycle 持久化 / Sync 资格原语 / API schemas),验收 A-J 全过,全量离线套件隔离库 **1209 passed / 6 skipped / 0 failed / 0 errors**(39.5s;基线同法 1116/0/0)。W0 并行波所有权文件(`sync.py` / `data_sources.py` / `schemas.py` / `main.py` / connector 实现)**零触碰**;两个共享文件改动仅为 models.py DataSource 类内 8 行列追加与 safety.py 增量扩展,行区与 W0 hunks 完全不相交。

## 2. 交付内容(对应任务书六项)

### 2.1 Secrets Technical Safety(PD-1)——`backend/connectors/safety.py` 增量

双层证据设计(响应 PD-1"不能只做脆弱扩展名 blacklist"):

- **名字层**(`secret_path_reason`,check_path 内、读内容前):凭证专属扩展名 `SECRET_EXTS`(.key/.ppk/.p12/.pfx/.jks/.keystore/.kdbx/.htpasswd)+ 高置信文件名(`.env`/`.netrc`/`.git-credentials`/SSH 私钥标准名 id_rsa|id_dsa|id_ecdsa|id_ed25519 及变体/`secrets|credentials × 数据扩展名` 惯例);machine reason=`secret_file`。
- **内容层**(`secret_content_reason`,check_content 内、ingest 既有调用点生效):PEM/OPENSSH/EC/DSA/PKCS#8/ENCRYPTED/PGP **私钥 armor 精确正则**;扩展名伪装(cert.pem 藏私钥)由此拦下;machine reason=`secret_content`。公钥(PUBLIC KEY)与证书(CERTIFICATE)armor 天然不命中。
- **不可绕过**:走既有 Layer 1 纪律(判定先于昂贵管线、无任何配置开关、connector `_should_include_path` 中先于用户策略);验收 B 有 connector 级端到端测试(file_types 显式含 `.key` 仍被拒,`safety_stats.reasons.secret_file` 计数=1)。
- **误伤红线**:`.env.example|sample|template|dist|defaults|schema` 模板豁免;`public*`/`*.pub` 命名豁免;`.pem`(证书链惯例)与 `.env` 模板/`.npmrc`/`.pypirc` 归入 `KnowledgeRole.SECRETS`(新增第 13 角色)→ **技术安全 + 推荐排除**,管理员确认后可纳入;generic YAML/JSON/TOML 零波及(测试锁定 `values.yaml`/`tsconfig.json`/`Cargo.toml`/`secrets-management.md`/`secrets.py` 全部放行)。

### 2.2 Shared Discovery Result Contract——`backend/services/source_discovery.py`(新,194 行)

复用 `FileAdmission`/`KnowledgeRole`(零新候选结构):`DiscoveryResult` envelope(kind/target/totals/by_role/groups/candidates/recommended_config/warnings/capability_notes)+ `summarize_candidates` 聚合器(by_role 聚合;分组规则冻结:组内混含 include+exclude → review,否则多数)+ `reason_text` 人读理由(枚举映射冻结文案,Stage⑯ 纪律,含全部安全 reason 的 zh 文案)。Git path 候选与 Website URL 候选共用同一模型(验收 E 有专门测试)。

### 2.3 Website Discovery Primitive——`backend/services/website_discovery.py`(新,230 行)

纯组合骨架,`fetch_fn` 注入 IO(全离线可测);组合顺序 = PD-3 冻结序:robots.txt `Sitemap:` 指令(新增 `parse_robots_sitemaps` 解析器)→ 显式 sitemap_url → 通用回退 `/sitemap_index.xml` → `/sitemap.xml`(回退层"已有发现即停",有界试探);sitemap index 递归**全部同域子表**(零命名过滤——Yoast 专用正则的退休在此完成,connector 改造留 #17);urlset 提取经既有 `canonical_url` 归一 + 同域边界;**零发现显式 flag + 冻结告警文案**;robots 声明的跨域 sitemap 显式跳过并出告警(不静默);max_sitemaps/max_entries 封顶(反 unbounded)。另交付 URL 分类启发 `classify_url`(低价值排除清单 + PD-3 优先类别 → 既有 KnowledgeRole,未知路径保守 review)与 `URL_EXCLUDE_PATTERNS`。**未改 `web_crawl.py`**。

### 2.4 Source Lifecycle Contract——models 3 列 + `backend/services/source_lifecycle.py`(新)+ 迁移脚本

- `data_sources` 增 3 NULLABLE 列:`lifecycle_state`(NULL=ACTIVE 既有行零回填)/`lifecycle_since`/`lifecycle_error`。
- 词汇表冻结:ACTIVE / DELETE_REQUESTED / DELETING / DELETE_FAILED;删除成功 = 整行删除(无 tombstone,与任务书一致)。
- 判定原语:`normalize / is_active / is_deletion_in_flight / is_delete_failed / is_sync_eligible`。
- `sync_eligible_condition()`:SQLAlchemy allow-list 条件(NULL ∪ active;**deny-by-default**——deleting/delete_failed/未来新状态一律不可同步),供 #18 一行接线进 `_load_configs_from_db`(S0 未动 sync.py)。
- `scripts/migrate_add_data_source_lifecycle.py`:幂等 `ADD COLUMN IF NOT EXISTS` ×3 + 期望列校验(房式);支持 `TEST_DATABASE_URL` 覆盖(与 conftest 同惯例)。

### 2.5 Sync Eligibility Primitive

即 §2.4 的 `is_sync_eligible` + `sync_eligible_condition`(任务书第 5 项要求的"单一可复用判断");真值表测试含 deny-by-default 断言(`"some_future_state"` → False)、SQL 编译断言(条件中不出现任何删除态字面量)、真实 DB 回归(deleting 行被条件过滤)。**实际 wiring 留 #18**(并行边界)。

### 2.6 API Schemas——`backend/api/admin/source_center_schemas.py`(新,130 行)

`GitHubDiscoveryRequest / WebsiteDiscoveryRequest / DiscoveryCandidateOut(from_admission) / DiscoveryGroupOut / DiscoveryResultOut(from_result) / SourceLifecycleOut / DeletionActionOut`。**零 endpoint、零 router 挂载、既有 `schemas.py` 零触碰**——三个文件均为新建,规避与 W0 波的 hunk 冲突。

---

## 3. 验收证据(A-J)

| 验收 | 证据 |
|---|---|
| A 秘密 fixture reject | `test_secret_named_paths_rejected`(21 路径参数化)+ `test_private_key_armor_rejected_regardless_of_extension`(6 armor × 3 伪装扩展名) |
| B file_types 显式包含仍 reject | `test_admin_file_types_cannot_whitelist_secrets`(connector 级,`.key` 入白名单仍拒,stats 计数断言)+ `test_policy_config_cannot_disable_secret_check` |
| C 合法配置不误杀 | `test_legitimate_config_and_docs_not_rejected`(11 路径)+ `test_generic_yaml_json_toml_not_blanket_banned` + `test_public_certificate_not_rejected` + 公钥命名豁免 4 例 |
| D 既有 .hef/.so/.bin 防线 | 既有 `test_safety.py` 18 例全绿(未改动)+ `test_existing_artifact_defense_unchanged`(6 扩展名 reason 精确断言) |
| E Git/Website 共用模型 | `test_git_and_website_candidates_share_one_model` |
| F 生命周期跨会话持久 | `test_lifecycle_state_persists_across_sessions`(真实 PG,新会话重读) |
| G deleting 源机器可读不可 sync | 同上(eligible_ids 断言)+ 真值表 `test_sync_eligibility_truth_table` |
| H 既有行迁移安全 | NULL≡ACTIVE 断言 + 迁移脚本幂等(本地 ask_ai_test 已执行成功,二次执行无副作用) |
| I 既有 ACTIVE 行为不变 | S0 未改任何既有查询/连接器/sync 路径;admin API 183 测试全绿 |
| J 全量回归 | 隔离库 ask_ai_test_s0:**1209 passed / 6 skipped / 0 failed / 0 errors**(39.54s);基线 main 同法对照 1116/0/0 |

测试增量:4 个新文件、49 个新用例(`tests/connectors/test_safety_secrets.py` / `tests/services/test_source_discovery.py` / `test_website_discovery.py` / `test_source_lifecycle.py`)。

## 4. 并行边界遵守情况

- **零触碰**:scripts/sync.py、backend/api/admin/data_sources.py、backend/api/admin/schemas.py、backend/main.py、scripts/sync_executor_loop.py、backend/connectors/{github,web_crawl,filesystem,exclusion}.py、admin/src/**。
- 共享文件改动仅 2 处,均为增量 hunk:`models.py`(DataSource 类内 +8 行,与 W0 的 SyncRun 列不同类不同行区)、`safety.py`(+118 行纯增量:常量/两 helper/SECRETS 角色/三处判定分支,该文件不在 W0 所有权清单)。
- 未引入与 sync_runs/sync_requests 竞争的 operation truth(生命周期状态存源行自身)。

## 5. 本地环境事故与恢复(如实报告)

调查测试抖动期间,因 **bash cwd 被重置回主仓**且命令使用相对路径,误将主仓 `models/`(HF 本地缓存,含 bge-m3 与 reranker,约 6.4G)删除——但随后核实:**完整副本一直在 `widget/models/hub/`**(早前相对路径误跑产物),已 `mv` 归位主仓 `models/hub/`(bge-m3 4.3G + bge-reranker-v2-m3 2.1G),`widget/models/hub/` 清空,主仓与 S0 worktree 的 bge 22 测试双绿,用户已确认无需重新下载。**净效果 = 模型缓存从误建位置归位 canonical 位置;无数据损失;未下载任何模型。** 代码零损失。

环境修复类动作(均本地):`ask_ai_test` 库执行幂等迁移补 3 列(create_all 不给已存在表补列,旧 schema 残留曾致 admin API 测试 500——正是迁移脚本的用途);一次性隔离库 `ask_ai_test_s0` 建表跑全量后已 DROP。

## 6. Known Limitations / 留给后续

1. **wiring 未做(设计如此)**:#18 需把 `sync_eligible_condition()` 接进 `sync.py::_load_configs_from_db`(一行)、把 lifecycle 列写进 delete 流;#16/#17 需实现 discovery 端点并挂载 router(schemas 已备)。
2. `SECRET_EXTS`/`_SECRET_STEM_NAMES` 为保守工程初版(任务书允许"known credential files"类扩);内容层目前只覆盖私钥 armor,cloud API key 等自由格式 token 的可靠内容检测未纳入(不可靠即不做,符合"obvious token/key material **where reliable**")。
3. 上传端点(`upload_source_files`)未加 secrets 硬校验——同步时 connector 层 safety 必拦,但字节已落盘;#16 可顺手在 upload 白名单校验处加 `secret_path_reason`(data_sources.py 属并行波文件,S0 不碰)。
4. `classify_url` 为 preview 启发(path 子串),正文级质量仍由 connector 薄内容阈值裁决(S0 不承诺内容级)。
5. web_crawl connector 的 Yoast 过滤仍在运行(其退休改造属 #17 的 connector 实现,S0 未动)。
6. 全量套件对共享 ask_ai_test 存在并行波抖动(本轮实证:失败集合逐轮漂移,隔离库下全绿)——建议后续波实现期默认用一次性隔离库。

## 7. Production Boundary

- **PRODUCTION_MUTATIONS = NONE**:零部署、零生产迁移、零生产源/向量触碰、零生产 sync 触发。
- 迁移仅在本地测试库(ask_ai_test)执行;生产(tesla-t4)上线时走部署授权流程(该迁移列入部署清单,幂等可先于镜像)。

---

```
STATUS: CANDIDATE_READY
BASELINE: 1d6f6b5(= origin/main;W0 波 0 commits ahead,无可消费实现)
FINAL_COMMIT: 2a6edce(分支 worktree-exec/s0-source-center-foundation-20260903,未合 main)
WORKTREE: /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/s0-source-center
SECRETS_SAFETY: DONE——双层证据(名字层+PEM armor 内容层),Layer 1 不可绕过,模板/公钥/普通配置豁免,reason=secret_file/secret_content 机器可读
DISCOVERY_CONTRACT: DONE——source_discovery.py(FileAdmission 复用,envelope+聚合+冻结 zh 文案,Git/Website 单一模型)
WEBSITE_PRIMITIVE: DONE——website_discovery.py(robots Sitemap: 指令/generic 回退/index 全子表/跨域显式跳过/零发现告警,fetch_fn 注入,connector 零改动)
SOURCE_LIFECYCLE: DONE——data_sources 3 NULLABLE 列+四态词汇表(无 tombstone)+幂等迁移(本地测试库已执行)
SYNC_ELIGIBILITY: DONE——is_sync_eligible 真值表(deny-by-default)+sync_eligible_condition SQL 原语+DB 回归;wiring 留 #18
CHANGED_FILES: M safety.py,models.py;A source_lifecycle.py,source_discovery.py,website_discovery.py,source_center_schemas.py,migrate_add_data_source_lifecycle.py,tests×4(共 11 文件 +1576)
TESTS: 新增 49 用例;全量离线隔离库 1209 passed/6 skipped/0 failed/0 errors(基线对照 1116/0/0)
CONFLICTS_WITH_W0: 无——sync.py/data_sources.py/schemas.py/main.py 零触碰;models.py/safety.py 为不相交行区增量
KNOWN_LIMITATIONS: 三 endpoint 未实现(S0 范围外);sync.py 接线留 #18;上传端点 secrets 硬校验留 #16;web_crawl Yoast 过滤退休留 #17;内容层秘密检测仅覆盖可靠形态(私钥 armor);共享 ask_ai_test 并行抖动建议隔离库规避
REPORT_PATH: docs/implementation/CAMTHINK_V1_DATA_SOURCE_CENTER_S0_FOUNDATION_2026-09-03.md
REPORT_COMMIT: (见 docs 仓本提交)
PRODUCTION_MUTATIONS: NONE
```
