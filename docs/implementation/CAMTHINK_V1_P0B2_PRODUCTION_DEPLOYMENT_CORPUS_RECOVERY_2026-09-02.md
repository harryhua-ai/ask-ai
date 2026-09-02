# CAMTHINK_V1_P0B2_PRODUCTION_DEPLOYMENT_CORPUS_RECOVERY_2026-09-02

- Gate: P0-B2 — 生产部署(P0-B1 候选镜像)+ website-camthink 受控语料恢复
- 执行窗口: 2026-09-02T03:08Z ~ 03:26Z(UTC)
- 生产主机: tesla-t4(VM-0-4-ubuntu);授权:本 Gate 限定生产部署 + website-camthink 恢复 + 所需验证/恢复写入
- 结论: **PASS** — backend 与 sync-cron 均运行候选镜像 `sha-3bf945b`(git_sha 实测一致),语料恢复收敛(web_crawl 163→371,逐篇样本账本↔实际一致),检索恢复正常;零回滚

---

## 1. Mandatory Preflight(03:08Z,只读)

| 项 | 值 | 与冻结假设 |
|---|---|---|
| backend | `05f7d396…`(sha-1ed84bb)/ git_sha `1ed84bb…` / healthy / Restarts=0 / StartedAt 09-01T16:40Z | 一致 |
| sync-cron | 同镜像同 git_sha / running / Restarts=0 / StartedAt 09-01T17:01Z | 一致 |
| backend health | 200 | 一致 |
| GPU | 15,737 / 16,384 MiB(无 embedder 余量) | 一致 |
| 回滚镜像 | `sha-1ed84bb` = `05f7d3961162` 在位 | 一致 |
| 候选镜像 | **不在主机 → 已拉取**;拉取后 IMAGE ID `d2d397935293` == P0-B1 CONFIG_DIGEST(身份交叉验证) | 一致 |
| PG website-camthink 账本 | 123 docs / 361 chunks | 一致(PA-0F) |
| Weaviate | 总量 126,204;web_crawl 163;github 125,459 / filesystem 481 / woocommerce 101 | 一致 |
| website 最新 sync | 02:42 failed(47 篇 OOM) | 一致(PA-0F 残留) |

无实质矛盾 → 未触发 BLOCKED。

## 2. Deployment(A: backend → B: sync-cron,均隔离单服务,未跑 update.sh 全程)

### A. Backend(03:09:03Z)
```
cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=sha-3bf945b docker compose -f deploy/prod/docker-compose.yml up -d backend
```
- Image=`sha256:d2d397935293…`(=sha-3bf945b);StartedAt 03:09:03Z
- health 200 @ ~15s → docker healthy;**Restarts=0**;OOMKilled=false
- `/app/.git-sha` = `3bf945bdc80829efabe5134dbc99711508d92b47`(逐字匹配 SOURCE_COMMIT)
- 启动日志:BGE-m3 + reranker 加载完成(cuda)→ `Ask AI 后端就绪` → `Application startup complete`;错误模式扫描唯一命中即 startup complete 行,无 Traceback/OOM

### B. sync-cron(03:10:26Z,backend 健康后)
```
ASKAI_IMAGE_TAG=sha-3bf945b docker compose -f deploy/prod/docker-compose.yml up -d sync-cron
```
- Image=`sha256:d2d397935293…` 同候选;`/app/.git-sha` = `3bf945b…`;Restarts=0
- backend 全程未受影响(同镜像 healthy)
- 旧镜像(sha-1ed84bb,含未修复 prune)自此不再以任何形式活跃 —— 满足「恢复开始前旧 sync-cron 不得存活」

## 3. Recovery Path Selection(契约 §5 要求先声明)

**选择 B:受控一次性 CPU embedding 恢复**(既有已验证机制):
1. GPU 15,737/16,384,无 embedder 余量(PA-0F 八轮 OOM + 本 Gate preflight 复测);
2. admin 内联路径需管理员凭证(本执行方不持有、亦不得使用);
3. `docker compose run --rm -e EMBEDDER_DEVICE=cpu sync python scripts/sync.py` 是 PA-0E 已验证模式,且一次性容器运行**候选镜像 = 修复后 prune 语义**。

## 4. Recovery Execution(03:14 ~ 03:20)

执行:`cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=sha-3bf945b docker compose -f deploy/prod/docker-compose.yml run --rm -e EMBEDDER_DEVICE=cpu sync python scripts/sync.py`

实际发生(sync_log 证据):**两轮收敛交错,均幂等无害**:
- 03:14:50 新 sync-cron 启动轮(GPU embed 竟获成功):website-camthink `partial, 255 updated`,detail:「一致性校验发现缺口 163/361;需重灌 47 篇(整篇缺失 0 + chunk 不一致 47);多余 chunk 0 个(已由 ingest 清理);orphan=10」;
- 03:20:00 CPU one-off 轮:同结果(partial, 255 updated,同 detail)—— 与启动轮重叠但确定性 UUID 幂等覆盖,**无重复对象、无越界删除**(逐篇样本与总量证实);
- 同轮 ne301-local 成功摄取上游新提交(2 新/40 更)→ github 125,459→125,461(合法上游内容,非回归);
- wiki-documents / woocommerce:无变更跳过。

## 5. Convergence Verification(P0B2-G005/G006)

| 维度 | 恢复前(03:08) | 恢复后(03:22) | 说明 |
|---|---|---|---|
| Weaviate TOTAL | 126,204 | **126,414** | Δ=+210(=web_crawl +208 + github +2) |
| web_crawl | 163 | **371** | 覆盖 PA-0E 水位 359;账本预期 361 + 10 ghost(见 §7) |
| github | 125,459 | 125,461 | 上游新提交(+2,合法) |
| filesystem / woocommerce | 481 / 101 | 不变 | 零扰动 |
| channel_visibility | api=widget=全量 | api=widget=**126,414** | 信任边界语义零变化 |

**Document-level samples(确定性 UUID 点查,非 token 过滤)**:

| 文档 | 账本 | 实际存量 |
|---|---|---|
| website-camthink/blog(listing,收缩敏感) | 1 | **1** ✓ |
| website-camthink/blog/ai-species-identification-camera-trap-images(PA-0F 事故样本) | 4 | **4** ✓ |
| website-camthink/blog/smart-waste-monitoring-edge-ai(11 chunk 多块页) | 11 | **11** ✓ |
| website-camthink/index | 2 | **2** ✓ |

PG 账本 123/361 与 Weaviate 对账本内文档**完全一致**;存量比账本多 10 个 ghost(见 §7,系统自身 orphan=10 如实披露,按冻结 V1 语义「幽灵不动、reported 供人工裁决」)。

## 6. Retrieval Smoke(P0B2-G008)

03:24:41Z,受控一次(admin 渠道,不污染公共统计):
`"How can edge AI cameras be used for smart waste monitoring?"` → **HTTP 200 / 17.9s / 344 token / sources+done,无 error/declined**。
引用含恢复页 `camthink.ai/blog/smart-bin-waste-management-ne301-tutorial/`(web_crawl)+ wiki 文档 —— 恢复知识端到端可检索、来源映射正常。
持久化:conversations/traces 106→**108/108**;本冒烟 `is_answered=t`、4 sources、trace type=rag。
补充:01:27:11Z 有一条运维者真实提问(「NE101 的功耗是多少?」,admin,answered,3 sources)—— 升级后真实使用正常。

## 7. Residual: 10 个 ghost 对象(系统披露,未处置)

存量 371 = 账本 361 + **10 个 orphan**站点文档(旧 URL,已不在当前 sitemap;其账本行被既有 content-hash 版本清理机制移除,Weaviate 对象残留)。恢复后系统如实报告 `orphan=10`,较恢复前 15 减少 5。
**影响**:下一轮 cron 一致性校验将继续看到 371/361 → refill 空 → 触发 RC 自愈全量重灌(112 篇)→ 成功后再报 partial(窗口不推进),或 GPU 余量不足时 OOM failed。**该循环无害**(确定性 UUID 幂等 + document-local prune,结构上不可能再跨文档删除),但会持续空转直至幽灵经人工裁决清理或账本收养 —— 需独立小 Gate(ghost 清理属冻结 V1 语义的人工裁决范围)。

## 8. P0B2-G001..G010

| 验收 | 结果 |
|---|---|
| G001 backend = sha-3bf945b | PASS(git_sha 逐字一致) |
| G002 sync-cron = sha-3bf945b | PASS(同镜像同 stamp) |
| G003 backend health PASS / restarts 稳定 | PASS(healthy,Restarts=0,OOMKilled=false) |
| G004 恢复无破坏性兄弟/跨文档损失 | PASS(修复语义 + 逐篇样本 + 总量收敛;两轮重叠写入亦无重复对象) |
| G005 sync 达成 success 或精确阻塞证明 | PASS(PARTIAL 是 refill 路径的设计态:数据已收敛,窗口不推进待复验;非运行故障) |
| G006 PG↔Weaviate 收敛(逐篇) | PASS(4 样本点查一致 + orphan=10 如实披露) |
| G007 语料实质恢复 | PASS(web_crawl 163→371,越过 PA-0E 水位 359;总量 126,414 落在预估邻域 126,389–126,402 附近) |
| G008 检索恢复 | PASS(恢复页进引用,持久化正常) |
| G009 无关语料回归 | PASS(fs/woo 零变化;github +2 为上游合法新内容,已溯源) |
| G010 回滚就绪 | PASS(未触发;sha-1ed84bb 镜像在位,回滚命令同 PA-0D 模式) |

## 9. Rollback Statement

ROLLBACK_EXECUTED = NO;ROLLBACK_READY = YES(`sha-1ed84bb`=`05f7d3961162` 在主机;`ASKAI_IMAGE_TAG=sha-1ed84bb up -d backend/sync-cron`)。按合同:若需回滚仅恢复运行时健康,不得恢复旧删除语义后继续 recovery(本 Gate 未需回滚)。

## 10. Final State(03:25:14Z)

- backend: `sha256:d2d39793…`(sha-3bf945b)/ git_sha `3bf945b…` / healthy / Restarts=0
- sync-cron: 同镜像同 stamp / running / Restarts=0(下一整点周期按 3600s 节奏)
- postgres / weaviate: 未重启,健康
- 生产知识面:web_crawl 恢复至 371(超过事故前 359),检索与持久化正常

**CORPUS_RECOVERY_STATUS = PASS**
**SYNC_RUNTIME_STATUS = PARTIAL**(窗口因 refill 路径设计不推进 + 10 ghost 待裁决;GPU 余量随负载波动,03:14 轮成功不代表容量已解 —— 按 PA-0F/合同口径 GPU_SYNC_RUNTIME_POLICY 仍为 KNOWN_UNRESOLVED)

**STATUS = PASS**
