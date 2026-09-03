# 生产同步观察后续报告:neoruntime-sdks 删除重建同步失败 RCA + GPU 两模型问题裁决

- **日期**: 2026-09-03(观察窗 07:33–08:40 UTC)
- **性质**: 严格只读生产观察 + 只读根因分析(侧聊跟进,前序报告 f4714d6 / `PRODUCTION_SYNC_OBSERVATION_2026-09-03_ne301-neoruntime-sdks.md`)
- **生产 release**: `1d6f6b5fe697b5f7a1b8decef1c29f51afcda937`(backend / sync-cron / sync-executor 三容器镜像 `sha-1d6f6b5` 一致,零重启)
- **PRODUCTION_MUTATIONS: NONE**(全程 SELECT / docker logs / docker inspect / 只读 python 诊断 / nvidia-smi / journalctl / Weaviate aggregate 计数)

```
STATUS:                    FAILED(sync embed 通道被容器级 CUDA 故障阻断;SHA 短路型同步不受影响)
PRODUCTION_RELEASE:        1d6f6b5(三服务一致,重启计数 0,backend healthy)
OBSERVED_SOURCE:           neoruntime-sdks-67cbac8f(重建新源)+ ne503-sdk-local(已删旧源)+ neomind-local(附带破案)
TRIGGER:                   manual(用户 Admin 点击,request 14/15)
REQUEST_ID:                14(08:15:52)、15(08:20:xx,重试点击)
SYNC_RUN_ID:               58(08:16:14→08:16:24,failed)、59(08:20:46→08:20:51,failed)
ATTEMPT:                   各 1(注意:request 级无自动重试,next_retry_at 空)
STARTED_AT:                2026-09-03 08:16:14 UTC
FINISHED_AT:               2026-09-03 08:16:24 UTC(10.6 秒全量失败)
FINAL_STAGE:               -(failed,未到 stage 终态标记;sync_runs.status=failed)
SYNC_LOG:                  status=failed,error_detail=「192 个文档灌入失败(可能 embed/写库故障,需重试)」
INGESTION_COUNTS:          discovered=192(github 抓取成功);indexed=0;embedded=0;失败=192/192(100%)
SAFETY_FILTER_RESULT:      无触发(失败发生在 embed,不在准入层)
DOCUMENT_STATE:            新源 PG 账本 0 行、Weaviate 0 块(干净无半写);UI「0 篇」如实
BACKEND_HEALTH:            ok(/health 200;注意:backend 老进程 CUDA 上下文存活,与新进程故障并存)
SYNC_EXECUTOR_HEALTH:      进程活着(restarts=0)但 GPU 能力已断(见 §5)
RESTARTS:                  三容器均为 0
RESOURCE_PRESSURE:         VRAM 15.56G 中他户占 ~11.4G(llama-server 5.77+root python 3.41+neomind 2.12),backend 3.75G;RAM swap 3.6/4G 满
ERRORS_WARNINGS:           「No CUDA GPUs are available」×192;cuInit ret=100;nvmlInit_v2 ret=999;07:32 cron 另有 CUDA OOM ×12(独立模式)
DATA_INTEGRITY:            无新损坏;存量孤儿债 +36(旧 sdk 源删除残留,见 §6)
OBSERVABILITY_GAPS:        sync_runs.counters 恒空 {} / run DONE vs sync_log partial 语义分裂 / request done vs run failed / UI「完成」不区分 SHA 短路零工作(§7)
```

---

## §1 结论(TL;DR)

1. **用户删除重建操作本身执行干净,不是失败原因。** 删除的是 UI 显示名「neoruntime-sdks」对应旧源 `ne503-sdk-local`(账本 110 篇/604 块同步清零),08:15:41 重建为 `neoruntime-sdks-67cbac8f`(新 file_types 发现 192 个文件)。
2. **直接根因:sync-executor 容器内新建 CUDA 上下文完全不可用**——`cuInit(0)` 返回 **100(CUDA_ERROR_NO_DEVICE)**、`nvmlInit_v2()` 返回 **999**;同刻主机 `cuInit=0` 完全健康、backend 06:21 启动的老进程上下文仍存活(稳占 3842 MiB)。故障层面 = 容器环境 ↔ 主机驱动边界(疑似 device cgroup / nvidia-container-runtime 状态),**发生在 07:32:47–08:16:14 之间的窗口**(07:32 cron 容器还能成功 init CUDA,08:16 executor 首次真实 init 即失败)。
3. **生产配置无回退路径**:`EMBEDDER_DEVICE=cuda` 显式指定,`detect_device()` 对显式值原样放行(`backend/embedder/base.py:25-26`);`ingest.py:462` 契约 = 任一 doc 失败即整体 RuntimeError → 192/192 全灭,账本零写入。
4. **附带破案:07:32 neomind-local 12 篇失败 = 另一个独立的病(显存耗尽)**,完整 OOM 报文实证:GPU 15.56G 仅剩 415.56 MiB(llama-server 5.77G + root python 3.41G + neomind 2.12G + backend 3.75G 四户瓜分),单批 embed 需 490 MiB → torch OOM。即记忆中「15.37/15.56G embed 必 OOM」的现行实例。
5. 当前生产存在**两个 GPU 病**:①容器新建上下文不可用(阻断一切 embed,硬失败);②共享 GPU 慢性显存不足(即使①修复,大源批量 embed 随时再 OOM)。

## §2 用户三次点击的真实映射(命名陷阱)

UI 显示名 ≠ source_id。`data_sources.config` 中无 name 字段,显示名实际取自 repo_url 推导;逐一以 repo_url 对齐:

| UI 显示名 | source_id | repo_url | 今日手动记录 |
|---|---|---|---|
| ne301 | `ne301-local` | …/ne301.git | request 10 → run 40 completed(DONE,partial)|
| neoruntime | `ne503-apic-69d3594b` | …/neoruntime.git | request 11 → run 41 completed(DONE,partial)|
| neoruntime-sdks | ~~`ne503-sdk-local`~~ → `neoruntime-sdks-67cbac8f` | …/neoruntime-sdks.git | request 12 → run 42 completed;**删除重建后** request 14/15 → run 58/59 **failed** |
| (neoruntime-apps) | `neoruntime-apps-1eea74dd` | …/neoruntime-apps.git | 仅 cron(用户称删建了它,实际未动:`updated_at` 仍为 09-02)|

07:41:12–13 三条 request 在 1.5 秒内连续创建,picked_at 串行(07:41:14/07:42:05/07:42:55)——sync-executor 单并发逐源消费,符合设计。

## §3 「实际并没有真正同步完成(完成到向量库)」裁决

**裁决:内容都在向量库,没有丢失;但用户点击的「同步」确实什么都没做——两个判断同时成立。**

时间线(全部实证):
- 02:54 / 03:15 UTC — ne301、neoruntime-sdks 仓库新提交(GitHub API 实查 HEAD);
- **03:35 UTC — 部署前(旧进程)完成真实摄取**:ne301 5454 篇/67126 块、ne503-sdk 110 篇/604 块写入账本并 embed(`documents.max(updated_at)=03:35:06/03:35:38`);因 Wave-0 `sync_runs` 表 06:22 才建,该轮只在 `sync_log` 留痕;
- 06:22 / 07:29 两轮 cron + 07:41 三次手动 — 仓库无新提交 → **GitHub commit SHA 短路**:零抽取、零 embed、**连模型都不加载**(executor 07:40–07:44 零日志输出;items 全 0;duration 28–31s 全花在 clone+对账);
- run 级 `completed/DONE` 与 sync_log 业务态 `partial` 分裂:partial 原因 = 一致性缺口(向量库孤儿块),非内容缺失。

账本 = expected 权威的实证(`documents` 表按 `source_id` 前缀聚合,`source_id` 实为 `源/分支/路径` 复合串):

| 源 | 账本 docs/chunks | consistency expected | Weaviate 实测(actual)| 缺口(missing=0)|
|---|---|---|---|---|
| aitoolstack-local | 37 / 955 | 955 | **955(精确相等)** | 无 |
| ne301-local | 5454 / 67126 | 67126 | ~67.4k(count 67413) | +287 孤儿块 / 21 孤儿 doc |
| ne503-apic-69d3594b | 1296 / 15657 | 15657 | 20198(精确) | +4541 / 103 |
| ne503-sdk-local(旧)| 110 / 604 | 604 | —(已删)| — |
| neoruntime-apps-1eea74dd | 62 / 39155 | 39155 | 60675(精确) | +21520 / 2 |

抽样可检索性实证:Weaviate 取出 `ne301-local/main/Appli/Core/Inc/adc.h` 真实 C 代码 chunk(text 可读、chunk_type=code、url 指向 GitHub blob、channel_visibility=['widget','api'])。

## §4 「同步期间两个模型都必须载入显卡吗?」——不需要,只有一个必须

| 模型 | 用途 | 同步期是否需要 | 生产实况 |
|---|---|---|---|
| BGE-M3(embedder)| 文本→向量 | **必须** | sync-executor **逐请求重载**(~16s/次,日志实证 06:33/07:02/07:06/07:07/07:08/07:15/07:18),用完随子进程释放;SHA 短路时**连加载都不发生**(08:00–08:05 扫描零加载日志)|
| bge-reranker-v2-m3(reranker)| 问答时重排 | **完全不需要** | 仅 backend 启动时常驻加载(device=cuda);执行器日志中 reranker 加载记录为零 |

显存预算(08:16 前后):总计 16384 MiB,他户常驻 ~11.4G + backend 3842 MiB → 同步 embed 高峰再叠 executor 的 BGE-M3 副本(约 2.3G fp16 + 490MiB/批激活)即逼近上限——07:32 的 OOM 正是该峰值。结论:**reranker 不占同步的显存代价;embedder 上 GPU 是配置选择而非硬性必须**(可 `EMBEDDER_DEVICE=cpu`,慢数倍)。

## §5 删除重建同步失败 RCA(核心)

### 5.1 故障证据链(按序)

1. run 58 failed 10.6s,192/192 全灭,错误摘要「可能 embed/写库故障」(该文案为 `ingest.py:462` 的猜测性 summary,真实异常在其上层的逐 doc 日志);
2. 执行器真实异常(docker logs,08:16:20):`批量 embed 失败(570 texts): No CUDA GPUs are available,回退逐 doc` → 192 条 `索引失败 …: No CUDA GPUs are available`;08:20:46 request 15 重试同灭(run 59);
3. 驱动级(ctypes 直调,容器内外对照):

   | 对象 | cuInit(0) | nvmlInit_v2() | 结论 |
   |---|---|---|---|
   | 主机 python3 | **0** / device=1 | — | 主机驱动健康 |
   | executor 容器 | **100** | **999** | 容器新建上下文被拒 |
   | backend 容器新进程 | —(torch device_count=0)| — | 同病 |
   | backend 容器**老进程**(06:21 起)| — | — | 上下文存活,占 3842 MiB,问答链路未受影响 |
   | cron 容器(07:32)| 成功(能走到 torch OOM 即证明 init 成功)| — | 当时还正常 → 故障窗口 07:32:47–08:16:14 |

4. 排除项:设备节点主次号主机↔容器一致(nvidia0=195:0、nvidiactl=195:255、nvidia-uvm=511:0/1,mtime 2025-08-06 未变 → 排除 uvm 重载/节点陈旧);驱动版本处处 575.64.03(dpkg 四包一致,libcuda/libnvidia-ml mtime 2025-07-02 → 排除静默升级);journal 07:30–08:20 无 GPU/NVRM 事件;fd 上限 1048576 未耗尽。
5. 未决:精确触发点不可证(主机 uptime 393 天,dmesg 环形缓冲早已轮转;journal 无记录)。**不排除**共享 GPU 上他户进程异常退出/驱动内部状态劣化导致容器侧新客户端被拒;现有日志无法进一步归因。

### 5.2 为什么是「全灭」而不是降级

- `EMBEDDER_DEVICE=cuda`(三容器 env 实查)→ `detect_device()` 原样放行,无 CPU 回退;
- `ingest.py` 契约:批量 embed 失败→逐 doc 重试(逐条同错)→ 汇总 RuntimeError → run failed、账本零写。
- 「BGE-m3 加载完成」日志为惰性构造假象——load 成功 ≠ GPU 可用,首次 encode 才暴露。

### 5.3 删除重建操作的核验(用户操作无责)

- 旧源删除:PG 账本 `ne503-sdk-local/%` 0 行(清零);Weaviate 604→**36 块残留**(清理不彻底,见 §6);
- 新源创建:08:15:41,file_types 扩容(.cmake/.hpp/.in/.ini/.json 等)→ 抓取 192 篇成功(08:16:15 日志「抓取到 192 篇文档」),失败全部发生在 embed 层;
- 用户自述「删掉了 neoruntime-apps」与事实不符:`neoruntime-apps-1eea74dd` 未被动过(updated_at=09-02);实删的是 neoruntime-sdks(UI 命名歧义所致,见 §2)。

### 5.4 后续将自动发生

cron 每小时扫描(上轮 07:29–07:35,下轮约 08:35),新源 192 篇等不到 embed → **每小时继续失败一次**,直至 GPU 恢复。

## §6 数据完整性观察(含存量债)

- 新源 0 行/0 块,无半写、无重复、无清零事故;
- 存量孤儿债(账本外 Weaviate 块,EXTRA_CONFIRMED_RETIRED=0 待安全退休):neoruntime-apps +21520(2 doc)、ne503-apic +4541(103)、ne301 +287(21)、ne503-sdk +1(1);
- **新增**:旧 sdk 源删除残留 +36 块(604→36,删除路径清理不彻底——新缺陷线索,建议并入孤儿 reconciliation 处理);
- 已知脏数据(账本内,准入层放行):`.hef` 二进制模型文件被切块入库(yolov8s_pose.hef 单文件 20524 块、person-detection.hef 10760、hailo_yolov8n_384_640.hef 7590,合计 ~38.9k 块 = neoruntime-apps 账本的 99%)、`.so` 二进制(libpcre2-8 950 块)——`.hef` 污染 DEFERRED 既有问题,建议排除二进制扩展名准入。

## §7 观测缺口(建议立项)

1. `sync_runs.counters` 恒为 `{}`——run 级无 discovered/admitted/parsed/indexed 持久化,真实摄取证据只能翻容器日志(NOT OBSERVABLE WITH CURRENT TELEMETRY);
2. run `completed/DONE` vs sync_log `partial` 语义分裂;request `done`(exit 0)vs run `failed` 分裂;
3. UI「同步中…/完成」不透出 SHA 短路零工作(用户体感「点了同步没反应」)与 partial(一致性缺口)被折叠成「完成」;
4. UI 显示名与 source_id 脱节(config 无 name 字段),排查成本高(本次 §2 即为此付出的对账);
5. sync-executor 子进程 stdout 在部分窗口不可见(日志管道时有时无),故障取证依赖 error_detail 摘要。

## §8 Next Action(全部需授权,本次未执行)

1. **立即**:强制重建三容器(`up -d --force-recreate backend sync-executor sync-cron`)重绑 GPU——大概率治愈 cuInit=100;避开同步窗口,backend 重启后首验 ~45s(BGE 加载)属正常;
2. 若重建无效 → 主机级驱动重载/重启,**必须先协调** llama-server / root python / neomind 三户(其上下文会同死);
3. **结构性**:同步 embed 显存隔离(executor/cron 改 `EMBEDDER_DEVICE=cpu`,或与 GPU 他户协商保底余量/时段),终结慢性 OOM;
4. GPU 恢复后:对新源重点「同步」,预期 192 篇入库;孤儿债 36+~26.4k 块并入 reconciliation;二进制准入排除(.hef/.so/.bin)立项。

## 附录:关键取证命令/SQL 摘要

```sql
-- 手动请求与 run(全部 done/failed 判定)
SELECT id,source_id,triggered_by,status,runner_exit_code FROM sync_requests WHERE created_at>'2026-09-03 07:45+00';
SELECT id,request_id,source_id,status,error_summary FROM sync_runs WHERE started_at>'2026-09-03 07:45+00';
-- 账本=expected 实证
SELECT substring(source_id from '^([^/]+)/') src, count(*), sum(chunk_count), max(updated_at) FROM documents GROUP BY 1;
-- 真实异常
SELECT l.error_detail FROM sync_log l JOIN sync_runs r ON r.sync_log_id=l.id WHERE r.id=58;
```

```bash
# 容器 vs 主机 CUDA 能力(决定性)
python3 -c "import ctypes; c=ctypes.CDLL('libcuda.so.1'); print(c.cuInit(0))"        # 主机: 0
docker exec tesla-t4-sync-executor-1 python -c "import ctypes; c=ctypes.CDLL('libcuda.so.1'); print(c.cuInit(0))"  # 容器: 100
docker exec tesla-t4-sync-executor-1 python -c "import ctypes; print(ctypes.CDLL('libnvidia-ml.so.1').nvmlInit_v2())"  # 999
# Weaviate 每源计数(aggregate + Filter.equal,已与 consistency actual 交叉验证)
coll.aggregate.over_all(total_count=True, filters=Filter.by_property('source_id').equal(sid))
```
