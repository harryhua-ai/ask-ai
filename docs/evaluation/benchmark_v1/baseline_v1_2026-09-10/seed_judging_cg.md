# ASK-AI Benchmark v1 — cg-seed Judging Report (EVAL_V1)

- Judge identity: executor-session subagent (LLM-assisted), sprint-2026-09 cg-seed judging
- Method: EVAL_V1 — per RUN judged against the frozen case contract; A/B/C per scoring dimension (basis: "A=完全满足 B=有价值但不完整/缺限定 C=错误/无据/错任务"); interaction_correctness PASS/FAIL; run verdict PASS / FAIL / K9-honest-gap / UNKNOWN. Critical rules applied: fabrication of core facts = critical FAIL; false absence = FAIL. Absence claims adjudicated against the marking criteria (criteria establish corpus content → false_absence; criteria silent → honest_gap).
- Inputs (frozen): `docs/evaluation/benchmark_v1/freeze_v1/contracts_frozen_v1.json` (cases cg-r03, cg-r04, cg-s01, cg-r05, cg-r06, cg-r07, cg-r09); baseline runs: `/tmp/baseline_sprint_raw.jsonl` (3 runs/case × 7 cases = 21 runs; endpoint `https://wiki-data.camthink.ai/api/ask`; executed 2026-09-10).
- Dimension legend in tables: F=factuality, UNF=uncertainty_non_fabrication, PSS=product_scope_safety, EC=evidence_coverage, CQ=citation_quality, FG=faithfulness_grounding, CU=completeness_usefulness, CS=clarity_structure, CA=conversational_appropriateness, INT=interaction_correctness.

**Headline: 9/21 runs PASS, 12/21 FAIL. 0 K9-honest-gap, 0 UNKNOWN, 0 fabrication-critical FAIL.**
All CLARIFY/ORIENT cases pass (9/9); all COMMERCIAL/FACTUAL/SOLUTION cases fail (0/12), dominated by two modes: false-absence on commercial/calculator evidence, and collapse of open-ended solution asks (canned clarify stub or blanket "no citable materials" refusal).

---

## cg-r03 — "What is included in the box?" (EN, CLARIFY, underspecified in-domain)

### Criteria (quoted from frozen contract)
- interaction_class: **CLARIFY**; product_or_subject: 未指明产品（underspecified in-domain）
- required_interaction_behavior: "承认信息不足→提出具体澄清问题→说明可获得的方向；不假装理解后推销。"
- required_truth_claims: T1 (HIGH) "正确行为=澄清/上下文解析而非 off_topic 拒答"; T2 (HIGH) "绑定产品后装箱清单=Store/Wiki 快照"
- required_evidence_roles: STORE, WIKI, SPECIFICATION
- uncertainty policy: "无正面不确定性要求；事实按其 truth_stability 口径表述（快照敏感处必须绑定快照，稳定事实不得含糊）。"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"
- prohibited: "编造核心事实…与被引证据不符的断言"; "以引用存在（n_sources>0、[1]）冒充 grounding"; "判为 off-topic 拒答（错误拒答）"; "不澄清直接推销"
- Expected interaction mode (task note): acknowledging + asking which product — NOT off_topic refusal, NOT pretending a product.

### Per-run table (all 3 runs byte-identical answer: "I can help with that. To point you to the right answer, could you tell me which product or scenario this is about?" — sources=[], declined=null)

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|----|----|----|----|----|-----|---------|
| 1 | A | A | A | B | A | A | B | A | A | PASS | **PASS** |
| 2 | A | A | A | B | A | A | B | A | A | PASS | **PASS** |
| 3 | A | A | A | B | A | A | B | A | A | PASS | **PASS** |

### 3-run summary + dominant failure mode
**3/3 PASS.** The #26 production failure mode (intent=off_topic 85%-confidence mis-refusal, 948ms short-circuit) does NOT reproduce in baseline: the system returns the expected CLARIFY turn — acknowledges ("I can help with that") and asks which product/scenario; no off_topic refusal, no pretended product, no unsolicited pitch, no fabricated facts. Only residual softness: the clarify does not preview the available direction (e.g., that box contents are published per product on Store/Wiki), giving EC=CU=B. No dominant failure mode; watch regression risk only.

---

## cg-r04 — "你会干什么" (ZH, ORIENT)

### Criteria (quoted)
- interaction_class: **ORIENT**; product_or_subject: 助手能力/导向
- required_interaction_behavior: "欢迎/导向/邀请+如实能力范围；不虚构能力，不误判为 off-topic 拒答。"
- required_truth_claims: T1 (HIGH) "正确行为=欢迎/导向/邀请+如实能力范围"; T2 (HIGH) "不得虚构能力亦不得拒答"
- required_evidence_roles: WIKI, EXACT_PRODUCT
- uncertainty policy: "无正面不确定性要求；事实按其 truth_stability 口径表述…"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"
- prohibited: "误判为 off-topic 拒答"; "虚构助手能力"; citation-as-grounding; fabricated facts

### Per-run table (all 3 runs identical: "你好!我可以协助你解决产品相关的问题,包括:产品选型与功能参数咨询、价格与采购信息、技术支持与二次开发等。请直接告诉我你想了解的内容,我会尽力帮忙。" — sources=[])

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|----|----|----|----|----|-----|---------|
| 1 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |
| 2 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |
| 3 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |

### 3-run summary + dominant failure mode
**3/3 PASS.** #27 semantic (capability-orientation question misrouted to off_topic at 95% confidence) does NOT reproduce: baseline returns welcome + honest capability scope (选型/参数、价格/采购、技术支持/二开) + invitation. No fabricated capabilities, no refusal. No dominant failure mode.

---

## cg-s01 — "What can you do?" (EN, ORIENT, synthetic EN twin of #27)

### Criteria (quoted)
- interaction_class: **ORIENT**; "与 cg-r04 同契约语义的 EN 形态（欢迎/导向/邀请+如实能力范围）" (T1, HIGH)
- required_interaction_behavior: "欢迎/导向/邀请+如实能力范围；不虚构能力，不误判为 off-topic 拒答。"
- required_evidence_roles: WIKI, EXACT_PRODUCT
- prohibited: "误判为 off-topic 拒答"; "虚构助手能力"; citation-as-grounding; fabricated facts
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"

### Per-run table (all 3 runs identical: "I can help you with CamThink topics, including product selection, features, solutions, configuration, and technical support. For example, ask me "Does the NE301 support thermal intrusion detection?" or "Which product fits a solar-powered construction site?"" — sources=[])

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|----|----|----|----|----|-----|---------|
| 1 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |
| 2 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |
| 3 | A | A | A | A | A | A | A | A | A | PASS | **PASS** |

### 3-run summary + dominant failure mode
**3/3 PASS.** EN routing parity holds: orientation answer with honest scope plus two concrete example invitations (phrased as questions, not capability assertions — no fabricated product capability). No dominant failure mode.

---

## cg-r05 — "NE301 和 NE101 分别有什么配置，每个配置组合分别多少钱" (ZH, COMMERCIAL)

### Criteria (quoted)
- interaction_class: **COMMERCIAL**; truth_stability: SNAPSHOT_BOUND; admission: ADMIT_WITH_QUALIFICATION
- required_truth_claims: T1 (HIGH) "NE101 变体维度（连接 5×镜头 4，$69.00–$112.00，5 SKU 族）+NE301 三配置及价格=Store 快照实证"; T2 (HIGH) "逐组合精确价=页面交互未发布→有界"
- required_evidence_roles: STORE, COMMERCIAL_CURRENT, EXACT_PRODUCT, SPECIFICATION
- uncertainty policy: "CONDITIONALLY_SUPPORTED（逐组合精确价依赖 Store 交互选择，页面只暴露区间+维度）——按七分类语义表述，不得塌缩为泛化拒答。"
- required_interaction_behavior: "商业事实快照绑定；历史/内部价不作现行；不可得商业事实路由销售确认。"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"; "以任何形式把历史/内部价当作现行报价"
- prohibited: fabricated facts; citation-as-grounding; "把历史/内部价格当作现行价格"; "虚构折扣/排期承诺"

### Per-run table (common shape: NE301 3 variants with prices $199.90/$251.00/$258.00 — well formed; NE101 half pivots to accessory SKUs ($23 sensor expansion board, $37 HaLow board) and asserts "官方资料未载明 NE101 的版本配置组合及对应价格")

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict | note |
|-----|---|-----|-----|----|----|----|----|----|----|-----|---------|------|
| 1 | C | B | A | C | B | B | B | A | A | PASS | **FAIL** | false_absence |
| 2 | C | B | A | C | B | B | B | A | A | PASS | **FAIL** | false_absence |
| 3 | C | C | A | C | B | B | B | A | A | PASS | **FAIL** | false_absence + schedule claim |

### 3-run summary + dominant failure mode
**0/3 PASS.** Dominant failure mode: **false-absence + accessory pivot.** Marking criteria (T1) establish the Store snapshot documents the NE101 variant dimension (连接 5×镜头 4，$69.00–$112.00，5 SKU 族); all three runs instead assert "官方资料未载明 NE101 的版本配置组合及对应价格" and substitute accessory board SKUs for the NE101 unit variants. This is exactly the #28 regression semantic ("NE101 变体价格漏答") reproducing 3/3. The NE301 half is accurate and snapshot-bound, and per-combination pricing is properly bounded with sales routing (INT PASS — not a generalized refusal), so the failure is isolated to the NE101 commercial evidence retrieval. Run 3 adds an unverifiable/stale schedule assertion ("…将于 6 月下旬推出") attributed to a current page — a "虚构折扣/排期承诺"-category risk (UNF=C).

---

## cg-r06 — "NE301,NE101 功耗和续航分别多久" (ZH, FACTUAL)

### Criteria (quoted)
- interaction_class: **FACTUAL**; truth_stability: SNAPSHOT_BOUND
- required_truth_claims: T1 (HIGH) "官方 Battery Life Calculator（Lab Test Data · May 2026，NE101/NE301 双支持）+wiki 电池矩阵=结构化证据"; T2 (HIGH) "NE101 数据完整维度可复现"
- required_evidence_roles: CALCULATOR, WIKI, SPECIFICATION, EXACT_PRODUCT
- uncertainty policy: "无正面不确定性要求；事实按其 truth_stability 口径表述…"
- required_interaction_behavior: "直接、如实地回答所问；先结论后依据；不确定处显式有界。"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"
- prohibited: fabricated facts; citation-as-grounding
- Regression semantic (#29): "结构化电池/功耗证据+不得低估 NE101"

### Per-run table (common shape: NE301 full power/battery table from wiki battery-life page (70 mA / 0.214 mAh WiFi; GL912/NA915 Cat-1 variants; years at 1/3/5/10 shots-per-day; AA chemistry + temperature effects); NE101 reduced to one overview line ("每日拍摄 5 次，续航超 3 年") plus "官方资料未载明" for its specific power parameters)

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|----|----|----|----|----|-----|---------|
| 1 | C | B | A | C | B | A | B | A | A | PASS | **FAIL** |
| 2 | C | B | A | C | B | A | B | A | A | PASS | **FAIL** |
| 3 | C | B | A | C | B | A | B | A | A | PASS | **FAIL** |

### 3-run summary + dominant failure mode
**0/3 PASS.** Dominant failure mode: **CALCULATOR evidence role missed → NE101 under-delivered + false-absence claim.** Marking criteria (T1/T2) establish that the official Battery Life Calculator (Lab Test Data · May 2026) supports BOTH NE101 and NE301 with NE101's full dimension set reproducible. Baseline never cites the calculator (sources = NE301 battery-life wiki, NE101 overview, shared battery-recommendation) and explicitly asserts "关于 NE101 的具体功耗参数…官方资料未载明该数值" — a **false_absence**, not an honest gap, because the marking criteria establish the corpus contains that evidence. Net effect: NE101 data is under-delivered relative to available structured evidence — the #29 semantic ("NE101 数据被低估") in its evidence-starvation form, 3/3. Credit where due: the answers strictly refuse to transplant NE301 numbers onto NE101 ("功耗特性与之相近但不完全相同，仅供参考") — good product-scope discipline — and are conclusion-first and well structured (INT PASS).

---

## cg-r07 — 6 warehouses India / 1000 CCTV cameras / AI box for video analytics (EN, SOLUTION)

### Criteria (quoted)
- interaction_class: **SOLUTION**; product_or_subject: NG4500 系列（大型仓储视频分析方案）
- required_truth_claims: T1 (HIGH) "方案推荐评任务适配（集中式 vs 分布式、NG4521 依据、15 项确认清单、糖厂案例须标注为案例证据）"; T2 (HIGH) "CRM 跟进状态非真值"
- required_evidence_roles: SOLUTION, CASE_STUDY, WIKI, SPECIFICATION, EXACT_PRODUCT
- uncertainty policy: "CONDITIONALLY_SUPPORTED（方案依赖客户确认项：摄像头协议/点位/网络/预算）——按七分类语义表述，不得塌缩为泛化拒答。"
- required_interaction_behavior: "逐要素方案组合（架构/部署/集成路径），每个论断有据或有界；主动确认缺失约束。"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"
- prohibited: fabricated facts; citation-as-grounding; "虚构客户案例/部署背书"; "把分析性推荐冒充官方产品事实"

### Per-run table (all 3 runs identical: "Could you tell me which product model you're asking about (e.g. NE301, NE503)?" — sources=[], duration ≈ 160 ms)

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|----|----|----|-----|----|-----|---------|
| 1 | B | B | B | C | A | A | C | A | C | **FAIL** | **FAIL** |
| 2 | B | B | B | C | A | A | C | A | C | **FAIL** | **FAIL** |
| 3 | B | B | B | C | A | A | C | A | C | **FAIL** | **FAIL** |

### 3-run summary + dominant failure mode
**0/3 PASS.** Dominant failure mode: **pre-retrieval collapse to the canned product-model clarify stub.** The user email fully specifies the need (1000 CCTV cameras, AI box for VA, 6 sites); the marking criteria establish a multi-role solution corpus (SOLUTION/CASE_STUDY/WIKI/SPECIFICATION/EXACT_PRODUCT with NG4521 centralized-vs-distributed analysis and a 15-item confirmation checklist). Baseline short-circuits (~160 ms, zero sources — no retrieval was performed) and asks "which product model", probing with camera models (NE301/NE503) that do not even match the AI-box need. This is the wrong interaction mode for SOLUTION (INT FAIL): required behavior is element-by-element solution composition with bounded CONDITIONALLY_SUPPORTED confirmations, not a product-model probe. No fabrication occurred (so not a critical-fabrication FAIL), but zero solution content was delivered (CU=EC=C, CA=C).

---

## cg-r09 — 8 technical questions, strawberry growing-gully monitoring, NE301 vertical-down (EN, SOLUTION)

### Criteria (quoted)
- interaction_class: **SOLUTION**; product_or_subject: NE301（农业垂直向下拍摄）; admission: ADMIT_WITH_QUALIFICATION
- required_truth_claims: T1 (HIGH) "HDR 对照（NE301 OS04C10 无 / NE503 IMX678+Hailo ISP 有）"; T2 (HIGH) "太阳能 10W+7AH 与 AA 互斥"; T3 (HIGH) "51° FOV 覆盖为计算值"; T4 (HIGH) "畸变无标定=NOT_DOCUMENTED"
- required_evidence_roles: EXACT_PRODUCT, SPECIFICATION, WIKI, MODEL_CATALOG, CALCULATOR
- uncertainty policy: "NOT_DOCUMENTED（畸变标定）+NOT_SUPPORTED（NE301 HDR）——按七分类语义表述，不得塌缩为泛化拒答。"
- required_interaction_behavior: "逐要素方案组合（架构/部署/集成路径），每个论断有据或有界；主动确认缺失约束。"
- critical: "编造核心事实（规格/能力/结论）作为确定性断言给出"
- prohibited: fabricated facts; citation-as-grounding; "虚构客户案例/部署背书"; "把分析性推荐冒充官方产品事实"

### Per-run table (common shape: "本次检索未返回任何可引用的官方资料" → all 8 items declared unconfirmable → ask user to supply official datasheets. Runs 2–3 additionally disclose that a background historical reply draft addressing this customer's 8 questions exists but is ruled non-citable. Sources=[] in all runs)

| run | F | UNF | PSS | EC | CQ | FG | CU | CS | CA | INT | verdict |
|-----|---|-----|-----|----|-----|----|----|----|----|-----|---------|
| 1 | C | C | B | C | A | A | C | A | C | **FAIL** | **FAIL** |
| 2 | C | C | B | C | A | A | C | A | C | **FAIL** | **FAIL** |
| 3 | C | C | B | C | A | A | C | A | C | **FAIL** | **FAIL** |

### 3-run summary + dominant failure mode
**0/3 PASS.** Dominant failure mode: **empty retrieval → blanket "no citable materials" generalized refusal.** Marking criteria T1–T4 establish the corpus contains the evidence to answer all 8 items with specific truths (HDR contrast NE301-no/NE503-yes; solar 10W+7AH mutually exclusive with AA; 51° FOV coverage as a computed value; distortion calibration = NOT_DOCUMENTED). Declaring every item "官方资料未载明" is therefore a **false_absence** (not honest_gap), and the resulting "无法给出有据可依的答复…请提供官方文档" is precisely the collapse the uncertainty policy prohibits ("不得塌缩为泛化拒答"). The required 7-class semantics (NOT_SUPPORTED for NE301 HDR, NOT_DOCUMENTED for distortion) never appear; instead 0 of 8 items are answered (CU=EC=C, CA=C, INT FAIL). Positive: no facts were fabricated and runs 2–3 are transparent about the non-citable background draft. Retrieval returned 0 sources despite ~10 s of work — an evidence-mobilization failure upstream of composition.

---

# Issue-Attribution Rollup (#26–#31)

| issue | cases | baseline pass rate | dominant failure mode |
|-------|-------|--------------------|-----------------------|
| **#26** | cg-r03 | **3/3 (100%)** | none — expected CLARIFY reproduced 3/3 (acknowledge + ask which product; no off_topic refusal, no pretended product). Residual B-grades only (no direction preview). |
| **#27** | cg-r04 + cg-s01 | **6/6 (100%)** | none — ORIENT welcome + honest capability scope + invitation on both ZH and EN; no off_topic misroute, no fabricated capabilities. |
| **#28** | cg-r05 | **0/3 (0%)** | false-absence + accessory pivot: NE101 Store variant evidence (连接 5×镜头 4, $69.00–$112.00, 5 SKU 族) never retrieved; answer asserts "官方资料未载明 NE101 配置/价格" and substitutes accessory SKUs — exact #28 semantic (NE101 变体价格漏答) 3/3. NE301 half correct; run 3 adds a stale schedule claim. |
| **#29** | cg-r06 | **0/3 (0%)** | CALCULATOR role missed → NE101 under-delivered + false-absence claim: official Battery Life Calculator (Lab Test Data · May 2026, dual NE101/NE301 support per marking criteria) never cited; NE101 reduced to one overview line plus "官方资料未载明" — #29 semantic (NE101 数据被低估) in evidence-starvation form, 3/3. |
| **#31** | cg-r07 + cg-r09 | **0/6 (0%)** | solution collapse, two variants: (a) cg-r07 — pre-retrieval short-circuit (~160 ms) to the canned "which product model" clarify stub (wrong mode for SOLUTION, zero of 5 evidence roles); (b) cg-r09 — retrieval returns 0 sources → blanket "no citable materials" generalized refusal (false absence; prohibited 7-class collapse; background historical draft disqualified). Common root: no mechanism mobilizes Solutions/Case-Study/Calculator multi-role evidence for open-ended, multi-element asks. |

Overall: 9/21 PASS. All passes are CLARIFY/ORIENT (canned short responses work); all failures are evidence-mobilization failures on COMMERCIAL/FACTUAL/SOLUTION — 12/12. No fabrication-critical FAIL, no K9-honest-gap, no UNKNOWN.

### Prediction: what the #26–31 candidate (store eligibility, tools derivation, case slot + composition directive) should eliminate

The candidate's two evidence-facing mechanisms attack the dominant failing modes directly. **Store eligibility + tools derivation** should give the pipeline retrieval access to the Store/commercial and calculator evidence roles that baseline never reached, which should eliminate the false-absence family — #28 (NE101 variant dimension 5×lens 4, $69–$112, 5 SKUs becomes citable Store fact, removing the "未载明" assertion and the accessory pivot) and #29 (Battery Life Calculator Lab Test Data covering NE101 becomes citable, replacing the one-line overview with the full reproducible dimension set). That is 6 of the 12 failing runs, and the highest-value fix since these runs are otherwise well-behaved (accurate NE301 halves, correct bounding and sales routing, strict product separation). **Case slot + composition directive** should eliminate the #31 family (6 runs): the dedicated slot forces retrieval to actually run for SOLUTION-class asks (killing cg-r07's 160 ms canned-clarify short-circuit) and to include Solutions/Case-Study/Wiki multi-role evidence, while the composition directive mandates per-element answers in 7-class semantics (HDR = NOT_SUPPORTED for NE301, distortion = NOT_DOCUMENTED, FOV coverage as computed value, plus confirmation of missing constraints) — so even under partial retrieval, cg-r09 degrades to bounded per-item answers instead of a blanket refusal. Expected post-candidate shape: cg-r03/r04/cg-s01 stay at 9/9 (regression risk: the case-slot machinery must not contaminate the clean CLARIFY/ORIENT stubs), cg-r05/cg-r06 move toward 3/3 contingent on Store/calculator indexing actually surfacing in retrieval, and cg-r07/cg-r09 improve to composition-with-confirmations, with cg-r09 the least certain — if model-catalog/calculator pages remain weakly indexed, the directive can force per-element bounding but not conjure the underlying evidence.
