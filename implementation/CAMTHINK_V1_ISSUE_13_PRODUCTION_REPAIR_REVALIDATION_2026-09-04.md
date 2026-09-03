# CamThink V1 — Issue #13 Production Data Repair Final Revalidation(READ-ONLY)

- 日期:2026-09-03T23:17Z → 2026-09-03T23:40Z(UTC,授权任务标注 2026-09-04)
- 生产版本:**v1.0.0 / 0e6a8a3bb72932b26fcf500954aacfe109373133**
- 执行模式:SINGLE EXECUTOR;**授权=只读观测;PRODUCTION_MUTATIONS=NONE(达成)**
- 结论:**READY_FOR_PROD_REPAIR_AUTHORIZATION**(附 4 项授权条件,见 §8)

---

## 1. READ_ONLY_BOUNDARY_PROOF(§3:先证明,后运行)

**invocation**:`python scripts/repair_corpus.py --source <id>`(v1.0.0 镜像内,经 `compose run --rm` 一次性容器;**无 `--apply`、无 `--check-source`**)。

代码级证明(0e6a8a3 树逐行核验):
1. CLI `scripts/repair_corpus.py`:`--apply` 为 `action="store_true"`(缺省 False);dry-run 分支在打印计划后 **`return 0` 提前返回**;`tool.apply(plan)`(唯一写入口)位于 `if not args.apply: return 0` 之后,无 `--apply` **不可达**。
2. `CorpusRepairTool.plan()`(backend/services/corpus_repair.py:140-257):数据来源仅 `_ledger_rows`(SELECT)、`_duplicate_hashes`(SELECT GROUP BY)、`historical_artifact_verdict`(纯路径判定,零 I/O)、`verify_source_vectors`(既有只读对账器)。**零写动词**。
3. 写动词全部位于 `apply()`/`_delete_ledger_row`(SQL DELETE)/`collection.data.delete_many`/`_rebuild_ledger_row`(零 embed INSERT),全部在 `--apply` 门后。
4. `_NoEmbedEmbedder`:任何 embed 路径显式 raise——**本工具结构性不可能 re-embed**。
5. 其余观测均为只读原语:`docker exec`(容器内 python/curl/psql SELECT)、`docker inspect/create+cp(RELEASE.json)`、宿主侧日志/JSON 落 `~/ask-ai/backups/`(宿主文件系统新增备份文件,非生产服务状态)。

**证据文件(生产机 `~/ask-ai/backups/repair_dryrun_v1.0.0_20260903T232101Z/`)**:15 源 × `{src}.json`(计划)+ `{src}.stderr`。15/15 exit=0。

## 2. PRODUCTION_RELEASE(§1)

- 三服务逐容器 `docker inspect`:`tesla-t4-{backend,sync-cron,sync-executor}-1` image = `ghcr.io/harryhua-ai/ask-ai:v1.0.0`,state=running(backend healthy,up since 16:51/16:52Z)
- 运行中 backend 容器 OCI label `org.opencontainers.image.revision` = 0e6a8a3bb72932b26fcf500954aacfe109373133
- `GET /health` = `{"status":"ok","version":"1.0.0","git_sha":"0e6a8a3bb72932b26fcf500954aacfe109373133","app_mode":"production"}`
- 镜像 RELEASE.json(version=1.0.0,git_sha=0e6a8a3…)与 origin/main(=0e6a8a3)三方一致,**无混版**

## 3. DOCUMENT_IDENTITY_STATE(§2)

| 项 | 值 | 判定 |
| --- | --- | --- |
| documents PK | `PRIMARY KEY (source_id)` | ✓ #13 新契约在产 |
| ledger 行数 | **11,933**(部署时 11,801,+132) | ✓ delta 已归因(§5) |
| duplicate source_id | **0** | ✓ |
| 已知 D2 对 `0cb4ff1daf5f`(lowpower-camera hw-v1.2 littlefs LICENSE + ne301 main littlefs LICENSE) | **2 行均在** | ✓ 跨前缀合法共存存活 |

## 4. NATURAL_SYNC_STATE(§2)

- 部署后每小时自然 tick 全部完成:最新 tick 22:27–22:31Z(Runs 277–284,15/15 `completed`),全库 `finished_at IS NULL` = 0
- executor 零 ERROR(仅既有 SAWarning 化妆品级);无新 CUDA 事件
- **新 identity contract 下 ingestion 正常**:部署后 132 行新增 ledger 自然写入(§5),无 UniqueViolation/身份冲突
- 最新 per-source consistency facts(每源最新 run):**missing 全 0**;orphan_count 仅 neoruntime-apps=2、website-camthink=5(ne503-sdk-local 的 orphan=1 为**陈旧事实**,该前缀在账本与 Weaviate 双侧均已无残留)

## 5. 精确修复集(§4)与 baseline delta(§5)

### 5.1 当前权威全量对账(15 源 dry-run,23:21–23:25Z)

**12/15 源零条目**(aitoolstack、knowledge-support、lowpower-camera、meta-hailo、ne301、neomind×4、neoruntime-sdks 除外注、website、wiki、woocommerce 中仅下列 4 源非零):

| Source | Action | Entries | Docs/Chunks | 明细 |
| --- | --- | --- | --- | --- |
| neoruntime-apps-1eea74dd | RETIRE_UNSAFE_ARTIFACT | 5 | 2 孤儿文档/21,520 chunks + 3 账本文档/38,874 chunks | 全部 `.hef`:orphan=`examples/object-detection/models/person_vehicle_v1.hef`(10,760)、`examples/people-counting/models/person_v1.hef`(10,760);ledger-bearing=`examples/person-detection/models/person-detection.hef`(10,760)、`showcases/gym-ops/models/hailo_yolov8n_384_640.hef`(7,590)、`showcases/gym-ops/models/yolov8s_pose.hef`(20,524) |
| website-camthink | REBUILD_ORPHAN_LEDGER_ROW | 5 | 5 docs/5 chunks(每文档 1 chunk) | `product`、`product/ne301`、`register`、`solutions/infrastructure-monitoring`、`tools`(安全路径孤儿 → 零 embed 账本收养) |
| ne503-apic-69d3594b | REPORT_DUPLICATE_IDENTITY | 103 | 206 docs/9,112 chunks | 源内同内容跨分支对(D2 合法,**零变更**) |
| neoruntime-sdks-67cbac8f | REPORT_DUPLICATE_IDENTITY | 2 | 4 docs/30 chunks | 同上(D2,**零变更**) |
| 其余 11 源 | — | 0 | 0 | 完全干净 |

### 5.2 汇总字段

- **MISSING = 0**(全源最新 consistency facts + Weaviate 总量 208,009 稳定交叉证实)
- **ORPHAN_DOCUMENTS = 7**(apps 2 个 .hef + website 5)
- **ORPHAN_VECTORS(chunk 级)= 21,525**(.hef 21,520 + website 5)
- **POLLUTED_ARTIFACT_CHUNKS = 60,394**(全部 `.hef`;其中账本内 38,874 + 孤儿 21,520,两类不相交);**无 .so/.bin/其他禁扩展命中**(MODEL_ARTIFACT_EXTS 判定下仅 .hef)
- **repair_required**:neoruntime-apps=true(pollution)、website-camthink=true(orphans)、其余 13 源 false

### 5.3 BASELINE_DELTA(对照 09-03 只读验收 baseline:139 孤儿/5 源、38,874 污染、missing=0)

Baseline 构成(docs 仓 421b559 §6):ne301=21(+287ch)、ne503-apic=108(+4,556ch)、neoruntime-apps=3(+21,521ch)、neoruntime-sdks=2(+15ch)、website=5(+5ch)。

| 源 | baseline | 当前 | delta 归因(证据) |
| --- | --- | --- | --- |
| ne503-apic | 108 孤儿 | **0** | **+108 ledger 行(部署后 updated_at 实证)**——CUDA 事故窗「向量已写/账本 pending」的文档随自然 tick 完成入账;随之首次显现 103 对源内 D2(跨分支同内容,本就存在于向量侧) |
| ne301 | 21 孤儿 | **0** | **+21 ledger 行**——16:53 cron 日志「21 孤儿」同批收敛;22:28 事实 orphan=0 |
| neoruntime-sdks | 2 孤儿 | **0** | **+2 ledger 行**(用户重建源 67cbac8f 的首个成功 tick);现余 2 对 D2 REPORT(合法) |
| neoruntime-apps | 3 孤儿 | **2 孤儿 + 污染 3 行账本内** | +1 ledger 行(其中 1 文档入账);其余 2 个即 .hef 孤儿(退休类);**38,874 污染分毫未变**(10,760+7,590+20,524=38,874 逐项吻合) |
| website | 5 孤儿 | **5** | 既有 EXTRA_UNRESOLVED_ORPHAN 循环,零增长零消退(每小时 partial 的同一批,tool 现分类为安全路径 → 账本收养) |

**总收敛恒等式:139 − 132 = 7;11,801 + 132 = 11,933**——部署后 ledger 增量 +108/+21/+2/+1(逐源)与 baseline 孤儿消解**逐源精确对应**,即 baseline 139 中 132 个已由自然同步在 v1.0.0 新契约下合法入账,余 7 个为真待修集。**38,874 污染:不变;missing:保持 0。** 所有变化均有 ledger 行级/sync_runs facts/Weaviate 前缀扫描证据,无未解释漂移。

## 6. D2_SIBLING_PROOF(§2/§6)

- 已知跨前缀对 `0cb4ff1daf5f…`:2 行均在(PK=source_id 下合法共存),`plan()` 单前缀扫描不视其为重复(前缀过滤),**任何 retirement 条目都不含这两行**。
- 新显现 105 对**源内** D2(ne503-apic 103 + sdks 2):`REPORT_DUPLICATE_IDENTITY` 在 `apply()` 中**第一分支即 `skipped (report-only per D2)` + `continue`**(corpus_repair.py:271-274,逐行核验)——计划包含它们仅为审计呈现,**结构性零变更**。
- 安全证明补充:D2 行均有账本行且路径安全(非 artifact),不落入 RETIRE(判据=扩展名)/REBUILD(判据=无账本行)任一 Target 集合。

## 7. 安全证明(§6)与 MUTATION_PREVIEW(§7)

安全证明:
1. **不删账本必需 chunks**:RETIRE 目标仅两类——(a) 扩展名判定 unsafe(.hef ∈ MODEL_ARTIFACT_EXTS,确定性);(b) **按定义无账本行**的孤儿向量。两者之外的任何 chunk 不进入枚举。
2. **不删合法 D2 sibling**:见 §6(apply 显式 skip;跨前缀对不在任何前缀计划内)。
3. **不删现行 Technical Safety/Knowledge Eligibility 下合法对象**: Retirement 判据复用现行准入同一份 `TechnicalSafetyPolicy.check_path`(集成期已核,零复制);12 个零条目源 = 对账全等的直接证明。
4. **零 re-embed/零 rebuild**:`_NoEmbedEmbedder` raise 兜底;website 收养为**零 embed 账本 INSERT**(从向量 props 重建行,向量不动)。
5. **确定性枚举**:向量寻址 = `uuid5(source_id#i)`(与 ingest 同一函数);chunk_indices 升序;plan 可持久化审计(注:JSON 审计件含 path/count,chunk_indices 为 apply 时进程内确定性重算——apply 门应同进程 plan→apply)。
6. **收敛预期**:见 §8 EXPECTED_POST_REPAIR_STATE。

MUTATION_PREVIEW(四类区分):

| Category | Source | Object Type | Count | Reason | Proposed Action | Rollback/Recovery | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **safe deterministic retirement** | neoruntime-apps | .hef 孤儿向量 | 2 docs / 21,520 chunks | model_artifact_ext + orphan_no_ledger_row | `--apply`(uuid5 delete_many,不触账本) | 不可恢复且无需恢复:现行准入禁止 .hef 再灌(重灌即拒),退休即终态 | HIGH |
| **safe deterministic retirement** | neoruntime-apps | .hef 账本行 + 其向量 | 3 docs(行)/ 38,874 chunks | model_artifact_ext(Technical Safety 覆盖 Admin allowlist) | `--apply`(删 3 账本行 + uuid5 向量) | 账本行可由 pg_dump(2970cbb8… + 后续新 dump)恢复;向量同上不可/无需恢复 | HIGH |
| **safe deterministic ledger adoption** | website-camthink | ledger 行(零 embed INSERT) | 5 rows | orphan_no_ledger_row(安全路径) | `--apply`(REBUILD_ORPHAN_LEDGER_ROW;向量不动) | 完全可逆(按 source_id DELETE 5 行);检索语义零变化(5 页向量本就可检索,收养仅为账本收敛) | HIGH(可选人工复核:5 页有抽取 partial 史) |
| **requires rebuild** | —(missing=0) | — | 0 | — | 无 | — | — |
| **requires manual review(非 mutation)** | ne503-apic / neoruntime-sdks | D2 同内容对(信息呈现) | 105 对 / 9,112 chunks | same_content_multiple_paths | REPORT-only;apply 强制 skip;可选产品裁决(分支重复是否优化) | n/a | — |
| **must not touch** | 全部 15 源 | 其余一切(含跨前缀 D2 `0cb4ff1daf5f`) | ~147,315 chunks + 全部健康源 | 契约 | 零动作 | n/a | — |

## 8. EXPECTED_POST_REPAIR_STATE / ROLLBACK_RECOVERY(§6)

Apply(全部三类)后预期:
- Weaviate:208,009 → **147,615**(−60,394,全部 .hef)
- ledger:11,933 − 3(.hef 行)+ 5(website 收养)= **11,935**
- 全源最新 consistency:**orphan_count=0、polluted_artifact_chunks=0、repair_required=false**;website 每小时 partial 循环收敛为 expected==actual 全成功;Knowledge Health 的 Consistency 维全源 ok(ACTION_REQUIRED 清零;freshness/ingest 维仍按自身权威独立计算)
- 检索面:仅移除 .hef 二进制噪声 chunk(#5 迁移后它们挂着 neoruntime 产品标签,本就是检索噪声);website 5 页检索行为零变化

ROLLBACK_RECOVERY:
- apply 前 must:新 pg_dump(现锚 2970cbb8… 为 09-03 版,账本已 +132)+ plan JSON 持久化(已在 `repair_dryrun_v1.0.0_20260903T232101Z/`)
- 账本侧全部可逆(dump 恢复 / 按 source_id DELETE);向量侧退休不可逆但语义终态(准入拒绝再灌);网站收养可逆
- 互斥纪律:apply 必须在 **writer-stop 窗口**(停 sync-cron+sync-executor,复用部署门同款流程)内执行——CLI 自述「与在线同步窗口互斥」

## 9. AUTHORIZATION_RECOMMENDATION(§8)

**READY_FOR_PROD_REPAIR_AUTHORIZATION**,附授权条件:
1. apply 窗口 = writer-stop(sync-cron + sync-executor stop → apply → update 式恢复),backend 可继续只读 Q&A;
2. apply 前新做 pg_dump + 复跑 dry-run 比对本报告数字(源级条目数须一致;自然同步若再收敛 website/孤儿,数字只减不增,逐项解释即可);
3. 建议同进程 plan→apply(CLI 单命令即此语义);逐源执行,先 neoruntime-apps(retire)后 website(adopt),任一失败即停(apply 单项失败不中断但以 failed 如实报告,exit=1);
4. website 收养(5 行)可独立裁决:若产品倾向重爬取文本而非收养,授权范围可仅含 neoruntime-apps——工具按 `--source` 天然圈定。

## 10. 返回字段

```
STATUS                      = READ_ONLY_PASS / READY_FOR_PROD_REPAIR_AUTHORIZATION
PRODUCTION_RELEASE          = v1.0.0 / 0e6a8a3bb72932b26fcf500954aacfe109373133(三服务一致 healthy)
READ_ONLY_BOUNDARY_PROOF    = CLI --apply 缺省 False + dry-run 提前 return;plan() 零写动词(SELECT+纯函数+只读对账器);apply() 唯一写路径在 --apply 门后;_NoEmbedEmbedder 结构性禁 embed;其余观测全为只读原语;15/15 dry-run exit=0
DOCUMENT_IDENTITY_STATE     = PK=(source_id);ledger 11,933;dup source_id=0;跨前缀 D2 对 0cb4ff1daf5f 双行存活
NATURAL_SYNC_STATE          = 部署后全部小时 tick completed(最新 22:27–22:31Z Runs 277–284);unfinished=0;新契约下 +132 行自然入账零身份冲突
MISSING                     = 0(全源)
ORPHAN_DOCUMENTS            = 7(neoruntime-apps 2 + website 5;baseline 139 → 收敛 132,见 BASELINE_DELTA)
ORPHAN_VECTORS              = 21,525 chunks(.hef 21,520 + website 5)
POLLUTED_ARTIFACT_CHUNKS    = 60,394(全 .hef;账本内 38,874 + 孤儿 21,520;无 .so/.bin 命中)
SOURCE_BREAKDOWN            = apps: retire 5 条(2 孤儿+3 账本)/60,394ch;website: rebuild 5 行;ne503-apic: D2 REPORT 103 对;neoruntime-sdks: D2 REPORT 2 对;其余 11 源零条目
ARTIFACT_BREAKDOWN          = person_vehicle_v1.hef 10,760(孤儿);person_v1.hef 10,760(孤儿);person-detection.hef 10,760(账本);hailo_yolov8n_384_640.hef 7,590(账本);yolov8s_pose.hef 20,524(账本)
BASELINE_DELTA              = 139→7 孤儿(132=+108 apic/+21 ne301/+2 sdks/+1 apps 逐源精确入账,恒等式 11,801+132=11,933);38,874 污染不变;missing 保持 0;新信息增量=105 对源内 D2 显现(apic/sdks 收带入账后可见,合法共存)
D2_SIBLING_PROOF            = 已知对 2 行存活且不在任何 retire/rebuild 枚举;apply() 对 REPORT_DUPLICATE_IDENTITY 首分支 skip+continue(逐行核验);单前缀计划不含跨前缀对
MUTATION_PREVIEW            = 见 §7 表(safe retirement 60,394ch+3行;safe adoption 5行;requires rebuild=0;manual review=105 对 D2 非mutation;must not touch=其余全部)
MANUAL_REVIEW_SET           = ①105 对源内 D2(产品可选裁决,零变更);②website 收养 vs 重爬(可从授权范围剔除);③apply 时 website 5 行的 props 抽查(收养数据源为向量 props)
EXPECTED_POST_REPAIR_STATE  = Weaviate 147,615;ledger 11,935;全源 orphan/polluted/repair_required 清零;website partial 循环收敛;ACTION_REQUIRED 清零;检索仅移除 .hef 噪声
ROLLBACK_RECOVERY           = apply 前新 pg_dump + plan JSON 已存证;账本侧全可逆;向量退休为语义终态(准入拒绝再灌);apply 须 writer-stop 窗口(CLI 互斥纪律)
AUTHORIZATION_RECOMMENDATION = READY_FOR_PROD_REPAIR_AUTHORIZATION(附 §9 四条件)
REPORT_PATH                 = docs/implementation/CAMTHINK_V1_ISSUE_13_PRODUCTION_REPAIR_REVALIDATION_2026-09-04.md
REPORT_COMMIT               = <见 docs 仓提交>
PRODUCTION_MUTATIONS        = NONE
```

**STOP。未执行任何 repair;未产生任何生产变更。**
