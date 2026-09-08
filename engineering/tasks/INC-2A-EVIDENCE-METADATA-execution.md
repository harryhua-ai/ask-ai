# INC-2A 证据语义元数据 + 确定性回填 — 执行报告

- 契约:INC-2a Frozen Implementation Contract(Evidence Metadata Schema + Deterministic Backfill)
- 基线核验:BASELINE_COMMIT = **a44c61c** 存在 ✓,含 INC-1 全部产物(telemetry.py / lineage 测试)✓;从其建立隔离分支,无差异需上报
- 实现分支:ask-ai 主仓 `task/inc2a-evidence-metadata`(已推 origin)
- 自评:**CANDIDATE READY**(待 Agent A 独立审查终验)

---

## 1. STATUS / 提交

- STATUS = **CANDIDATE READY**
- BASELINE_COMMIT = `a44c61c`
- FINAL_COMMIT = `cdbb234`(实现+测试单提交,追加于分支,未合并未部署)

## 2. CHANGED_FILES

| 文件 | 变更 |
|---|---|
| `backend/evidence_meta.py`(新) | 冻结词表 + EvidenceMeta + `derive_evidence_meta` 纯函数 + 5 个 property 名常量 + 溯源码 |
| `backend/pipeline/ingest.py` | `COLLECTION_PROPERTIES` 单一定义点(建表含证据 schema);`_evidence_props` + `_build_props` 增 5 键;`getattr` 防御读取 |
| `backend/retrieval/search.py` | SearchResult 增 5 字段(缺省显式 unknown);search_symbols/search_bucket 投影白名单补齐;`_EVIDENCE_READ_DEFAULTS` 缺省读;`_to_search_result` 映射 |
| `scripts/migrate_add_evidence_meta_props.py`(新) | 幂等增量加 5 个 Weaviate property(add_property,不删数据) |
| `scripts/migrate_backfill_evidence_meta.py`(新) | 确定性回填:纯核心 `plan_backfill`/`plan_object`/`apply_changes`(可测)+ dry-run/--apply + 孤儿只上报 |
| 测试 ×4(新) | tests/test_evidence_meta.py、tests/pipeline/test_evidence_ingest_propagation.py、tests/retrieval/test_search_evidence_propagation.py、tests/scripts/test_migrate_backfill_evidence_meta.py |

## 3. SEMANTIC_MODEL

四个语义维度 + 显式 unknown 安全域(词表 = 目标架构 §6 + 契约 §3):

| 维度 | 词表 |
|---|---|
| authority_class | authoritative-doc / official-pricing / case-example / community / marketing / **unknown** |
| temporality | current / historical-as-of / undated / **unknown** |
| sensitivity | public / internal / personal-data / user-provided / **unknown** |
| citation_eligibility | citable-numbered / background-declared / context-only / **unknown** |

溯源(契约 §7):`evidence_origin` 4 字符定长码,位置固定 A/T/S/C,字符 E(EXPLICIT,源显式配置标记)/ D(DERIVED,系统映射)/ U(UNKNOWN)。无逐 chunk 解释文本。

存储:5 个 TEXT property(`evidence_authority_class/evidence_temporality/evidence_sensitivity/evidence_citation_eligibility/evidence_origin`)随 chunk 持久化于 Weaviate `Document` collection;PG 无新表(data_sources.config 原样承载 visibility,无第二事实源)。

## 4. DETERMINISTIC_MAPPING(全部源自既有系统语义)

| 输入(仅 chunk 自身持久化事实) | authority | sensitivity | citation | origin(A/T/S/C) |
|---|---|---|---|---|
| source_type=filesystem | case-example | internal | background-declared | DUDD |
| source_type=woocommerce | official-pricing | public | citable-numbered | DUDD |
| github/website/web_crawl/local_git | **unknown**(不推断 stronger class) | public | citable-numbered | UUDD |
| 任意源 + config `channel_visibility:["internal"]` 标记 | 不变 | **internal(EXPLICIT,E)** | background-declared | s 位=E |
| 未知类型 | unknown | unknown | unknown | UUUU |
| temporality | **恒 unknown** | — | — | t 位=U |

判定依据:filesystem=系统内即内部支持案例库(架构 case-example 类);woocommerce=官方商城目录(价格账本);github/website 等不唯一蕴含单一权威类(契约 §5 明示);`internal` 标记为既有显式源配置惯例(migrate_channel_visibility 契约);citation 映射=既有组合白名单(PUBLIC_SOURCE_TYPES)/背景通道语义的元数据化。

UNKNOWN_POLICY:无安全规则可判 ⇒ unknown;personal-data/user-provided **永不**由规则赋值(内容审查属 INC-2b);摄取/同步时间戳一律不作 source-valid 日期 ⇒ temporality 恒 unknown;测试断言全规则空间(7 源类型 × 5 visibility)词表封闭 + personal-data 零赋值。

## 5. STORAGE_AND_PROPAGATION

摄取:`_build_props`(三条写路径共用)调 `derive_evidence_meta(doc.source_type, doc.channel_visibility)`;检索:主 hybrid 路径全量返回天然携带;search_symbols/search_bucket 两条显式白名单已补 `*EVIDENCE_PROPERTIES`;`_to_search_result` 缺省读(存量缺失 ⇒ 显式 unknown/空 origin);SearchResult 增 5 字段(带默认,全部既有构造零回归)。**应答关键路径零新 DB join、零新 LLM 调用、零源网络调用、零文本解析**(契约 §14)——语义在写入期烘焙进索引对象。

## 6. BACKFILL_IMPLEMENTATION + DRY_RUN_EVIDENCE(本地非生产实证,§16 授权)

`scripts/migrate_backfill_evidence_meta.py`:全量只读迭代 → 逐对象用其自身 source_type/channel_visibility 规划 → 与存量证据值比较 → update 式写(仅 5 属性)。计数器:total_inspected/eligible/changed/unchanged/unknown_unclassifiable/orphans/failures + 语义分布 + 按源分布。

本地 weaviate(localhost:8080,非生产)实测:

```
1. migrate_add_evidence_meta_props: 新增 5 property(HTTP 200,幂等跳过复验)
2. DRY-RUN:  total_inspected=70575 eligible=70575 orphan=0 changed=70575 unchanged=0
   authority {unknown:67824, case-example:2751}
   sensitivity {public:67823, internal:2751, unknown:1}
   citation {citable-numbered:67823, background-declared:2751, unknown:1}
   unknown_unclassifiable=1 failures=0;未写任何对象
3. APPLY:    写入 70575/70575(91s 墙钟,单进程顺序 update)
4. 幂等复跑: changed=0 unchanged=70575 failures=0
5. 抽查:     证据字段在位;text 未动;按 uuid 取回 vector present dim=1024(向量存活)
```

附注:DB 不可用时孤儿判定降级跳过(设计);修复过程中发现并修复 `asyncio.get_event_loop` 无运行 loop 报错(改 `asyncio.run`)。本地库观察(非本任务域):ne101 源含二进制文件(.EXE)文本化 chunk,分类为 public/github 系规则如实输出,语料质量归 ingestion 治理。

## 7. VECTOR_TEXT_PRESERVATION

回填写入路径 `col.data.update(uuid=..., properties=evidence_5)` 只传证据属性;不传 vector、不改 text(单元测试断言写集键集 == 5 证据属性,无 text/vector);确定性 uuid(`uuid5(source_id#chunk_index)`)不参与变更;本地实证 7 万对象应用后向量 dim=1024 存活。

## 8. TESTS(命令+结果)

```
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests/test_evidence_meta.py \
  tests/pipeline/test_evidence_ingest_propagation.py \
  tests/retrieval/test_search_evidence_propagation.py \
  tests/scripts/test_migrate_backfill_evidence_meta.py -q
  → 31 passed

HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests/pipeline tests/retrieval tests/llm \
  tests/connectors tests/scripts -q
  → 974 passed, 3 skipped

HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests -q --ignore=tests/e2e
  → 1773 passed, 4 skipped, 0 failed(46.7s;基线 1743/3 → +31 新测,+1 skip 为
    tests/api/admin/test_sync_trigger_isolation.py 既有共享库环境态,非本次改动)
```

测试覆盖对照 §15:词表/UNKNOWN/缺失兼容 ✓;同输入同输出 + 歧义→unknown(表驱动 10 例 + 全空间封闭)✓;新摄取带元数据(端到端 insert_many 捕获)✓;三路检索投影传播(主 hybrid/符号/桶)+ 存量缺读 ✓;回填 dry-run 零 mutation(规划纯度断言)/首刷变更/二刷零变更/uuid 向量保持/写集有界/孤儿上报 ✓;行为保持(全量回归)✓。

## 9. ACCEPTANCE

- A1 ✓ 词表+unknown 安全域(evidence_meta.py,封闭性测试)
- A2 ✓ 仅授权持久化输入(source_type+channel_visibility;规则表可审计)
- A3 ✓ 新摄取写入(端到端测试)
- A4 ✓ chunk 携带元数据,零文本/向量变更(写集有界测试+本地实证向量存活)
- A5 ✓ 全部活跃检索路径传播(主/符号/桶三路测试)
- A6 ✓ 存量知识确定性回填(本地 70575 实证;无源抓取/重切/重嵌入)
- A7 ✓ 幂等+dry-run(本地复跑 changed=0;规划纯度测试)
- A8 ✓ 歧义显式 unknown(personal-data 永不赋值测试;unknown_unclassifiable 计数)
- A9 ✓ 零新 LLM/源网络/应答路径强制 PG join(写入期烘焙;derive 1.89μs 仅摄取期)
- A10 ✓ 应答行为不变(全量回归 1773 绿;新元数据不进任何运行期决策)
- A11 ✓ 相关测试+全量离线通过
- A12 ✓ 生产零触碰(所有实证仅本地 weaviate)

## 10. PERFORMANCE_IMPACT

- 应答路径:0 新增调用/解析;证据属性随既有 props 返回(主路径全量返回,符号/桶路径白名单 +5 个字符串字段的拷贝开销,ns 级)。
- `derive_evidence_meta`:1.89 μs/次(仅摄取每 doc 一次 + 回填)。
- 全量套件:46.7s vs 基线 46.05s(+31 测试);无"零开销"声明,以上为实测。
- 回填吞吐:本地 70575 对象 91s(单进程顺序,可分批/--source 限源)。

## 11. PRODUCTION_MUTATION = NO / BENCHMARK_MUTATION = NO

生产 DB/Weaviate/部署零触碰;Benchmark v1 产物未动;本地(非生产)weaviate 迁移+回填为 §16 授权内的 local/test 操作。

## 12. SCOPE_DEVIATIONS = NONE

未实现 INC-2b 脱敏/INC-3~INC-7 任何行为;新元数据未接入任何过滤/排序/剪枝/组合/引用/策略决策(§11 冻结)。

## 13. AMENDMENT = INC-2A-CLASSIFICATION-SAFETY-01(A 审查 PARTIAL → 窄化修订,已实施)

**OLD(已被撤销的映射)**:
- sensitivity:`source_type ∈ PUBLIC_SOURCE_TYPES` → public(DERIVED);filesystem → internal(DERIVED)
- authority:filesystem → case-example;woocommerce → official-pricing

**NEW(修订后)**:
- sensitivity:**唯一判定 = 显式 `internal` 标记** → internal(EXPLICIT,溯源 s 位=E);其余一律 unknown——`PUBLIC_SOURCE_TYPES`(引用/组合语义)与 `channel_visibility`(请求渠道语义)均非敏感度证明,missing internal ≠ public
- authority:**全量 unknown**——组合期证据只证明 filesystem 的 internal/background 处置,不证明案例语义;woocommerce 无法对**每个** chunk 建立定价证据保证(连接器含商品描述等非定价正文),按修订令"不能保证 ⇒ unknown"撤除
- citation_eligibility:严格镜像既有组合语义且独立于 sensitivity——`build_citation_context` 既有行为即 source_type ∈ PUBLIC 白名单 → citable-numbered、其余 → background-declared(仓库证据证明等价;映射不再引用 visibility 标记)
- 回填 unknown_unclassifiable 判据:authority+sensitivity 双 unknown(citation 镜像恒有值)
- temporality:不变(恒 unknown)

**REASON** = Frozen Contract 要求 unknown-safe 语义,禁止从非等价结构范畴推导 sensitivity/authority(渠道可见性≠敏感度;引用资格≠敏感度;源类型≠权威类;缺失标记≠public)。

**UNCHANGED CONTRACT SURFACES** = 五个元数据 property/EvidenceMeta 结构/evidence_origin 概念/摄取传播/Weaviate 增量 schema/SearchResult 传播/检索投影/回填 dry-run-apply-幂等架构/稳定 chunk uuid/向量与正文保全/零新 LLM 调用/零应答行为变更/零生产触碰/INC-2b 边界/INC-3+ 范围——全部未动。

**FINAL_COMMIT** = `48b9480`(追加提交于 task/inc2a-evidence-metadata,已推 origin;前序 cdbb234 未改写)

**TESTS** = 分类表 11 例按新映射重写 + 修订令 10 项逐项证明测试(公开类型无标记→unknown×4 / internal→internal+E / 全空间缺标记绝不 public / filesystem≠case-example / authority 歧义恒 unknown / citation 与 sensitivity 独立 / 确定性 / 摄取回填同函数零漂移);本地 70k 回填**未重跑**(修订令:非必要不重跑;本地库现持 v1 分类值,生产/本地重放须按新分类器再授权执行);`1773+48=1821 passed / 3 skipped / 0 failed`(48.9s)。

**PRODUCTION_MUTATION** = NO

## 14. OPEN_RISKS(修订后)

1. **R1 标注粒度**:修订后 authority 对全部源类型恒 unknown、sensitivity 仅 internal 标记可判——任何正面分类(如 authoritative-doc)需未来的显式 config 通道(EXPLICIT 溯源 E 码已预留,config→chunk 传递属后续小增量)。本地 weaviate 现持 v1 分类值(修订令禁止非必要重跑),本地/生产重放按新分类器执行时将整批改写(幂等架构不变)。
2. **R2 生产回填规模**:生产索引体量 > 本地 7 万;回填工具支持 --source 分批 + 幂等重入,生产执行需单独授权与批次计划。
3. **R3 存量缺失语义依赖消费端守约**:回填前读取 evidence_* 一律得 unknown(读取缺省已实现并有测试);后续 S5/S6 若忽略 unknown 语义将构成越权使用(契约 §11 由后续增量自身的审查把关)。
4. **R4 共享测试库环境**:全量套件中 1 个既有 skip(test_sync_trigger_isolation)因共享库状态波动,与本次改动无关(迁移前基线亦波动)。
