# F-1' 检索/重排矫正执行报告(#28 跟进,2026-09-11)

分支 `fix/26-31-answer-intel-shared` @ `4675fa2`;集成候选
`integration/f1p-answer-intel-20260911`(main d0230f9 + 本谱系,见 §6)。

## 1. RCA(11 阶段逐项实证,只读探针 probe_f1p,数据存 acceptance 目录)

三个失败种子的失败层**不在 reranker 打分**(分数正确且高),而在
**top-k 截断处计划角色无保留权** + **sq-045 类叙事查询的规格证据不入候选池**:

- cg-r05(commercial,[ne301,ne101]):fused 87;重排 319#1(NE101 主品页,
  含 $69 基价+L01GL/HL01 SKU 族)加权 0.7878,距 rank-10 截断线 0.7934
  **差 0.0057 一位于阈上被截**;2092#1/#2(NE301 价格页,0.7537/0.7018)同截;
  幸存者中 6 席为知识案例(不匹配任何计划槽)。required STORE 槽无保留权。
- sq-026(commercial,[ne101]):319#1 幸存(0.9227)但 **319#2(变体表)0.5396
  被截**——同页证据被截断撕裂。
- sq-045(support,查询不含产品名,解析合法返回空):电池 wiki
  (`5-ne301-battery-life`)在混合检索深度 69-96 才出现,**86 条候选池内没有**;
  池内截断下 80 条全部 <0.3。规格证据零。

失败类判定:**角色/多样性保留(截断深度)+ 候选生成(范围)**;明确排除
reranker 打分、融合/校准。

## 2. 矫正(commit `4675fa2`)

- `RerankPipeline.rerank_scored`:超集视图(幸存者 + 全量加权分数表);
  `rerank` 委托至此,既有调用方零行为变更。
- `backend/pipeline/evidence_reservation.py`(新),三规则:
  - **R1** required 槽 × 目标保位:STORE_OFFICIAL 按「标题含产品展示名
    (容忍品牌词复数;配件名领起不算锚定)」判定;无锚定幸存者 → 从既有池
    晋升最优阈上锚定候选;非 STORE 角色退化为「该目标零匹配幸存者」。
  - **R2** 锚定页补全:锚定 store 页已有幸存 chunk(含 R1 刚晋升者)→
    晋升该页一个最优阈上兄弟。
  - **R3** 规格救援:PRODUCT_SPEC 槽零幸存 → 池内阈上直接晋升(R3a);
    否则至多一次补充检索(锚定=幸存案例标题中的唯一产品;聚焦查询=
    `展示名 + 案例标题`;聚焦重排先例=比较管线冻结 RCA),晋升阈上 top-6
    页(每页最优 chunk)(R3b)。
  - 全部:计划驱动、阈值门控、零 LLM、总量有界、fail-open(证据不存在
    即不补位)、比较管线不参与、answer/stream 双路径 parity +
    `evidence_reservation` trace。

**Genericity**:无产品 ID/种子 ID/查询串/URL/期望答案匹配;锚定与聚焦
查询全部由 taxonomy 配置与幸存证据标题派生;测试夹具用自造 stub 非
基准数据。

## 3. 测试

- `tests/pipeline/test_evidence_reservation.py` 13 条(含 fail-open/上限/
  零机械配额/歧义锚定不启用)+ `tests/retrieval/test_rerank.py` parity 2 条。
- 测试 mock 协议升级:`rerank_scored` 孪生(空表=行为中性),13 文件。
- 全量后端(分支树)**2227 绿 / 8 skip / 0 fail**;集成树 **2256 绿**
  (= 2227 + #45 的 12 + #34 的 17,精确对账)。

## 4. 基准与判分(26/26,0 错误;证据 `f1p_seed_subset.jsonl`)

- **红线**:cg-r03/r04/cg-s01 与矫正前**逐字节相同**(6/6)。
- **无回归**:cg-r06/sq-073/sq-080 源集合不变;cg-r09/sq-040/sq-034 新增
  ne301 规格/商店源(R3a 加性、主题一致);**sq-080 维持 PASS×2;
  cg-r07(#31A)维持真实作答;sq-034 判分升级为 PASS×2**。
- **机制因果实证**:cg-r05 两 run 均枚举 NE101 五个连接 SKU 族
  (Standard/L01GL/L02NA/HL00/HL01)——该事实仅存在于 R1 晋升的 319#1;
  访客 sources 出现两页锚定商店页。判分:cg-r05 T1a 由缺转满足。
- **判分汇总**(独立 subagent,冻结契约):sq-026 两 run 达成历史/现行
  口径区分 + TELEC 正确(run1 PARTIAL/run2 一句快照误述判 FAIL);
  cg-r05 FAIL/FAIL(残余见 §5);sq-045 FAIL/FAIL(基线仍引案例);
  **sq-080 PASS/PASS、sq-034 PASS/PASS**。
- **邻近/改写集 B**(非冻结字符串,probe_paraphrase_out.json):商业类
  3/3 权威商店页在上下文(P1/P2 经 R1/R2 触发,P3 自然幸存——机制条件性);
  support 类:P4 spec 槽被 quick-start 结构性满足→R3 不触发(记录为限制),
  P5 走上游产品澄清(非排序层)。

## 5. 残余与 Scope Expansion 候选(不在 F-1' 授权内,未实施)

F-1' 目标(修正「资格语料中已存在的权威证据输掉 top-k/上下文选择」)已
达成并验证;种子完全过约仍被排序层之外的缺口阻断:

1. **语料变体粒度缺口(cg-r05 T1c)**:`$69.00–$112.00` 价带在语料中不存在
   ——319 页仅基础价 $69 + SKU 族名;$112 只在无关页 4307 与一个案例文件。
   Woo 变体价格未入灌入管道 → **需产品/平台决策:store 源契约是否纳入
   变体实体**。
2. **生成层证据权威优先(sq-045 T1)**:wiki 矩阵 chunk 已在上下文(R3b
   实证),模型仍以案例 [1] 背书基线 → **需产品决策:「规格>案例」引用
   优先策略**(响应策略语义)。
3. 快照日期绑定(T2)= INC-2b 系统级缺口,维持原判。
4. 判分勘误(存档):sq-045 的 2.1 年/1.1 年与现行 wiki 矩阵 2.09/1.08
   数值一致,「过期基线」标签属过度引申;实质缺口是授权层级错配。

## 6. 集成候选

`integration/f1p-answer-intel-20260911` @ merge `cf97072` =
origin/main `d0230f9` + `fix/26-31-answer-intel-shared`;merge-tree 预检与
实际合并**零冲突**;ISC-1 双语义保留(#45 counters + #34 传输分类/exit 2
共 14 处标记实证);集成树全量 **2256 绿**。未并 main、未部署,
待独立 Role A 评审。
