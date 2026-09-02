# CAMTHINK V1 — DATA SOURCE RELIABILITY PRODUCT CONTRACT & UX ARCHITECTURE

- 日期:2026-09-02(v1.1 Final Revision)
- Gate 类型:PRODUCT CONTRACT + UX ARCHITECTURE(非实现 Gate)
- 源基线:`193f206a3d0e8695f1c40766a1ba54667fcba2fb`(生产冻结源)
- 输入:Data Source Reliability Discovery(PASS,docs 245a19b)、2026-09-02 生产 504 事故实证、neoruntime/neoruntime-apps 摄取实证、现有 Admin/backend/sync 架构、Planner Review 修订意见
- 边界:零生产访问、零代码/Schema/前端改动、零 sync 触发;残缺/污染 neoruntime-apps 数据按 PO 决定 **DEFERRED**(记录不处理,§19.2)

## 修订记录(v1.0 → v1.1,Planner Review 全部采纳)

| # | 修订 | 摘要 |
|---|---|---|
| R1 | Technical Safety 与 Knowledge Value 严格分离 | 准入三层改为 Technical Safety Boundary(技术硬边界)/ Knowledge Eligibility(知识判断)/ Admin Source Policy;生成物/vendor/低价值不再属于 Hard Exclusion |
| R2 | V1 不允许正常产生 Orphan Corpus | 生命周期收敛为 Disable / Delete 两操作;「删配置留知识」取消;orphan 只能作为一致性/恢复问题存在 |
| R3 | 冻结双阈值**机制**,不冻结 2MB/8MB **数字** | 数值为 INITIAL HYPOTHESIS,由阶段1「数据导入安全保护」实证标定 |
| R4 | TOKENIZE_ERROR 不冻结实现 HOW | 冻结文档级失败隔离的产品要求,HOW 留给执行端 |
| R5 | Embedding 并发调参不属于普通管理员 | 资源压力动作=[稍后重试][查看资源状态][查看失败详情] |
| R6 | Open Decisions 收敛 | Expected State/Role 默认/存量不回填/尺寸/新鲜度/节奏/Disable/Needs Review 均已决策,纳入正文 |
| R7 | 工程 Gate 改用中文阶段名(阶段1-8)并重审依赖 | 见 §17 |
| R8 | 生产 .hef 污染记录为 **DEFERRED BY PRODUCT OWNER** | 见 §19.2 |

---

## 1. Executive Product Decision

把「数据源同步监控」升级为 **Data Source Reliability & Governance Center**,以五个冻结原则为地基:

1. **健康 ≠ 任务成功**(P1):健康是五个维度(连接/同步/覆盖/新鲜度/一致性)的合成结论,30 天裸成功率退役为同步维度的一个输入。
2. **期望态先行**(P2):每个源声明 REQUIRED / OPTIONAL / DISCOVERY / EXCLUDED;EMPTY_EXPECTED 与 EMPTY_UNEXPECTED 从此是两个不同的健康结论。
3. **准入三层**(P3):`TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED`——技术安全是系统硬边界,知识价值是推荐判断,管理员策略只能收紧;`.hef` 式事故由**解析前**的通用技术边界拦截,而非逐个黑名单。
4. **同步不在线**(P4):重型摄取永远不占用在线服务进程;进度是 backend 真值(P7),不是假进度条。
5. **可中断可恢复**(P5):中断的首次同步绝不产生「假健康」;删除永远文档局部(P6),且 V1 不存在「无主语料」这一正常生命周期状态。

一次性把过去一周全部真实事故定为禁飞区(§16 Golden Failures):healthy+0、.hef 84MB 二进制进文本管线、中断 64/169 假健康、GPU OOM 风暴、TEXT equal 跨源误删。

**本文不选 worker 框架、不定义 DB schema**;冻结的是状态模型、语义、信息架构、交互与阶段边界。

---

## 2. Product Goals

管理员不 SSH、不查库、不猜日志,即可:

1. 判断每个源是否真的健康(五维健康 + 期望态);
2. 知道知识是否完整/最新/可用(覆盖 = 实际/期望,新鲜度 vs 节奏,一致性);
3. 看懂一次同步在做什么(阶段 + 真实计数);
4. 知道增/更/删/失败了多少(delta 统计);
5. 看懂异常原因与影响(WHAT/WHY/IMPACT/SYSTEM DID/ADMIN SHOULD DO);
6. 知道系统是否在自动恢复(RECOVERING 可见);
7. 拿到明确且**安全**的处理动作(无一键修一切,无参数调优负担);
8. 技术上不安全的数据进不来,知识价值低的数据默认不进来;
9. 同步永远不影响在线问答(执行隔离)。

---

## 3. Frozen Principles(冻结,不再讨论)

| # | 原则 | 合同约束 |
|---|---|---|
| P1 | Job Success ≠ Knowledge Health | 健康必须合成 Connectivity/Sync/Coverage/Freshness/Consistency ≥1 个非任务维度;禁止单一成功率即健康 |
| P2 | Expected vs Actual | REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED 四态期望;EMPTY_EXPECTED 与 EMPTY_UNEXPECTED 语义分离 |
| P3 | 三层准入 | `TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED`;Technical Safety 不可被任何配置绕过;知识价值判断(含 vendor/生成物)**不得**伪装成技术危险;源码检索能力必须保留(非 document-only) |
| P4 | Sync Must Not Block Online | 摄取不得在 API/Chat/Admin 服务进程内执行;backend 重启不得杀死进行中的同步 |
| P5 | Interrupted Must Be Recoverable | 中断 run 必须被检测、标记、可续传;「existing>0 → 无变更 → 健康」路径必须被 incomplete-run 标志门控 |
| P6 | PRUNE IS DOCUMENT-LOCAL + 无主语料非法 | 一切删除只按确定性 UUID 点删或迭代器实扫对象 UUID;禁 TEXT 属性过滤删除;V1 中每个 corpus 都必须有所属 Source 配置(§11) |
| P7 | Progress Must Be Truthful | 进度/计数/阶段全部来自持久化 Sync Run 状态;分母未知时显示不确定态,不伪造 |

---

## 4. Source Lifecycle(源生命周期)

三个平面分离,**不得混用**:

### 4.1 配置生命周期(Configuration Lifecycle)——R2 修订
```
CREATED ──validate──▶ READY ──┬──disable──▶ DISABLED ──enable──▶ READY
   ▲                          └──delete──▶ (Delete Job:配置+知识)──▶ DELETED
```
- CREATED:已保存配置,未通过首次校验(分支存在性/凭证/可达性)。
- READY:校验通过,可参与调度。
- DISABLED:仅停同步;配置与已摄取知识**全部保留**,知识继续参与正常检索,可重新 Enable。
- DELETED:配置 + 该源全部已摄取知识均按删除 Job 安全处置(可观察、结束验证残留=0)。**V1 不存在「仅删配置、知识留存」的正常路径**(§11)。

### 4.2 运行态(Run State,单源同时至多一个活动 run)
`IDLE · QUEUED · RUNNING · WAITING_FOR_RESOURCES · RECOVERING ·(终态)COMPLETED / FAILED / INTERRUPTED`

### 4.3 健康态(Health,§7 九态)
`HEALTHY · EMPTY_EXPECTED · EMPTY_UNEXPECTED · PARTIAL · DEGRADED · STALE · RECOVERING · ACTION_REQUIRED · INSUFFICIENT_DATA`(DISABLED 不评价,显示禁用)

**退役词汇**:「补齐」废止;旧 partial 拆分归属 PARTIAL(覆盖/一致性缺口且安全)/ DEGRADED(任务成功率低)/ ACTION_REQUIRED(需人工裁决)。

---

## 5. Knowledge Eligibility Model(知识准入模型)——R1 修订

### 5.1 三层管线(CONTRACT)
```
Discovered(全量发现)
  → Layer 1 TECHNICAL SAFETY BOUNDARY(系统硬边界,不可绕过)
  → Layer 2 KNOWLEDGE ELIGIBILITY(知识价值分类:推荐纳入/推荐排除/需确认)
  → Layer 3 ADMIN SOURCE POLICY(管理员策略,只能在 Layer 2 之后收紧)
  → Eligible(最终准入)
```
**最终准入 = TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED**

三层回答的是三个不同的问题,不得互相混充:

| 层 | 回答的问题 | 判定者 | 可否绕过 |
|---|---|---|---|
| Layer 1 Technical Safety | 「这个文件能不能被当前 ingestion pipeline **安全处理**?」 | 系统 | **不可**(管理员配置只能更严) |
| Layer 2 Knowledge Eligibility | 「技术上可处理,但**是否值得成为 ASK-AI 的知识**?」 | 系统推荐 | 可被管理员在边界内调整 |
| Layer 3 Admin Source Policy | 「我希望**这个 Source** 摄取哪些?」 | 管理员 | 只能收紧,不可穿透 Layer 1 |

### 5.2 Layer 1 — Technical Safety Boundary(技术硬边界)
命中即出局并记录原因;**必须发生在昂贵 parsing/chunking/tokenization/embedding 之前**(目标:杜绝 `.hef 84MB → regex/tiktoken → CPU 100%` 类事故):

| 规则 | 说明 |
|---|---|
| 内容嗅探 binary | 首 N KB 检测:NULL 字节占比、magic signature(HEF/ONNX/protobuf/zip 系/可执行等)、不可打印字符占比超阈 → BINARY。**扩展名错的二进制也会被拦** |
| 解码质量 | text 解码后 replacement-char 占比超阈 → 判 binary/corrupt,不入文本管线 |
| 模型/权重工件 | 扩展名类:hef/onnx/pt/pth/ckpt/safetensors/tflite/plan/engine/trt/npy/npz/pkl/so/dll/axf/elf/…(类名单,工程可扩) |
| Hard Safety Ceiling(硬尺寸上限) | 超过硬上限的内容在昂贵管线**之前**阻断。**机制冻结,数值不冻结**:推荐上限(可调,触发 warning/Needs Review)与硬上限(系统阻断)双阈值;示例值 2MB/8MB 仅为 INITIAL HYPOTHESIS,由阶段1「数据导入安全保护」以真实仓库尺寸分布/parser 性能/`.hef 84MB` 场景实证标定 |
| 不支持/不安全格式 | 解析器无法安全处理的类型 |
| 空正文 | 解析后不存在任何可处理正文(技术性:无内容可管线化) |

其余一切「价值低」的判断(生成物/vendor/lock/测试/构建等)**不属于本层**——它们技术上无害,只是知识价值判断(R1)。

### 5.3 Layer 2 — Knowledge Eligibility(知识价值分类)
对通过 Layer 1 的文件自动赋予 Knowledge Role(§6)与三值推荐:

- `RECOMMENDED_INCLUDE`(默认纳入)
- `RECOMMENDED_EXCLUDE`(默认排除,管理员可纳入)
- `NEEDS_REVIEW`(置信度低,默认不摄取,管理员批准确认后后续 sync 摄取——已决策,不阻塞首次同步)

典型 RECOMMENDED_EXCLUDE(都是**知识判断,不是技术危险**):generated files、vendor/third_party、tests、build/deployment files、lock files、low-value content、duplicate/boilerplate content。
**显式冻结:vendor/third_party 不是技术危险**——Technical Support 场景中第三方 SDK/vendor 源码/依赖实现具有真实排障价值,只是默认噪音偏高,属推荐排除。

### 5.4 Layer 3 — Admin Source Policy(管理员策略)
- 管理员手段:file_types、include_dirs、Knowledge Role 开关、类别勾选;
- 语义:在 Layer 2 产出的合法集合内**收紧**;试图包含 Layer 1 排除项 → UI 拒绝并解释「系统安全边界,不可加入」;
- NEEDS_REVIEW 批准也属本层动作。

### 5.5 准入漏斗计数(每个 Run 与 Repository Scan 都产出)
`discovered → safety_excluded{technical reasons} → classified → recommended_excluded{knowledge reasons} → needs_review → policy_excluded → eligible`
该漏斗是 §16 场景 G2 的可见性解药:零合格文件从「看不见」变为「Discovered 1401 → 各层排除原因清楚」。

---

## 6. Knowledge Role Taxonomy(知识角色)——R1/R6 修订

| Role | 典型内容 | 默认推荐(知识判断,非技术危险) |
|---|---|---|
| PRODUCT_DOC | 产品说明/规格/数据表 | RECOMMENDED_INCLUDE |
| TECHNICAL_DOC | 技术文档/设计/白皮书 | RECOMMENDED_INCLUDE |
| API_REFERENCE | API/SDK 参考 | RECOMMENDED_INCLUDE |
| SOURCE_CODE | 源码(含符号级 chunk,既有能力保留) | RECOMMENDED_INCLUDE |
| CONFIGURATION | app.yaml/config/manifest 类 | RECOMMENDED_INCLUDE(超大走尺寸建议阈) |
| EXAMPLE | examples/showcases 示例 | RECOMMENDED_INCLUDE |
| TROUBLESHOOTING | FAQ/排障/已知问题 | RECOMMENDED_INCLUDE |
| TEST | 测试代码/夹具 | RECOMMENDED_EXCLUDE |
| BUILD_DEPLOYMENT | CI/Dockerfile/构建脚本 | RECOMMENDED_EXCLUDE |
| GENERATED | 生成物/lock/编译输出 | RECOMMENDED_EXCLUDE |
| VENDOR / THIRD_PARTY | vendor/third_party 依赖与 SDK 源码 | RECOMMENDED_EXCLUDE(**非技术排除**;排障需要时管理员可纳入) |
| BINARY / ASSET | 二进制/图片/音视频/模型 | **Layer 1 技术排除**(不经 Layer 2) |

- 推荐排除 ≠ Technical Hard Exclusion;管理员可在技术安全边界内调整任何 Layer 2 结论(已决策,§19.1)。
- Role 是准入与展示语义,不改变现有 chunk 属性;**存量语料不做强制 reindex/backfill**——Role 自能力上线起对新摄取生效,回填按需独立处理(已决策)。
- 是否把 Role 写入检索元数据影响排序 = DEFERRED(Answer Correctness 边界)。

---

## 7. Health Model(健康模型)

### 7.1 五维定义
| 维度 | 问题 | 数据来源(CONTRACT 级) |
|---|---|---|
| Connectivity | 现在够得着源吗 | 最近一次 run 的 fetch/鉴权结果(per type) |
| Sync | 近期任务可靠吗 | 窗口内 run 终态分布(30 天聚合降级为本维输入;阈值沿用 0.9/0.5) |
| Coverage | 期望的知识都在吗 | `indexed+failed+skipped = expected`;EMPTY_EXPECTED/EMPTY_UNEXPECTED 在此判定 |
| Freshness | 知识跟得上源吗 | last successful index time vs 期望节奏;**STALE 阈 ≈ 2 × expected sync cadence(默认语义,允许 Source Policy 按源类型调整)**(已决策) |
| Consistency | 账本和向量库一致吗 | ledger↔vector 校验:HEALTHY/GAP/ORPHAN_PENDING |

### 7.2 Overall Health 合成规则(CONTRACT)
1. DISABLED → 显示「已禁用」不评价;
2. 无足够 run 样本 → INSUFFICIENT_DATA;
3. Coverage 判 EMPTY:期望非空且实际 0 → **EMPTY_UNEXPECTED(ACTION_REQUIRED 级)**;期望 EMPTY 且实际 0 → **EMPTY_EXPECTED(HEALTHY 系)**;实际非空但期望 EMPTY → 异常残留 → ACTION_REQUIRED(或一致性恢复流程);
4. 存在 INTERRUPTED 未恢复 run → **RECOVERING**;
5. Coverage 缺口 >0 或 Consistency ≠ HEALTHY → **PARTIAL**(附缺口数);
6. Freshness 超 STALE 阈 → **STALE**;
7. Sync 维低分且其余正常 → **DEGRADED**;
8. 存在需人工裁决项(unresolved 孤儿、Needs Review、删除任务失败)→ **ACTION_REQUIRED**(可叠加显示)。

### 7.3 期望态默认值(已决策,§19.1)
正式生产知识源默认 **REQUIRED**;非核心/实验/探索源 **OPTIONAL / DISCOVERY**;**EXCLUDED** 用于明确不参与知识系统的 Source。

### 7.4 「success + 0 content」终局
源 expected=EMPTY 且实际 0 → EMPTY_EXPECTED,徽章中性;expected=REQUIRED/OPTIONAL 而实际 0 → EMPTY_UNEXPECTED,**从第一轮起即红色**。

---

## 8. Sync Run Model(同步运行模型)

### 8.1 Run 记录(CONTRACT 字段,DB schema DEFERRED)
```
run_id / source_id / trigger(cron|manual|recovery)
status: QUEUED→RUNNING→(WAITING_FOR_RESOURCES)→COMPLETED|FAILED|INTERRUPTED
stage: DISCOVER→SAFETY_FILTER→FETCH→PARSE→CHUNK→EMBED→INDEX→CONSISTENCY→DONE
stage_counters(实时):
  discovered / safety_excluded{reason} / eligible
  fetched / fetch_failed / parsed / parse_failed
  chunked / chunks_total
  embedded / embedded_failed
  indexed / index_failed
delta: added / updated / deleted / unchanged / skipped / failed(文档级终态账)
corpus: expected_docs / actual_docs / consistency_status
timing: started_at / heartbeat_at / finished_at / elapsed
resource: gpu_pressure{bool,level} / waiting_for_resources{duration}
error: primary_error_class / detail(分类见 §10.2)
```

### 8.2 阶段语义
| 阶段 | 开始条件 | 计数含义 |
|---|---|---|
| DISCOVER | run 开始 | 枚举到的源条目数 |
| SAFETY_FILTER | 枚举完成 | 三层漏斗逐格计数(§5.5),产出 eligible 与 needs_review |
| FETCH | 准入确定 | 拉取成功/失败(eligible 为分母) |
| PARSE/CHUNK | 逐文件 | 文本化+切块;chunks_total 首文件后逐步可知 |
| EMBED | 首块就绪 | 向量化计数;GPU 压力在此暴露 |
| INDEX | 随批写入 | 写入向量库计数 |
| CONSISTENCY | 写入完成 | expected vs actual 对账 + 处置 |
| DONE | 复验收敛 | 终态 delta 与 corpus 快照 |

### 8.3 中断与可恢复(P5,CONTRACT)
- 判定:RUNNING 且 heartbeat 落后 > 阈(如 3× 心跳周期),或执行器启动时发现孤儿 RUNNING → 标 **INTERRUPTED**;
- 标记即持久:该源进入 RECOVERING;**incomplete-run 标志门控 no-change 健康路径**——存在未恢复中断时,「existing>0 → 一致性健康 → success」不得成立;
- 恢复语义:以权威成员集对账「已入/未入」,仅补 missing,绝不回滚已安全写入文档;
- 中断 run 的部分产物是可信的(逐文档幂等写入)。

---

## 9. Progress Semantics(进度语义)

1. 总进度分母 = eligible(文件级),SAFETY_FILTER 完成时确定;此前显示「发现中…/评估中…」不确定态,不显示百分比;
2. 分块/嵌入/写库子阶段用 chunks_total 作分母,与文件级阶段分行显示,不混算;
3. `总进度 = 已完成文件数 / eligible`;子阶段条是细节,不回填总进度;
4. 阶段失败:该阶段标 FAILED + 失败计数,run 终态 FAILED/PARTIAL;已成功部分保留,UI 明示「N 篇已完成不受影响」;
5. 部分完成:missing = eligible − added − skipped − failed,显示「待续传」,RECOVERING 由系统续传;
6. 假进度禁区:前端不得根据 elapsed 推算百分比。

---

## 10. Failure & Recovery Semantics(失败与恢复)

### 10.1 管理员视图五问
`WHAT HAPPENED / WHY / IMPACT / WHAT SYSTEM DID / WHAT ADMIN SHOULD DO`

### 10.2 错误分类(CONTRACT,首版)
`AUTH · NETWORK · NOT_FOUND · BINARY_CONTENT · OVERSIZED · PARSE_ERROR · TOKENIZE_ERROR · EMBED_RESOURCE(GPU) · INDEX_WRITE · CONSISTENCY_GAP · ORPHAN_UNRESOLVED · INTERRUPTED · POLICY_EMPTY · UNKNOWN`

- **EMBED_RESOURCE(GPU OOM,apic 实证)**→ WAITING_FOR_RESOURCES + 退避重试;连续 N 轮后 ACTION_REQUIRED「计算资源不足,建议稍后重试/查看资源状态」。资源调优参数不属于本页面动作面(§13)。
- **BINARY_CONTENT** → 逐文件排除计数,不 fail 整轮(.hef 第二防线)。
- **TOKENIZE_ERROR / PARSE_ERROR(R4 修订:冻结要求,不冻结 HOW)**:单个合法文档发生 tokenizer/chunker/parser 异常时——
  1. 不得导致整个 Source Sync 失控;
  2. 不得阻塞在线服务;
  3. 必须隔离为 document-level failure;
  4. 必须记录明确 failure classification;
  5. Corpus / Health / Progress 必须真实反映该失败;
  6. 系统能安全自动恢复则恢复;不能则进入 failed / action-required 语义。
  具体手段(sanitize / escape / fallback tokenizer / alternate chunking / skip / retry)由执行端依真实 root cause 决定,本合同不冻结。

### 10.3 动作按钮(安全语义冻结后才可出现)
| 动作 | 语义 | 安全边界 |
|---|---|---|
| Retry Failed | 仅重试 failed 文档 | 文档局部,幂等 |
| Resume Sync | 续传 missing(RECOVERING/interrupted) | 权威成员集对账,不回滚已入 |
| Full Reconcile | 权威枚举 vs 语料全量对账(含退休) | 需发现完整性满足(discovered>0 等);不完整发现禁退休 |
| Delete Source | §11 删除 Job(配置+知识一体) | 双确认;文档局部 UUID 删除;残留=0 验证 |
| View Details / View Resource Status | 只读深链 | — |
**禁止**:「一键修复所有问题」;普通管理员参数调优入口(并发/batch/worker);跨源操作出现在单源面板。

### 10.4 恢复可视化
RECOVERING 态显示中断点、已自动补齐计数、剩余估计;收敛 → HEALTHY 并在 Run 历史留痕。

---

## 11. Safe Source Delete(安全删除语义)——R2 修订

### 11.1 V1 生命周期操作 = 两个

| 操作 | 配置 | 知识 | 检索 |
|---|---|---|---|
| **Disable Source** | 保留 | 保留 | **继续参与正常检索**;可重新 Enable |
| **Delete Source** | 删除 | **文档局部安全删除该源全部知识** | 知识退出 |

Disable 与 Delete 的本质区别:**Disable=只停同步,一切保留;Delete=配置与知识一起退场**。

### 11.2 Delete Source 的硬边界(P6)
1. 删除必须是**可观察的 Job**:进度可见、失败可重试、进入 ACTION_REQUIRED;
2. 范围 = 账本已知文档的确定性 UUID 集(uuid5(source_id, 0..chunk_count-1))∪ 迭代器实扫到的该源前缀对象 UUID;
3. 禁止一切 TEXT 属性 equal/like 删除(旧 Admin delete 的 equal 原语必须被替换);
4. 删除结束**必须验证残留 = 0**(账本行 + 该源向量对象);
5. UI 文案明确「删除源 = 配置与知识一起删除,不可撤销」,双确认。

### 11.3 Orphan Corpus 的定位(R2)
- V1 **不允许**任何正常生命周期操作产生 orphan corpus(无 Source 配置的语料不是合法稳态);
- 若底层缺陷产生 orphan → 归类为 **Consistency Problem / Recovery Problem**,由一致性校验/恢复机制披露与处置,不是管理员功能;
- 未来若确需「Detach Source but Retain Corpus(归档保留语料)」,必须作为独立的 **Archive/Detach Product Capability** 重新设计;**V1 不提供**。

---

## 12. Scheduling / Concurrency Semantics(调度与并发)

- 单源单 run:重复触发返回「已在进行」或并入 QUEUED(产品默认去重);
- 手动 vs 定时互不抢占;资源不足时新 run 进 WAITING_FOR_RESOURCES;
- **每 Source 拥有真实 expected sync cadence**(已决策):当前生产「每小时 cron」不是 Product Truth;默认 cadence 由阶段7「调度、资源控制与一致性完善」按 Source 类型与运行成本确定,Source Policy 可覆盖;
- 触发来源(cron/manual/recovery)在 Run 历史必现;
- 管理员可见状态:QUEUED / RUNNING / WAITING_FOR_RESOURCES / RECOVERING。

---

## 13. Runtime Resource Boundary(与系统运行时页的边界)——R5 修订

- 本中心不成为服务器监控页;CPU/RAM/GPU 明细属未来「System Runtime & Resource Observability」;
- Run 记录携带 `resource` 字段(gpu_pressure / waiting_for_resources),数据源页以徽章表达;
- 资源压力时的管理员动作**仅限**:`[稍后重试]` `[查看资源状态]`(未来跳转 Runtime 页) `[查看失败详情]`;
- **embedding concurrency / batch size / worker tuning / GPU scheduling 属于 System Runtime / Advanced Operations 职责**,普通数据源页面不提供、不解释、不暴露该类参数。

---

## 14. Admin Information Architecture(信息架构)

### 14.1 数据源列表(每行)
`源(id+type+product) / 期望态 / 健康(徽章+一句话) / 覆盖(indexed/expected) / 新鲜度(相对时间+✓/!) / 内容(docs·chunks) / 当前活动(run 态或进度摘要) / 行内操作`

### 14.2 源详情(推荐 5 Tab)
1. **概览**:五维健康卡 + 期望 vs 实际 + 当前活动 + 主行动按钮;
2. **知识覆盖**:expected/actual/skipped/failed 明细、缺失清单、unresolved 孤儿(一致性问题描述)、内容清单(按 Role 标注);
3. **同步记录**:Run 历史(状态/触发/耗时/delta/错误分类),单 run 阶段计数;
4. **准入与文件**:三层漏斗 + 文件级 included/excluded+原因+大小+Role;
5. **设置**:配置、期望态、策略、节奏、**危险区(Disable / Delete 两操作;Delete=配置+知识一体,残留=0 验证)**。

### 14.3 活动同步(Active Sync)
列表行内联进度条 + 页首固定卡;任何活动同步都可在列表页看懂阶段。

### 14.4 失败态
一律落 §10.1 五问结构;禁用裸词 partial/failed/补齐 作为唯一信息。

---

## 15. UX Wireframes(ASCII;v1.1 仅修订受决策影响的三处:15.4 / 15.5 / 新增 15.6)

### 15.1 数据源列表
```
数据源可靠性中心                                                          [＋新建数据源]
────────────────────────────────────────────────────────────────────────────────
源                      期望    健康            覆盖        新鲜度    内容      当前活动
────────────────────────────────────────────────────────────────────────────────
neoruntime-apps-1eea74dd 必需   ◐ PARTIAL       64/169      3h前 ✓    59 篇    ● SYNCING 41%
 github · main                  首次灌入中断      缺105 待续传             嵌入 2140/5103 ↗
                                [续传同步] [详情]
website-camthink         必需   ◐ PARTIAL       366/366     1h前 ✓    123 页    —
 web_crawl                      5页持续抽取失败    缺5页待裁决                        [详情]
neoruntime (apic)        必需   ⛔ ACTION_REQ   0/1401      9h前 ✗    0 篇     ⏳ WAITING_RES
 github · main                  计算资源不足       全部待灌       陈旧               [详情]
neoruntime-sdks          必需   ✓ HEALTHY       107/107     2h前 ✓    107 篇   —
 github · main                  全部正常         完整                            [详情]
sandbox-playground       可选   ○ EMPTY_EXPECTED 0/0         —         0 篇     —
 github · main                  期望为空,正常                                     [详情]
────────────────────────────────────────────────────────────────────────────────
● 运行中 2 · ⏳ 等资源 1 · ⚠ 需处理 2          资源压力 ⚠  [查看资源状态(规划中)]
```

### 15.2 源详情 — 概览
```
neoruntime-apps-1eea74dd        github · product:neoruntime-apps · 期望:必需
[概览] [知识覆盖] [同步记录] [准入与文件] [设置]
────────────────────────────────────────────────────────────────────────────────
健康 ◐ PARTIAL — 首次同步于 09:26 被中断,105 篇未灌入;已完成 64 篇安全保留

  连接    ✓ 正常(09:39 API 200)
  同步    ✗ 中断 1 次(heartbeat 失联)
  覆盖    64/169 篇(缺 105)      实际 chunk 3,912
  新鲜度  ✓ 3h 前
  一致性  ✓ 62/62 账本↔向量一致

影响:本源知识不完整,相关问答可能缺失。
系统动作:自动恢复等待执行器 → [立即续传]
[续传同步]   [全量对账]   [查看中断详情]
```

### 15.3 活动同步(行内展开/固定卡)
```
● 正在同步 neoruntime-apps-1eea74dd · 手动 · 已进行 12m · 不影响在线服务

  发现      194 / 194
  技术安全  178(排除 16:模型二进制 11 · 解码失败 2 · 超过硬上限 3)
  知识推荐  建议纳入 130 · 建议排除 46(生成物 21 · 测试 17 · 构建 8)· 需确认 2
  抓取      96 / 130
  解析      96 / 96
  分块      4,102 / 4,102
  嵌入      2,140 / 4,102  ⚠ GPU 压力(共享 95%)
  写入库    1,908 / 4,102
  一致性    待执行

  变更     +94 新增 · 0 更新 · 0 删除 · 2 跳过 · 2 失败(查看:1 tokenize · 1 空)
```

### 15.4 失败/恢复详情(R5 修订:删除并发调参)
```
⛔ PARTIAL · 需要处理 — neoruntime (apic)

发生了什么   同步因计算资源不足暂停,已连续 3 轮未能完成嵌入
为什么       GPU 显存/算力不可用(共享 GPU 已接近满载)
影响         1,401 篇合格文档未入知识库;相关问答暂无法命中本源
系统已做     已自动等待资源并安全退避重试;失败均已逐文档记录
建议操作     ① 稍后自动重试(默认已安排)
             ② 查看资源状态(何时有空闲算力)
             ③ 查看失败明细
             [稍后重试]   [查看资源状态]   [查看失败详情]
```

### 15.5 新建数据源 — Repository Scan(R1 修订:四类排除语义分明)
```
新建数据源 · GitHub · camthink-ai/neoruntime-apps @ main          [重新扫描]
────────────────────────────────────────────────────────────────────────────────
发现 194 个文件

 🛡 系统安全排除 16 —— 不可加入(技术硬边界)
     模型/二进制 11(.hef 等,184.8 MB)· 解码失败 2 · 超过硬上限 3(示例阈值,待阶段1标定)
     [展开文件与原因](灰色锁定,仅可查看)

 ◐ 知识推荐排除 46 —— 默认不纳入,可自行调整
     生成物 21 · 测试 17 · 构建/部署 8     (均为知识价值判断,非技术危险)

 ⚠ 需确认 2 —— 无法自动分类(无扩展名),默认不摄取
     [查看] [批准纳入]

 ☑ 知识推荐纳入 130
     文档 10 · 源码 96 · 配置 14 · 示例 10

  你的策略:☐ 追加纳入测试 ☐ 追加纳入构建  ☐ 追加纳入 vendor/第三方
  (只能收紧/放宽「推荐」层;🛡 系统安全排除不可被勾选)

节奏 每日 1 次 ▾(默认节奏由调度阶段确定,可按源覆盖)   期望状态 必需 ▾
                                     [取消]  [保存并执行首次同步]
说明:首次同步在后台执行,不影响在线服务;进度可在列表实时查看。
```

### 15.6 设置 · 危险区(R2 修订:两操作,无「删配置留知识」)
```
[设置]  ···  危险区 ────────────────────────────────────────
  ⏸ 停用源(Disable)
     停止后续同步;配置与知识全部保留;知识继续参与检索;可随时重新启用
     [停用源]
  ────────────────────────────────────────────────
  🗑 删除源(Delete)
     删除源配置,并文档局部删除该源全部已摄取知识
     过程可观察 · 结束自动验证残留=0 · 失败进入「需要处理」
     ⚠ 不可撤销。将删除 62 篇文档 / 39,155 chunks
     [删除源](双确认:勾选理解 + 输入源 ID)
  ────────────────────────────────────────────────
  说明:V1 不提供「仅删配置、保留语料」。如未来需要归档保留,
  将作为独立的 Archive 能力另行设计。
```

---

## 16. Golden Failure Scenarios(真实事故 → 设计如何兜住)

| # | 事故(实证) | 旧世界行为 | 新合同下的行为 | 兜底条款 |
|---|---|---|---|---|
| G1 | `.hef` 84MB 二进制入文本管线 → 单核 100%、504、64/169 中断 | preview 全列扩展名全收;无技术安全嗅探;无硬尺寸上限;同步在 backend 进程内 | Layer 1 在解析前嗅探+类名单+硬上限 → 11 个 .hef 全部「技术安全排除」(**其被拦原因是技术危险,而非价值判断**);即便漏网,隔离执行器保在线服务;单文档异常只隔离到文档级 | §5.2 / §10.2 / P4 |
| G2 | healthy + content=0(apic 前期) | 30 天成功率 100% = 健康;零合格文件不可见 | Coverage 维:eligible=0 + expected=REQUIRED → EMPTY_UNEXPECTED 红色;三层漏斗显示各层排除原因 | §7.2 / §5.5 |
| G3 | 中断首次同步 → existing>0 → 下轮「无变更=健康」→ 105 篇永不补齐 | 无 run 持久化;无中断检测 | INTERRUPTED 标记 + RECOVERING + incomplete 标志门控 no-change 健康路径 | §8.3 / P5 |
| G4 | GPU OOM 风暴:apic 1,400 篇全灭(单轮) | 整轮 failed,无资源语义,反复空转 | EMBED_RESOURCE 分类 + WAITING_FOR_RESOURCES + 退避;升级 ACTION_REQUIRED;管理员动作=[稍后重试][查看资源状态][查看失败详情],无调参入口 | §10.2 / §13 |
| G5 | TEXT equal 删除过匹配(Admin delete 残留 P0 候选) | 跨源误删风险仍在 | Delete Job 仅确定性 UUID/实扫对象 UUID;TEXT 过滤删除被合同禁止;残留=0 验证 | §11.2 / P6 |
| G6 | 空/畸形 sitemap 判「完整发现」→ 孤儿批量退休(Discovery §11#2) | complete=True + 空成员集 | Full Reconcile 仅在发现完整性满足(discovered>0 等)时允许退休;否则 KEEP+REPORT | §10.3 |
| G7 | 「补齐」一词三义 | 管理员无法区分 | 一词退役,拆为 PARTIAL/DEGRADED/ACTION_REQUIRED + 五问结构 | §4.3/§10.1 |

---

## 17. Engineering Gates — 阶段分解与依赖(R7:中文名称,重审依赖)

### 17.1 八个阶段

| 阶段 | 名称 | 解决什么 | 重点 Golden | 依赖 | 可并行 | 主要冲突区 | Acceptance Evidence(概要) |
|---|---|---|---|---|---|---|---|
| 1 | **数据导入安全保护** | Technical Safety Boundary、Knowledge Eligibility 分类、Repository Scan 基础、Safe Delete(UUID 化)、空/畸形发现不得错误退休 | `.hef 84MB` | 无(**阻塞级,先行**) | 否 | connectors/、exclusion、ingest 入口、data_sources.py 删除段 | .hef 树复算 184.8MB 全拦截;真实 Weaviate 删除回归;空 sitemap 演习=KEEP;vendor 文件不被技术排除 |
| 2 | **同步任务与在线服务隔离** | Full Sync 移出在线 API 执行路径;backend 生命周期与 sync 生命周期隔离 | 2026-09-02 nginx 504 | 阶段1 | 否(与1共享 sync.py 热区) | scripts/sync.py、data_sources.py 触发端、deploy compose | 全量灌入期间 /health P99 正常;backend 重启不杀 run |
| 3 | **同步中断后的自动恢复** | INTERRUPTED 检测、incomplete-run truth、Resume/Retry/Reconcile、防 64/169 假健康 | 中断 64/169 | 阶段2 | 与 4 可并行(接口冻结后) | scripts/sync.py(恢复语义)、run 存储 | kill 执行器→INTERRUPTED→续传收敛;incomplete 期间 no-change 不判健康 |
| 4 | **数据源真实健康状态** | 五维健康、Expected vs Actual、EMPTY 二分、PARTIAL/STALE/ACTION_REQUIRED | healthy+0 | 阶段1-3 | **与 5 并行** | analytics.py、models(迁移)、admin API | 现网 15 源健康重算报告:apic=ACTION_REQUIRED、空源=EMPTY_*、website=PARTIAL |
| 5 | **同步实时进度与统计** | 八阶段计数 + 六类 delta,backend truth | 进度假条 | 阶段2 | **与 4 并行** | sync.py 计数埋点、admin API | 真实全量 run 计数与日志一致;分母未知期显示正确 |
| 6 | **Admin 数据源管理中心** | List/Detail/Repository Scan/Active Sync/Eligibility/Failure Diagnostics/Safe Recovery/Settings 前端 | 五问失败面板 | 阶段4+5 | 否(消费 4/5 API) | admin/src(DataSources 大改) | wireframe 对齐评审;关键态截图;admin 前端测试 |
| 7 | **调度、资源控制与一致性完善** | manual/scheduled 协调、单源单 run、重复触发、WAITING_FOR_RESOURCES、retry/backoff、一致性校验、sync_interval 真实生效与默认 cadence 标定 | cron×manual 并发 | 阶段2、3 | 可与 6 并行(6 纯前端) | sync.py 调度层、data_sources.py、compose | 双触发去重;并发锁测试;节奏按源生效 |
| 8 | **数据源完整性最终验收** | 重演全部 Golden Failures;证明 binary 不污染、safe delete 不跨源、误发现不误删、中断可恢复、full sync 不扰在线、health/progress 与 backend truth 一致、Admin 可解释 | G1-G7 全部 | 1-7 | 最终门 | 只读+评测 | 每场景一条 PASS 证据;垃圾 chunk 计数收敛 |

### 17.2 推荐执行拓扑(供 Planner 决定 SINGLE/PARALLEL)
```
阶段1 ──▶ 阶段2 ──▶ 阶段3 ──┬─▶ 阶段4 ──┐
                            └─▶ 阶段5 ──┴─▶ 阶段6 ──▶ 阶段8
                         阶段7(可与 6 并行;须在 3 后)
```
- 阶段1 **必须单独先行**(P0 安全 + 两处删除/退休修复,改动集中、影响面最大);
- 阶段2 单独(sync.py 执行层热区);
- 4∥5 双窗可行(阶段2 冻结 run 数据契约后各自成面);7 与 6 可并行;
- 冲突热区:`scripts/sync.py`(1/2/3/5/7)——除 4∥5 与 6∥7 外避免双窗同触;`data_sources.py`(1/2/6/7);`analytics.py`(4);`admin/src`(6)。

---

## 18. Acceptance Criteria(本合同 Gate,含 v1.1 修订验收)

1. Technical Safety 与 Knowledge Eligibility 完全分离,vendor/third_party 不属于系统 Hard Exclusion(R1);
2. V1 不存在「删配置留语料」正常生命周期;Disable 与 Delete 语义明确,Delete 可观察且残留=0 验证(R2);
3. 双尺寸阈值机制冻结,2MB/8MB 仅 INITIAL HYPOTHESIS,数值标定归阶段1(R3);
4. 文档级失败隔离为冻结要求,实现 HOW 不冻结(R4);
5. GPU/并发调参不出现在普通管理员动作面(R5);
6. Discovery 与 504 证据全部吸收(G1-G7 有对应条款);
7. 中断可恢复语义完整(INTERRUPTED/RECOVERING/门控假健康);
8. 同步执行隔离为冻结要求,不指定框架;
9. 健康五维合成 + 期望态四值 + EMPTY 二分;「补齐」退役;
10. 进度 = backend 真值;代码/配置/文档保持合法知识(非 document-only);
11. wireframe 与最终语义一致(四类排除分明/失败无调参/危险区两操作);
12. 阶段使用中文名,依赖/并行/冲突/验收证据明示;
13. 生产 .hef 污染记录为 DEFERRED,零 mutation;
14. 本 Gate 零生产访问、零实现改动。

---

## 19. Product Decisions 收敛与生产污染记录

### 19.1 已决策记录(Planner Review 收敛,不再列为待决)
| 决策 | 冻结语义 |
|---|---|
| Expected State | 正式生产知识源默认 REQUIRED;非核心/实验/探索 = OPTIONAL/DISCOVERY;EXCLUDED = 明确不参与知识系统的 Source |
| Knowledge Role 默认 | INCLUDE:PRODUCT_DOC/TECHNICAL_DOC/API_REFERENCE/SOURCE_CODE/CONFIGURATION/EXAMPLE/TROUBLESHOOTING;EXCLUDE:TEST/BUILD_DEPLOYMENT/GENERATED/VENDOR(推荐排除≠技术排除) |
| 存量语料 Role 迁移 | 不做强制 reindex/backfill;Role 自能力上线起生效;回填按需独立处理 |
| Size Threshold | 冻结「推荐上限 + 硬上限」双阈机制;数值由阶段1实证标定(2MB/8MB 为示例假设) |
| Freshness | STALE ≈ 2× expected sync cadence,允许 Source Policy 调整 |
| sync cadence | 每 Source 真实 cadence;默认值由阶段7 按源类型与运行成本确定;「每小时 cron」不是 Product Truth |
| Disable | 停同步;配置与知识保留;知识继续参与检索 |
| Needs Review | 不阻塞首次同步;未确认默认不摄取;批准后后续 sync 摄取 |

### 19.2 P0 PRODUCTION CORPUS CONTAMINATION — **DEFERRED BY PRODUCT OWNER**
- 事实(CONFIRMED,2026-09-02 取证):生产存在 `neoruntime-apps-1eea74dd` ≈ **62 ledger documents / 39,155 chunks**,其中 **≈38,874 chunks 来自 3 个 `.hef` binary model artifacts(≈99.3%)**;
- 定级:**P0 生产语料污染**;
- PO 决定:优先继续 Data Source Reliability 主线 → 本 Gate **记录不处理**;禁止访问生产 / purge / delete / reindex / recovery / trigger sync;
- 合同记录:**Safe Purge Required**——推荐在阶段1「数据导入安全保护」交付 Safe Delete / Technical Safety Boundary 正式机制后,使用该机制处理;
- 触发条款:若实际回答明显受污染影响,独立进入 **Emergency Production Cleanup Gate**。

### 19.3 PRODUCT_DECISIONS_REQUIRED
**none**(全部收敛;唯一挂起项为 §19.2 的执行时点,已由 PO 决策框架覆盖)。

---

## 20. Non-goals(本 Gate 明确不做)

修改 production code / Admin 前端 / DB schema / migration / sync 实现;部署;生产访问;清理/purge 生产语料;恢复 neoruntime-apps;开始「阶段1 数据导入安全保护」的实现;实现 System Runtime 页;实现 Answer Correctness;运行 ask-ai-eval;选定 worker 框架。

---

## 附:交付信息与生产状态快照

- v1.0 报告 commit `7baa4e6`;v1.1 Final Revision commit 见最终答复(同文件增量修订)
- 依据:Discovery(245a19b)· 504 事故 triage · neoruntime 摄取实证(sync_log 9,532+550 runs、.hef 184.8MB、中断 62 篇)
- 生产状态快照(截至本修订):backend healthy、/health 与 /admin 200;`neoruntime-apps-1eea74dd` 62 篇/39,155 chunks 污染在库(**DEFERRED**,§19.2);旧 `ne503-aipc-apps-20e0886a` / `ne503-apic-69d3594b` 配置仍在(0 内容);无进行中 mutation
