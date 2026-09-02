# CAMTHINK V1 — DATA SOURCE RELIABILITY PRODUCT CONTRACT & UX ARCHITECTURE

- 日期:2026-09-02
- Gate 类型:PRODUCT CONTRACT + UX ARCHITECTURE(非实现 Gate)
- 源基线:`193f206a3d0e8695f1c40766a1ba54667fcba2fb`(生产冻结源)
- 输入:Data Source Reliability Discovery(PASS,docs 245a19b)、2026-09-02 生产 504 事故实证、neoruntime/neoruntime-apps 摄取实证、现有 Admin/backend/sync 架构
- 边界:零生产访问、零代码/Schema/前端改动、零 sync 触发;残缺 neoruntime-apps 数据按 PO 决定**不再恢复**
- 状态词:CONFIRMED(既有实证)/ CONTRACT(本文冻结的产品语义)/ DEFERRED(留待实现 Gate)

---

## 1. Executive Product Decision

把「数据源同步监控」升级为 **Data Source Reliability & Governance Center**,以五个冻结原则为地基:

1. **健康 ≠ 任务成功**(P1):健康是五个维度(连接/同步/覆盖/新鲜度/一致性)的合成结论,30 天裸成功率退役为同步维度的一个输入。
2. **期望态先行**(P2):每个源声明 REQUIRED / OPTIONAL / DISCOVERY / EXCLUDED;EMPTY_EXPECTED 与 EMPTY_UNEXPECTED 从此是两个不同的健康结论。
3. **准入 = 安全 ∧ 知识 ∧ 策略**(P3):系统级硬安全边界不可被管理员配置绕过;`.hef` 式事故由通用 binary/超大物检出拦截,而非逐个黑名单。
4. **同步不在线**(P4):重型摄取永远不占用在线服务进程;进度是 backend 真值(P7),不是假进度条。
5. **可中断可恢复**(P5):中断的首次同步绝不产生「假健康」;删除永远文档局部(P6)。

一次性把过去一周全部真实事故定为国家禁飞区(§16 Golden Failures):healthy+0(零合格文件不可见)、.hef 84MB 二进制进文本管线(单核 100% + 504)、中断 64/169(假健康陷阱)、GPU OOM 风暴(1400 篇全灭)、TEXT equal 跨源误删。

**本文不选 worker 框架、不定义 DB schema**;冻结的是状态模型、语义、信息架构、交互与 Gate 边界。

---

## 2. Product Goals

管理员不 SSH、不查库、不猜日志,即可:

1. 判断每个源是否真的健康(五维健康 + 期望态);
2. 知道知识是否完整/最新/可用(覆盖 = 实际/期望,新鲜度 vs 节奏,一致性);
3. 看懂一次同步在做什么(阶段 + 真实计数);
4. 知道增/更/删/失败了多少(delta 统计);
5. 看懂异常原因与影响(WHAT/WHY/IMPACT/SYSTEM DID/ADMIN SHOULD DO);
6. 知道系统是否在自动恢复(RECOVERING 可见);
7. 拿到明确且**安全**的处理动作(无一键修一切);
8. 不适合进知识库的数据进不来(硬安全边界);
9. 同步永远不影响在线问答(执行隔离)。

---

## 3. Frozen Principles(冻结,不再讨论)

| # | 原则 | 合同约束 |
|---|---|---|
| P1 | Job Success ≠ Knowledge Health | 健康必须合成 Connectivity/Sync/Coverage/Freshness/Consistency ≥1 个非任务维度;禁止单一成功率即健康 |
| P2 | Expected vs Actual | REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED 四态期望;EMPTY_EXPECTED 与 EMPTY_UNEXPECTED 语义分离 |
| P3 | Knowledge Eligibility | 准入 = SYSTEM SAFETY ∧ KNOWLEDGE ELIGIBILITY ∧ SOURCE POLICY;管理员配置只能**收紧**,不能穿透硬安全;源码检索能力必须保留(非 document-only) |
| P4 | Sync Must Not Block Online | 摄取不得在 API/Chat/Admin 服务进程内执行;backend 重启不得杀死进行中的同步 |
| P5 | Interrupted Must Be Recoverable | 中断 run 必须被检测、标记、可续传;「existing>0 → 无变更 → 健康」路径必须被 incomplete-run 标志门控 |
| P6 | PRUNE IS DOCUMENT-LOCAL | 一切删除只按 (source_id, chunk_index) 确定性 UUID 点删或迭代器实扫对象 UUID;禁 TEXT 属性过滤删除;Admin 删除同边界 |
| P7 | Progress Must Be Truthful | 进度/计数/阶段全部来自持久化 Sync Run 状态;分母未知时显示不确定态,不伪造 |

---

## 4. Source Lifecycle(源生命周期)

三个平面分离,**不得混用**(现状正是混用导致「补齐」一词三义):

### 4.1 配置生命周期(Configuration Lifecycle)
```
CREATED ──validate──▶ READY ──┬──disable──▶ DISABLED ──enable──▶ READY
   ▲                          └──delete──▶ (Delete Job)──▶ DELETED
   └────── re-create ◀── DELETE 完成
```
- CREATED:已保存配置,未通过首次校验(分支存在性/凭证/可达性)。
- READY:校验通过,可参与调度。
- DISABLED:仅停同步;**已入知识保留且仍可检索**(与「删除知识」语义分离,§11)。
- DELETED:配置与(可选)知识均已按删除 Job 结果处置。

### 4.2 运行态(Run State,单源同时至多一个活动 run)
`IDLE · QUEUED · RUNNING · WAITING_FOR_RESOURCES · RECOVERING ·(终态)COMPLETED / FAILED / INTERRUPTED`
- RECOVERING:检测到 INTERRUPTED run,系统正在续传/对账。
- INTERRUPTED:worker/进程死亡或超时失去心跳的 run(§8.3)。

### 4.3 健康态(Health,§7 九态)
`HEALTHY · EMPTY_EXPECTED · EMPTY_UNEXPECTED · PARTIAL · DEGRADED · STALE · RECOVERING · ACTION_REQUIRED · INSUFFICIENT_DATA`(DISABLED 不评价,显示禁用)

**退役词汇**:「补齐」废止;旧 partial 拆分归属 PARTIAL(覆盖/一致性缺口且安全)/ DEGRADED(任务成功率低)/ ACTION_REQUIRED(需人工裁决)。

---

## 5. Knowledge Eligibility Model(知识准入模型)

### 5.1 三层管线(CONTRACT)
```
Discovered(全量发现)
  → ① SYSTEM SAFETY(硬安全,系统级,管理员不可绕过)
  → ② KNOWLEDGE CLASSIFICATION(自动知识分类,赋予 Knowledge Role,§6)
  → ③ SOURCE POLICY(管理员策略:file_types/目录/角色选择,只能②的合法集合内收紧)
  → Eligible(最终准入)
```

### 5.2 ① 硬安全层(Hard Exclusion,不可覆盖)
按序判定,命中即出局并记录原因(供 UI 展示):

| 规则 | 说明(防 .hef 类事故的通用边界,非黑名单) |
|---|---|
| 内容嗅探 binary | 首 N KB 检测:NULL 字节占比、magic signature(HEF/ONNX/protobuf/zip 系/可执行等)、不可打印字符占比超阈 → BINARY。**扩展名错的二进制也会被拦**(.hef 事故根因) |
| 解码质量 | text 解码后 replacement-char 占比超阈(如 >5%)→ 判 binary/corrupt,不入文本管线 |
| 模型/权重工件 | 扩展名类:hef/onnx/pt/pth/ckpt/safetensors/tflite/plan/engine/trt/npy/npz/pkl/so/dll/axf/elf/…(类名单,工程可扩) |
| 超大文件 | 双阈:硬上限(hard max,如 8MB,系统不可超)与建议上限(max_file_size,默认 CONTRACT 建议值见 §19-D);超硬上限直接排除 |
| 生成/依赖工件 | BUILD_DIRS(既有)扩展:dist-info、coverage、.turbo、bazel-*、vendor/、third_party/(可配) |
| 空/低价值 | 解析后正文为空或低于最小语义长度 |
| 不支持格式 | 解析器无法安全处理的类型 |

**关键语义**:硬安全层在**解析之前**即可由「路径+元数据+头部嗅探」判定,天然防止 84MB 二进制进入 regex/tiktoken(504 事故的直接防线)。

### 5.3 ② 知识分类层(Knowledge Classification)
对通过硬安全的文件赋予 Knowledge Role(§6),纯自动、可解释、可展示。

### 5.4 ③ 管理员策略层(Soft Recommendation + Admin Policy)
- **Hard Exclusion**:不可见即可,不可绕过;UI 明示「系统安全排除,不可加入」。
- **Soft Recommendation**:系统推荐纳入/排除(按 Role 默认表,§6);管理员可改。
- **Admin Policy**:file_types / include_dirs / 角色开关,只能在②产出的合法集合内**收紧**;试图包含硬排除文件 → UI 拒绝并解释。
- **Needs Review**:自动分类置信度低的文件(如无扩展名、混合内容)标「需确认」,默认不纳入,管理员一键批准确认后才进管线。

### 5.5 准入漏斗计数(每个 Run 与 Repository Scan 都产出)
`discovered → safety_excluded{reasons} → classified → policy_excluded → needs_review → eligible`
该漏斗是 §16 场景「healthy+0」的可见性解药:零合格文件从「看不见」变为「Discovered 1401 → 全部安全排除/分类为 X」。

---

## 6. Knowledge Role Taxonomy(知识角色)

| Role | 典型内容 | 默认准入 | 需管理员确认 | 检索优先级影响(DEFERRED) |
|---|---|---|---|---|
| PRODUCT_DOC | 产品说明/规格/数据表 | ✅ 纳入 | 否 | 高(意图路由加权) |
| TECHNICAL_DOC | 技术文档/设计/白皮书 | ✅ 纳入 | 否 | 高 |
| API_REFERENCE | API/SDK 参考 | ✅ 纳入 | 否 | 高 |
| SOURCE_CODE | 源码(含符号级 chunk,既有能力保留) | ✅ 纳入 | 否 | 中(代码意图路由) |
| CONFIGURATION | app.yaml/config/manifest 类 | ✅ 纳入(小) | 大文件确认 | 中 |
| EXAMPLE | examples/showcases 示例 | ✅ 纳入 | 否 | 中低 |
| TROUBLESHOOTING | FAQ/排障/已知问题 | ✅ 纳入 | 否 | 高(support 意图) |
| BUILD_DEPLOYMENT | CI/Dockerfile/构建脚本 | ⚠️ 默认排除 | 是 | 低 |
| TEST | 测试代码/夹具 | ⚠️ 默认排除 | 是 | 低 |
| GENERATED | 生成物/lock/编译输出 | ❌ 默认排除 | — | — |
| VENDOR | vendor/third_party | ❌ 默认排除 | — | — |
| BINARY / ASSET | 二进制/图片/音视频/模型 | ❌ **硬排除** | — | — |

- Role 是**准入与展示语义**,不改变现有 chunk 属性;是否把 Role 写入检索元数据影响排序 = DEFERRED(Answer Correctness 边界,本合同只声明未来存在此关系)。
- 现有 15 个生产源不迁移 Role 重算;Role 从新 Gate 起对**新发现文件**生效(存量按需回填 = Open Decision)。

---

## 7. Health Model(健康模型)

### 7.1 五维定义
| 维度 | 问题 | 数据来源(CONTRACT 级) |
|---|---|---|
| Connectivity | 现在够得着源吗 | 最近一次 run 的 fetch/鉴权结果(per type:API 200、clone 成功、sitemap 可达、store API 200) |
| Sync | 近期任务可靠吗 | 窗口内 run 终态分布(现有 30 天聚合**降级**为本维输入;阈值沿用 0.9/0.5) |
| Coverage | 期望的知识都在吗 | `indexed+failed+skipped = expected`;缺口=failed+missing;`EMPTY_EXPECTED/UNEXPECTED` 在此判定 |
| Freshness | 知识跟得上源吗 | last successful index time vs 期望节奏(2× sync_interval 为 STALE 阈,Open Decision 数值) |
| Consistency | 账本和向量库一致吗 | ledger↔vector 校验状态(既有 verify 语义):HEALTHY/GAP/ORPHAN_PENDING |

### 7.2 Overall Health 合成规则(CONTRACT)
1. DISABLED → 显示「已禁用」不评价;
2. 无足够 run 样本 → INSUFFICIENT_DATA;
3. Coverage 判 EMPTY:期望非空且实际 0 → **EMPTY_UNEXPECTED(ACTION_REQUIRED 级)**;期望 EMPTY 且实际 0 → **EMPTY_EXPECTED(HEALTHY 系)**;实际非空但期望 EMPTY → 异常残留 → ACTION_REQUIRED;
4. 存在 INTERRUPTED 未恢复 run → **RECOVERING**;
5. Coverage 缺口 >0 或 Consistency ≠ HEALTHY → **PARTIAL**(附缺口数);
6. Freshness 超 STALE 阈 → **STALE**;
7. Sync 维低分且其余正常 → **DEGRADED**;
8. 存在需人工裁决项(unresolved 孤儿、Needs Review、删除任务失败)→ **ACTION_REQUIRED**(可与上述叠加显示)。

### 7.3 「success + 0 content」终局
- 源配置 EXPECTED=EMPTY(如确无知识价值的仓库)→ EMPTY_EXPECTED,徽章中性;
- EXPECTED=REQUIRED/OPTIONAL 而实际 0 → EMPTY_UNEXPECTED,**从第一轮起即红色**,不存在「永远正常」(直接封杀 Discovery §16 场景)。

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
- 每阶段计数**持久化、可轮询**(P7);阶段边界由工程映射到各 connector 真实步骤(CONTRACT 只冻结逻辑阶段名)。
- `heartbeat_at` 由执行器周期刷新;是 §8.3 中断判定的依据。

### 8.2 阶段语义
| 阶段 | 开始条件 | 计数含义 |
|---|---|---|
| DISCOVER | run 开始 | 枚举到的源条目数(repo 文件/sitemap URL/产品数) |
| SAFETY_FILTER | 枚举完成 | 漏斗逐格计数(§5.5),产出 eligible 与 needs_review |
| FETCH | 准入确定 | 拉取字节数/成功失败(eligible 为分母) |
| PARSE/CHUNK | 逐文件 | 文本化+切块;chunks_total 在首个文件完成 chunk 后逐步可知 |
| EMBED | 首块就绪 | 向量化计数;GPU 压力在此暴露 |
| INDEX | 与 EMBED 并行/随批 | 写入向量库计数 |
| CONSISTENCY | 写入完成 | expected vs actual 对账 + 三分类处置 |
| DONE | 复验收敛 | 终态 delta 与 corpus 快照 |

### 8.3 中断与可恢复(P5,CONTRACT)
- 判定:RUNNING 且 heartbeat 落后 > 阈(如 3× 心跳周期),或执行器启动时发现孤儿 RUNNING → 标 **INTERRUPTED**;
- 标记即持久:该源进入 RECOVERING;**incomplete-run 标志门控 no-change 健康路径**——存在未恢复中断时,「existing>0 → 一致性健康 → success」不得成立,必须走续传/对账;
- 恢复策略(工程 Gate 内定实现,合同只冻结语义):续传 = 以权威成员集对账「已入/未入」,仅补 missing;绝不因中断回滚已安全写入的文档;
- 中断 run 的部分产物是**可信的**(逐文档幂等写入),不因中断而失效。

---

## 9. Progress Semantics(进度语义)

1. **总进度分母** = eligible(文件级),在 SAFETY_FILTER 完成时确定;此前总进度显示「发现中…/评估中…」**不确定态**,不显示百分比(P7)。
2. 分块/嵌入/写库三个子阶段用 **chunks_total** 作分母(已知后显示),与文件级阶段分行显示,不混算。
3. `总进度 = 已完成文件数 / eligible`;子阶段条是细节,不回填总进度。
4. **阶段失败**:该阶段标 FAILED + 失败计数,run 终态 FAILED/PARTIAL;已成功部分保留(幂等),UI 明示「N 篇已完成不受影响」。
5. **部分完成**:eligible - added - skipped - failed = missing,显示为「待续传」;RECOVERING 态由系统续传,非管理员猜。
6. **假进度禁区**:前端不得根据 elapsed 推算百分比;一切计数来自 run 记录轮询。

---

## 10. Failure & Recovery Semantics(失败与恢复)

### 10.1 管理员视图五问(每类失败/异常状态必答)
`WHAT HAPPENED / WHY / IMPACT / WHAT SYSTEM DID / WHAT ADMIN SHOULD DO`

### 10.2 错误分类(CONTRACT,首版)
`AUTH · NETWORK · NOT_FOUND · BINARY_CONTENT · OVERSIZED · PARSE_ERROR · TOKENIZE_ERROR · EMBED_RESOURCE(GPU) · INDEX_WRITE · CONSISTENCY_GAP · ORPHAN_UNRESOLVED · INTERRUPTED · POLICY_EMPTY · UNKNOWN`
每类绑定:默认系统行为 + 是否可自动恢复 + 建议动作。示例:
- EMBED_RESOURCE(GPU OOM 风暴,apic 实证)→ WAITING_FOR_RESOURCES + 退避重试,连续 N 轮后 ACTION_REQUIRED「GPU 资源不足,建议降低并发/稍后重试」;
- BINARY_CONTENT → 逐文件排除计数,**永不**使其 fail 整轮(.hef 事故的第二防线);
- TOKENIZE_ERROR(特殊 token 实证)→ 降级截断处理,计数呈现,不炸整轮。

### 10.3 动作按钮(安全语义冻结后才可出现)
| 动作 | 语义 | 安全边界 |
|---|---|---|
| Retry Failed | 仅重试 failed 文档 | 文档局部,幂等 |
| Resume Sync | 续传 missing(RECOVERING/interrupted 场景) | 以权威成员集对账,不回滚已入 |
| Full Reconcile | 权威枚举 vs 语料全量对账(含退休) | 需发现完整性满足;不完整发现禁退休 |
| Purge & Resync | 清空本源知识后重灌 | 双确认;仅文档局部删除 |
| View Details | 只读深链 | — |
**禁止**「一键修复所有问题」;跨源操作禁止出现在单源面板。

### 10.4 恢复可视化
RECOVERING 态显示:检测到的中断点、已自动补齐计数、剩余估计;恢复收敛 → HEALTHY 并在 Run 历史留痕。

---

## 11. Safe Source Delete(安全删除语义)

三个独立操作,**UI 与权限分离**:

| 操作 | 影响 | 知识 |
|---|---|---|
| Disable Source | 停同步 | **保留**,仍可检索 |
| Remove Configuration | 仅删配置行 | **保留**(标记为 orphaned corpus,列表可见) |
| Delete Indexed Knowledge | 删除知识(可独立执行,或随删配置) | 仅限该源 |

**删除知识的硬边界(P6)**:
1. 范围 = 账本已知文档的确定性 UUID 集(uuid5(source_id, 0..chunk_count-1))∪ **迭代器实扫**到的该源前缀孤儿对象 UUID;
2. 禁止一切 TEXT 属性 equal/like 删除(504 序列中旧 Admin delete 的 equal 原语必须被替换,Discovery §11#1);
3. 删除是**带 run 记录的 Job**:可观察进度、失败保留可重试、完成后自动复验(实际残留=0);
4. UI 文案明确「删除配置 ≠ 删除知识」;删除前展示将删除的文档/chunk 数。

---

## 12. Scheduling / Concurrency Semantics(调度与并发)

- **单源单 run**:同源已有 RUNNING/QUEUED → 重复触发返回「已在进行」或并入 QUEUED(产品默认:去重,提示原 run);
- **手动 vs 定时**:互不抢占;资源不足时新 run 进 WAITING_FOR_RESOURCES,不终止进行中 run;
- **sync_interval 升级为真实语义**:每源节奏独立调度(CONTRACT 确认;现死配置转正);全局默认节奏保留;
- **触发来源可见**:cron/manual/recovery 在 Run 历史必现;
- **无重叠破坏**:并发保护由调度层保证(实现 HOW DEFERRED),产品语义 = 任何时刻同源至多一个活动 run,跨源可并行但受资源闸门;
- 管理员可见状态:QUEUED / RUNNING / WAITING_FOR_RESOURCES / RECOVERING(源行与 Run 详情均显示)。

---

## 13. Runtime Resource Boundary(与系统运行时页的边界)

- 本中心**不成为**服务器监控页;CPU/RAM/磁盘明细属未来「System Runtime & Resource Observability」Gate;
- 接口边界(CONTRACT):Sync Run 记录携带 `resource` 字段(gpu_pressure / waiting_for_resources),数据源页以**徽章**表达「同步受资源影响」:
  - `WAITING_FOR_RESOURCES`(排队等资源)
  - `GPU_MEMORY_PRESSURE`(嵌入降速/退避中,实证:15.6/16.4GiB、95% util 的 T4 共享环境)
- 点开徽章 → 解释文案 + 链接到未来 Runtime 页(先占位)。

---

## 14. Admin Information Architecture(信息架构)

### 14.1 数据源列表(每行)
`源(id+type+product) / 期望态 / 健康(徽章+一句话) / 覆盖(indexed/expected) / 新鲜度(相对时间+✓/!) / 内容(docs·chunks) / 当前活动(run 态或进度摘要) / 行内操作`
信息分层:一眼看「健康+活动」,悬停/进详情看维度;**不再**展示裸 30 天百分比(降级到详情)。

### 14.2 源详情(推荐 5 Tab)
1. **概览**:五维健康卡 + 期望 vs 实际 + 当前活动 + 主行动按钮;
2. **知识覆盖**:expected/actual/skipped/failed 明细、缺失清单、unresolved 孤儿(处置状态)、内容清单(按 Role 标注);
3. **同步记录**:Run 历史(状态/触发/耗时/delta/错误分类),点开单 run 看阶段计数(复活现有死端点 sync-logs 的产品形态);
4. **准入与文件**:准入漏斗 + 文件级 included/excluded+原因+大小+Role(即 Repository Scan 结果的常驻版);
5. **设置**:配置、期望态、策略(file_types/角色)、节奏、危险区(删除三分离)。
(诊断独立 Tab 不设:内容并入概览与同步记录,避免六 Tab 过载。)

### 14.3 活动同步(Active Sync)
列表行内联进度条 + 页首「正在同步」固定卡(多源并行时聚合);**任何活动同步都可在列表页看懂阶段**,不要求进详情或日志(P7)。

### 14.4 失败态
一律落 §10.1 五问结构;禁用裸词 partial/failed/补齐 作为唯一信息。

---

## 15. UX Wireframes(ASCII,确认信息层级/结构/状态/操作/决策路径)

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
 github · main                  GPU资源不足       全部待灌       陈旧               [详情]
neoruntime-sdks          必需   ✓ HEALTHY       107/107     2h前 ✓    107 篇   —
 github · main                  全部正常         完整                            [详情]
sandbox-playground       可选   ○ EMPTY_EXPECTED 0/0         —         0 篇     —
 github · main                  期望为空,正常                                     [详情]
────────────────────────────────────────────────────────────────────────────────
● 运行中 2 · ⏳ 等资源 1 · ⚠ 需处理 2          GPU 压力 ⚠(共享 95%)  [运行时监控(规划中)]
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
  安全过滤  172(排除 22:模型二进制 11 · 超大 3 · 生成物 6 · 低价值 2)
  抓取      96 / 157
  解析      96 / 96
  分块      4,102 / 4,102
  嵌入      2,140 / 4,102  ⚠ GPU 压力(共享 95%)
  写入库    1,908 / 4,102
  一致性    待执行

  变更     +94 新增 · 0 更新 · 0 删除 · 2 跳过 · 2 失败(查看:1 tokenize · 1 空)
```

### 15.4 失败/恢复详情
```
⛔ PARTIAL · 需要处理 — neoruntime (apic)

发生了什么   同步连续 3 轮在嵌入阶段失败
为什么       GPU 显存不足(共享 T4 已用 15.6/16.4 GiB),批量嵌入反复 OOM
影响         1,401 篇合格文档全部未入知识库;相关问答将无法命中本源
系统已做     3 轮退避重试均失败;已标记 WAITING_FOR_RESOURCES 并暂停本轮
建议操作     ① 稍后自动重试(默认,已安排 10:24)
             ② 降低嵌入并发后立即重试
             ③ 查看失败明细(1,400 篇 CUDA OOM)
             [立即重试]  [调整并发重试]  [查看明细]        (无「一键修复」)
```

### 15.5 新建数据源 — Repository Scan
```
新建数据源 · GitHub · camthink-ai/neoruntime-apps @ main          [重新扫描]
────────────────────────────────────────────────────────────────────────────────
发现 194 个文件
 ├─ 🛡 系统安全排除 37(不可加入)
 │    模型/二进制 11(.hef 等,184.8 MB)· 超大 3(>8MB)· 生成物 21 · 无法解码 2
 ├─ 自动分类 157
 │    文档 10 · 源码 96 · 配置 14 · 示例 12 · 构建部署 8 · 测试 17
 └─ 建议纳入 132 / 建议排除 25(测试 17 · 构建 8)

  ☑ 纳入文档/源码/配置/示例(推荐)
  ☐ 纳入测试与构建(默认排除,可勾选)
  🛡 安全排除项为灰色锁定,展开可看文件与原因(不可勾选)
  ⚠ 2 个文件需确认(无扩展名):[查看]

节奏 每日 1 次 ▾   期望状态 必需 ▾
                                     [取消]  [保存并执行首次同步]
说明:首次同步在后台执行,不影响在线服务;进度可在列表实时查看。
```

---

## 16. Golden Failure Scenarios(真实事故 → 设计如何兜住)

| # | 事故(实证) | 旧世界行为 | 新合同下的行为 | 兜底条款 |
|---|---|---|---|---|
| G1 | `.hef` 84MB 二进制入文本管线 → 单核 100%、504、64/169 中断 | preview 全列扩展名全收;无 binary 嗅探;无大小上限;同步在 backend 进程内 | 硬安全层解析前嗅探+类名单+硬尺寸上限 → 11 个 .hef 全部「系统安全排除」;即便漏网,同步在隔离执行器中,在线服务不受影响 | §5.2 / P4 |
| G2 | healthy + content=0(apic 前期/「期望空」不可见) | 30 天成功率 100% = 健康;零合格文件不可见 | Coverage 维:eligible=0 + expected=REQUIRED → EMPTY_UNEXPECTED 红色;漏斗显示「Discovered 1401 → 排除原因」 | §7.2 / §5.5 |
| G3 | 中断首次同步 → existing>0 → 下轮「无变更=健康」→ 105 篇永不补齐 | 无 run 持久化;无中断检测 | INTERRUPTED 标记 + RECOVERING + incomplete 标志门控 no-change 健康路径;续传动作 | §8.3 / P5 |
| G4 | GPU OOM 风暴:apic 1,400 篇全灭(单轮) | 整轮 failed,无资源语义,反复空转 | EMBED_RESOURCE 分类 + WAITING_FOR_RESOURCES + 退避;连续失败升级 ACTION_REQUIRED 附建议 | §10.2 |
| G5 | TEXT equal 删除过匹配(Admin delete 残留 P0 候选) | 跨源误删风险仍在 | Delete Job 仅确定性 UUID/实扫对象 UUID;TEXT 过滤删除被合同禁止 | §11 / P6 |
| G6 | 空/畸形 sitemap 判「完整发现」→ 孤儿批量退休(Discovery §11#2) | complete=True + 空成员集 | Full Reconcile 仅在「发现完整性满足(含 discovered>0)」时允许退休;否则 KEEP+REPORT | §10.3 |
| G7 | 「补齐」一词三义(覆盖缺口/一致性自愈/待裁决) | 管理员无法区分 | 一词退役,拆为 PARTIAL/DEGRADED/ACTION_REQUIRED + 五问结构 | §4.3/§10.1 |

---

## 17. Engineering Gate Decomposition(工程 Gate 分解)

| Gate | 范围 | 依赖 | 可并行 | 预计冲突面 | 验收证据(概要) |
|---|---|---|---|---|---|
| **A — Corpus / Ingestion Safety** | 硬安全层(嗅探/类名单/双尺寸阈/解码质量)+ Knowledge Role 分类骨架 + **两个 P0 删除/退休修复**(Admin delete UUID 化、空发现不得退休) | 无(**阻塞级,先行**) | 否 | connectors/、exclusion、chunk 入口、data_sources.py 删除段 | .hef 树复算:184.8MB 全拦截;真实 Weaviate 删除回归;空 sitemap 演习=KEEP |
| **B — Sync Execution Isolation & Recoverability** | 摄取移出 API 进程;Run 记录持久化(含 heartbeat);INTERRUPTED 检测;incomplete 门控 no-change 健康 | A(run 结构含安全漏斗计数) | 与 C 并行度低(同 sync.py 热区) | scripts/sync.py、data_sources.py 触发端、部署(compose 新服务) | 504 重演测试:全量灌入期间 /health P99 正常;kill 执行器→INTERRUPTED→续传收敛 |
| **C — Health / Expected State** | 期望态字段+迁移;五维健康合成;九态输出;EMPTY 二分 | A;B 的 run 数据(freshness/中断信号) | **与 D 并行**(接口先行冻结) | analytics.py、models(迁移)、admin API | 现网 15 源健康重算报告;apic=ACTION_REQUIRED、空源=EMPTY_*、website=PARTIAL(5 页) |
| **D — Sync Run Observability & Progress** | 阶段计数器落地(漏斗/各阶段);progress API;heartbeat | B(执行器写 run) | **与 C 并行**(消费 B 的 run 表) | sync.py 计数埋点、admin API、(轻)admin | 真实全量 run 的阶段计数与后端日志一致;分母未知期显示正确 |
| **E — Admin Governance UX** | 列表/详情 5 Tab/活动卡/失败五问/Repository Scan 前端 | C+D 数据齐 | 在 C/D 冻结 API 后开工 | admin/src(DataSources 大改) | wireframe 对齐评审;关键态截图;admin 前端测试 |
| **F — Scheduling / Concurrency / Recovery Actions** | sync_interval 真实调度;单源单 run;WAITING_FOR_RESOURCES;Retry/Resume/Purge 动作后端 | B;A(Purge 复用 UUID 删除) | 与 C/D 后期并行 | sync.py 调度层、data_sources.py、compose | 双触发去重测试;跨 cron×manual 并发锁测试;Purge 后残留=0 |
| **G — Corpus Integrity Acceptance** | 全量验收门:15 源五维健康报告 + 检索冒烟 + 事故重演清单(G1-G7)+ ask-ai-eval 回归(需生产授权) | A-F | 最终门 | 只读+评测 | 每场景一条 PASS 证据;语料总量/垃圾 chunk 计数收敛 |

- **顺序**:A → B → (C ∥ D) → E → F → G;F 的「安全删除动作」部分可随 B 提前(纯 A 复用)。
- **SINGLE/PARALLEL 建议**:A 单独先行(P0,改动集中);B 单独(sync.py 热区);C∥D 双窗(API 接口在 B 内先冻结为契约文件);E 单独(前端);F 可并入 B 尾段或独立;G 最终单独。
- **迁移清单(随 C)**:expected_state 字段 + 15 个存量源默认值回填;sync_log→run 表形态(DEFERRED schema)。

---

## 18. Acceptance Criteria(本 Gate)

1. Discovery 与 504 事故证据全部被合同条款吸收(G1-G7 有对应条款);
2. Binary/Artifact 摄取安全以**通用边界**表达(非 .hef 黑名单),含解析前拦截与解码质量防线;
3. 中断可恢复语义完整(INTERRUPTED/RECOVERING/门控假健康);
4. 同步执行隔离为冻结要求,且不指定具体框架;
5. 安全删除三分离 + 文档局部硬边界(禁 TEXT 匹配删除);
6. 健康五维合成 + 期望态四值 + EMPTY 二分;「补齐」退役;
7. 进度 = backend 真值,分母未知显式表达;
8. 失败态五问 + 安全动作集,无一键修复;
9. 代码/配置/文档保持合法知识(非 document-only),源码符号检索保留;
10. 5 张 wireframe 覆盖列表/详情/活动/失败/创建;
11. Gate 分解可独立验收,依赖与冲突面明示;
12. 本 Gate 零生产访问、零实现改动。

---

## 19. Open Product Decisions(仅真正需 PO 拍板)

- **A.〔紧急,运营级〕现存污染数据处置**:`neoruntime-apps-1eea74dd` 现有 62 篇账本 / 39,155 chunks(其中 **38,874 chunks 来自 3 个 .hef 二进制,≈99.3%**,已可被检索命中)。PO 已定「不恢复」,但**清除(purge)≠恢复**。建议:授权一次 Gate A 前置的文档局部清理(62 篇 UUID 点删,禁 TEXT 匹配),预计几分钟完成。不清理则知识库 ~24% chunk 为二进制噪声直至 E/F 上线。
- **B. 期望态默认值与迁移**:15 个存量源默认 REQUIRED?哪些应标 OPTIONAL/EXCLUDED?(建议:除 sandbox/测试源外全 REQUIRED,空源单列)
- **C. Role 默认表确认**(§6):BUILD_DEPLOYMENT/TEST 默认排除、CONFIGURATION 默认纳入(大文件需确认)是否符合产品意图;Role 是否回填存量语料(建议:新 Gate 起仅对新发现文件生效)。
- **D. 尺寸阈值**:建议 max_file_size 默认 **2MB**、硬上限 **8MB**(可配,超硬上限一律排除)——数值请拍板。
- **E. STALE 阈值**:建议 2× sync_interval(如日更源 48h 未成功索引即 STALE)。
- **F. sync_interval 节奏转正后的默认值**:保持 24h?每小时?(现生产实际为每小时 cron;转正后建议默认 24h、可按源覆盖)
- **G. Disable 的知识可见性**:禁用源知识继续可检索(本合同默认)是否符合销售/支持场景预期?
- **H. Needs Review 文件**:创建时是否**阻塞**首次同步(建议:不阻塞,默认不纳入,事后批准入)。

---

## 20. Non-goals(本 Gate 明确不做)

修改 production code / Admin 前端 / DB schema / migration / sync 实现;部署;生产访问;恢复 neoruntime-apps 残缺数据;实现 System Runtime 页;实现 Answer Correctness;运行 ask-ai-eval;选定 worker 框架(Celery/RQ 等 HOW)。

---

## 附:交付信息

- STATUS / REPORT_PATH / REPORT_COMMIT 见最终答复
- 依据:Discovery(245a19b)· 504 事故 triage(本会话实证)· neoruntime 摄取实证(sync_log 9,532+550 runs、.hef 184.8MB、中断 64→62 篇)
- 生产遗留状态快照(截至本报告):backend healthy;/health 与 /admin 200;`neoruntime-apps-1eea74dd` 存在 62 篇/39,155 chunks 污染数据(未清理,见 Open Decision A);旧 `ne503-aipc-apps-20e0886a`/`ne503-apic-69d3594b` 配置仍在(0 内容);无进行中 mutation
