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
- 基准强制种子子集(13 cases × 2 runs,run id BF-SPRINT-V1-FU-20260911,
  endpoint=本地组合树后端,语料=入库 cleaned freeze):
  结果与 LLM-assisted 判分 + 原始 trace 三层证据见 acceptance 目录
  `final_seed_subset.jsonl` 与判分记录;**以冻结契约为准的逐 run 判分**是
  #28/#31 是否 FINAL PASS 的唯一裁决层。

## 5. 残留与边界

- T2(SHA/快照绑定的机器可验物化)未实现 —— 依赖 INC-2b 权威类物化,不伪造。
- sq-045/sq-080 的 TROUBLESHOOT 循环完整性缺口(纠正/验证步骤)不在本矫正范围
  (Role A 判分已列为独立质量缺口)。
- 生产端到端(#29 激活、website-camthink re-ingest)等待发布门授权;本候选未合并、未部署。
