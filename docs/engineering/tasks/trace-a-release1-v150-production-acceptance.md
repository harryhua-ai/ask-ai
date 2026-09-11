# Trace A — Release 1 / v1.5.0 Production Acceptance Report

日期:2026-09-11。执行:集成门后授权的发布(readiness → deploy → runtime
acceptance → #29 激活门)。本报告即 deliverable 的仓库证据锚。

## 1. 基线与候选

- 发布前 origin/main:`bb80c389c6d38aa2474f383b60f3aec0de7397a1`(推送前
  fresh fetch 复验零漂移;部署 dispatch 前再次复验 = bb80c38)。
- 发布候选:**v1.5.0 = annotated tag @ bb80c38**(精确接受树;tag 指向
  bb80c38 本身,零额外 commit,main 未因发布物移动)。
- 发布前生产:v1.4.0 / `41278f07eb4abbf4f3420b2d7b65db28c7fdcbb1`
  (/health 实证;三容器 v1.4.0 healthy)。

## 2. Readiness 发现

- 部署机制(仓库现行权威):`deploy-production.yml` 仅 workflow_dispatch,
  输入精确不可变 tag vX.Y.Z;身份冻结(tag git 解析)→ release-publish
  Guard(五不变量)→ in_progress Deployment 记录 → 迁移 → flock+SSH
  update.sh → /health 身份核验 → recorder success。回滚 = 用上一不可变 tag
  重 dispatch(v1.3.0/v1.4.0 两次实证)。
- 迁移:`deploy/prod/migrations.json`(冻结树)→ 计划仅
  `migrate_add_site_launcher_presentation.py`(幂等,v1.4.0 已执行过,
  重跑安全;本次部署步骤 Migrate PASS)。**41278f0..bb80c38 零 schema 迁移**
  (唯一差异 = evidence_meta 回填脚本 +product 参数,未入部署计划)。
- Env:无新增必需变量(生产 EMBEDDER_MAX_LENGTH=1024 在位;
  GITHUB_GIT_TIMEOUT_SECONDS 可选缺省 900)。
- Readiness verdict:**READY FOR PRODUCTION DEPLOYMENT**。

### CI 阻塞与处置(披露)

tag v1.5.0 首次 build 失败:
`tests/runtime/test_manager.py::test_query_preempts_queued_sync`
(`'s2:start' is not in list`)。该失败**先于 F-1' 存在**(d0230f9 的 main
build 同测同因失败;bb80c38 main build 同;本地同树两轮全量 2227/2256 全绿)
—— 50ms 线程调度窗在 runner 负载下的时序脆弱测试,非本发布语义缺陷。
处置:`gh run rerun --failed`(合法 flake 重试,零代码变更)→ 重跑 test 绿,
build-and-push 成功,镜像 `ghcr.io/harryhua-ai/ask-ai:v1.5.0` 推送
(run 34563566836)。**遗留:该测试需要确定性加固(等 s2 注册等待者而非
sleep),属测试鲁棒性跟进,不在本 gate 实施。**

## 3. 部署(production mutation 全记录)

- GitHub Release:v1.5.0(非 draft,body 2153 字符;guard 三项满足)。
- Workflow run **34564587117 = success**(全部步骤绿:identity freeze →
  guard → record in_progress → migrate → update.sh → identity verify →
  record success;finalize-failure 步骤 skipped=按设计)。
- Deployment 记录:GitHub Deployment **6386829992, state=success,
  "success v1.5.0 @ bb80c389c6d3"**。

## 4. Runtime Acceptance(生产实证,非仓库推断)

- 三容器 `ghcr.io/harryhua-ai/ask-ai:v1.5.0` healthy(restarts=0,
  Up 正常);`/health` =
  `{"status":"ok","version":"1.5.0","git_sha":"bb80c389c6d38...","app_mode":"production"}`
  —— 与 tag 解析 SHA 逐字节一致。
- **API/SSE 路径**(冻结用例,生产 GPU,benchmark runner 走真实 SSE 流):
  - cg-r05(F-1' 旗舰):访客 sources 含**两页锚定商店页**
    (NE301 Wireless Edge AI + NE101 Modular Sensing Camera),答案按产品
    分节给配置与口径 —— F-1' 矫正行为在生产路径实证。
  - sq-080:GPIO3 机制+版本对+历史框架完整 ✓。
  - 红线 cg-r03/cg-r04/cg-s01:澄清/拒答/能力导向逐字符合accepted ✓。
- **Widget 路径**:https://www.camthink.ai 200;
  `/widget/widget.js` 200(生产 access log 实证多次 200)。
- **#29 激活门**(部署后独立 gate):
  1. 部署后首个同步轮(05:06-05:09)**website-camthink #2963 completed**
     —— #45 字符契约修复使 09-03 起 413 失败的源经正常 cron 自愈
     (web_crawl 367→379、woocommerce 101→114,含此前恒败页面)。
  2. `/tools/` 页面在库但残留旧标签(product=unknown,v1.4.0 时代灌入,
     lastmod 未变 → 增量轮不再重灌)。**最小激活**:删除 2 条陈旧 chunk
     (tools hub + battery-calculator;ai-tool-stack 标签正确未触碰)→
     系统自愈机制(`_handle_no_change` 向量一致性 refill)按设计触发,
     手动 `--source website-camthink`(triggered_by=manual)重灌:
     - `website-camthink/tools` → **product=tools**(1 chunk)
     - `website-camthink/tools/battery-calculator` → **product=tools**
       (3 chunks)
     - `ai-tool-stack` 保持 aitoolstack(特异规则优先)✓
  3. 行为实证(生产):cg-r06 访客 sources 出现
     `('web_crawl','tools','Battery Life Calculator')` —— tools 证据
     **可检索、合格、对外可见**;sq-073 AA 电池问从知识案例正确作答。
  - 回滚性:改动仅 2 页 product 标签,幂等可重放;无需回滚路径。
  - **#29 = 激活完成,生产行为实证;但 issue 关闭仍待独立 Role A 验收。**

## 5. 发现的既有缺陷(非本发布引入;单独 corrective,本 gate 未修)

`traces.type` 列 VARCHAR(20),而 capability-orientation 轮次写入
`"capability_orientation"`(21 字符)→ INSERT 失败 → **该轮 analytics
记录丢失**(conversations+traces 同事务回滚;用户答案照常送达,fail-open
仅损失遥测)。代码 v1.4.0 (rag.py:1460/2180) 与 bb80c38 完全一致 =
**既有潜在缺陷**,本窗口首现(验收探针包含能力导向问)。需独立矫正:
列宽迁移(traces.type → varchar(32)+)或写侧截断;走迁移所有权模型另立项。

## 6. Final Reconciliation

| 项 | 状态 |
| --- | --- |
| Release 1(v1.5.0) | **DEPLOYED + RUNTIME ACCEPTED** |
| 生产运行时 | v1.5.0 @ bb80c38(三容器 healthy,/health 身份精确) |
| #26 | VERIFIED(生产红线 cg-r03 实证保持) |
| #27 | VERIFIED(生产 cg-r04/cg-s01 实证保持) |
| #28 | PARTIAL(排序矫正已入生产并实证;变体粒度残余=Scope Expansion 待产品决策) |
| #29 | **激活完成+生产行为实证**(calculator=tools 可检索可引用);issue 关闭待 Role A |
| #31 | PARTIAL(#31A 已入生产;31B sq-034 判分 PASS;T2=INC-2b 待) |
| F-1' | CLOSED / IN MAIN / 生产行为实证 |
| Trace A | **PRODUCTION CLOSED**(#28/#29/#31 的 issue 关闭与残余移交见下) |
| 残余移交 | Woo 变体灌入 → Trace B Phase 3 候选;PRODUCT_SPEC>CASE 引用优先 → 产品决策;INC-2b;traces.type 列宽矫正 → 新独立 corrective |

## 7. 证据物

- `ask-ai-acceptance/sprint-review-20260911/evidence/release1_prod_subset.jsonl`
  (生产 5 冻结用例)、`release1_prod_29gate.jsonl`(cg-r06/sq-073)、
  `release1_runtime_probes.json`、`probe_paraphrase_out.json`、
  `f1p_seed_subset.jsonl`(26/26)、`f1p_judge_final.md`、
  `corpus_attribution.txt`、`probe_f1p_out.json`。
- GitHub:Release v1.5.0;Deployment 6386829992(success);
  workflow runs:build 34563566836(success,含一次合法 flake 重试)、
  deploy 34564587117(success)。
