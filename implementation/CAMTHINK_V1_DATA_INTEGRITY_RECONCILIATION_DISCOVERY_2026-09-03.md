# CamThink V1 — Issue #13 Data Integrity Discovery(只读 Discovery,零实现)

- 日期:2026-09-03(证据窗 07:33–09:05 UTC)
- 模式:SINGLE EXECUTOR — DISCOVERY ONLY(CODE_MUTATION=NONE / PRODUCTION_MUTATIONS=NONE)
- Issue:**#13 — Data consistency: orphan vector reconciliation fails on duplicate content hashes**
- 报告人:Worktree 2 — Data Integrity Discovery Executor

---

## 1. Executive Summary

Issue #13 的表象是「reconciliation 无法收敛、孤儿向量永久保留」。Discovery 结论:**这不是 reconciliation 逻辑的 bug,而是双身份模型错配的必然结果**,叠加一类独立的历史污染,再叠加源生命周期缺口。三个根因全部有生产实锤:

| # | 根因 | 机制 | 生产规模(2026-09-03 实测) |
|---|---|---|---|
| RC-1 | **账本=内容寻址 vs 向量=路径寻址** | `documents` PK=(content_hash, branch):同内容同分支多路径只允许一行,行归属被"最后灌入者"抢占;其余路径在 Weaviate 有向量、账本永远无行 → 结构性孤儿;reconciliation 的"零 embed 重建账本行"INSERT 撞同一主键 → `documents_pkey` UniqueViolation → 永久 EXTRA_UNRESOLVED_ORPHAN → 永不收敛(**即 Issue #13 标题机制**) | 孤儿 ~127 篇 / 多余 ~4,829 chunks:ne301 +287(21 orphans)、ne503-apic +4,541(103)、sdk +1(1) |
| RC-2 | **历史 artifact 污染**(Stage1 safety 上线前灌入) | .hef 模型二进制被当文本灌入(2026-09-02 09:39 UTC 创建,早于 safety 进生产);neoruntime-apps 全部 60,394 个 .hef chunks:38,874 在**账本 3 行里(占该源账本 99.3%)**+ 21,520 在 2 个孤儿路径(=该源 +21,520 缺口的全部);另有 libcrypt.so.1 孤儿 | neoruntime-apps 缺口 +21,520 全部由 .hef 解释;全局 +26,354 = 21,520(.hef)+ ~4,829(RC-1) |
| RC-3 | **源重命名/重建生命周期缺口** | 观察期内实锤:用户删 `ne503-sdk-local` 建 `neoruntime-sdks-67cbac8f`(08:15:41);旧源经 Admin 三清正确清零(账本+向量归零),但新源**三次首灌全失败**(见 RC-4),且"重命名=全量重嵌+若不先删则整库按新前缀重复"的结构风险成立 | 新源 3 连败(192 docs/次);sync_runs/sync_log 残留死 id 历史(无害但语义混淆) |
| RC-4 | **运行时硬阻塞(环境,非本仓代码)** | sync-executor/sync-cron 容器内 CUDA **整体不可见**:`No CUDA GPUs are available`(08:16 起;容器内 `torch.cuda.is_available()=False, device_count=0`),宿主 GPU 与驱动健康(13.9G/16G,backend 上下文仍活着);早晨 07:32 的失败则是 OOM(需 490MiB 仅剩 415.56MiB) | **当前一切需要 embed 的修复(refill/reindex/新源首灌)均不可能执行** |

关键澄清(与 Issue 描述对齐):**"当前向量库存在 .hef/.so" 不能证明当前 Technical Safety 失效** — 两者均为历史遗留(§9),当前四层准入经代码+生产日志双重验证有效。同时,**重复内容身份碰撞(RC-1)只解释孤儿篇数(~127),不解释缺口 chunk 大头(+21.5k 是 .hef)** — 修复必须分型处置,单一方案会误伤。

Final Verdict:**NEEDS_PRODUCT_DECISION**(3 项产品拍板,见 §20;工程侧已完全勘明,拍板后即为 READY_FOR_IMPLEMENTATION)。

---

## 2. Baseline

```
DISCOVERY_BASELINE=1d6f6b5fe697b5f7a1b8decef1c29f51afcda937  (= origin/main = 生产 release)
branch: main(未 reset/rebase;仅有的脏文件=.gitignore 存量改动,与本 Discovery 无关)
```

- `git log -10` 顶部:1d6f6b5(三候选集成)← 895a3fe(Stage⑯)← 458cee3(Wave-0)。
- worktree list:main + 7 个既有 worktree(llm-provider / generation-localization / integration-candidates / preflight-report / test-isolation / v1-checkpoint / wave0),本 Discovery **未新建 worktree、未改任何代码**(只读)。
- 生产观察身份:VM-0-4-ubuntu,三服务 sha-1d6f6b5 零重启(backend/sync-cron/sync-executor,up since 06:21–06:22 UTC)。
- 关联只读前作:`PRODUCTION_SYNC_OBSERVATION_2026-09-03_ne301-neoruntime-sdks.md`(docs 仓 f4714d6)。

---

## 3. Current Document Identity

源码事实(`backend/db/models.py:41-67`,`backend/pipeline/ingest.py:665-714`):

- **PK = `(content_hash, branch)`**,docstring 明示是故意的:「同内容跨分支各留一行,同分支重复灌入仅更新 chunk_count 与 updated_at,**避免 Postgres 行膨胀**」→ 当前 documents identity 实际表达的是 **content identity(内容身份),不是 source document identity(源文档/路径身份)**。
- `content_hash = sha256(content)`(github.py:242),对内容逐字节计算 — 两个不同 path 的文件只要字节相同,hash 即相同。
- `source_id`(varchar 200)= **复合串 `<source_id>/<branch>/<rel_path>`**(github.py:235),是真正的路径身份,但只是**普通可索引列,无唯一约束**,且会被 upsert 改写(见下)。
- **行归属抢占**(`ingest.py:_upsert_postgres`):命中已有 (content_hash, branch) 时执行 `existing.source_id = doc.source_id` 等**整行字段覆写** — 谁后灌,行就归谁。同分支两个同内容路径 A/B 交替灌入会让这一行在 A/B 之间**来回翻转**。
- 账本生命周期:内容变更时先删同 source_id 旧 hash 行(ingest.py:686-691);删除文档按 source_id 删行(ingest.py:716-728);Wave-0 的一致性/退休/重建都以此表为 expected 权威。

**是否符合产品语义?——不符合,这是产品语义缺口而非实现疏忽**:知识库的检索/溯源/删除都以「路径(文档)」为心智单元(Admin 显示篇数=路径数、引用展示 provenance URL=路径、用户删除=删文档),而账本按内容去重导致「同内容多路径」在账本里不可见。它对纯 RAG 去重有价值,但对 #13 的对账语义是错的:对账要求「每个路径要么账本有行+向量齐,要么没有行+没有向量」。

## 4. Current Vector Identity

- chunk 身份 = **`uuid5(NAMESPACE_URL, f"{source_id}#{chunk_index}")`**(ingest.py:47-53)— **路径寻址、全局唯一、确定性、幂等覆盖**。跨分支因 source_id 含 branch 不冲突。
- Weaviate 对象属性携带 `source_id`(复合路径串)、`chunk_index`、`content_hash`、`branch` 等(ingest.py:93-110);collection `Document`,TEXT 属性(过滤分词不可靠,一切计数以迭代器为准 — vector_consistency.py:82-99,P0-A 冻结)。
- **要点:向量侧身份已经是路径身份,且无需迁移** — RC-1 的修复只需账本侧改造,60 万向量对象零移动(§12)。

## 5. Reconciliation Runtime Truth

链路(scripts/sync.py + backend/services/vector_consistency.py,逐行已读):

```
expected = SUM(documents.chunk_count) WHERE source_id LIKE '<source>/%'   # PG,路径前缀
actual   = 迭代器全扫 Weaviate,客户端前缀过滤,按 source_id 聚 chunk_index 集合
missing  = pg 有 sid、Weaviate 无该 sid            → 整篇缺失
refill   = missing ∪ {chunk_index 集合 ≠ 0..n-1}    → 需整篇重灌
stale    = 集合内超出 0..n-1 的 index(仅计数)
orphan   = Weaviate 有 sid、pg 无该 sid(只 warning 不删;明细 orphan_chunks)
```

- `is_healthy` = expected==actual ∧ refill=∅ ∧ orphan=0(vector_consistency.py:40-51)→ **任何一个孤儿都让该源永久 partial**(sync.py:438-442 复验同口径),partial 不推进增量窗口(sync.py:349-351)→ UI 永久"补齐"。
- **孤儿处置三分类**(`_reconcile_orphan_vectors`,sync.py:524-645):
  1. `EXTRA_CONFIRMED_RETIRED`:完整权威发现(fetch_all 成功 + web_crawl 覆盖率≥80% + discovered>0 守卫)确认源已无此路径 → 按确定性 UUID `delete_many` 精确退休(sync.py:628-640);
  2. **源仍在且本轮抽取成功 → "账本行丢失,零 embedding 重建"**:`session.add(Document(content_hash=<Weaviate props>, source_id=<孤儿路径>…))`(sync.py:603-617)→ **这正是 Issue #13 的爆点**:RC-1 下该 INSERT 必撞 (content_hash, branch) 主键 → `UniqueViolation` → unresolved。**该分支对重复内容孤儿在结构上不可能成功**;
  3. `EXTRA_UNRESOLVED_ORPHAN`:发现失败/不完整/成员在但抽取失败/属性缺失 → 保留+上报。
- 退休判定权威:`authoritative_source_ids()` **仅 web_crawl 实现**;git/fs/woo 回退"抽取集=枚举集"(sync.py:515-521,设计上抽取即枚举成立)。
- 事后复验(sync.py:435-450)与终局一致性事实(Wave-0,写入 sync_runs.consistency)共用同一校验器,口径一致。
- **收敛性结论**:分类 1/3 可收敛(退休或等待);分类 2 对 RC-1 孤儿**几何上必败** — 每轮 partial → 永不收敛,与生产日志完全吻合(今晨 ne301×42、apic×206、sdk×2 行 UniqueViolation,=orphan_count×2 轮)。

## 6. Duplicate Content Root Cause

生产实锤(全部只读取得):

1. 孤儿路径 `ne301-local/main/WakeCore/Custom/Lib/cJSON/cJSON.c` → Weaviate 对象存在,`content_hash=f892717f26cf…` → PG 该 hash 的行只有一行,`source_id='ne503-apic-69d3594b/main/mcu_board_prj/app/Custom/Lib/cJSON/cJSON.c'`(chunk_count=127)→ **跨源同内容、一行、行归属被 apic 抢占,ne301 路径永为孤儿**。
2. 同 hash 三路径:`cmsis_compiler.h` 在 ne301×1 + ne503-apic×2(全库扫描 TOPDUP 实测)。
3. 规模:全库 206,689 对象中 **118 个 content_hash 有 ≥2 路径(多余 132 向量)** — 撞库源主要是 vendor 文件拷贝(CMSIS/FreeRTOS/cJSON/LICENSE)与网站产品页模板(web_crawl `website-camthink/product/...` 同模板 5 路径)。
4. 失败日志(今晨 cron,`tesla-t4-sync-cron-1`):`孤儿 <路径> 账本重建失败,保留:(psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint "documents_pkey"`。

**答案**:identity collision 的成因 = 账本 PK 内容寻址 + 向量路径寻址 + upsert 行归属抢占;当前 documents identity 表达的是 content identity,**与产品"按文档管理知识"的语义不符**(§3)。RC-1 影响面=孤儿篇数与"补齐"徽章永不消失;**它不是 +26k 缺口的大头**(那是 RC-2 的 .hef)。

## 7. Missing vs Extra Semantics

- **missing(pg 有、向量无)**:今晨三手动源 runs 40-42 `missing=0`;全库口径下"应有数据没进去"当前**不存在**(与 Issue 前提一致)。理论产生路径=灌入部分失败(今晨 neomind-local OOM 12 篇是 fetch 后灌入失败,run=failed,账本未写,不产生 missing)。
- **extra/orphan**:两类成因(RC-1 重复身份 ~4.8k chunks / RC-2 .hef ~21.5k 孤儿 chunks),**必须分型**,处置完全不同(§11)。
- **stale_chunk_count**:今日所有 run=0(P0-A 文档局部 prune 后未再观测到)。
- **stale vector 是否参与检索?** — 是。检索按 channel_visibility+branch 过滤,**无"孤儿排除"逻辑**(retrieval/search.py 按 source_id 前缀无对账概念);.hef 垃圾 chunk 若被召回会直接污染答案(文本为二进制乱码,见 §8 实测样本)。这是 RC-2 修复的紧迫性来源。

## 8. Historical Pollution Analysis

- **.hef**:Weaviate 内 **60,394 个 .hef chunks,全部在 neoruntime-apps-1eea74dd**。对象 `person_vehicle_v1.hef#0` 实测:
  - 创建时间 **2026-09-02T09:39:10 UTC** — 早于 Stage1 safety 提交(f481f94,09-02 11:01 UTC)更早于其进生产(09-03 06:21 UTC,sha-1d6f6b5);
  - `text` 属性 = **原始 HEF 二进制字节**(`'\x01HEF\x00\x00…'`,含 NUL)— 今日 pipeline `check_content` 会以 binary_content 拦截,当前不可能再进入。
  - 分布:38,874 chunks 在**账本 3 行**(即该源 62 行/39,155 chunks 的 99.3% — **账本本身被污染**)+ 21,520 chunks 在 2 个孤儿路径(=该源 consistency 缺口 +21,520 的全部)。
- **.so**:孤儿 `ne503-apic-69d3594b/main/deploy/nginx/runtime/rootfs/lib/aarch64-linux-gnu/libcrypt.so.1`(今晨 rebuild 失败日志);`.so` 不在任何源 file_types 白名单 → 今日 connector 层即排除。
- **分类结论(任务 §3 的 A/B/C/D)**:**B — 当前 safety 已阻止,存量=历史 stale data**;唯 `.bin` 一项带 **C 色彩**:ne503-apic 的管理员 file_types **显式含 `.bin`**(neoruntime-apps 还含 `.hef/.npy/.png/.mp4`)— Layer 3 SOURCE_POLICY 与 Layer 1 技术安全存在配置张力,当前由 Layer 1(非绕过)压住(`model_artifact_ext` 拦截,今晨生产日志实证)。这个张力本身需要产品知悉:管理员"想要"的 .bin 文件今日永远进不来。

## 9. Current Technical Safety Verification

四层准入,全部源码+生产日志验证,**非 bypassable 成立**:

| 层 | 位置 | 对 .hef/.so/.bin/.pt 等 | 证据 |
|---|---|---|---|
| L3 file_types 白名单 | github.py:218 / filesystem.py:110(白名单外直接 skip,读盘前) | 不在白名单即排除(所有源白名单均不含 .so/.pt;.bin 仅 apic 配置了) | data_sources.config 实测 |
| L1 TechnicalSafetyPolicy.check_path | github.py:226 / filesystem.py:159(读内容**之前**) | `MODEL_ARTIFACT_EXTS`(safety.py:67-112)含 .hef/.onnx/.pt/.pth/.so/.dll/.a/.o/.elf/.bin/.wasm…+ 硬尺寸上限(16MB,绝对上限 64MB,配置只许收紧) | 今晨生产日志:`技术安全排除 …person_vehicle_v1.hef: model_artifact_ext` |
| L0.5 ExclusionPolicy | github.py:230(BUILD_DIRS/BINARY_EXT) | 叠加排除构建目录/常见二进制 | exclusion.py:14-36 |
| L1 check_content(内容嗅探) | ingest.py:230/487(管线内,文档级隔离) | NUL 采样/控制字符>5%/U+FFFD>5% → binary_content/poor_decode;**扩展名伪装与无扩展名二进制的兜底**,safety.py 红线明示"不得退化成扩展名黑名单" | .hef 对象 text 含 NUL → 今日必被此层拦 |

- connector 覆盖:生产 git 源全部走 github.py(统一 git 类型,LocalGitConnector 已退役不注册,仅存测试);filesystem 有 L1;web_crawl/woocommerce 只产 HTML/文本(无二进制文件路径),内容仍过管线嗅探。
- **结论:当前 Technical Safety 对 .hef/.so/.bin/model artifacts 有效;存量 = Stage1 上线(09-03 06:21 UTC)前的历史遗留。**

## 10. Correct Corpus Contract(冻结"正确 corpus"定义)

**权威 = Expected Ledger(按路径身份),向量库必须与之逐路径精确相等。** 冻结语义:

1. **路径身份唯一**:每个 `<source>/<branch>/<path>`(启用源)要么「账本 1 行 + 恰好 chunk_count 个向量(uuid5 连续集合)」,要么「无行 + 0 向量」;不存在中间态。
2. **内容去重不发生在账本层**:同内容多路径各自成行(检索天然多路命中,由 rerank 融合;是否在灌入层做内容级去重属产品决策,见 §20-D2)。账本可另设 content_hash 索引服务"同内容检测",但不再承担身份。
3. **artifact 不可入**:任何 MODEL_ARTIFACT_EXTS/嗅探拦截物,在账本与向量库中都不得存在;存量按 POLLUTED_ARTIFACT 处置(非 missing)。
4. **死源不留 corpus**:源删除必须清账本+向量(现 Admin 三清已达成);源重命名视为"删除+新建",必须走同一清理,禁止新旧前缀并存双份语料。
5. 一致性权威口径保持 Wave-0 `verify_source_vectors` 单实现(禁止第二套口径)。

## 11. Frozen Repair Semantics(分型处置矩阵)

| 类别 | 判定 | 自动处置 | 依据 |
|---|---|---|---|
| missing required | pg 行有、向量缺(整篇/部分) | **自动 refill**(现 refill_source_ids 路径,embed-gated) | 账本权威 |
| extra/orphan,源已无此路径(完整发现) | membership 排除 | **自动精确退休**(delete_many by uuid5,现 EXTRA_CONFIRMED_RETIRED) | SOURCE-CONFIRMED,现行为保留 |
| extra/orphan,源仍有此路径、账本无行(=RC-1) | 同内容兄弟行存在 | **禁止现行"重建单行"**(必撞 PK);修法二选一:D2 拍板后 (a) 账本身份迁移后重建行,或 (b) 判定 DUPLICATE_CONTENT_RETIRED 删除冗余路径向量(若产品选择灌入层内容去重) | §20-D2 |
| stale forbidden artifact(账本行/向量均为 .hef 等) | 路径后缀+属性嗅探双验 | **自动退休:删向量 + 删账本行**(3 行/38,874 chunks + 2 孤儿路径/21,520 chunks);**绝不 refill**(fetch_all 已不含它们,refill 会变永久 missing) | RC-2,POLLUTED_ARTIFACT |
| deleted upstream | fetch_deleted(D-filter) | 现行为:delete_document 文档局部点删(正确,保留) | 现行为不变 |
| renamed/moved path | git 语义=D+新增 | 现行为等价(删旧+灌新),保留 | — |
| **renamed/deleted source(源级)** | data_sources 无此前缀 | **新冻结:源删除/重命名必须三清(账本+向量+留痕标记)**;残留前缀由"死前缀清扫"门兜底 | RC-3 |
| duplicate identity(账本内同 hash 多行) | 迁移后不再存在 | — | §12 |

## 12. Migration Requirement

**推荐 M1(增量、零停机、向量零移动)**:

- documents 表**新增 `doc_path` 列(=现 source_id 复合串)+ UNIQUE 索引**;`content_hash` 降级为普通索引列(保留同内容检测能力);**不改 PK**(避免锁表/兼容雪崩)。账本"行归属抢占"即自然消失:每个路径必有一行。
- 查询面切换(4 处):`_upsert_postgres`(按 doc_path upsert)、`_delete_postgres`/`delete_document`(按 doc_path 删)、`vector_consistency`/`_count_documents`(LIKE 前缀不变,零改动)、Admin 计数。**Weaviate 零迁移**(uuid5 已路径寻址),sync_log/sync_runs 零影响(引用的是源 id 非文档 id)。
- backfill:从存量行回填 doc_path=source_id(值即路径);**同 hash 多行冲突不存在**(现表同 hash 本就只有一行,新增唯一列无冲突);RC-1 孤儿路径在迁移后由 reconciliation 重建行(零 embed,来自向量 props)即可收敛 — **迁移完成后 Issue #13 的 rebuild 分支自动变为可收敛**。
- 兼容:documents PK 变更不影响 content_hash 现有消费方(retrieval 不读此表;admin 计数走前缀 LIKE)。
- 回滚:新列为 additive,drop index/column 即回滚;写入双写期(schema 兼容发布顺序:先加列→切代码→清旧路径)。
- 评估过 M2(改 PK 为 source_id)与 M3(reindex 全量重建):M2 锁表+破坏跨分支语义,否决;M3 需要 embed(当前 GPU 阻塞)+ 会把 .hef 缺口变永久 missing(账本不同步清理时),仅作最后手段,否决为常规路径。

## 13. Production Repair Plan(仅设计,本轮零执行;执行需 `PROD_MUTATION_AUTHORIZATION_REQUIRED`)

前置硬门:**GPU/CUDA 恢复**(RC-4,当前不满足)+ 部署授权窗口。阶段序(每阶段独立授权、独立回滚锚):

1. **R0 冻结快照**(只读):记录 verify_source_vectors 全源基线 + 本报告计数(ne301 67,413/67,126/21;apic 20,198/15,657/103;apps 60,675/39,155/2;全局 206,689)。
2. **R1 .hef/artifact 退休**(纯删除,零 embed,可先行):删 3 个 .hef 账本行 + 60,394 个 .hef 向量(uuid5 点删)+ libcrypt.so.1 孤儿向量。预期后验:apps expected 39,155→281,actual 60,675→281,**is_healthy=true**;全局 expected 142,066、actual 收敛同值(需按当时快照重算)。
3. **R2 账本身份迁移**(M1,DDL+回填,低风险窗口)。
4. **R3 重复身份孤儿收敛**(依赖 §20-D2):重建 125 行(零 embed)或 DUPLICATE_CONTENT_RETIRED 精确删向量;后验全部启用源 is_healthy。
5. **R4 源级清理门固化**:源删除/重命名三清 + 死前缀清扫(当前无存量,防再发)。
6. **R5 补灌**(embed-gated,等 GPU):neomind-local 12 篇 + neoruntime-sdks 新源首灌(192 篇)。

## 14. Dry-run Contract

每个修复阶段必须先产出一轮 dry-run 报告(零写),含:

- 精确 uuid 清单(数量 + 前 10 样本 + sha256(清单) 作为执行锚);
- 按源/按类型计数矩阵(expected/actual/before/after 预测);
- 影响面断言:只触碰清单内 uuid(delete_many by_id)、只删清单内账本行;**禁止任何 collection 级删除/reindex**;
- 幂等证明(重放同一清单 → 0 变更)与中断安全(重跑从残余状态继续,verify_source_vectors 为真值仲裁);
- 执行后必须附 before/after 两轮 verify_source_vectors 输出 + 检索回归(eval 集合上 recall/引用正确性,确认无 valid 向量丢失)。

## 15. Acceptance Criteria

1. 所有启用源 `verify_source_vectors.is_healthy == true`(expected==actual ∧ refill=0 ∧ orphan=0);
2. Weaviate 中 MODEL_ARTIFACT_EXTS 后缀对象数 = 0;.hef/.so 账本行数 = 0;
3. 同 content_hash 多路径:账本行数 = 路径数(M1 后),或符合 D2 拍板语义;
4. UI"补齐"徽章全部消失(sync_runs.consistency.orphan_count=0 连续两轮 cron);
5. 检索回归:eval 集 P50 延迟不劣化、引用命中不回退、无二进制乱码引用;
6. 修复全程 sync_runs 可追溯(每阶段一轮 request,reconciliation facts 落 consistency)。

## 16. Regression Risks

- **删除面误伤**(最大风险):全部删除走 uuid5 点删(文档局部不变量),禁止 TEXT 属性过滤(P0-A 红线);dry-run 清单 sha256 锚定。
- **.hef 退休引发"missing 假信号"**:必须同步删账本行(§11),否则 refill 循环复活;顺序=先停相关源同步(授权窗口内)再执行。
- **M1 迁移双写期窗口**:先加列后切码;旧代码继续按 (content_hash,branch) upsert 期间,新列数据可能滞后 → 迁移窗口内暂停手动同步(窗口由授权决定)。
- **GPU 环境未恢复时执行 R3 的重建分支** → 零 embed 路径不受 GPU 影响,可先行;R1 纯删除亦不依赖 GPU;仅 R5 需要。
- **检索面**:同内容多路径若按 D2(b) 去重删除,URL 溯源多样性下降(引用只能给保留路径)— 必须由 D2 明确接受。
- 观察期发现:生产正被用户并行操作(删源建源),任何修复窗口必须与人工操作互斥。

## 17. Shared Telemetry Interface(#11/#12/#15 接口,全部 PROPOSED 不实现)

`PROPOSED_SHARED_INTERFACE — consistency facts v2`(写入 sync_runs.consistency,向后兼容增量):

```json
{
  "expected_chunks": int, "actual_chunks": int,          // 既有
  "missing": int, "refill": int, "stale_chunk_count": int, // 既有
  "orphan_count": int,                                     // 既有
  "duplicate_doc_count": int,        // NEW 同内容多路径篇数(RC-1 面)
  "polluted_artifact_chunks": int,   // NEW artifact 污染向量数(RC-2 面)
  "retired_chunks": int,             // NEW 本轮 EXTRA_CONFIRMED/POLLUTED 退休数
  "repaired_ledger_rows": int,       // NEW 本轮账本重建成功数(迁移后可收敛)
  "repair_required": bool            // NEW 是否需要修复门介入(#15 消费)
}
```

- #11(健康/进度)消费 repair_required 与 orphan_count 做"健康"语义;#12 共享同一 run 真相;#15 的修复执行写 retired/repaired 计数回流。**Worktree 1 不得另建竞争 schema** — 字段全部收敛进 sync_runs.consistency 既有 jsonb,无新表。

## 18. Implementation File Boundary(后续实现允许触碰的文件面)

- `backend/db/models.py`(documents 加列/索引)+ 新增 `scripts/migrate_documents_doc_path.py`;
- `backend/pipeline/ingest.py`(`_upsert_postgres`/`_delete_postgres` 按 doc_path);
- `backend/connectors/safety.py` / `backend/api/admin/data_sources.py`(POLLUTED_ARTIFACT 分类与 retire 原语,如需);
- `scripts/sync.py`(`_reconcile_orphan_vectors` 重建分支改按 doc_path + DUPLICATE_CONTENT_RETIRED 分支);
- `backend/services/vector_consistency.py`(facts v2 增量字段);
- 测试:tests/ 对应模块。
**禁触**:生产 compose/.env/CORS/迁移执行本身(需独立授权)、retrieval 语义、embedder。

## 19. Recommended Execution Mode

- **两阶段**:Stage A(零 embed,可先做)= R1 artifact 退休 + R2/M1 迁移 + R3 按拍板收敛 — 单 Executor 常规合同(实现→自证→Planner 验收);Stage B(R5 补灌)依赖 GPU 恢复,独立窗口。
- 修复执行必须独立授权单(生产写),dry-run 报告先行(§14);同步暂停窗与用户人工操作互斥(观察期已证实用户在并行操作 Admin)。
- GPU/容器 CUDA 问题(RC-4)不在本仓修复面 → 报告给产品/运维,由宿主运维处理(Persistence-M=Off 的共享 GPU 主机),**不要**由 ask-ai 执行端处理。

## 20. Final Verdict

**NEEDS_PRODUCT_DECISION** — 工程根因全部勘明、修复语义已冻结,三个决策点是产品语义,拍板后即 READY_FOR_IMPLEMENTATION:

- **D1(账本身份)**:documents 是否改为路径身份(M1:doc_path 唯一 + content_hash 降级索引)?**建议:是**(对账/删除/溯源的产品语义全部按路径;内容检测保留为索引)。
- **D2(同内容多路径)**:同内容第二路径 (a) 各自成行全量入库(检索多路命中、成本=冗余向量),还是 (b) 灌入层内容去重、冗余路径向量判 DUPLICATE_CONTENT_RETIRED?**建议 (b)**:省 ~132 向量与未来重复灌入,溯源 URL 给保留路径;若产品重视"多页面独立引用"则选 (a)。
- **D3(artifact 存量处置 + allowlist 张力)**:授权 R1 一次性退休 60,394 .hef + .so 孤儿(账本+向量)?以及:管理员 file_types 中的 .bin/.hef/.npy(被 Layer 1 压制)是"配置遗留应清理"还是"产品确要纳入的非模型 .bin(如固件 hex 文本)"?**建议:授权退休;allowlist 由产品清理并在 Admin 提示"技术安全边界不可绕过"**。

---

### 附:关键证据索引(全部 READ-ONLY 取得)

- 代码:models.py:41-67(PK 文档串)、ingest.py:47-53(uuid5)/599-608/665-714(upsert 抢占)、vector_consistency.py(全文)、sync.py:327-457/459-521/524-645(reconciliation 全文)、safety.py(全文)、github.py:215-260(四层准入)、local_git.py(退役声明)。
- 生产 SQL:sync_runs 40/41/42 consistency;documents 前缀分布(15 源/180,940 chunks);同 hash 兄弟行(f892717f→apic cJSON.c 127 chunks);.hef 账本 3 行/38,874 chunks;neoruntime-sdks-67cbac8f created_at=08:15:41 + 3 次 failed;旧 sdk 前缀账本/向量=0(三清成功)。
- 生产 Weaviate:total 206,689(08:0x 快照;07:5x aggregate 曾为 207,294,期间用户删旧 sdk 语料 −605);.hef 60,394 全在 apps;DUP 118 hash/132 extra;person_vehicle_v1.hef#0 创建 2026-09-02T09:39:10Z、text=HEF 二进制头。
- 生产日志:cron UniqueViolation ×250(06:23/07:32 两轮);exec/cron `No CUDA GPUs are available`(08:16-08:39);早晨 `CUDA out of memory…415.56MiB free`(07:32);`技术安全排除 …*.hef`(06:26,今日安全在位实证)。
- 本机容器:`torch.cuda.is_available()=False, device_count=0`(sync-executor);宿主 nvidia-smi 健康(13,943MiB/16,384MiB,Persistence-M=Off)。

**CODE_MUTATION: NONE / PRODUCTION_MUTATIONS: NONE**(观察期内用户自行执行了删源/建源与同步点击,非本 Discovery 行为,已在 §8/§16 记录)。
