# ISSUE #26–#31 实施执行报告 —— 答案智能共享矫正(证据资格 / 覆盖组合)

- 日期:2026-09-10
- 分支:`fix/26-31-answer-intel-shared`(自 main `03e6c57` 切出)
- 状态:CANDIDATE READY(未合并、未部署,待 Role A 独立评审)
- 验收框架:#32 Benchmark v1(121 冻结案例;种子映射见下);runner 本次入库

## 1. 五个 bug 的架构归因(共享层,证据驱动)

| Issue | 种子案例(冻结契约) | 根因层 | 本次处置 |
| --- | --- | --- | --- |
| #26 未指名在域问题误判 off_topic | `cg-r03`(+基线 sq 族) | INC-3 任务理解(已修:clarification_required 语义 + 「仅缺少产品名称不足以判 off_topic」规则在 _UNDERSTANDING_PROMPT) | **零代码改动** —— 生产事故先于 INC-3;以基线基准验收 |
| #27 能力/导向问题误判 off_topic | `cg-r04` + `cg-s01` | INC-3(已修:capability_orientation 模式 + 导向模板) | **零代码改动** —— 同上,基线验收 |
| #28 Store 变体价格缺失 | `cg-r05`、`sq-026/045/080` | **结构层**:store 证据类被产品资格闸整体排除(生产实证:38 个 commercial chunk 全部不可达;原「store 永不入围」设计针对产品事实冒充,被扩大化为禁止第一方商城证据) | 税务层矫正:store kind 入资格展开(见 §2.1) |
| #29 电池计算器证据缺失 | `cg-r06`、`sq-073` | **结构层**:`/tools/battery-calculator/` 无推导规则 → product=unknown → 资格闸拦截(计算器是跨机型第一方证据) | 推导规则 + tools 共享桶(见 §2.2) |
| #31 方案推荐缺 Solution/Case/Wiki 组合 | `cg-r07`、`cg-r09`、`sq-034/040` | **计划/组合层**:推荐计划无案例槽;SOLUTION 信号词表过窄(英文方案页假阴性);推荐帧指令无跨证据类组合与事实/推荐分层 | 计划槽 + 信号词表 + 帧指令(见 §2.3) |

## 2. 变更清单

### 2.1 #28 — store 证据类入资格展开(单一权威缝)

- `config/product_taxonomy.yaml`:commercial(store)实体补 `applies_to: [全产品线]`;
- `backend/product_taxonomy.py`:`SHARABLE_KINDS` 纳入 `KIND_STORE`,docstring 记录决策依据。
- 传播:资格集合单一权威 → 检索标签闸(hybrid/symbol/bucket)、防御性二次过滤、
  引用资格校验、**比较证据管线 per-target 标签**(此前 store 在比较路径也不可达,
  cg-r05 的问题形态恰是比较式)全部一致受益,零第二真值源。
- 边界不松动:sibling 产品/混合源标签仍不入围(`test_sibling_products_still_excluded`);
  store 仍不可作解析目标(`is_targetable("commercial") is False`)。

### 2.2 #29 — 官方工具页 = tools 共享桶

- `config/product_taxonomy.yaml`:新增 shared 桶 `tools`(applies_to 全产品线);
  website 推导组新增通用规则 `{url_any: ["/tools/"], product: tools}`,
  置于特异性规则 `/tools/ai-tool-stack → aitoolstack` 之后(特异性优先,测试锁定)。

### 2.3 #31 — 推荐计划案例槽 + 信号词表 + 帧指令

- `evidence_planning.py`:recommendation 计划增加 `CASE_EVIDENCE` 可选背景槽
  (SOLUTION_GUIDE required 语义不变;缺失由 coverage 诚实呈现,INC-5);
- `evidence_selection.py`:`_SOLUTION_SIGNALS` 扩充英文/中文强结构信号
  (case study / use case / deployment / 案例),修正英文方案页无法满足
  SOLUTION_GUIDE 槽的系统性假阴性;
- `response_strategy.py`:FRAME_RECOMMENDATION 指令追加「综合多类证据 + 先事实后
  推荐、二者分开表述」—— 与 INC-7 既有 gap_labels 缺口直呈耦合(coverage 真值
  驱动,不新增 LLM 调用,NEW_LLM_CALLS=0)。

### 2.4 #26/#27 — 零改动说明

生产事故样本(2026-09-07)发生在 INC-3 之前;当前 main 的 `_UNDERSTANDING_PROMPT`
已含逐字对应的判定规则与示例(cg-r03/cg-r04 语义)。烟雾测试(cg-r03 经生产
v1.4.0)已返回澄清式回答。验收 = #32 基线种子判分;若判分不达契约再立项。

## 3. 部署效果边界(诚实披露)

- #28:store chunk 生产已在库(commercial 标签),合并后**立即生效**,无需重灌;
- #29:计算器页生产现标 unknown —— 推导规则只影响新灌入;需 website-camthink
  源恢复同步(#45 候选修复 413 后 cron 自然恢复)且页面 lastmod 落入增量窗口,
  或发布门一次性 reindex(生产变更,延至发布授权)。在库 unknown chunk 的
  计算器证据在重灌前不可达 —— 本报告如实声明,不虚判已修。

## 4. 测试

- 新增 `tests/services/test_answer_intel_shared_correctives.py`(8 条):store 入围/
  历史标签/不可作目标/sibling 不松动;calculator→tools/tools 入围/特异性优先/无关页仍 unknown;
- 既有断言更新为新冻结语义(带 #28/#29/#31 注释):`test_product_taxonomy.py`(eligibility/derivation)、
  `test_inc4_evidence_planning.py`(推荐计划含案例槽 ×2)、`test_final_rc_combination.py`(推导一致性)。
- 全量后端:**2198 passed, 8 skipped**(基线 2190 + 新增 8)。

## 5. 候选

- 分支:`fix/26-31-answer-intel-shared` @ <push 后补>
- 变更面:`config/product_taxonomy.yaml`、`backend/product_taxonomy.py`、
  `backend/pipeline/{evidence_planning,evidence_selection,response_strategy}.py`、
  测试 4 文件、本报告;**零新生成 LLM 调用,检索默认参数不变**
- 验收:**基线已测**(docs/evaluation/benchmark_v1/baseline_v1_2026-09-10/,363 runs/0 传输错):
  基线种子 9/21 PASS —— #26(3/3)#27(6/6)证 INC-3 修复成立;#28/#29/#31 全败且
  失败模式(false_absence / no_composition / cg-r07 前检索误路由)与候选设计逐一对位。
  **追加矫正**:依据 cg-r07 判分证据(场景充分却 ~160ms 误路由 clarify),
  `_UNDERSTANDING_PROMPT` 补场景充分性 guard(区域/规模/约束齐备 → standard,
  型号不确定在答案内分述)—— 候选内唯一 #26 邻接改动,判分报告为直接证据。
  回归红线:cg-r03/r04/s01 必须保持 9/9(集成后种子复测核验)。
