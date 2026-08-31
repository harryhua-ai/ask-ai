# Execution Report: REL-WIN(T1a 前一次性发布 + 三项观察)

> **契约**:`docs/engineering/contracts/rel-win-one-shot-release.md`(冻结)
> **执行日期**:2026-08-31 | **执行者**:Engineering Executor
> **状态总评**:**PASS**(A1-A4 全过;零代码改动)

## 1. Baseline Commit

`76d75e7`(= origin/main;CI run 33321125298 产物镜像)

## 2. Final Commit

无(零代码契约;main = origin/main = `76d75e7` 未动)

## 3. 前置与发布(A1 / A3 前读数)

| 项 | 证据 |
|---|---|
| CI 33321125298 | `{"conclusion":"success","head":"76d75e7"}` |
| 磁盘(发布前) | `/dev/vda2 1.3T 277G 952G(23%)` — 余量 77%,红线 20% 通过 |
| 磁盘(发布后) | `952G(23%)` — 无异常增长 |

**发布**:`update.sh` 成功(backend Recreate→Started);健康检查首验失败为 BGE-m3 GPU 加载慢(既有已知模式),约 50s 后 `{"status":"ok"}`。

**A1 版本实查(容器内双特征,防运行旧版)**:
```
$ docker exec tesla-t4-backend-1 ls backend/connectors/web_crawl.py
backend/connectors/web_crawl.py          ← C8 特征存在
$ docker exec tesla-t4-backend-1 grep -c _sanitize backend/connectors/github.py
3                                        ← D4/C10 特征存在
```
运行版本 = `76d75e7` 实锤。

## 4. 观察①:同步全部前后 SyncLog 对照 —— **PASS**

**发布前基线**(DISTINCT ON per source):9 success / **5 partial**
(ne301-local、ne503-sdk-local、neomind-dashboard-local、neomind-extensions-local、neomind-local)

**发布后首轮**(07:40 触发,15 源含新种子 website-camthink):**15/15 全 success**
- 五源 + dashboard + neomind-local:全部 partial→success ✓(孤儿已清 + 校验器口径统一)
- **ne503-sdk-local 直接收敛为 success(未走契约预留的"一轮 partial 重灌")**:D4 记账修复后,此前震荡轮的真实写入在统一迭代器口径下本就一致——契约预期"允许一轮 partial 后下轮收敛",实际一轮到位,优于预期
- website-camthink 首爬 success(items_updated=369 chunks)

**第二轮**(稳定性确认):19 行 sync_log **0 个非 success**;终态逐源表 **15/15 success**。

## 5. 观察②:website-camthink T4 首爬 —— **PASS**

| 项 | 结果 |
|---|---|
| 首爬入库 | **116 篇**(116 distinct pages,1:1;369 chunks) |
| `/store/` 泄漏 | **0 行**(SQL 直查 `LIKE '%/store/%'`) |
| 与本地 126 的差异 | T4 版代码排除 `/wp-json` 等噪音页(最终修复),符合语义 |
| NG4500 抽查 | T4 入库含 NG4500 相关页;本地库 BM25 `NG4500` 命中官网 blog 页(同 connector 同清洗逻辑) |

## 6. 观察③:admin 聊天检索(P1 生效)—— **PASS**

`POST /api/ask {"message":"NE503 specs","channel":"admin"}`:
```
event: sources
data: {"sources": [{"url": "https://github.com/camthink-ai/wiki-documents/blob/main/.../6-neoeyes-ne503-series/2-hardware...", ...
event: token
data: {"content": "**Core Processing Board**..."}(流式回答)
```
**admin 渠道出 sources + 流式回答**——对比发布前同渠道拒答(零命中),P1 修复生产生效实锤。

## 7. PAT 泄漏行(独立动作)—— **跳过注明,状态更新**

产品负责人尚未确认处置方式 → 契约规定跳过删除。**状态更新**:复查 `sync_log` 中 `error_detail LIKE '%github_pat_%'` 行数 = **0**——泄漏行已不在库中(非本任务所为,应为产品侧已处置);**PAT 本体轮换仍强烈建议**(已落库即视暴露,删行不等于撤销暴露)。

## 8. Acceptance Self-assessment

| # | 验收 | 自评 | 证据 |
|---|---|---|---|
| A1 | 版本实查(双特征) | **PASS** | web_crawl.py 存在 + _sanitize×3 |
| A2 | 三项观察各留证据 | **PASS** | §4/§5/§6(前后对照表/首爬计数+store 0/问答 sources) |
| A3 | 磁盘前后读数 + 红线 | **PASS** | 952G 前后一致;无 --reindex;零提交;未动 PAT 行 |
| A4 | 执行报告 | **PASS** | 本文件 |

**Overall: PASS**(待 Review 判定)

## 9. Deviations

1. update.sh 健康检查首验失败为 BGE 加载慢(契约已预期,50s 复验通过),非偏离。
2. ne503-sdk 未出现契约预留的"一轮 partial":修复后直接收敛,优于预期,如实记录。
3. 观察②计数 116 与契约"~126 预期"的差异 = 最终代码排除 `/wp-json` 等噪音页(本地库旧爬行含这些行),属修复语义的体现,非缺失。

## 10. Remaining Risks

1. **PAT 本体未轮换**(泄漏行已清,但暴露事实未撤销)——建议尽快在 GitHub 侧轮换。
2. 发布后三项均为单轮观察;建议后续日常 cron 运行中留意连续 success 的稳定性(尤其 ne503-sdk 与 website 增量)。
3. 官网爬取运行于 cron(24h 间隔 + 500ms/页限速),对站点压力可控;如站点方有异议可调 crawl_delay_ms。
