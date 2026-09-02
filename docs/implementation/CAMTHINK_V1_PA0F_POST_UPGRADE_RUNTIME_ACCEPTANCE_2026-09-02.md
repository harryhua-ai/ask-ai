# CAMTHINK_V1_PA0F_POST_UPGRADE_RUNTIME_ACCEPTANCE_2026-09-02

- Gate: PA-0F — PA-0D/PA-0E 之后的生产运行时只读验收
- 执行窗口: 2026-09-02T01:24Z ~ 01:45Z(UTC;覆盖 PA-0E 后 ~8.5 小时运行)
- 生产主机: tesla-t4(VM-0-4-ubuntu)
- 授权: PRODUCTION_READ_ONLY_ACCESS = AUTHORIZED;**本 Gate 零变更**(观察到的变更全部来自 cron 调度器自身与管理端人工动作,见 §6/§9)
- 结论: **PARTIAL** — 服务面(backend/DB/检索/持久化/GPU-backend)全程稳定;但发现 **1 个新 P0(corpus 完整性)**与 1 个 P1(sync 循环失败),PRODUCTION_ACTIVATION_DECISION = **C. NOT_READY**(仅限 sync/corpus 面)

---

## 1. PF-G001 Identity / Drift — PASS(全部 EXPECTED,零漂移)

| 对象 | 现场(01:24Z) | PA-0D/PA-0E 冻结值 | 漂移 |
|---|---|---|---|
| backend Image / git_sha | `05f7d396…` / `1ed84bb…` | 同 | 无 |
| backend StartedAt / Restarts / Health / OOMKilled | 2026-09-01T16:40:16Z / 0 / healthy / false | 同 | 无 |
| sync-cron Image / git_sha | `05f7d396…` / `1ed84bb…` | 同 | 无 |
| sync-cron StartedAt / Restarts | 2026-09-01T17:01:47Z / 0 | 同 | 无 |
| postgres / weaviate | running+healthy,StartedAt 2026-08-17,Restarts=0 | 同 | 无 |
| tooling | `41a7a2d` | 同 | 无 |

## 2. PF-G002 Backend Stability — PASS

- 运行 8h44m(至观察时):running、healthy、Restarts=0、OOMKilled=false、无退出史。
- 全量错误扫描(自 PA-0D 起):**唯一命中 = 1 次** `intent.py:74 JSONDecodeError` → 按设计 **fail-open 为 product**(WARNING,单次,自恢复,非 P0/P1)。
- 请求面:`/health` 200(1046 次);`POST /api/ask` 200 ×2(= PA-0D/PA-0E 受控冒烟,无其他 ask 流量);admin API 全部 200;`GET /` 404 ×3 为反代探测(benign)。无 5xx。
- 无 CUDA OOM、无 DB/Weaviate/LLM 重复失败、无检索失败循环。

## 3. PF-G003 Sync-Cron Runtime Stability — **FAIL**(一个源处于活跃失败循环)

**调度器本身健康**:8 小时内 8 个整点周期(18:04→01:34,每小时,漂移 = 运行时长),容器 Restarts=0,无 fatal;14/15 源每轮 success 无变更(窗口正常推进);woocommerce-mall 保持 PA-0E 闭环(success,40 unchanged,无重试环)。

**website-camthink:连续 8 轮 failed**(18:08、19:12、20:16、21:20、22:25、23:29、00:33、01:37),根因两级:
1. **GPU 容量(已知残留,本轮实证未解)**:cron 侧 embedder 需 ~2.5G,常驻 15.37/15.56G 无位 → CUDA OOM;
2. **一致性缺口持续存在**(见 §5/§9:账本 vs 实际不一致),使每轮都进入 refill/self-heal → 触发 embed → OOM → failed → 窗口不推进 → 下轮重复。01:37 轮实测:refill 47 篇 → 全部 OOM 失败。

**GPU_SYNC_RUNTIME_POLICY = KNOWN_UNRESOLVED**(生产证据证实,非推测;管理端内联同步因复用 backend 常驻 embedder 可成功,见 §9)。

## 4. PF-G004 PostgreSQL Runtime Health — PASS

- healthy、Restarts=0(自 08-17);conversations **107** / traces **107**(= PA-0E 后 +2,即两次受控冒烟,各自成功持久化含 trace);documents 10,389;sync_log 124,668(每小时 cron 行为正常)。
- `conversations.site_id` 列在位;`site_experiences`(3 行)、`llm_allowed_hosts` 表在位。
- 日志无 UndefinedColumn / 持久化失败 / 事务失败 / 连接耗尽。

## 5. PF-G005 Weaviate / Corpus Stability — **FAIL(相对 PA-0E 验收态发生重大未授权-in-Gate 变化,已定位写入门径)**

| 维度 | PA-0E 验收 | 本 Gate 实测(01:33Z) | Δ |
|---|---|---|---|
| TOTAL | 126,400 | **126,204** | **−196** |
| web_crawl | 359 | **163** | **−196** |
| github / filesystem / woocommerce | 125,459 / 481 / 101 | 不变 | 0 |
| visibility | api=widget=全量 | api=widget=126,204(语义零变化) | 0 |

**变化定位(全部证据只读取得)**:
- 唯一成功的写入窗口 = **2026-09-02T01:23:10Z 管理端人工触发** `POST /api/admin/data-sources/website-camthink/sync`(非本 Gate 发起;backend 进程内联执行,01:23–01:25,112 篇全部报成功);
- cron 周期 18:08–00:33 全部 failed 且 **items=0**(embed 前即 OOM,零写入零删除);
- 结果:web_crawl 对象 359→163(**净删除 196**),而 documents 账本记 123 篇/361 chunks(其中本轮 touched 110 篇 = **348 chunks**)——**账本(348/361)与实际(163)结构性背离**;
- 逐篇实例:`blog/ai-species-identification-camera-trap-images` 账本 chunk_count=4、日志"4/4 chunk 成功",实际仅存 chunk_index=0 一个对象——**写入成功后对象被删除**;
- 唯一删除机制 = ingest 成功后的 `_prune_stale_chunks`(按 `source_id` TEXT 属性 equal 过滤 + `chunk_index >= current_count` 删除)。**该过滤在 TEXT 属性上受分词语义影响(仓库已知:TEXT like/Equal 分词不可靠),对路径型 source_id 存在过度匹配/误删同前缀兄弟文档 chunks 的缺陷特征**;精确机制需实现级调查(本 Gate 只读,不深挖不修复)。
- 内容正确性:每页 chunk 数显著下降(旧 ~3.7/篇 → 新 ~1.5/篇)也可能混有重抽取内容变化因素,需单独内容级审查(本 Gate 禁止导出语料正文)。

## 6. PF-G006 Trust Boundary Runtime State — PASS(相对 PA-0E 零回归)

- `SourceVisibilityGuard 已启用` 在位(PA-0D 启动日志);运行期无 visibility 刷新失败、无 ghost/未知源拦截事件、无 fail-open 迹象(扫描零命中)。
- `channel_visibility` 元数据:api=widget=126,204,与 PA-0E 语义一致(全库默认公开,15 源 config 仍无覆盖键)。
- 本 Gate 未改任何配置(PA-0F 不涉内部源标记决策)。

## 7. PF-G007 GPU Runtime Stability

- **BACKEND_GPU_HEALTH = PASS**:backend(pid 1257699)3,866 MiB 常驻健康,工作集稳定(3.78→3.87G),零 CUDA 错误;常驻四进程(root 3,492 / llama-server 5,910 / neomind 2,466)与 PA-0D/0E 一致,utilization 0%。
- **SYNC_GPU_CAPACITY = INSUFFICIENT_FOR_INCREMENTAL_EMBEDDING**(15.56G 中常驻 15.37G;cron 侧 embedder 无法加载;8 轮 OOM 实证)。

## 8. PF-G008 Production API / Persistence Evidence

- **NATURAL_TRAFFIC = NOT_VERIFIED**:PA-0E 之后无自然 `/api/ask` 流量(仅本 Gate 前的两次受控冒烟,渠道 admin)。未制造流量(遵守只读低扰动)。
- 历史(仍有效)证据:PA-0D 冒烟(conversation/trace 持久化 is_answered=t,5 引用)、PA-0E 冒烟(引用含当轮新灌文档)。
- 管理面真实使用正常:admin UI 会话/数据源/分析端点全 200,并成功触发了一次内联同步(该动作的 corpus 后果见 §5/§9)。

## 9. PF-G009 Error / Regression Scan(逐项 CAUSE→IMPACT→RECOVERY→CURRENT_STATE)

| # | 命中 | 定性 | CAUSE | IMPACT | RECOVERY | CURRENT |
|---|---|---|---|---|---|---|
| 1 | intent JSONDecodeError ×1 | WARNING | LLM 返回非 JSON | 单次意图退化为 product | 设计内 fail-open | 已自愈,无重复 |
| 2 | website-camthink cron failed ×8 | **P1** | GPU 容量(已知)× 一致性缺口(新) | 该源同步不可用、窗口冻结、每小时重试空转 | 需容量/策略处置 | **活跃未解** |
| 3 | **web_crawl 重灌后净删除 196 对象、账本-实际背离(348/361 vs 163)、逐篇丢块(4→1)** | **P0** | RC ingest `_prune_stale_chunks` 的 TEXT source_id 过滤缺陷特征(过度删除)+ 可能混入重抽取差异 | 官网知识检索覆盖损失、同步永不收敛(refill 47 篇持续 OOM)、再次人工同步会重复该破坏 | 无(需实现修复) | **活跃未解** |
| 4 | `GET /` 404(反代探测)、passlib/transformers deprecation | INFO | 既有 | 无 | — | 稳定 |

已知残留 vs 新回归:**#2 的 GPU 容量为已知残留但当前处于活跃失败循环;#3 为本 Gate 新发现的 P0(由管理端人工同步触发显形,机制指向 RC ingest prune 路径)**。

## 10. PF-G010 Production Activation Exit Decision

- 服务面四项硬条件(backend 健康/DB 健康/Weaviate 健康/正常检索健康)满足;
- 但合同明确:**正常生产同步当前不健康时不得使用 PASS_WITH_KNOWN_RESIDUAL** —— 现状正是:一个源连续 8 轮失败 + corpus 发生未收敛的完整性破坏。
- **PRODUCTION_ACTIVATION_DECISION = C. PRODUCTION_ACTIVATION_NOT_READY**(范围限定:sync/corpus 面未就绪;backend 服务面本身保持 PA-0D 验收质量)。

## 11. Evidence Summary

| 字段 | 值 |
|---|---|
| PRODUCTION_HOST | tesla-t4 (VM-0-4-ubuntu) |
| BACKEND_IMAGE / GIT_SHA / HEALTH / RESTARTS / OOM | sha256:05f7d396… / 1ed84bb… / healthy / 0 / false |
| BACKEND_GPU_HEALTH | PASS |
| SYNC_IMAGE / GIT_SHA / RESTARTS | sha256:05f7d396… / 1ed84bb… / 0 |
| SYNC_CYCLES_AFTER_PA0E | 8(每小时,调度正常) |
| SYNC_LAST_STATUS | 14 源 success;website-camthink **failed**(01:37,refill 47 篇 OOM) |
| SYNC_REPEATED_FAILURE | YES(website-camthink ×8) |
| SYNC_GPU_CAPACITY | INSUFFICIENT_FOR_INCREMENTAL_EMBEDDING(KNOWN_UNRESOLVED,实证) |
| POSTGRES_HEALTH / CONVERSATIONS / TRACES | healthy / 107 / 107 |
| WEAVIATE_HEALTH | 服务健康(schema/聚合/读取正常) |
| CORPUS_TOTAL / DELTA_FROM_PA0E | 126,204(**−196**) |
| CORPUS_BY_SOURCE_TYPE | github 125,459 / filesystem 481 / web_crawl **163** / woocommerce 101 |
| CORPUS_VISIBILITY | api=126,204 且 widget=126,204(语义零变化) |
| TRUST_BOUNDARY_STATUS | PASS(零回归) |
| NATURAL_TRAFFIC | NOT_VERIFIED(无自然流量;未制造) |
| POST_UPGRADE_API_STATUS | 受控冒烟历史证据有效;管理面正常 |
| POST_UPGRADE_PERSISTENCE_STATUS | PASS(冒烟两轮 conversation+trace 均落库) |
| NEW_P0 | web_crawl 重灌静默删块/账本-实际背离(详见 §5/§9#3) |
| NEW_P1 | website-camthink 同步循环失败(GPU×缺口,§9#2) |
| KNOWN_RESIDUALS | GPU sync embed 容量(KNOWN_UNRESOLVED,实证未解);内部源 channel_visibility 标记决策待定 |
| PRODUCTION_MUTATION_PERFORMED | **NO**(本 Gate 全部动作为只读观察) |

## 12. STOP 与移交建议(非本 Gate 范围,需新合同/授权)

1. **P0 实现任务**:调查修复 RC ingest `_prune_stale_chunks` 对路径型 source_id 的删除语义(TEXT 分词过滤不可靠 → 应按精确 UUID/迭代器点名);并裁决 359→163 的内容正确性(内容级审查)。
2. **Sync Embedding Runtime Policy**:GPU 容量永久决策(释放显存 / CPU 通道 / 后端进程内嵌通道)。
3. 上述两项解决并修复后,需新 Gate 对 website-camthink 做收敛验收(账本↔实际一致)。

**STATUS = PARTIAL**
