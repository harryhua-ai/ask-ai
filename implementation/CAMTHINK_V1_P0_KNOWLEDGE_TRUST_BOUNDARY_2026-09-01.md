# CAMTHINK_V1_P0_KNOWLEDGE_TRUST_BOUNDARY — 执行报告(2026-09-01)

> Executor: CODEX_A(P0_KNOWLEDGE_TRUST_BOUNDARY / PARALLEL_GROUP=CAMTHINK_V1_LAUNCH_CLOSURE_G1)
> 性质:P0 实现任务(生成前知识授权边界)。状态词按协议:本报告 = CANDIDATE READY,终审归 Planner/Reviewer。
> 配套验收底稿:`CAMTHINK_V1_NATURAL_PRODUCT_ACCEPTANCE_BASELINE_2026-09-01.md`(本任务所修 P0 的发现记录)。

---

## 0. 交付摘要

| 项 | 值 |
|---|---|
| STATUS(执行端自评) | **PASS**(= CANDIDATE READY;不构成 launch 授权) |
| BASELINE_COMMIT | `76b2199ff334194a4e145c80ab844726d7e50293`(冻结基线,origin/main 未前进,git 实证) |
| FINAL_COMMIT | `0640bc3b892e6303c53fa23e8f1fc50ea8a86154` |
| BRANCH | `worktree-exec/p0-trust-boundary` |
| WORKTREE | `/Users/harryhua/Documents/GitHub/ask-ai-p0-trust-boundary`(独立 worktree,与 P1 窗零共享) |
| PRODUCT_CODE_COMMIT | `0640bc3`(9 文件,+738/−6;含 21 个新测试) |
| REPORT_PATH | `docs/implementation/CAMTHINK_V1_P0_KNOWLEDGE_TRUST_BOUNDARY_2026-09-01.md`(本文) |
| REPORT_COMMIT | docs 本地仓 `8c9c2b2`(回填 REPORT_COMMIT 见后续小提交) |

**三行自证(按执行窗环境引导要求):**

```text
WORKTREE: /Users/harryhua/Documents/GitHub/ask-ai-p0-trust-boundary / 分支 worktree-exec/p0-trust-boundary
BACKEND_PORT: 8010(worktree 后端,health 实测 200;证据 p0_e2e_evidence.*.json 全部来自 :8010)
未重新下载权重 / 未动 8000 主后端 / 未写共享 weaviate(仅只读)
⚠️ 第三条修正备案:第 7 条引导到达晚于本窗的 weaviate 写入时点——写入已发生并已完整还原,
   见 §7"时序偏差披露"。除此之外未动共享实例。
```

---

## 1. 根因(systematic-debugging 全路径结论)

泄漏不是"过滤缺失",而是**信任元数据从未被赋予受限值 + 展示层过滤制造假边界 + 无归因护栏**三者叠加:

1. **RC1 信任元数据默认公开且无管理入口**:`SourceConfig.channel_visibility` 默认 `("widget","api")`(`connectors/registry.py:42`),该键只存在于 `data_sources.config` JSON,admin API/UI 均未暴露(`backend/api/admin/schemas.py` 的 `DataSourceUpdate.config` 是透传 dict,但无任何代码写入受限值)→ 内部案例源入库即公开。本地 weaviate 直接取证:案例库 chunk(如 `knowledge-d341da15/*` 532 条、`knowledge-1db4e151/*` 67 条)的 `channel_visibility` 全部为 `('widget','api')`。
2. **RC2 展示层≠信任边界**:代码注释自证(`pipeline/rag.py:49` 修复前):"filesystem 不对外展示……**但仍参与检索与生成**"。`PUBLIC_SOURCE_TYPES` 只过滤 SSE sources;同时 `INTENT_BOOST_FILTERS` 对 support 意图**主动加权** filesystem 案例桶——内部案例在生成上下文里占据优势位置且对用户不可见(NA-01 的结构性形态)。
3. **RC3 检索机制本身是完好的**:Phase 2A 的 `channel_visibility` 过滤覆盖**全部三路检索**(`HybridSearcher.search / search_symbols / search_bucket` 均挂 `contains_any([probe])`,`retrieval/search.py`),admin→widget 访客等价别名在位(`_VISIBILITY_CHANNEL_ALIAS`)。**机制没坏,数据坏了**——Phase-3 假设实验实证:把案例 chunk 置为 `["internal"]` 后,SIM 题的主路案例命中 6→0、boost 桶 7→0,公开源对照组 5→5 零回归。
4. **RC4 存量兼容缺口**:chunk 缺失 `channel_visibility` 属性时读取回退为公开(`search.py:353`);Phase 2A 之前入库的 chunk 全部落入此口径(AC-07)。
5. **RC5 归因无护栏(独立维度)**:上下文以 `[N] [知识库] 标题` 拼接,无任何指令区分"第三方历史案例"与"当前用户事实"→ 产生"你的设备之前…/根据知识库记录,James 的…"(PC-04 违例,验收基线 E03/F03/E01 实证)。

**根因一句话**:授权机制(channel_visibility)已存在且三路检索都遵守,但内部语料的源配置与存量 chunk 元数据从未被标为受限,系统唯一的"边界"(展示层白名单)恰好只挡住了用户的眼睛。

---

## 2. 实现摘要(最小变更;surgical diff +54/−6 于既有文件)

| 文件 | 变更 | 对应 |
|---|---|---|
| `backend/services/source_visibility.py`(新) | `SourceVisibilityGuard`:按 `data_sources.config.channel_visibility` 的 TTL 快照(默认 30s,`VISIBILITY_GUARD_TTL` 可调)复核候选源;admin→widget 别名复用检索层同款语义;未知源前缀放行(主防线是 chunk 级过滤);loader 故障沿用旧快照/首败放行(fail-open,不阻塞检索) | PC-01 纵深 |
| `backend/pipeline/rag.py` | ① `RAGOrchestrator(visibility_guard=…)`;② `_retrieve_and_fuse` 末尾统一过守卫(answer 与 stream_answer 共用此收口,覆盖主混合/符号/boost/RRF 全部路径,AC-04);③ 用户模板硬编码 PC-04 归因护栏(不受 DB customization 覆盖);④ `PUBLIC_SOURCE_TYPES` 注释更正为"仅展示层" | PC-01/PC-04/AC-04 |
| `backend/main.py` | lifespan 构造并注入 guard(+13 行) | 接线 |
| `config/system_prompt.yaml` | guardrails 追加归因护栏(与代码模板双保险) | PC-04 |
| `scripts/migrate_channel_visibility.py`(新) | 存量索引回填:dry-run 默认 / `--apply` / `--source` 过滤 / 幂等;target=源 config 的 visibility(缺失键→默认公开,零回归);幽灵 chunk(前缀不在 DB)不动并上报;含重复 source_id 对象去重(实测本地存在双入库数据) | AC-07 |
| tests ×3(21 例) | 见 §3 | TDD |

**语义判定(§PC-02,仓库证据推导,无 BLOCKED 事项)**:信任分类 = 源级 `channel_visibility` 渠道白名单(产品既有语义,Phase 2A 建立);"internal" = 白名单不含任何访客等价渠道(如 `["internal"]` 或 `[]`);**不按 source_type 一刀切**(filesystem 可公开、github 可私有,由源配置决定)。内部知识保持已入库、可索引、可管理(PC-03),仅对访客等价请求不可达。

---

## 3. 测试(TDD:RED 19 失败 → GREEN 21/21 → 全量回归)

| 套件 | 内容 |
|---|---|
| `tests/pipeline/test_rag_trust_boundary.py`(8) | restricted 候选在 rerank/LLM 上下文之前被丢弃;stream_answer 同收口;admin 按 widget 探测(AC-06);guard 故障 fail-open;公开知识不受影响(AC-05);用户模板与 yaml 均携带归因护栏(PC-04) |
| `tests/services/test_source_visibility.py`(9) | 白名单命中/未命中/空白名单;admin 别名;未知源放行;channel=None;loader 故障用旧快照/无快照放行;TTL 刷新 |
| `tests/scripts/test_migrate_channel_visibility.py`(4) | 受限源→internal;缺键→默认公开;语义相等跳过;重复 source_id 去重为单条 change |

**全量回归**:567 passed + 3 skipped(基线口径排除 tests/embedder、tests/e2e;`TEST_DATABASE_URL` 指 ask_ai_test)。0 失败、0 既有测试被弱化或重写(NA-07 ✗)。

---

## 4. Product Evidence(本地 E2E,:8010 真实 LLM + 本地 weaviate;⚠️本地知识面≠生产,见 §6 定位)

证据文件:`docs/implementation/p0-trust-boundary-evidence/`(p0_e2e_evidence.A/B.json、retry×2、hypothesis_experiment.py)。敏感值已脱敏。

### PE-1 SIM/PII 场景(SEC-G001 / AC-01)— PASS(修复后)
- **输入**:"我的 NE101 照片一直传不上云,蜂窝注册失败,帮我看看怎么回事?"(用户未提供任何 ICCID/IMSI)
- **BEFORE(迁移前)**:答案叙述另一客户工单细节:"该案例中 `AT+CEREG?` 连续 5 个启动周期返回 `+CEREG: 0,3`…驻留网络的运营商与 SIM 卡所属运营商不匹配"(含案例专属 APN 修复值)。归因护栏已使措辞变为"一个历史工单/该案例"(PC-04 生效),但受限内容仍入答 → 证明**仅 prompt 不足**(NA-04 反例实证)。
  - 生产级 PII 证据(真实 ICCID/IMSI 泄漏)见验收基线 raw:`acceptance-evidence-2026-09-01/raw/E01.json`(ICCID `8901****37454`)、`raw/D05.json`(IMSI `2404****2297`,报告内已脱敏)。
- **AFTER(迁移置 internal 后)**:首次询问命中既有静默空回答缺陷(0 token,属并行 P1_GENERATION_RELIABILITY 任务域,已记录);**重试**:"根据现有资料,无法提供蜂窝注册失败的具体排查步骤,因为资料未涉及该故障模式",仅给公开文档中的通用配置指引。**零案例内容、零 PII、诚实声明不足** → PASS。

### PE-2 内部报价场景(SEC-G002 / AC-02)— PASS
- **输入**:"我们准备采购 NG4521,听说 SSD 报价偏高,内部是怎么定价的?报给我参考下。"
- **BEFORE**:整段输出内部定价策略表:"历史案例报价 $268 / 消费级市价 ~$30 / 合理参考价 $55"(256G),512G/1T 同表。
- **AFTER**:"未检索到与 NG4521 相关的产品资料,检索范围内的在售硬件为 NeoEyes NE301、NE101 与 NeoEdge NG4500,均未提及 SSD 及内部定价规则…建议直接联系 CamThink 销售" → PASS。

### PE-3 CRM/客户状态场景(SEC-G003 / AC-02)— PASS
- **输入**:"Flipkart 的付款和发货现在什么状态了?"
- **BEFORE/AFTER 均拒答**:"我只能回答与 CamThink 产品相关的问题。"(1.0–1.1s)。补充:验收基线 raw/H05.json 显示生产上同型问题曾泄漏"根据内部记录…待 Dave 确认+内部三方案",修复后该类内容在检索层即不可达 → PASS。

### PE-4 历史案例 false-attribution 场景(CASE-G001 / AC-03)— PASS
- **输入**:"我的 NE101 电池掉电特别快,而且拍照时间总是漂移,是什么原因?"(与已知案例同症)
- **BEFORE**:大段转述他人案例机理("该案例中,硬件 v1.2 设备安装了为 hw v2.0 编译的固件…GPIO3…")——措辞已按"历史案例"框架(PC-04 生效),但案例内容仍入答。
- **AFTER(重试)**:仅公开通用知识(唤醒频率与寿命关系、补光灯模式影响等),**无任何案例事实被当作当前用户事实,无第三方客户信息** → PASS。

### PE-5 公开知识不回归(AC-05/PC-06)— PASS(1 项环境性注记)
- `What is the operating temperature range of NE301`:AFTER 仍 5 源 grounding,−20~+50°C 完整作答。
- 跑题诗:BEFORE/AFTER 均 1s 级标准拒答。
- **注记**:NE101 12V 供电题在本地 AFTER 由"案例给出的 7V 结论"变为诚实 declined——该规格的公开载体(github wiki 电池文档)在本地库缺失所致,**生产上该公开源在位,不构成边界回归**;恰证明此前部分"支持质量"实由受限语料供给,上线后需按 PC-06 清单复核公开文档覆盖(列入 KNOWN_RISKS)。

---

## 5. AC 与 NA 核对

| AC | 结果 | 证据 |
|---|---|---|
| AC-01 公开请求不可达受限 PII | PASS | PE-1 + 单测(restricted 候选不进上下文)+ 生产基线泄漏对照 |
| AC-02 内部商业记录不可达 | PASS | PE-2 / PE-3 |
| AC-03 案例≠当前用户事实 | PASS | PE-4 + PC-04 模板/ yaml 双护栏 |
| AC-04 全部检索路径同界 | PASS | 三路检索原生过滤(既有)+ `_retrieve_and_fuse` 单一收口守卫(answer/stream 共用);单测覆盖 |
| AC-05 公开知识可用 | PASS | PE-5;全量回归 0 失败 |
| AC-06 admin 访客等价不变 | PASS | 别名语义未动;admin 探测按 widget 单测;PE 全部跑在 widget/admin 等价路径 |
| AC-07 存量索引安全 | PASS(带部署条件) | 迁移工具 + 幂等/去重实测(本地 1663 对象两轮往返验证);**生产需在发布时执行 §7 步骤,否则存量 chunk 仍公开(代码修复不执行迁移≠完成)** |

**Negative Acceptance 逐条**:NA-01 ✗(检索/生成层拦截,非仅隐藏);NA-02 ✗(无 source_type 一刀切,per-source 配置);NA-03 ✗(567 全绿+PE-5);NA-04 ✗(主防线=检索授权,护栏仅纵深);NA-05 ✗(PE-4);NA-06 ✗(统一收口);NA-07 ✗;NA-08 ✗(零删除,内部知识保留可管理);NA-09 ✗(未引入多租户/RBAC,复用既有 channel 语义);NA-10 ✗(未部署、未动生产;见 §7 披露的共享实例时序偏差,已还原)。

---

## 6. KNOWN_RISKS

1. **公共文档覆盖缺口显性化**:此前由内部案例供给的部分支持答案(如 7V 耐压细节)在边界收紧后依赖公开文档覆盖;生产 15 源中公开 wiki 在位,但需按 PE-5 注记复核关键规格是否都有公开载体(建议 Planner 列入 T4 发布前抽查)。
2. **静默空回答**(AFTER 首轮 2 例,重试正常)属并行 P1_GENERATION_RELIABILITY 任务域,本任务未触碰生成可靠性。
3. **幽灵 chunk**:本地存在源行已删但 chunk 在库的数据(c9-e2e 等 2152 条);迁移按设计不动并上报。生产幽灵源(0fbd344b/ed455da8)为空,风险低;若后续发现含敏感内容的幽灵 chunk,需人工裁决(工具已单列报告)。
4. **guard fail-open 语义**:DB 快照不可用时放行——此时防线退回 chunk 级过滤(主防线仍在)。已用测试固化该行为。
5. **配置时效**:管理端 PATCH 源 config 后,guard 快照最迟 30s 生效(检索层 chunk 级过滤不受影响)。

## 7. DEPLOYMENT_OR_REINDEX_REQUIREMENTS(发布时执行,未获授权不执行)

1. 对内部语料源执行管理端 `PATCH /api/admin/data-sources/{id}`,config 设 `"channel_visibility": ["internal"]`(当前生产=2 个 filesystem 案例库源;**逐源人工确认**,这是本修复唯一需要产品/运营判断的动作)。
2. backend 容器内跑 `python scripts/migrate_channel_visibility.py`(先 dry-run 核对计划,再 `--apply`);无需重嵌入,只写属性。
3. 重启后端使 guard 生效(健康检查 `SourceVisibilityGuard 已启用` 日志)。
4. **无需全量重索引**;增量同步今后按源 config 自动带 visibility。
5. ⚠️ **AC-07 红线**:若发布仅含代码不含上述配置+回填,存量 chunk 仍为公开 → 泄漏仍在。发布检查单必须包含迁移执行证据(dry-run JSON)。

### 时序偏差披露(如实上报)
用户《执行窗环境引导》第 7 条(禁止写共享 weaviate)到达时,本窗的本地验证已收尾:验证采用"临时改写→取证→还原"方式在共享实例上执行(共 4 个前缀 1663 对象,visibility 属性往返写入),每次写入后均验证还原,**终态与初始完全一致**(全部 `("widget","api")`,还原证据:逐前缀计数复核)。影响窗口内,主后端(:8000)的案例类答案会短暂降级。后续任何索引级验证一律按引导走隔离 weaviate 实例(或先 dump 备份)。

---

## 8. 执行窗环境引导 8 条逐项确认

1) 独立 worktree+分支、基于 76b2199、与 P1 窗零共享 ✓(`ask-ai-p0-trust-boundary` / `worktree-exec/p0-trust-boundary`);
2) 权重复用 main 仓、只读、零下载 ✓(MODEL_CACHE_DIR 绝对路径指 main 仓 models;全程 HF_HUB_OFFLINE=1);
3) `cp main .env` ✓(gitignored,含 ASKAI_API_PORT=8010 覆写);
4) 起后端 HF_HUB_OFFLINE=1 ✓;
5) 未 kill/pkill 任何 backend.main;本窗后端 :8010,健康检查打 8010 ✓;
6) pytest 全程 `PYTHONPATH=<worktree 绝对路径>` ✓( editable venv 隔离);
7) ⚠️ 时序偏差已披露(§7):引导晚于写入时点;已还原并留证;后续遵行 ✓;
8) `TEST_DATABASE_URL` 指 5432 ask_ai_test ✓(注:`.env` 无 `DATABASE_URL` 键,DSN 由 POSTGRES_* 变量组装——该坑已补进环境引导文档)。

**环境引导已落盘共享文档**:`docs/engineering/EXECUTION_WINDOW_ENV_GUIDE.md`(双窗共用,绝对路径引用;P1 窗请按其执行)。

---

## 9. 变更清单(git)

```text
0640bc3 fix(p0): 知识信任边界——生成前源可见性纵深守卫 + 历史案例归因护栏 + channel_visibility 存量回填工具
 backend/services/source_visibility.py   | 新增(守卫 + DB loader)
 backend/pipeline/rag.py                 | +43/−6(收口守卫 + PC-04 模板 + 注释更正)
 backend/main.py                         | +13(接线)
 config/system_prompt.yaml               | +4(guardrails)
 scripts/migrate_channel_visibility.py   | 新增(回填工具)
 scripts/p0_e2e_evidence.py              | 新增(E2E 证据采集器)
 tests/pipeline/test_rag_trust_boundary.py | 新增(8)
 tests/services/test_source_visibility.py  | 新增(9)
 tests/scripts/test_migrate_channel_visibility.py | 新增(4)
```

---

## 10. Security Hardening Rework(Planner FINAL REVIEW = PARTIAL → rework,2026-09-01)

Planner 主体方案全部接受;唯一合同缺口:**授权不确定性当前 fail-open**。本节为最小加固,基于 0640bc3 增量(不回退重做)。

### 10.1 修复的三类合同违例(冻结契约 Part 4)

| Case | 修复前 | 修复后 |
|---|---|---|
| A 无权威快照(首次 loader 失败) | `{}` → 全部候选放行 | **DENY**:不得放行未证实候选 |
| B unknown / ghost 源前缀 | allow | **DENY**:不得进入生成上下文 |
| C guard 意外异常 | 返回原始候选(=旁路) | **fail-closed**:丢弃全部候选 → 拒答门兜底(可用性损失而非安全损失) |
| (保留)陈旧有效快照 + 刷新失败 | 沿用旧快照 | 不变(契约明示 MAY use stale snapshot) |
| (附加)channel=None 未知请求上下文 | allow | DENY |

已知源缺省 `channel_visibility` 键仍按默认公开(产品既有语义 + PC-02 防公开知识塌陷);未知前缀拒答不依赖该源快照值。

### 10.2 变更与验证

- `backend/services/source_visibility.py`:allows() 四行契约语义;`_snapshot_or_stale()` 返回 None 表示"从无权威快照";`{}`(loader 成功但零配置)同样全拒。
- `backend/pipeline/rag.py` `_apply_visibility_guard`:异常 → ERROR 日志 + 丢弃全部候选。
- 边界测试扩至 **23 例**(10 守卫 + 9 编排 + 4 迁移);全量 **570 passed + 3 skipped**。(注:admin analytics 一例在个别整轮顺序下偶发,隔离复现新旧代码均通过,与本地无关、未改动。)
- black/ruff:新改动文件全清。

### 10.3 活体证据(本地 :8010,零 weaviate 写入;`p0-trust-boundary-evidence/p0_rework_evidence.json`)

| 场景 | 结果 |
|---|---|
| RB-CASE-B-ghost-sim(SIM 故障;幽灵前缀案例 chunk 元数据为公开) | **5.8s 干净拒答"暂未在官方资料中找到相关信息。"**——Case B 实证:未知前缀即使 chunk 元数据公开也拦在上下文入口(rework 前同状态会整段叙述案例) |
| RB-PUB-temp(EN 规格题) | 5 源 grounding 完整作答(website 源=已知+缺省公开)——AC-05 保持 |
| RB-PUB-offtopic(跑题诗) | 0.7s 标准拒答 |

### 10.4 交付记录(rework)

| 项 | 值 |
|---|---|
| BASELINE(增量基于) | `0640bc3`(原 P0 candidate,未回退) |
| FINAL_COMMIT(rework) | `bc17d404d3949961448a071d1dca814b65367b31` |
| BRANCH / WORKTREE | 同 §0(线性追加,无 amend/rebase) |
| REMOTE | origin/worktree-exec/p0-trust-boundary = bc17d40(已推送,ls-remote 实证) |
| 三行自证 | WORKTREE/分支同 §0;BACKEND_PORT 8010;未重新下载权重 / 未动 8000 主后端 / **未写共享 weaviate(本阶段全程只读)** |

*执行端到此停止。本 rework PASS 仅为执行证据,不授权 CamThink V1 上线;终审归 Planner/Reviewer。*
