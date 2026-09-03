# Production Data Sync Observation — 手动三源(ne301 / neoruntime / neoruntime-sdks)+ GPU 加速验证

- 日期:2026-09-03(观察窗 07:33–07:50 UTC)
- 执行:Production Data Sync Observer(严格 READ-ONLY,零生产写操作)
- 生产 release:**sha-1d6f6b5**(backend / sync-cron / sync-executor 三容器一致,git_sha 核验通过)
- 主机:VM-0-4-ubuntu(up 393d)

## STATUS: COMPLETED_WITH_WARNINGS

| 项 | 值 |
|---|---|
| PRODUCTION_RELEASE | sha-1d6f6b5(=目标 1d6f6b5fe697b,三服务统一,零重启) |
| OBSERVED_SOURCE | UI ne301=`ne301-local`;UI neoruntime=`ne503-apic-69d3594b`;UI neoruntime-sdks=`ne503-sdk-local`(经 documents 账本篇数 5454/1296/110 与 UI 完全吻合确认映射) |
| TRIGGER | manual(Admin 同步按钮 → sync_requests;非 cron) |
| REQUEST_ID | 10 (ne301-local) / 11 (ne503-apic-69d3594b) / 12 (ne503-sdk-local) |
| SYNC_RUN_ID | 40 / 41 / 42 |
| ATTEMPT | 全部 attempt=1,无 retry |
| STARTED_AT | 07:41:34 / 07:42:25 / 07:43:14 UTC(request 10→11→12 由 sync-executor **单槽串行**接管,picked_at 链严丝合缝) |
| FINISHED_AT | 07:42:03 / 07:42:53 / 07:43:42 UTC(各 ~30s) |
| FINAL_STAGE | 三 run 全部 `completed / stage=DONE` |
| SYNC_LOG | 202a2bce…(ne301)/ cd2e9658…(neoruntime)/ f6296243…(sdks),**status=partial**(存在已知一致性缺口,非 success) |

## 真实同步进展(不是 UI 表面"成功")

本轮三个手动 run **没有做任何文档灌入**:

- `items_new=0, items_updated=0, items_deleted=0, items_unchanged=0` — 三个源上游(GitHub camthink-ai/*)HEAD SHA 自 07:29–07:35 的 cron 扫描后无新提交 → **SHA 短路跳过枚举**,0 重复灌入(设计行为,非故障;对照:本地目录源 aitoolstack-local 在 07:02/07:06 两次手动同步均实测枚举 37 files 全 unchanged,status=success)。
- run 的实际工作 = BGE 模型加载 + 一致性校验。status=partial 的唯一原因是下述**存量孤儿缺口**,与本次点击操作无关。
- 生命周期完整性审计**全绿**:`terminal_runs_no_log=0, stale_running=0, stale_requests=0`;42 个 run 的 request→run→sync_log 链全部闭合;无重复 attempt、无孤儿 request/run/log。

## 向量库真值(Weaviate vs Postgres 账本,只读实测)

| 源(UI 名) | 账本 docs | 账本期望 chunks | Weaviate 实际 chunks | 缺口 | orphans |
|---|---|---|---|---|---|
| ne301 | 5,454 | 67,126 | 67,413 | **+287** | 21 |
| neoruntime | 1,296 | 15,657 | 20,198 | **+4,541** | 103 |
| neoruntime-sdks | 110 | 604 | 605 | **+1** | 1 |
| (同晨 cron 另见)neoruntime-apps | 62 | 39,155 | 60,675 | **+21,520** | 2 |

**全局对账**:Weaviate Document 总对象 **207,294** vs 账本 15 源期望合计 **180,940** → 超出 **26,354**,与上述各源实测缺口之和(26,349)+ 未拉取源零星缺口**精确吻合** — Wave-0 一致性遥测可信,UI"补齐"徽章数字(67413/6712x、20198/156x、605/604)即 sync_runs.consistency 的 actual/expected 原值。

## GPU 加速:是,证据链完整

进入向量库的 embedding **确实调用 T4 GPU 加速**,四层证据:

1. **容器直通**:backend / sync-executor / sync-cron 三容器 `DeviceRequests=[{Driver:nvidia, Count:-1, Capabilities:[[gpu]]}]`;
2. **显式配置**:三容器 `EMBEDDER_DEVICE=cuda`,`EMBEDDER_BATCH_SIZE=16`,`EMBEDDER_MAX_LENGTH=1024`,模型挂载 `/models`(只读);
3. **运行时日志**:sync-executor 在每次手动同步前 `加载 BGE-m3 嵌入模型(device=cuda, cache=/models)…BGE-m3 加载完成`(今晨 07:02/07:06/07:07/07:08/07:15/07:18/07:19/07:41… 共 10+ 次);backend 常驻加载 BGE-m3 + **bge-reranker-v2-m3** 均 `device=cuda`(在线问答检索/重排同样走 GPU);
4. **nvidia-smi 实测**:backend 进程(PID 1743061,`/app/.venv/bin/python -m backend.main`)常驻显存 3.75–3.84 GiB;GPU 全局 15,415/16,384 MiB。

⚠️ **GPU 也是本轮唯一失败的根因**:07:32:46 cron 扫描 `neomind-local` 检测到上游 12 篇文档变更(GitHub NeoMind repo 增量),批量 embed 604 段文本时 **CUDA out of memory(需 490MiB,仅剩 415.56MiB)** — 显存被 5 个进程瓜分(root server.py 3.41G + llama-server 5.77G + neomind-extension-runner 2.12G + ask-ai backend 3.75G + 其他 0.1G);批量失败→自动回退逐 doc→逐个同样 OOM→12 篇全部索引失败→run 35 `failed`。**这是结构性 lottery 风险**(共享 GPU 近饱和时任何需要 embed 的同步都可能失败),与 PA-0E 已知"15.37/15.56G embed 必 OOM"警告一致。12 篇失败为**干净失败**(账本仍 873 篇,无 partial write 污染),但 neomind-local 知识**落后上游 12 篇**,需 GPU 有余量时重试。

## Safety / Admission Filtering(真实发生)

cron 扫描日志实测 Stage1 技术安全排除生效:
`技术安全排除 examples/object-detection/models/person_vehicle_v1.hef: model_artifact_ext ext=.hef`(neoruntime-apps 源,同类多处)— model artifact 按扩展名正确拦截。本轮三手动源无新文档故无新过滤事件。

## 发现的结构性缺陷(非本次操作造成,建议立项)

1. **孤儿账本重建 UniqueViolation(解释所有"补齐"徽章)**:reconciliation 对"Weaviate 有、账本无"的孤儿做零 embed 账本重建时,INSERT 撞 `documents_pkey (content_hash, branch)`:`duplicate key value violates unique constraint "documents_pkey"`。根因=账本按**内容哈希**寻址,而同内容不同路径的文件(LICENSE.txt / CMSIS 头文件 / cJSON.c / syscalls.c 等跨目录拷贝,甚至 `libcrypt.so.1` 二进制)哈希相同 → 每轮重建失败→孤儿永久保留→每轮重复检测→UI 永久"补齐"。今晨失败行数:ne301=42 / ne503-apic=206 / ne503-sdk=2(=orphan_count×2 轮,吻合)。Weaviate +26,354 冗余 chunks 由此而来。**修复需账本主键设计评审(加入 path/source 维度)或孤儿精确退休授权**,观察期不动。
2. **sync_runs.counters 恒为 `{}`**:per-file discovered/admitted/parsed/indexed 统计未持久化(run 级 `NOT OBSERVABLE WITH CURRENT TELEMETRY`),真实入库过程只能靠容器日志回溯。
3. **BGE 模型逐 run 重复加载**:每次手动 run 冷加载 ~17s(06:33 起 10+ 次),既拖慢同步也放大显存峰值/OOM 概率 — 常驻化或 LRU 复用是明显优化点。
4. **swap 3.7/4.0 GiB 偏高**(RAM available 尚有 12Gi,非同步致急迫,但长期紧绷);磁盘充裕(948G free);load 0.86/8 核正常。

## 运行时安全

- backend `/health` = `{"status":"ok"}`(观察首末各一次);backend 日志 90 分钟窗内**无 5xx/Traceback**;
- 三容器 RestartCount=0,up since 06:21–06:22 UTC(今晨部署),postgres/weaviate healthy;
- 同步未阻塞在线 backend(embed 在 sync-executor/sync-cron 进程内,符合阶段9 隔离设计;今晨唯一 504 类风险路径未复现);
- DB 连接无耗尽迹象,无 DB error(除上述被捕获的预期约束冲突)。

## DATA_INTEGRITY

- 三个手动源:账本与 Weaviate **零意外变化**(无清零、无暴涨、无重复写入、无 partial write);
- neomind-local:缺失 12 篇(干净失败可重试),账本 873 篇与向量一致;
- 全局:Weaviate 冗余 +26,354 为**存量孤儿**(多于账本但方向单一,无 missing=0、stale=0),不损害检索正确性,浪费存储并造成 UI 永久"补齐"提示。

## OBSERVABILITY_GAPS

- run 级 per-file admission 计数未持久化(counters={});
- sync_log.items_unchanged 语义在 GitHub SHA 短路路径记 0(与本地源全枚举路径不可比),易误读;
- Weaviate TEXT 属性过滤分词不可靠,全局计数采用无过滤 aggregate 交叉验证(可靠)。

## PRODUCTION_MUTATIONS: NONE

全部操作=只读 SQL SELECT、docker ps/inspect/logs/top/stats(只读)、nvidia-smi、/health GET、Weaviate aggregate(只读)。未点击任何同步/删除,未执行任何 UPDATE/INSERT/DELETE/migration/restart。

---

### Conclusion

你点击的三个手动同步**真实完成且安全**:sync-executor 单槽串行 30 秒/个,上游无变更故零重复灌入,账本与向量库零污染。UI"同步中"结束时变回的"补齐"徽章是**存量孤儿缺口**(260+ 篇跨目录同内容文件 + 1 个 .so 二进制卡在账本重建 PK 冲突上),不是本次操作失败。GPU 加速确认存在于"文档→向量库"全链路(embed=cuda、rerank=cuda),但共享 GPU 近饱和,已实际导致 neomind-local 12 篇 OOM 失败 — 这是当前同步体系唯一的真实失败点。整体运行面:backend/问答服务健康、零重启、无 5xx、资源平稳(swap 偏高为长岭)。

### Evidence(关键证据索引)

- `sync_requests` id=10/11/12(manual,done,attempt=1);`sync_runs` id=40/41/42(completed/DONE,~30s,has_log=true);`sync_log` 三行 status=partial items 全 0;
- `sync_runs.consistency`:40→67413/67126/21 orphans;41→20198/15657/103;42→605/604/1;
- Weaviate `Document.aggregate.over_all` total=207,294;documents 账本 GROUP BY 前缀 15 源合计 180,940 chunks;
- sync-executor/cron/backend 日志:`加载 BGE-m3 嵌入模型(device=cuda)`×10+;`批量 embed 失败(604 texts): CUDA out of memory…415.56 MiB is free`;`索引失败 neomind-local/…(×12)`;`技术安全排除 …*.hef`;`孤儿 … 账本重建失败…UniqueViolation`×250;
- docker inspect DeviceRequests(nvidia 全卡直通)×3;env `EMBEDDER_DEVICE=cuda`×3;nvidia-smi 1743061=backend 3.84GiB;
- 完整性审计三查全 0(terminal_runs_no_log/stale_running/stale_requests)。

### Next Action

**SAFE_TO_CONTINUE_CANARY_SYNC**(带三个附带条件):

1. **neomind-local 待 GPU 余量窗口再点同步**(12 篇可安全重试;连续 OOM 只浪费一次尝试,数据无风险);
2. "补齐"徽章在三源会持续存在直至孤儿 PK 设计修复 — **不要**用反复点同步来消除它(每轮都是 SHA 短路+同样的 partial);
3. 孤儿账本重建 UniqueViolation(账本主键内容寻址 vs 向量库路径寻址的结构错配)与 sync executor BGE 逐 run 冷加载,建议作为独立工程任务立项(本观察不实施)。
