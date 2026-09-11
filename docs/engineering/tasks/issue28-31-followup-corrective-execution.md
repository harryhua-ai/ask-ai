# Bug Fix Sprint Follow-up — #28/#31 Corrective + #32 Governance Execution Report

Date: 2026-09-11
Branch: `fix/26-31-answer-intel-shared`(在 9557ce4 之上追加,不重写历史)
Base: sprint 集成后 main = `d0230f9`(=#45 ebc45c2 + #34 8d0350b 的 ISC-1 组合)
Role A 前序裁决:BUG FIX SPRINT CONSOLIDATED REVIEW = PARTIAL
本报告对应增量:`c1ec496`(治理)+ `b057afe`(矫正)+ `f77cb76`(契约落测)+ 本报告

---

## 0. Phase 1 集成账目(#45 + #34,不含 Answer Intelligence)

- `origin/main` ff → `ebc45c2`(#45),随后合并 `8d0350b`(#34)。
- `scripts/sync.py` `_sync_one` except 块为唯一冲突区,按 **ISC-1** 双语义机械保留
  (`docs_failed`/`docs_failed_retryable` 计数 + `transport_failures` 分类与 exit2 有界重试共存;
  413 类 permanent 失败不进入重试,传输类 exit2 落 executor 既有 runner_failed)。
- 双向 diff 证明零语义丢失;集成验证:焦点 17+17 绿、后端全量 2219 绿(仅已知共享库 flake)。
- 集成提交 `d0230f9` 已推送;#45/#34 已 close(证据评论)+ 板 Done。

## 1. Phase 2 — #32 冻结语料治理(commit `c1ec496`)

- cleaned `freeze_v1/` 六文件入库(`git add -f`,docs/ 全忽略不变):
  契约/语料中 17 处客户姓名机械替换(对照表见 freeze_v1/PERSISTENCE.md),
  case_id(121 唯一)/题目语义/判据零变;`anonymization_map_v1.json`(PII 反查表)
  **继续不入库**。
- `PERSISTENCE.md`:pre-scrub hash 账本(基线 manifest 绑定 `5a436f05`/`a1f920c0`)
  ↔ 入库态绑定(`3c935500`/`207f9684`);基线 363 runs 原样保留为不可变证据。
- 治理测试 `tests/benchmark/test_freeze_governance.py`(4 条):白名单集合、
  反查表不入库、无邮箱/姓名 token、runner 默认路径加载 121 cases + 强制种子。
- runner(`scripts/benchmark_v1/run_benchmark.py`)默认语料路径 = 入库文件,已验证。

## 2. Phase 3 — #28 矫正(commit `b057afe`)

### RCA(逐阶段实证,非假设)

以 sq-026/cg-r05 全链路探针(understanding→三路融合→资格→rerank→计划→选择→生成)取证:

| 阶段 | 事实 |
|---|---|
| 检索/资格 | `knowledge-support-cases` 的 TELEC 案例 chunk **已召回**(hybrid 路,fused 1–9 位)且 knowledge 桶对 ne101/ne301 目标本就入围;4 个 Store SKU 页亦在列 |
| rerank | TELEC 案例chunk 重排分 **1.1996 / 0.9982 = 全场第 1、2 名** —— 检索/精排不是瓶颈 |
| 组合/引用 | `_extract_sources` 公开源白名单(PUBLIC_SOURCE_TYPES)把 filesystem 一律排除 → `build_citation_context` 的 LLM 编号集=访客可见集 → **模型根本看不到 TELEC 证据**,答案谎称「官方资料未载明」= false_absence 的直接机制 |
| 变体区间 | Store 商品页 chunk 实含变体族语义(Wi-Fi/LTE Cat.1/HaLow + OV5640 镜头选项,$69 起),非缺失,但被「价格口径不区分」的生成方式稀释(官网标价与历史样品价混述) |

### 矫正(窄口径共享语义,零 benchmark 词硬编码)

1. **第一方知识案例可引用化**(`citation.py`/`rag.py`/`evidence_meta.py`/ingest/migration 双写路径):
   `filesystem + product=knowledge`(且无显式 `internal` 可见性标记)成为**有编号的可引用来源**;
   展示以标题呈现、`url` 置空(不外泄文件系统路径);身份按 `source_id` 匹配;
   非 knowledge 的 filesystem 与显式 internal 仍走背景语义(隐私边界收窄而非取消)。
2. **商务帧指令**(`response_strategy.py`):商业事实逐 SKU/变体列举 + 价格口径
   (官网标价/记录日期)必须注明;未发布的组合价与交期如实有界并路由销售;
   不得虚构搭配、不得折叠变体价格。

### 效果(修正后活体 trace,sq-026/cg-r05/sq-034)

- sq-026:sources = 4×Store SKU + **知识案例[5]**;答案区分「官网标价 $69 vs 记录样品价 $59」
  口径、给出案例记录的交期与(正文后半)TELEC 日期化口径。
- cg-r05:知识案例进入可引用集合;NE301 变体逐项列价。
- 基准终判见 §4(判分为准,不以检索计数替代)。

### 契约修订声明(非静默)

RED-4 原契约「案例证据一律背景、永无公开引用权威」由本矫正**收窄**为
「非 knowledge filesystem 与显式 internal 案例维持背景;第一方知识案例可引用」。
四处既有测试按新契约更新(docstring 注明 #28),并保留反例守护:
`test_rag_filters_all_internal_when_no_public_source`(非 knowledge 仍过滤)。

## 3. Phase 4 — #31 矫正(commit `b057afe`)

### A. cg-r07 前置短路(Role A 实证:14–21ms canned clarify,guard 不可达)

- 机制:cg-r07 题干「the cameras」子串命中 deixis 模式「the camera」→
  `has_device_deixis=True` → 无处解析 → `MODE_AMBIGUOUS` 在 understanding LLM 之前
  直接返回 canned 澄清 —— prompt 级 guard 永不执行。
- 矫正(`product_taxonomy.py`):deixis 匹配分族 —— **ASCII 模式整词边界**
  (`(?<!\w)pattern(?!\w)`),CJK 模式维持子串。「the cameras」(复数/客观描述)
  不再命中;「this device / this camera / which model / 这个设备」等真指代不受影响。
- 保护验证(单元 66 绿):cg-r03 类欠指定查询不走 deixis 路径、仍由 understanding
  判 clarify;off_topic 语义零改动;活体 cg-r07 进入标准作答(见 §4)。

### B. sq-034 组合完整性

- 判分缺口 = T1(yolov8n 指南 + AIToolStack 现存)与 T2(SHA 绑定)。
- 活体证据(修正后):答案正文同时确认两半 —— 「NE301 预装 YOLOv8n(COCO 80 类);
  AI Tool Stack(自部署 Docker,MIT 许可)覆盖采集→标注→训练→量化→部署全流程」,
  并把既有冰箱库存监控指南工作流映射到 OOS/Planogram 等零售要素(逐要素组合,
  事实/边界分层)。AIToolStack 平台证据的检索浮现与知识案例可引用化共同生效。
- T2(SHA 绑定)依赖 evidence_meta 权威/口径物化,属后续迭代(INC-2b 方向),
  本矫正不伪造绑定 —— 最终判分如实反映。

## 4. Phase 6 — 回归与基准(权威判分层)

- 后端全量:**2212 绿 / 8 skip / 0 fail**(含上述契约修订测试)。
- #29 激活契约(离线隔离,commit `b057afe` 行为):独立 class 注入
  battery-calculator(website/tools)+ 电池 wiki(ne301)+ NE101 商品格;
  推导=tools(rule)、tools ∈ eligible_labels(ne301)、检索同时命中 tools+wiki、
  evidence_authority_class=unknown(不得越权)、含 Caveat chunk 可检索 → **PASS**
  (探针脚本 + 输出存 acceptance 目录)。生产激活(re-ingest)按裁决继续冻结至发布门。
- 基准强制种子子集(13 cases × 2 runs = 26 runs,全部成功 0 error,run id
  BF-SPRINT-V1-FU-20260911,endpoint=本地组合树后端,语料=生产只读隧道,
  runner 用入库 cleaned freeze DEFAULT_CORPUS):
  `final_seed_subset.jsonl`(acceptance 目录)。

### 判分结果(LLM-assisted EVAL_V1 为一层;原始 trace 复核为独立一层)

| case | 基线(第一轮评审) | 本次 2 runs | 裁决 |
| --- | --- | --- | --- |
| sq-080(#28 旗舰) | 0 sources(案例不可达) | GPIO3 机制+版本对+症状归一全对,历史框架显式 | **PASS/PASS** |
| sq-034(#31B) | 0/2 FAIL | 组合语义全对(逐产品角色、proven/推荐/不确定区分、可引证逐条对语料核实、零 critical fail);T2 SHA 绑定未做(见残留) | **PARTIAL** |
| cg-r05(#28) | 0/2 FAIL | NE301 半边达标;NE101 变体区间($69–$112/5×4)仍未进上下文 | **FAIL/FAIL** |
| sq-026(#28) | 0/2 FAIL | run1 TELEC 缺定答、区间缺;run2 历史 $59/$109 当现行报出 | **FAIL(PARTIAL+FAIL)** |
| sq-045(#28) | FAIL | 基线值引用了案例文件而非 wiki 矩阵(授权层级错配) | **FAIL/FAIL** |
| cg-r07(#31A) | 14–21ms canned clarify | **37–38s 真实作答**(1000 路规模分析+NG4500 架构推荐),双 run 稳定 | **FIXED(live)** |
| 红线 cg-r03/r04/cg-s01 | PASS | clarify/拒绝文本逐字节稳定,0 sources | **PASS** |
| cg-r06/cg-r09/sq-040/sq-073 | — | 变体/模组全枚举+续航矩阵全值;历史案例有界+缺失资料显式声明 | 正常 |

### 失败种子全链归因(管线级实证,只读探针存 acceptance 目录)

- **语料在库证据**:NE101 Store 页 `woocommerce-mall/319`(4 chunks,含
  $69/$112)在生产语料**在库**(GraphQL 实证);电池 wiki 矩阵
  `github/5-ne301-battery-life`(wiki.camthink.ai)在库(cg-r06 双 run 引用即证)。
- 因此 cg-r05/sq-026/sq-045 的剩余失败全部落在**检索/rerank 排序层**
  (top-k=10 竞争下 NE101 商品格与 wiki 规格页未进上下文),不是资格闸、
  不是语料缺失——与第一轮评审 F-1 的预判一致。
- sq-045 判分勘误(原始 trace 复核):答案中 2.1 年/1.1 年与现行 wiki 矩阵
  2.09/1.08 数值一致,**不构成"过期事实当现行"的实质性现势错误**;真实缺口
  是授权层级错配(案例文件背书规格事实而非 wiki 权威)+ 舍入口径。判分层
  "critical fail" 标签属过度引申,以原始 trace 复核为准。

### #28/#31 裁决(按 dispatch 标准:强制种子须过冻结契约,而非仅改进)

- **#28 = PARTIAL**:sq-080 FAIL→**PASS**(资格闸矫正的直接实证),sq-026/
  cg-r05 商业事实语义与可引性已通,但 3/4 强制种子仍在排序层未达标——
  不满足 FINAL PASS 条件。
- **#31 = PARTIAL**:A 侧(cg-r07 deixis)**已修复并 live 验证**(F-2 关闭);
  B 侧组合语义判分零 critical fail 且引用逐条对语料核实通过;T2 快照绑定
  属系统级缺口(INC-2b),不在本窄口径矫正内。

## 5. 残留与边界

- **排序层(首要后续)**:NE101 商品格/wiki 规格页在混合查询下进不了
  top-k —— 需检索深度/配额或 rerank 混合策略的独立矫正(非窄语义改动,
  超出本授权,列为 F-1' 跟进);矫正后重判 cg-r05/sq-026/sq-045。
- T2(SHA/快照绑定的机器可验物化)未实现 —— 依赖 INC-2b 权威类物化,不伪造。
- sq-026 run2 显示历史商业条款有被当作现行报出的模型方差(指令已含口径
  要求,run1 合规)——发布门回归需多 run 观察该方差。
- 生产端到端(#29 激活、website-camthink re-ingest)等待发布门授权;本候选
  未合并、未部署。
