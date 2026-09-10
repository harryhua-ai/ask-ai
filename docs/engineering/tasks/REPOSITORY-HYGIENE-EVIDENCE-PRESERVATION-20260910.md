# Repository Hygiene — Phase 2B Canonical Evidence Preservation (2026-09-10)

**STATUS**: EVIDENCE PRESERVATION CANDIDATE READY(待独立评审后方可并入 main)
**BASE**: `9343e65d302570ac2e943d6450507a54cfee44b2`(= origin/main;非本地 main)
**BRANCH**: `hygiene/evidence-preservation-20260910`(独立 worktree `.worktrees/hygiene-evidence-preservation`)

## 1. 保存范围(恰三项,无第四项)

| # | 工件 | 来源 ref/commit(源路径) | 目的地 | 操作 | 完整性证明(SHA-256) |
|---|------|--------------------------|--------|------|----------------------|
| A | I-002 契约收口报告 | `docs/i002-contract-closure-20260908` @ `1090029`(`docs/engineering/discovery/I002-EVIDENCE-INTELLIGENCE-CONTRACT-CLOSURE.md`) | `docs/engineering/tasks/I002-EVIDENCE-INTELLIGENCE-CONTRACT-CLOSURE.md` | COPY AS-IS(目标在 main 缺失,已核实) | source=`80d7f29f…a1d26f2` = dest(逐字节一致) |
| B | Issue #33 主题闪变 RCA(历史证据) | `origin/docs/issue33-widget-theme-flash-rca` @ `0da88b9`(`engineering/discovery/ISSUE-33-WIDGET-THEME-FLASH-RCA.md`,14,788 B) | `docs/engineering/tasks/ISSUE-33-WIDGET-THEME-FLASH-RCA.md` | 前置 912 B 授权历史状态头;正文零改写 | header 后正文 tail = source `6f0e2268…d1cbb1d`(逐字节一致);复现台架/截图未复制(§9 最小证据) |
| C | Widget 集成交付报告 **v2.1 修订** | `origin/worktree-exec/widget-integration-handoff` @ `eb112fa`(`docs/implementation/CAMTHINK_V1_WIDGET_INTEGRATION_HANDOFF_2026-09-02.md`) | 同路径(替换 main 旧修订) | 文档替换(仅此文档;未触 config/sites.yaml) | candidate=`16e99cd3…0195f89` = eb112fa 源;vs main 旧版 = **+39/−0**(纯追加 §11) |

## 2. C 项「确实更晚/同文档后继」证明

- main 现存副本(由 `721d16f` 于 09-02 12:13 force-add)与分支 `657338b`(§10 版)**diff=0** —— 二者同一文档状态;
- `eb112fa` 的父提交即 `657338b`,其变更对本文件**纯追加** §11(v2.1 生产基址回填 + §11.3 字段覆盖声明),零删改 —— 同文档直接后继,非分叉改写;
- 分支链时间:2fb1a86(10:51)→ 657338b(11:20)→ eb112fa(11:48);main 侧 721d16f 的 12:13 为主仓补提交时间戳,不影响内容谱系。

## 3. 权威/替代关系(防「历史变现行权威」)

- **A**:历史契约记录(2026-09-08 冻结)。I-002 INC 系列已按其实现并合入 main;现行 I-UX-001 矫正契约(`I-UX-001-POST-PRODUCTION-CORRECTIVE-implementation-contract.md`,冻结 `376565f`)在冲突处优先。
- **B**:文首授权头显式声明「历史证据/非现行实现权威」,并载明候选上下文(`b7a016d`、后续已接受实现 `2cff7bf`→REV1 `3c5a56b` 已在 main)与矫正契约优先关系。RCA 正文保持历史原貌,未改写以迎合现行实现。
- **C**:交付报告自我标注日期 2026-09-02,属历史交付记录(与 main 既有旧修订同性质);现行接入权威 = `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md`(v1.3.0 更新,`9343e65`)。§11.3 的分站就绪字段为 09-02 时点快照(如 STORE_READY=NO 已被 09-03 store origin 修复后事实取代),保留为历史快照、不构成现行运维指令。

## 4. 边界声明

- 本候选**仅含**上述 3 份文档 + 本报告(`git diff --stat 9343e65..HEAD` 可复核);零代码/零测试/零配置(sites.yaml 未触碰)/零 Product 范围/零矫正契约改动。
- **未删除任何分支/worktree/远程 ref**;源证据分支(`docs/i002-contract-closure-20260908`、`origin/docs/issue33-widget-theme-flash-rca`、`origin/worktree-exec/widget-integration-handoff`)全部原样保留,退役属后续独立卫生门。
- origin/main 未被触碰;未合并;未部署。

## 5. 候选

- CANDIDATE SHA:见提交(本文件所在提交)。
