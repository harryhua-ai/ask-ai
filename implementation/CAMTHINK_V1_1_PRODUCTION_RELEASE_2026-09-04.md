# CAMTHINK V1.1.0 — Main Integration & Production Release Report

- 日期:2026-09-04
- 角色:Engineering Executor
- STATUS:**FINAL PRODUCTION PASS**(2026-09-04 发布定稿节授予;原 CANDIDATE READY / PARTIAL 结论依次被后续节取代,历史保留于各追加节)
- RECOMMENDED_PRODUCTION_VERDICT:**已授予并完成发布正式化**(Release v1.1.0,详见文末「发布定稿」节)
- Release:**v1.1.0**(annotated tag + GitHub Release,target=`762eae3b067f5adcc7c32a33996bfcaea3dab2bd` = main = 生产)
- 执行边界:发布正式化完成——tag/Release 已发,#22/#24 已带完成注释关闭,#14 历史语义保留未动

---

## == 发布定稿(2026-09-04)==

| 项 | 值 |
|---|---|
| Release | **v1.1.0**(annotated tag;`refs/tags/v1.1.0` → tag object 7f2cf354 → commit `762eae3…`;GitHub Release 已发布,targetCommitish=762eae3) |
| main = 生产 = tag | 三者同 SHA,逐一实证 |
| CI | 33885620242 success(test+build-and-push,head_sha=762eae3) |
| #22 | 已关闭(完成注释:Release/SHA/PASS/报告路径) |
| #24 | 已关闭(完成注释:Release/SHA/PASS/报告路径) |
| #14 | 历史已完成 issue,**未重开未改写**(保留其窄范围 Sync 回退语义) |

**FINAL PRODUCTION PASS 的容量证据定稿**(全部生产实测,详见下方容量门节):

- 规范 GPU UUID:`GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba`(torch/策略/nvidia-smi/Admin 单一身份);
- 数值化容量读数:total 16384 / used / free 全部实数(不再 unknown);
- 有效预算:auto **4210 MiB**;
- RUNTIME_PLAN = **reranker_transient**(容量证据驱动);
- 瞬态驻留实测:pre 1238 → peak ~3375(重排物化)→ post 1238 MiB(ASK-AI 口径),
  精确回落,7 连问首末采样恒定、零累积;
- 最低查询窗余量:**964 MiB**(双驻留形态 596 的 1.6×;稳态余量 3100 为其 5×);
- **CUDA OOM = 0**(三服务全量日志);
- 单一 backend GPU 模型所有权(执行器/cron 零 GPU 模型);
- Ask PASS(7/7 + 历史门 16/16)、Sync + Ask PASS(run 594 execution_device=gpu,sync 中 3/3 Ask);
- #22/#24 冒烟 PASS(preview-dirs 200;site-config 统一外观字段)。

原 PARTIAL 结论(容量门节)被本节取代:其不可判定项(§12 瞬态证明、§17 预算
驱动分级)已由 REV3.1(762eae3)补齐并通过;其其余证据(验收 A-D、单一所有权、
RCA 更正)继续有效。

**STOP 状态解除:发布正式化完成(tag/Release/#22/#24/roadmap),无遗留授权缺口。**

---

# == 容量门(RELEASE CANDIDATE 72cdcbf)== 历史节:REV0 发布门(2026-09-04 上午;结论已被文首定稿节取代)

## TARGET_VERSION

v1.1.0

## RELEASE_CANDIDATE

`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`(IMMUTABLE;全程零改动)

## PRE_RELEASE_MAIN

`0e6a8a3bb72932b26fcf500954aacfe109373133`(origin/main;实证为候选祖先,零偏离提交)

## MAIN_SHA

**`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`**(fast-forward:`git push origin b7a016d…:refs/heads/main`,`0e6a8a3..b7a016d`)

## MAIN_INTEGRATION

| 项 | 结果 |
|---|---|
| MAIN-1 origin/main 预期态 | 0e6a8a3 = final-rc-20260903,候选祖先 ✓ |
| MAIN-2 b7a016d 远程在位 | ✓ |
| MAIN-3 RC 血缘无新提交 | 0e6a8a3..b7a016d 恰 4 提交(2ba83d6→698e727→2306118→b7a016d),与已接受证据一致 ✓ |
| MAIN-4 不丢已接受提交 | FF 保留精确历史 ✓ |
| MAIN-5/6/7 | main contains 698e727 / 2306118 / b7a016d ✓ |
| MAIN-8 树内容零变化 | `git diff b7a016d MAIN_SHA` = 空 ✓ |
| MAIN-9 工作树干净 | 验证 worktree tracked 零改动 ✓ |
| MAIN-10 origin/main == MAIN_SHA | ✓ |

## POST_MERGE_CI

- Run **33853247365**(workflow_dispatch on main,headSha = MAIN_SHA):`test` **success** + `build-and-push` **success**
- CI-1..CI-4 ✓;CI-5:镜像内 RELEASE.json `git_sha=b7a016d…`、`ci_run_id=33853247365`(fail-closed 实证)
- 未复用 RC 分支镜像:部署物 = main 精确构建(避免任何同号异证歧义)

## IMAGE_TAG / IMAGE_DIGEST

- IMAGE_TAG:`ghcr.io/harryhua-ai/ask-ai:sha-b7a016d`
- RepoDigest:`sha256:8b009e8d50c247918e364a34d1908fac0b4d581fd58c2810e877172c94548135`
- ImageID:`sha256:16f7c74ec5ef81bfab2b0d956478b74052e47be8bb41c00d42c5a572167913ed`(运行容器与目标镜像逐一相等)
- RELEASE_METADATA:version `0.0.0+main.b7a016d0` / git_sha `b7a016d…` / built_at 2026-09-04T08:35:42Z / ci_run 33853247365
- DEPLOYMENT_TIME:**2026-09-04T08:54:51Z**(三服务同批切换)

## PRE_MIGRATION_STATE(DB-1..DB-5)

- 生产 schema 实证:site_experiences **11 列,零 launcher 列**(ba90450 基线态;DB-1/DB-2 → REV0+REV1 两段都需执行)
- 行数 3(camthink-website / camthink-wiki / camthink-store,全部 enabled)
- DB-4 备份:`~/ask-ai/backups/v110_release_20260904/`
  - `site_experiences_pre_v110.sql`(表级)
  - `pg_askai_pre_v1.1.0_20260904T082424Z.sql.gz`(全库,6.4MB)
- DB-5 schema 证据:上方列清单 + 备份内 CREATE TABLE

## MIGRATIONS_EXECUTED

目标镜像一次性容器(compose 网络内,凭据从运行中后端容器透传、零回显):
1. `scripts/migrate_add_site_launcher_appearance.py`(REV0:launcher_style/launcher_theme)
2. `scripts/migrate_add_site_launcher_icon_shape.py`(REV1:launcher_icon/launcher_shape)
3. 两脚本幂等重跑各一次(DB-15:与隔离彩排一致)

> 执行注记:首次尝试因镜像内缺 `PYTHONPATH=/app` 失败(ModuleNotFoundError),加 `-w /app -e PYTHONPATH=/app` 后成功——纯执行环境修正,未改任何代码。

## POST_MIGRATION_STATE(DB-6..DB-15)

- DB-6:launcher_style/theme/icon/shape 四列齐备 ✓
- DB-7:行数 3 保持 ✓;DB-8 site_id ✓;DB-9 allowed_origins ✓;DB-10 enabled ✓;DB-11 welcome/starters ✓
- DB-12:生产无遗留 launcher_style 数据(基线无此列)——空集成立,如实记录
- DB-13/14:四列全 NULL,零图稿 opt-in ✓
- DB-15:幂等重跑一致 ✓

## DEPLOYMENT

- DEPLOY-1 健康 PASS(部署后 ~25s 内 ok;GPU 预检 14,599/16,384 MiB)
- DEPLOY-2 `/health` → `git_sha=b7a016d…`(运行时身份 = 镜像身份 = MAIN_SHA)✓
- DEPLOY-3 运行容器 ImageID == 目标镜像 ImageID(16f7c74e…)✓
- DEPLOY-4 无迁移/schema mismatch 启动异常 ✓
- DEPLOY-5 Admin 加载(登录 200 + 数据面 API 200)✓
- DEPLOY-6 Widget 产物加载(widget.js/css 200)✓

## CORE_PRODUCTION_SMOKE

| 项 | 结果 |
|---|---|
| PA-CORE-1 health | ✓ |
| PA-CORE-2 Admin 认证 | ✓(登录签发 token) |
| PA-CORE-3 知识/源视图 | ✓(data-sources 200) |
| PA-CORE-4 Widget 加载 | ✓(同源产物 200) |
| PA-CORE-5 打开/关闭 | ✓(生产工件真实浏览器:launcher→ChatPanel→✕→launcher) |
| PA-CORE-6/7 ask + SSE | **先挫后复**:`**NE503…` 240 content token 流式 + done(详见 KNOWN_LIMITATIONS #1 的 GPU OOM 瞬态) |
| PA-CORE-8 引用/来源 | ✓(sources 事件随流返回) |
| PA-CORE-9/10 | ✓ 非预期错误为零(仅 2 次 OOM 瞬态已归因);无迁移异常循环 |

## ISSUE_22_PRODUCTION_ACCEPTANCE

- PA22-1 ✓ Source Center 数据面 API 200;PA22-3 ✓ 治理持久位(config JSONB `discovery_rules`)可读(当前空态=预采用预期);PA22-6 ✓ 持久化路径健康
- PA22-2/4/5:**NOT MUTATED IN RELEASE ACCEPTANCE** —— 依赖已接受的组合验收证据(RC 门 D22-1..10 全过,含 neomind-dashboard/components 具体案例);生产零发现策略改写、零同步
- 未为验收发起任何生产同步

## ISSUE_24_PRODUCTION_ACCEPTANCE

受控可逆变更 site:**camthink-wiki**(未实嵌 Widget,三站中影响面最小);变更前先验证兼容性。

- PA24-1 ✓ 未配置站 = current(兼容默认)
- PA24-2 ✓ 既有嵌入零改动(生产 widget.js 同路径同产物;本地页加载生产工件渲染正常)
- PA24-3/4 ✓ Admin 外观页数据面:3 站列表与持久值正确
- 受控变更:wiki NULL 素态 → `bot-sparkle / round / auto`(PA24-5 Save ✓;PA24-6 重读恢复 ✓;PA24-7 site-config(允许 Origin)即时反映 ✓)
- PA24-8 ✓ 客户嵌入零改动;PA24-9 ✓ 授权仍强制(变更期间错 Origin 仍 403)
- PA24-10 ✓ launcher 打开未变的真实 ChatPanel(生产工件活体)
- PA24-11 ✓ ask 恢复后同管道正常(全站同 ask 管道,PA-CORE-6 证据)
- **恢复**:SQL 将 wiki 四列复位 NULL(精确还原素态),Admin 呈现回到 current/rounded-square/auto,`restored_to_pristine = t` 复验 ✓

## SECURITY_SMOKE

- SEC-1 ✓ 允许 Origin → 200;SEC-2 ✓ 错 Origin → 403;SEC-3 ✓ 外观已设置 + 错 Origin 仍 403(外观不授予访问);SEC-4 ✓ 仅 site_id 无 Origin → 403(标识非凭证);SEC-5 ✓ Admin 外观 API 未认证 → 401
- 授权链代码在 ba90450→b7a016d 零改动(scope audit)

## OBSERVATION

- OBS-1 健康 8/8 稳定(1 分钟间隔 × 8 分钟,恢复后窗口)✓
- OBS-2 零迁移错误 ✓;OBS-3 恢复后近 8 分钟 ERROR=0 ✓
- OBS-4/5 Widget/Admin 产物与服务健康 ✓;OBS-6 ask 流恢复后健康 ✓
- OBS-7 Source Center 无回归迹象(数据面 200、同步面正常启动)✓
- OBS-8 生产数据零意外变更(3 站素态保持;变更台账仅含授权项)✓
- sync-executor 启动正常(独立执行面已启动;既存 SAWarning 为已知小修候选,与本发布无关)

## ROLLBACK_READINESS

- 备份:表级 + 全库 dump(见 PRE_MIGRATION);应用回滚 = `ASKAI_IMAGE_TAG=sha-ba90450` 同批三服务切换(上一不可变 tag)
- 回滚语义:launcher 四列为 additive nullable,旧镜像忽略之,launcher_style 在生产为空集 → 回滚行为确定
- 破坏性 schema 回滚(DROP COLUMN)未测试、不声称

## PRODUCTION_MUTATIONS(台账)

1. v1.1 DB 迁移执行(REV0+REV1,加列幂等 ×2 轮)
2. 三服务部署 MAIN_SHA 精确工件(sha-b7a016d)
3. camthink-wiki 受控外观变更 + 复位恢复(发布验收专用)
4. 最小 ask 冒烟流量(4 次;其中 2 次 OOM 瞬态产生 2 条失败会话记录,属正常冒烟数据)
5. 主机 /tmp 认证 token 临时文件用后删除

未授权项均未发生:无相关数据修复、无广域同步、无发现策略清理、无凭证/origin 策略变更、无生产测试数据污染、无无关配置编辑。

## KNOWN_LIMITATIONS

1. **GPU 显存争用瞬态(已恢复)**:部署后初始两次 ask 因宿主 CUDA OOM 失败(第三方共享服务 ~11.5G + 已知孤儿 root sync/backend 进程 ~3.7G 占满 15.56G;DeepSeek API 本身 200)。第三方进程释放显存后第三次 ask 起完全恢复并保持。归因:宿主环境既有状况(09-03 已有同类事故记录;ba90450..b7a016d 的 ask/embed 管道代码零改动);孤儿 root 进程清理须用户单独授权(不在本契约内);#14 embedder CPU 回退缺位为已知产品缺口,W2 契约已冻结待实现。
2. wiki/store 站当前未实嵌真实页面 → PA24-7 以 API 级 site-config 证据 + RC 门浏览器级渲染证据组合覆盖。
3. PA22-2/4/5 依赖 RC 门组合证据 + 生产只读健康(生产未做发现策略变异)。
4. 破坏性回滚未测(契约明示不要求)。
5. 主机孤儿 root sync.py/backend 进程(~3.7G VRAM)建议尽快单独授权清理,可显著缓解 OOM 复发风险。

## RECOMMENDED_PRODUCTION_VERDICT

**FINAL PRODUCTION PASS**(建议)—— MAIN 集成/CI/迁移/部署/验收/观察全链通过;唯一次生事件(GPU OOM)为宿主环境既有状况、已自愈并经 8 分钟稳定窗复验,不影响发布物正确性。Planner 拍板后进入 §16 正式化(v1.1.0 tag → GitHub Release → #22/#24 closure → Roadmap)。

---

# == 容量门(RELEASE CANDIDATE 72cdcbf)== 2026-09-04 追加;本节取代上方旧结论

> 本节依「MAIN INTEGRATION + PRODUCTION CAPACITY GATE(STATUS: AUTHORIZED)」执行。
> 上半部(b7a016d 发布门)中 KNOWN_LIMITATIONS #1/#5 的「孤儿进程」归因被本节
> §P **强制更正**;其 FINAL PASS 建议作废——容量证据当时即未采集, Planner 未授予。

## A. RELEASE_CANDIDATE / MAIN_INTEGRATION

| 项 | 证据 |
|---|---|
| RELEASE_CANDIDATE | **72cdcbf**(REV2;Planner verdict: ENGINEERING FINAL PASS) |
| 集成前 origin/main | `b7a016d…`(fetch 后核验,与门声明一致) |
| merge-base / ahead-behind | `b7a016d`;0 behind / 3 ahead(FF 可行) |
| 谱系 | `b7a016d → 35785a4(REV0) → 1e58dbd(REV1) → 72cdcbf(REV2)`,**fast-forward only** |
| 推送后 | `origin/main == main == 72cdcbf6a704138bd9a591d4cdf2a2c1884bf6d4` |
| 工作树注记 | 主仓检出原为陈旧分支 `codex/issue-14-w1-sync-runtime-reliability`(内容早已被吸收;分支未动);`.gitignore` 一行**既有未提交本地卫生行**(`ght/`)与候选树零交集——stash→FF→恢复,披露不隐瞒 |

## B. HOSTED_CI / IMAGE_PROVENANCE

- CI_RUN **33878095495**(head_sha 核验 = 72cdcbf6…):test ✅ + build-and-push ✅
- IMAGE_TAG `ghcr.io/harryhua-ai/ask-ai:sha-72cdcbf`
- IMAGE_DIGEST `sha256:d174819fa44e233f224c5cad029eef02d5f2628a69157f30eed70ca55c95b0ba`
- IMAGE_ID `sha256:4693d92ac826…`(生产 inspect)
- RELEASE.json:`git_sha=72cdcbf6a704…` 全串、`ci_run_id=33878095495`(fail-closed 实证;无浮动镜像歧义)

## C. RUNTIME_PLAN — undecided(候选缺陷;容量验收不可判定的根因)

实测:3 workloads configured=GPU/effective=GPU/loaded;shared_embedding_runtime=true;
**plan.mode=`undecided`**(reason: GPU 预算不可读)、容量分级=`unknown` →
**reranker_transient 未激活**,重排双驻留惰性物化(=v1.1 现状行为)。

**根因(生产容器内实证)**:torch `get_device_properties().uuid` 产出**无前缀**
`3caad314-…`,而容器内 `nvidia-smi --id=` 只认 `GPU-` 前缀形态:
`read_gpu_memory(短uuid)=None`,同容器 `read_gpu_memory(None)` 与
`read_gpu_memory("GPU-…")` 均正常(3100/16384)→ 单点 UUID 前缀格式不匹配。
后果链:预算不可读 → undecided(fail-safe=维持双驻留)→ B3 瞬态驻留与 B4 预算
驱动计划生产未激活;容量分级恒 unknown,UNSAFE/HEALTHY 无法如实呈现。

**拟议 REV3(供 Planner 立项)**:`read_gpu_memory` 全卡查询 + 本地归一化匹配
(strip `GPU-` 前缀)或 `--id` 前缀重试;单点小修 + 生产形态回归测试。

**为何非 FAIL**:fail-safe 按设计工作(证据不可读→维持现状+如实 unknown,不臆造),
§22 无任一实质失败条件;但 §12/§17 验收证据**不可判定**——按 §22 报 PARTIAL,不虚报。

## D. PRE_DEPLOY_BASELINE(只读)

- 生产 sha-b7a016d ×3 服务(healthy);镜像 `sha256:16f7c74e…`;
- DB:`model_runtime_*` 两表**不存在**(迁移未跑过);`sync_runs.execution_device` 在位;
- GPU:T4,UUID `GPU-3caad314-…`,**total 实测 16384 MiB**;used 15637/free 294;
  三方 = server.py 3492 + llama-server 5910 + neomind 2188 = **11592 MiB(全程零触碰)**;
  旧 backend 4044;有效容量 ≈ **4792 MiB**;
- 口径注记:门书「≈15.56 GiB」为发现期口径;实测 16384 MiB——按 §17 依实测评判。

## E. MIGRATION / DEPLOYMENT

- 备份 `~/ask-ai-backups/ask_ai-pre-72cdcbf-20260904-212954.sql.gz`(6.5MB);
- 迁移 ×2 幂等 ✓;两表建立、0 行(缺省=EMBEDDER_DEVICE 引导默认,GPU-first 保留,零回填);
- 顺序 migration → backend(health 30s,git_sha 断言✓)→ sync-executor → sync-cron,
  三服务统一 `sha-72cdcbf`,全程显式 ASKAI_IMAGE_TAG(无 latest 回落);
- 回滚锚:`sha-b7a016d` + 全库备份;未触发。

## F. 启动驻留 + GPU_MEMORY_TIMELINE(§10/§17)

| 时点 | used/free (MiB) | ASK-AI 驻留 |
|---|---|---|
| 部署前 | 15637 / 294 | 4044(旧 backend,双模型) |
| 新 backend 稳态(未 Ask) | 12831 / 3100 | **1238**(仅嵌入;重排权重在主机内存) |
| Acceptance A 峰值 | **15335 / 596** | 嵌入+重排物化+激活 |
| A 后稳态 | 15335 / 596 | 4070(双驻留形态,≈旧 4044) |
| sync 嵌入后 | **15799 / 132** | 4070(分配器缓存 +460) |

- **MINIMUM_HEADROOM = 132 MiB**(sync 嵌入缓存后);查询窗最低 596 MiB;
- §10 的「瞬态生效→不再复现 4044 驻留」论证**前提不成立**(瞬态未激活)——移交 REV3;
- 结构收益已兑现:sync 零模型装载/零 GPU 进程(与计划无关,恒生效)。

## G. ASK_ONLY_ACCEPTANCE(§11)

16/16 真实生产 Ask 成功;CUDA OOM=0(三服务全量日志 grep=0)。
无 sync 基线 6 连问:TTFT 2.75–7.87s / E2E 4.29–8.84s;RAG 分段:rerank
**1010–1871ms(GPU)**(旧 CPU 26.7s)、rewrite 468–766ms、search 50–73ms、
ttft 305–618ms、llm_total 837–2710ms。无累积增长迹象(样本有限,见 UNKNOWN)。

## H. TRANSIENT_RERANKER_ACCEPTANCE(§12)

**N/A — 未激活**。双驻留下重排「首跳物化后保持驻留」为设计语义(证据:1238→15335→稳态 15335)。
瞬态「用后卸载」显存证明需 REV3 后重测。不虚报。

## I/J. SYNC_ACCEPTANCE + ASK_SYNC + SYNC_REPEATED_ASK(§13-15)

- **真实嵌入同步(受控可逆测试文件注入 `experience/`,事后全清理)**:
  run 547 `execution_device="gpu"`、fallback_reason=NULL、completed;
  backend 日志 `POST /api/internal/embeddings 200`(来源=执行器容器);
  执行器:零「加载 BGE」日志、**零 GPU 进程** → §16 单一模型所有权实证
  (全机 4 个 compute PID:三方 3 个逐 PID 等于基线 + backend 1 个 4206 MiB);
- **C**:sync 运行中 3/3 Ask 成功(TTFT 3.26–8.63s);
- **D**:sync-all 滚动中 6/6 Ask 成功(TTFT 3.06–8.48s);20 分钟窗 18 runs 全
  completed,无饥饿(公平性语义另有候选内确定性并发测试背书);
- sync 嵌入后 free=132 MiB 紧态下探针 Ask 仍成功(分配器缓存复用),但该紧态
  无法被容量分级呈现(unknown)——缺陷后果,强化 PARTIAL。

## K. BUDGET CONTROL PLANE(§18,可逆)

manual 4096 写入→DB 落库→快照如实(manual/undecided)→恢复 auto→DB 复核
`auto/NULL`。保存-持久-恢复工作;「驱动计划」受同一读数缺陷阻断。生产未留变化。

## L. ADMIN_ACCEPTANCE(§19,真浏览器经 SSH 隧道)

模型配置双 Tab ✓;检索模型卡带「运行设备:Tesla T4 · GPU 0」硬件标签 ✓;LLM 流水线 ✓;
模型运行:可用执行设备(T4+CPU)、三 workload 卡(configured/effective/状态 + 双共享徽标)、
GPU 运行容量(自动管理=还原后状态)、容量与建议(容量未知/外部占用/ASK-AI 驻留 4.0GB/
「运行计划:维持当前驻留(预算不可读)」)✓;无 System Information 蔓延;零变更操作(除 §18 可逆)。

## M. ISSUE_22_SMOKE / ISSUE_24_SMOKE(§20)

- #22:`preview-dirs` 200(生产路径实测);数据源页正常;无回归迹象;
- #24:`site-config?site_id=camthink-wiki`(合法 Origin)返回 `launcher_icon=current /
  launcher_shape=rounded-square / launcher_theme=auto` + 遗留桥 `launcher_style=current`;
  widget.js 200。无回归迹象。

## P. RCA_CORRECTION(强制更正)

**更正前(错误)**:「孤儿 GPU 进程导致容量被占」(见上半部 KNOWN_LIMITATIONS #1/#5——作废)。
**更正后(正确)**:此前观察到的 backend/sync GPU PID **全部可归属**(在役容器正常
进程或 sync 运行期瞬态子进程,cgroup 归属实证),从不存在孤儿;结构性根因 =
**(1) 进程本地重复模型驻留**(sync 子进程自载 BGE GPU 副本)+ **(2) backend
嵌入+重排双模型常驻/峰值** 超出真实有效容量;本候选对症处置:单一模型所有权
(backend 唯一持有,sync 经内部端点消费——§16 生产实证)、驻留计划(因 §C 缺陷
本次未激活,REV3 激活)、有界 GPU 执行(已生效)。

## Q. RISKS / UNKNOWN / ROLLBACK_STATUS

- RISKS:①读数缺陷使容量分级不可见(HEALTHY/UNSAFE→全 unknown),sync 后 free
  曾至 132 MiB 运营不可见;②双驻留下 A 窗最低 free=596 贴近 512 保留,并发/大批量
  sync 下 OOM 风险真实(本次 16/16 零 OOM,样本有限);③生产 admin 默认密码既有隐患;
- UNKNOWN:sync 缓存增长长窗收敛性;REV3 后实际 plan 判定;
- ROLLBACK_STATUS:未触发;锚完备(`sha-b7a016d`+全库备份;迁移纯加表)。

## S. §25 FINAL EXECUTOR RETURN 摘要

| 字段 | 值 |
|---|---|
| STATUS | **PARTIAL** |
| MAIN_BEFORE → MAIN_AFTER | `b7a016d…` → `72cdcbf6…`(FF;origin/main 核验一致) |
| CI_RUN / CI_RESULT | 33878095495 / success(test+build-and-push,head_sha=72cdcbf) |
| IMAGE_TAG / DIGEST / ID | sha-72cdcbf / `sha256:d174819f…` / `sha256:4693d92a…` |
| MIGRATION_RESULT | ×2 幂等成功;两表 0 行;零回填 |
| PRODUCTION_SHA | 72cdcbf6a704138bd9a591d4cdf2a2c1884bf6d4(三服务统一,/health 实证) |
| RUNTIME_PLAN | **undecided**(读数缺陷)→ 双驻留回退;预期 transient 未激活 |
| GPU_TOTAL | 16384 MiB(实测) |
| EXTERNAL_GPU_USAGE | 11592 MiB(server.py 3492+llama 5910+neomind 2188;零触碰) |
| ASKAI_STEADY_GPU | 4070 MiB(Ask 后双驻留稳态);启动期 1238(仅嵌入) |
| ASKAI_PEAK_GPU | 15335 used 全窗(A 峰);sync 后 15799 |
| MINIMUM_HEADROOM | **132 MiB**(sync 嵌入缓存后);查询窗 596 |
| ASK_ONLY_RESULT | PASS:16/16,TTFT 2.75–7.87s,rerank GPU 1010–1871ms |
| TRANSIENT_RERANKER_RESULT | **N/A / 未激活**(计划 undecided;REV3 后重测) |
| SYNC_RESULT | PASS:run 547 execution_device=gpu + 内部端点 200 + 执行器零 GPU 进程 |
| ASK_SYNC_RESULT | PASS:sync 中 3/3 Ask 成功 |
| SYNC_REPEATED_ASK_RESULT | PASS:sync-all 中 6/6 + sync 后探针 1/1;20min 窗 18 runs 全 completed |
| CUDA_OOM_COUNT | **0**(三服务全量日志) |
| MODEL_OWNERSHIP_RESULT | 单一 backend 所有(4 PID=三方3+backend1);执行器/cron 零 GPU 模型 |
| ADMIN_ACCEPTANCE | PASS(真浏览器;双 Tab/真相面/共享徽标/容量未知如实) |
| ISSUE_22_SMOKE / ISSUE_24_SMOKE | PASS / PASS(preview-dirs 200;site-config 统一外观字段) |
| RCA_CORRECTION | §P(孤儿结论作废;根因=进程本地重复驻留+双模型常驻/峰值) |
| ROLLBACK_STATUS | 未触发;锚完备 |
| RISKS / UNKNOWN | §Q |
| REPORT_PATH | docs/implementation/CAMTHINK_V1_1_PRODUCTION_RELEASE_2026-09-04.md(本节) |
| REPORT_COMMIT | docs 仓本提交 |
| PRODUCTION_MUTATIONS | 上半部台账(作废部分以本节 §M/账本为准):镜像 pull+三服务更新(授权)、迁移×2、预算 manual→auto 还原、13 测试文档受控注入→全量清理(文件+weaviate 13 对象点删,复核归零)、/tmp 清理;**无 tag/Release/关单/三方触碰** |

**STOP。未打 tag、未发 Release、未关 #22/#24。等待 Planner 裁定(建议:授权 REV3
读数修复候选 → 重跑 §9-§12/§17-§18 四项 → 再议 FINAL PRODUCTION PASS)。**

---

# == REV3.1 生产容量 DELTA 门(候选 762eae3)== 2026-09-04 追加

> 基线:72cdcbf 生产态(上一节 PARTIAL);授权:REV3.1 生产容量 DELTA 门。
> 结果:**UUID 归一化缺陷修复在生产实证生效;§12/§17 容量证据补齐;全项 PASS 证据在案**。
> 未打 tag/未发 Release/未关 #22/#24 —— Planner 独立裁定 FINAL PRODUCTION PASS。

## REV3_1_SHA / CI / IMAGE

| 项 | 值 |
|---|---|
| REV3_1_SHA | **762eae3**(谱系 72cdcbf→ab0e29c→762eae3,严格直系无偏离;FF 集成) |
| MAIN_BEFORE → MAIN_AFTER | `72cdcbf…` → `762eae3…`(origin/main 推送后核验一致) |
| CI | Run **33885620242**(head_sha=762eae3 核验):test ✅ + build-and-push ✅ |
| IMAGE | tag `sha-762eae3`;digest `sha256:04215cb4aed7…`;ImageID `sha256:e9042cba…`;RELEASE.json `git_sha=762eae3b…` 全串 + `ci_run_id=33885620242` |

## UUID_NORMALIZATION_PROOF(§5 关键阻断复测——缺陷修复实证)

| 指标 | 72cdcbf(容量门) | **762eae3(本次)** |
|---|---|---|
| GPU UUID | 裸形 `3caad314-…` | **规范形 `GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba`** |
| 读数 | None(未知) | **数值快照:16384 / used 12831 / free 3100** |
| 有效预算 | null | **auto=4210 MiB**(数值) |
| RUNTIME_PLAN | undecided | **reranker_transient**(reason 如实;floors 4562/4050/3412) |
| CAPACITY_STATE | unknown | **HEALTHY** |
| 部署 | — | migration:无(REV3.1 无新迁移);backend→sync-executor→sync-cron,health 30s,三服务镜像逐一核验 |

## RUNTIME_PLAN / CAPACITY_STATE(§10)

plan=`reranker_transient`;容量=HEALTHY(预算 4210 ≥ 驻留 1110+512);
Configured/Effective/Status 全真;**residency=transient 经 API 如实暴露**
(query_embedding/sync_embedding=resident,query_reranker=transient);
容量不再因 UUID 格式原因 unknown——当前 unknown 全消。

## TRANSIENT_RESIDENCY_PROOF(§6;1s 采样 nvidia-smi 实测,非仅应用态字段)

| 阶段 | GPU used/free (MiB) | 语义 |
|---|---|---|
| **Ask 前**(瞬态稳态) | 12831 / **3100** | ASK-AI=1238(仅嵌入常驻);重排权重在主机内存 → **TRANSIENT_PRE** |
| **Ask 中**(重排物化) | 峰值 **14967 / 964** | 重排上卡(+~1150 权重+激活)→ **TRANSIENT_PEAK / MINIMUM_HEADROOM(查询窗)=964** |
| **Ask 后**(卸载完成) | **12831 / 3100** | 精确回落到 Ask 前水平 → **TRANSIENT_POST**;7 连问首末采样相同,**零累积增长** |

对照:双驻留形态(72cdcbf 容量门)Ask 后卡死在 free=596;瞬态卸载后 free=3100——
**查询余量提升 5×,B3 理论(瞬态峰≤4050 预算内)在生产实测成立**。

## GPU_MEMORY_TIMELINE / CAPACITY_NUMBERS(§9)

- GPU_TOTAL_MB = 16384;EXTERNAL_GPU_MB = 11592(三方逐 PID 与基线一致,零触碰);
- ASKAI_STARTUP_MB = 1110(仅嵌入);ASKAI_STEADY_MB = **1238/12841**(瞬态卸载后,非重排期);
- ASKAI_ASK_PEAK_MB ≈ 3375(全机 14967 − 三方 11592);
- ASKAI_ASK_SYNC_PEAK_MB:sync 嵌入批与 Ask 共享嵌入实例+闸互斥,未观测到超越
  Ask 峰的新峰值(sampler 窗内 max 仍 14967);
- MINIMUM_HEADROOM_MB = **964**(查询窗;对照双驻留 596);
- TRANSIENT_PRE/PEAK/POST = 1238 / ~3375 / 1238(ASK-AI 口径);
- **CUDA_OOM_COUNT = 0**(backend/sync-executor/sync-cron 全量日志)。

## ASK_RESULT(§7)

7/7 真实 Ask 成功(≥6 最低要求):TTFT 4.02–10.0s / E2E 4.55–11.16s;后端 RAG
分段 rerank 维持 GPU 毫秒级;瞬态卸载 7 次重复成功,首末 GPU 采样相同(无泄漏)。

## SYNC_ASK_RESULT(§8;受控真实嵌入,非短路)

- 受控注入 13 测试文档 → run 594:`execution_device="gpu"`、completed;
- backend 日志 `POST /api/internal/embeddings 200`(执行器容器来源);
- 执行器/cron:零「加载 BGE」日志、零 GPU 进程(sync 期全机 compute PID=
  三方 3 + backend 1 @1238 —— **单一 GPU 模型所有者**,无重复嵌入副本);
- sync 运行中 3/3 Ask 成功(TTFT 0.72–9.31s;首问为短答拒答形态,属正常);
- 清理:文件删除→resync→weaviate 13 对象 uuid 点删,复核 ksc=481 chunks(原态);
- sync 完成后 GPU 稳态 12841/3090(有界,无失控增长)。

## MODEL_OWNERSHIP

单一 backend GPU 模型所有者;执行器/cron 零 GPU 模型(全门沿用容量门 §16 结论,
本次部署后实测一致)。

## REGRESSION_SMOKE(§11 轻回归)

health 200(git_sha=762eae3b)✓;#22 preview-dirs 200 ✓;#24 site-config
(camthink-wiki,合法 Origin)返回统一外观字段 ✓。未重做全量验收(按契约)。

## RISKS

1. 重排瞬态化使每次 Ask 重排步含 ~0.5-1s 上卡开销(re-rank 总时长仍 1.0-1.9s
   GPU 量级,显著优于 CPU 26.7s);
2. 查询窗最低余量 964 MiB 健康,但三方显存若继续增长将压缩预算(计划器会如实
   降级——这正是容量分级恢复可见性后的保护);
3. 生产 admin 默认密码既有隐患(持续提醒)。

## UNKNOWN

- 长时窗(小时级)瞬态往返的分配器长期行为未测(观测窗 7 连问首末采样恒定);
- 多卡主机上的行为由单测 fixture 覆盖,未做多卡生产验证(生产单卡)。

## PRODUCTION_MUTATIONS(台账)

1. 镜像 `sha-762eae3` pull;三服务滚动更新(授权动作);
2. 受控测试语料 13 文件(experience/)注入→真实嵌入同步(594)→**文件删除+
   weaviate 13 对象 uuid 点删(复核归零,知识库恢复 481 chunks 原态)**;
3. /tmp 采样文件清理;
4. 未做:tag / GitHub Release / 关 #22/#24 / roadmap / 三方 GPU 触碰 / 迁移(无新迁移)。

## PRODUCTION_ACCEPTANCE_CANDIDATE 结论

REV3.1 在生产实证:UUID 归一化修复生效(§5 全项绿)、计划=**reranker_transient**
(容量证据驱动,非强推)、瞬态驻留以真实 nvidia-smi 采样证明(物化→卸载→精确回落)、
16+ 次跨门 Ask 与真实嵌入 sync 零 OOM、单一 GPU 模型所有权保持、容量分级恢复
数值化呈现。**Executor 证据链完整,提请 Planner 独立裁定 FINAL PRODUCTION PASS**
(通过后进入 v1.1.0 tag/Release/#22/#24 closure/roadmap 的 §16 正式化)。

**STOP。**
