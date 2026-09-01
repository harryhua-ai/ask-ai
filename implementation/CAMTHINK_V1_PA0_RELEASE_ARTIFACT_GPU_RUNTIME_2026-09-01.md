# CAMTHINK V1 — PA-0A Release Artifact Gate 执行报告(RC 镜像 CI 构建 + GHCR 溯源)

- 任务:CAMTHINK_V1_PA0_RELEASE_ARTIFACT_GPU_RUNTIME —— **PA-0A 范围**(2026-09-01
  范围修正后的当期交付;GPU 运行时验证部分按修正令明确移出本门)
- 基线 / RC:`1ed84bbfcad08224c8c322f7c7a7a817b8916147`(release/camthink-v1-rc-2026-09-01)
- 报告仓:docs 本地仓(分支 main)
- 执行仓:主仓 ask-ai(worktree `.worktrees/technical-insights`)

## 0. 范围修正的执行记录(如实)

原 PA-0 合同含真机 GPU 验证。执行早期(修正令到达前)曾对生产主机 `tesla-t4`
做过只读巡检与隔离验证栈试验,并创建了三个完全隔离的一次性容器
(`pa0-postgres`/`pa0-weaviate`/`pa0-backend`,专用网络 `pa0-net`,未挂载任何生产卷、
未连任何生产数据库)。收到修正令后:

1. **已将上述自建隔离产物全部删除**(`docker rm -f` 三个 pa0 容器 + `docker network rm`),
   删除后核验:无任何 `pa0*` 残留容器/网络;生产栈四容器
   (backend/sync-cron/postgres/weaviate)状态与持续运行时间不变(backend `Up 34 hours`
   贯穿前后)——即除自建隔离物外,生产主机未被修改;
2. 此后**未再访问生产主机**;全部剩余验证改在 GitHub CI / GHCR API / 本机完成。

以下所有"门"判定均基于修正后 PA-0A 范围;修正前的观察仅作附录 A 事实记录,
**不作为任何门的不声明式证据**。

## 1. Executive Result

**PA-0A Executor 自评:PASS(限 PA-0A 范围)。**

既有 CI(`.github/workflows/build-image.yml`,未建并行管线)以 `workflow_dispatch`
从 release 分支对**精确 RC SHA** 触发构建;test + build-and-push 双 job 成功;
GHCR 产出 `ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb`,**linux/amd64** 单平台,
经五级证据链(tag→run headSha→index digest→amd64 manifest→config 层历史 GIT_SHA)
溯源到 `1ed84bbfcad08224c8c322f7c7a7a817b8916147`,证据全部来自 GitHub API /
GHCR registry API(非生产上下文)。

GPU 运行时验证(Ubuntu NVIDIA 主机)按范围修正**不在本门执行**,移交 PA-0 正式门;
附录 A 记录了修正前观察到的**GPU 显存饱和(15633/16384 MiB,空闲 ~751 MiB)**
——这是下一门安排 GPU 冒烟前必须先解决的基础设施事实。

## 2. CI 构建(PA0-G001 / G002)

| 项 | 值 / 证据 |
| --- | --- |
| Workflow | `.github/workflows/build-image.yml`(既有管线,未新建) |
| 触发 | `gh workflow run build-image.yml --ref release/camthink-v1-rc-2026-09-01`(workflow_dispatch) |
| Run ID | **33524587791**(2026-09-01T15:15:11Z queued) |
| headSha | `1ed84bbfcad08224c8c322f7c7a7a817b8916147`(GitHub API `gh run view --json headSha`,与 RC commit 逐字节一致) |
| Jobs | `test`(RC 分支 pytest 子集)→ success;`build-and-push`(SPA build → buildx → push GHCR,`GIT_SHA={{github.sha}}` build-arg)→ success |
| 结论 | **PA0-G001 PASS**(构建自精确 RC 谱系);**PA0-G002 PASS**(权威构建成功并推送) |

## 3. 镜像溯源链(PA0-G003 / G004)

```
RC commit  1ed84bbfcad08224c8c322f7c7a7a817b8916147
   = CI run 33524587791.headSha        (GitHub API)
   → tag    ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb
   → index  sha256:ddacb7f5848d7544a717026572cf4c3b261b656e367cf6068dd1d4f8305d53d1
       ├─ linux/amd64  manifest sha256:3aa4e0f4052e4d1862c55a1bc77a8433e7de90f0aa0dd237138b3e172d8240f4
       │    └─ config  sha256:05f7d396116236831e68de10720820b501f8e53f7b990fc6b5bb19ca43edf626
       │         └─ history 含 `ARG GIT_SHA=…1ed84bbfcad08224c8c322f7c7a7a817b8916147`
       │            (即 /app/.git-sha 戳印的构建参数,精确等于 RC SHA)
       └─ unknown/unknown attestation(buildx 常规来源证明)
```

- **PA0-G003 PASS**:`imagetools inspect` 显示平台 `linux/amd64`(附 attestation);
  本机不带 platform 的 `docker pull` 被 registry 正确拒绝
  ("no matching manifest for linux/arm64")→ 索引中**只有 amd64**,与生产架构裁决一致。
- **PA0-G004 PASS**:以上五级链条全部经 GitHub API / GHCR registry API 取证
  (config blob 直接下载核验,`contains RC SHA: True`);另有附录 A 修正前在 T4 上
  观察到 `/app/.git-sha` 文件内容与本地 image id `sha256:05f7d396…` 双重印证。

## 4. 镜像内容物核验(制品完备性佐证)

从 config blob 判定镜像含 12 层;修正前 T4 拉取实践中同 image id 的容器内
`ls` 已确认包含运行时必备物:`/app/admin/dist/index.html`(管理端 SPA)、
`/app/widget/dist/widget.js`(Widget)、`/app/config/sites.yaml`、
`/app/scripts/migrate_add_site_experiences.py`、`/app/scripts/migrate_channel_visibility.py`
(激活所需迁移脚本随镜像分发)。该观察属附录 A;如需在非生产上下文复验,
可在任意 amd64 Linux/CI 环境拉取后执行(本机因 GHCR 匿名限流改用 API 路径取证)。

## 5. GPU 运行时验证 —— 不在本门(范围修正令第 4/5 条)

PA0-G005/G006/G007/G008 对应的真机验证(Ubuntu NVIDIA 主机上的 nvidia-smi、
driver/runtime 兼容、容器 GPU 访问、torch.cuda、RC 镜像启动后端、隔离 GPU 冒烟)
**全部移交下一门(Production Activation 内的 PA-0 正式执行)**。本门不做任何声明。

**附录 A(修正前事实记录,非本门证据)**:
- 主机 `tesla-t4`(VM-0-4-ubuntu):Tesla T4,driver **575.64.03**(CUDA 12.9),
  nvidia container runtime 在位 —— 与 Dockerfile 的 cu128 契约兼容;
- RC 镜像在该机容器内 `torch.cuda.is_available()=True`、`device=Tesla T4`、
  torch 2.11.0+cu128(未加载模型权重);
- ⚠️ **GPU 显存饱和**:15633/16384 MiB 已用(空闲 ~751 MiB),占用者:
  llama-server 5910 MiB、python 3492 MiB、生产 ask-ai backend 3762 MiB、
  neomind-extension-runner 2466 MiB —— **下一门做 GPU 路径冒烟(BGE+reranker
  需 ~5GB 显存驻留)前必须先由业务侧释放显存/安排维护窗口**,否则必然 CUDA OOM;
- 修正前的隔离栈曾用 RC 镜像启动后端(隔离 pg/weaviate,EMBEDDER_DEVICE=cpu)
  health 200 —— 仅作"镜像可启动"的早期观察;正式判定以下一门真机验证为准。

## 6. 回滚 / 失效边界证据(PA0-G010)

- 本门**未部署任何东西到生产主机** → 无需回滚;生产栈运行时间贯穿证据
  (backend `Up 34 hours` 前后一致)即"零影响"证明;
- 自建隔离产物已清理并核验为零残留(§0);
- 过程失效与处置:GHCR 匿名拉取限流(bogus `retry-after` 头)→ 改用
  registry API 取证路径完成验证(未放水、未改依赖);本地 Mac 无 amd64 原生
  能力 → 权威构建本就归属 CI(前门已裁决)。

## 7. 验收映射(PA0-G001..G010)

| 门 | 结论 | 依据 |
| --- | --- | --- |
| G001 CI 自精确 RC 谱系执行 | PASS | §2(headSha 逐字节一致) |
| G002 权威镜像构建成功 | PASS | §2(build-and-push success → GHCR) |
| G003 linux/amd64 | PASS | §3(index 平台 + arm64 拒绝 + config amd64/linux) |
| G004 tag/digest/RC-SHA 可溯源 | PASS | §3 五级证据链 |
| G005 Ubuntu NVIDIA 运行时健康 | **NOT IN SCOPE(PA-0A)** | 范围修正令;附录 A 仅事实 |
| G006 容器见 GPU/torch CUDA | **NOT IN SCOPE(PA-0A)** | 同上 |
| G007 RC 镜像启动后端(真机) | **NOT IN SCOPE(PA-0A)** | 同上 |
| G008 GPU 路径冒烟 | **NOT PERFORMED(PA-0A)** | 同上;显存饱和=下一门前置条件 |
| G009 生产 DB/语料/站点零改动 | PASS | §0/§6(生产栈 uptime 贯穿 + 零残留;无任何生产写入路径) |
| G010 回滚/失效证据 | PASS | §6 |

## 8. Delivery

| 字段 | 值 |
| --- | --- |
| STATUS | PASS(限 PA-0A 范围;G005-G008 移交下一门) |
| RC_COMMIT | 1ed84bbfcad08224c8c322f7c7a7a817b8916147 |
| CI_RUN | 33524587791(workflow_dispatch,success) |
| IMAGE_TAG | ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb |
| IMAGE_DIGEST | sha256:ddacb7f5848d7544a717026572cf4c3b261b656e367cf6068dd1d4f8305d53d1(index;amd64 manifest sha256:3aa4e0f4…) |
| IMAGE_PLATFORM | linux/amd64 |
| GPU_HOST | 本门未访问(修正前只读巡检:tesla-t4 / VM-0-4-ubuntu,附录 A) |
| PA0_G001_G010 | G001-G004 PASS;G005-G008 NOT IN SCOPE(移交);G009/G010 PASS |
| REPORT_PATH | docs/implementation/CAMTHINK_V1_PA0_RELEASE_ARTIFACT_GPU_RUNTIME_2026-09-01.md |
| REPORT_COMMIT | (见 docs 仓提交记录,交付响应给出) |
| PRODUCTION_DB_MUTATED | NO |
| PRODUCTION_CORPUS_MUTATED | NO |
| PUBLIC_TRAFFIC_ACTIVATED | NO |

停在 PA-0A 交接;Planner 独立验收;GPU 运行时验证随下一门在具备显存余量的
维护窗口执行。
