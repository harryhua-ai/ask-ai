# ask-ai PRODUCT STATE

> **性质**:当前产品状态快照 — 每次 significant FINAL PASS / 能力成熟度变化 / 产品假设失效后更新(协议 PART VI §27)。
> **本版**:2026-09-04(v1.1.0 发布定稿,FINAL PRODUCTION PASS)。**2026-09-08 增注:I-001 Answer Intelligence Foundation 已完成(9/9)并入主干,未部署生产——见 §1.1。**定位/原则见 `PRODUCT_VISION.md`,规划与候选池见 `PRODUCT_ROADMAP.md`。(上一版 2026-08-31 的内容保留于 git 历史。)

---

## 1. 总体判断

**v1.1.0 已发布并经生产容量验收(FINAL PRODUCTION PASS)——距真实访客仍差 T1a Phase 4(wiki 灰度嵌入的上线窗口,待用户确认)。**

- 代码:main = origin/main = `762eae3b…`;Release:**v1.1.0**(annotated tag + GitHub Release);CI 33885620242 success
- 生产:tesla-t4 三服务统一 `sha-762eae3`(healthy);数据面同步正常(受控真实嵌入同步 + 删除回流均验证)
- GPU 运行时(本版核心):MODEL×WORKLOAD×DEVICE 契约;单一 backend GPU 所有权(sync 零自载模型);GPU 执行闸(查询优先+有界公平);容量计划 **reranker_transient** 生效(预算 auto=4210MiB,HEALTHY);**瞬态重排**生产实测 pre1238→峰3375→post1238 MiB 精确回落;容量分级数值化呈现(UUID 归一化修复后)
- 质量面:后端全量 1665/6/0;admin 274/0;生产 16+9 次 Ask 零 OOM;#22/#24 生产冒烟过并关闭
- 既有风险延续:admin 种子密码仍有效;三方显存增长会压缩预算(计划器会如实降级并可见)

### 1.1 增量(2026-09-08):I-001 Answer Intelligence Foundation 关闭

- **状态:COMPLETE(9/9)**——Target Architecture / Engineering Discovery / Benchmark v1 Freeze / Production Baseline Measurement / Independent Baseline Review / Failure Attribution / INC-1(请求级 LLM 遥测+证据血统)/ INC-2a(证据元数据词表+确定性回填)/ INC-3(任务理解合并+交互模式)全部 FINAL PASS;Project #2 对应条目全部 Done
- **集成**:PR #35 已合并(merge `1790909`),main = `a364240`;父 Issue #32 保持 OPEN
- **Benchmark 真相**:冻结基线 = **80.2/100**(I-001 前);**post-I-001 分数 NOT YET MEASURED;Product Target Score NOT YET FROZEN**(待 post 测量后冻结,不预填)
- **生产状态:未变更**——I-001 代码未部署生产(未授权);生产仍为 v1.1.0 `sha-762eae3`,§1 快照对生产仍然成立
- **能力增量(已并入主干、未上线)**:LLM 调用请求级遥测;证据元数据(authority/temporality/sensitivity/citation 词表 + unknown 安全域);合并任务理解(单次 LLM 调用,交互模式 standard / clarification_required / capability_orientation / off_topic,trace 呈现生效态)
- **后续**:INC-2b / INC-4~7 保持 Backlog(不属 I-001,不追溯并入);下一迭代选择待定(就绪候选:Issue #34-A Multi-Branch GitHub Change Detection)

## 2. 能力成熟度(2026-08-31)

| 能力 | 现状 | 成熟度 |
|---|---|---|
| 问答核心(检索/拒答/引用/流式) | 生产运行验证(admin 聊天恢复、15 源全绿) | **生产就绪,未经真实访客检验** |
| 数据接入 | 4 类 connector 全通;同步自愈闭环;C9 上传建源经三波加固(创建/编辑/合并/默认全选)全部独立 E2E 验证 | **真可用** |
| 管理后台 | 8 页全链路可用,上传/编辑交互坑本周清零 | **可用** |
| 入口层(widget) | 配置接口标准化(`data-api-url`/`data-language`/`data-primary-color`);未托管、未嵌入任何真实站点;唯一集成 = admin 内嵌(测试) | **开发完成、未上线——唯一挡上线的** |
| 标准件化(多租户/licensing/配置化分发) | 未开始(T1b + E 类) | 概念阶段 |
| 工程治理 | 双角色协议 v2.0;6 契约 7 审查全部留痕(artifacts 在 docs/engineering/) | 运转良好 |

## 3. 状态维度表

| 维度 | 状态 |
|---|---|
| 生产运行 | tesla-t4 运行 `76d75e7`;15/15 源全 success;磁盘余量健康;公开站点零嵌入(唯一集成 admin 聊天,可用) |
| 代码 | main = origin/main = `4db4c41`(CI 33355154229 success);T1a 代码包(widget 托管/CORS)未开发 |
| 测试 | 后端本地全量(除 embedder/e2e)**534 passed + 3 skipped**;admin vitest 113/113 + tsc 干净;⚠️ CI pytest 不含 `tests/api/admin`(扩围=候选 12) |
| 数据规模 | 15 源全绿:10 github + 2 filesystem + 1 woocommerce + 1 官网爬取(116 篇)+ 1 测试新增;一致性自愈 + prune + 记账真实全部生产验证 |
| 通用化程度 | 架构层达标;connector 4 类;业务语义耦合未剥离(意图体系/常量,E 类待启动) |
| 已知风险 | ne503/官网源 cron 稳定性留意;admin 种子密码(admin123)仍有效;Node.js 20 deprecation(CI 非阻塞注记) |
| 遗留挂起 | 真幽灵源 2 个待 UI 删(0fbd344b/ed455da8;**0aa5b846 有实内容勿删**);d341da15 目录(174 文件)复用待定;PAT 本体轮换(用户挂起勿催);Task #25;TraceLanes;ruff 低优清单 |

## 4. 产品能力地图(已实现能力的事实记录)

### 4.1 C 端问答(Widget)

- 嵌入式聊天组件(`widget.js`,IIFE,`<script>` 嵌入);SSE 流式 + Markdown 渲染(XSS 清洗 + DOMPurify),内联来源引用 + 类型标签(链接过协议+域白名单)
- 有限多轮(前端保留最近 5 轮);👍/👎 反馈;首屏推荐问题
- 附件上传(Phase 1a):txt/log 文本日志,补充上下文注入;有附件绕过拒答门;30 天清理
- 免登录匿名;PII 脱敏入库
- Admin 全局内嵌同一聊天窗口——管理员测试环境;独立 `channel="admin"`(`c8117f4`),测试对话与访客数据可区分

### 4.2 RAG 管线

```
mask_pii → BudgetLimiter 预扣 → 附件注入
→ 意图分类(4 类:commercial/product/support/off_topic;off_topic 拒答)
→ 查询改写(多轮重写 + 长文本提取)
→ 混合检索(BGE-m3 dense + BM25 hybrid;文件级 + 符号级 BM25 → RRF 融合)
→ 重排(bge-reranker-v2-m3 + chunk_type 加权;commercial 意图 boost 桶)
→ 拒答门(rerank min_score,不足 3 条拒答;降级用 fused top-N 防误拒)
→ LLM 生成(deepseek 流式,按意图分风格 prompt)
→ SSE:sources → tokens → done → 落库 conversations + trace
```

可选增强:Pruner(上下文裁剪)、OverrideMatcher(人工答案覆盖)。

### 4.3 知识接入与索引(数据面)

- **15 个数据源在同步**:10 github + 2 filesystem + 1 woocommerce + 1 官网爬取 + 1 测试
- 分块:文档语义分块 + 代码 tree-sitter AST 函数级分块;channel_visibility 隔离
- 增量同步:cron 每小时 + admin 手动;窗口按上次成功推进(失败不推进)
- **向量一致性自愈**:无变更源两级校验(汇总 SUM → chunk 级差集),缺口自动补灌、`refill_source_ids` 自愈、prune 陈旧 chunk/幽灵行、写失败诚实上报(partial 语义)
- 确定性 UUID 幂等 upsert;filesystem 上传模式(落盘 `data/uploads/data-sources/<id>/`,合并覆盖,白名单+垃圾文件过滤,include_dirs 默认全选)

### 4.4 管理后台(8 页 + Login)

- **运营组**:业务概览(KPI+三列意图卡+趋势+线索/场景/需求/地域)、对话审查(4 色阶段条+markers+5 泳道 trace 详情)、技术洞察(性能 P50/P95+知识缺口,下钻)
- **配置组**:数据源(结构化表单/同步/partial 黄标/上传与目录树勾选)、对话接入(Customization 按渠道)、模型配置(6 环节网格/chain 路由/连通性测试/热重载/凭证 AES)、答案覆盖(CRUD+一键 prefill)、用户管理(RBAC)

### 4.5 可观测与分析

- trace 数据层(1 conversation : N trace;stages jsonb 6 阶段)
- 业务信号 pipeline(LLM 批跑,cron 低峰定期 per D-7)
- 分析聚合:Coverage Gaps / Top Questions / Source Analytics / 聚类

### 4.6 平台与部署

- 生产:tesla-t4(GPU T4,纯 CI 镜像 GHCR,backend :18000 + sync + sync-cron),公网入口 wiki-data.camthink.ai
- 开发:mac 本地 CPU(dev-local.sh 热更)
- CI:GitHub Actions(test → 前端构建 → GPU 镜像)
- Postgres 15 表;Weaviate 单 collection(hybrid + symbol)
- 安全:JWT/bcrypt/Fernet、成本熔断、限流、prod 密钥强校验

## 5. 外部生态

ask-ai-eval skill(`camthink/skills/ask-ai-eval/`)共享 trace 数据层做答案优化,数据存 `Knowledge/Think/ASK AI/optimize/`;对话审查页与它同一数据底座分工(admin 浏览 / skill 命令行优化)。
