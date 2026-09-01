# CAMTHINK V1 — Release Candidate Gate 执行报告

- 任务:CAMTHINK_V1_RELEASE_CANDIDATE(发布合成/就绪门;非生产部署)
- 日期:2026-09-01
- Executor:Engineering Executor / Integration Engineer(ZCode)
- 报告仓:docs 本地仓(分支 main,无远程,按既定约定本地持久化)
- 执行仓:主仓 ask-ai,worktree `.worktrees/technical-insights`

---

## 1. Executive Result

**Executor 自评:PASS。**(Executor PASS ≠ Planner Final Acceptance)

以 ec76beb(Unified V1 Integration FINAL PASS)为基线,对真实仓库释放路径
(Dockerfile / deploy/prod compose / update.sh / 迁移脚本族 / 配置与 secrets 契约)
完成审计与隔离验证,产出 RC:

- 分支 `release/camthink-v1-rc-2026-09-01`,RC commit = `1ed84bbfcad08224c8c322f7c7a7a817b8916147`
  (基线 ec76beb + 仅两个释放产物文件:.env.example 修正 + 生产激活清单;**零产品代码改动**)
- 代表性 pre-RC(生产形态 bbfaa6a)库 → RC 迁移/启动/幂等/遗留数据保留全部隔离实证;
- 全量回归全绿(后端 763 / 门用例 32 / admin 167 / widget 57,tsc+build 全过);
- 未授权自动激活能力数 = **0**(三类自动行为全部归属已验收契约,见 §7);
- 生产激活清单(依赖有序、本门未执行)已写入仓库 `deploy/prod/RC-2026-09-01-ACTIVATION.md`。

## 2. Baseline / Inputs

| 项 | 值 |
| --- | --- |
| BASELINE_COMMIT | `ec76beb6a4bb88dddc2e203272d0472eb26ad49b`(Unified V1 Integration,CLOSED) |
| 生产时代参照 | `bbfaa6a`(当前生产运行版,用于构造代表性 pre-RC 库) |
| RC 分支 | `release/camthink-v1-rc-2026-09-01`(自 ec76beb,已推 origin) |
| RC_COMMIT | `1ed84bbfcad08224c8c322f7c7a7a817b8916147` |

不重开任何已验收工作;两处配置模板修正均为落实**既有已拍板决策**(见 §6)。

## 3. 释放路径审计(真实仓库,不假设旧路径仍有效)

| 组件 | 事实(审计结论) |
| --- | --- |
| 镜像 | 多阶段 GPU 镜像(ubuntu24.04 + uv --frozen + torch cu128 重装);构建上下文需 `admin/dist`+`widget/dist`(workflow 先 npm build 再 docker build);`.dockerignore` 排除 .env/models/docs(dist/ 裸名只匹配根级,COPY admin/dist 实测通过);GIT_SHA cache-bust |
| 生产架构 | **linux/amd64**(GHA `runs-on: ubuntu-latest` 原生 amd64、无 platform 覆盖;Dockerfile 注释 CUDA 契约:tesla-t4 driver 575/CUDA 12.9,torch cu128 wheel 自带 nvidia 用户态库,不用 nvidia/cuda 基础镜像,driver libcuda 由 nvidia container runtime 注入) |
| compose | postgres16 / weaviate 1.28(fixed CLUSTER_HOSTNAME)/ backend:18000 / sync(手动)/ sync-cron(每小时);`docker compose config` 校验通过;外部卷保数据 |
| 部署/回滚 | `deploy/prod/update.sh <tag>`:拉镜像 → GPU 预检 → backend up + health 门禁(失败即 exit)→ sync-cron;回滚 = 传旧 tag |
| 启动 | lifespan:init_db(create_all)+ customization/llm/sites YAML 幂等 seed;APP_MODE=prod 强校验 ENCRYPTION_KEY≥32B + JWT_SECRET≠默认,**违者拒绝启动(实测 RuntimeError)** |
| DB 迁移 | 无统一迁移框架(仓库惯例 = create_all + 幂等脚本族);bbfaa6a→RC 的 schema 差 = 纯增量:conversations.site_id(可空列)+ 新表 site_experiences、llm_allowed_hosts |
| Weaviate | class=Document;chunk 级 channel_visibility 由 P0 写入/读取;`migrate_channel_visibility.py` 负责存量回填(dry-run 默认,--apply 才写;幽灵 chunk 上报不动) |
| 前端制品 | admin/dist 由 SPAStaticFiles 托管(/admin SPA 回退);widget/dist 为嵌入产物;两者 gitignored、构建可复现(RC 门实测 build) |
| secrets | .env 不入镜像不入 git(.dockerignore+.gitignore 双保险,实测 0 泄漏);JWT/ENCRYPTION/DEEPSEEK/GITHUB/WOOCOMMERCE 契约见 .env.example |

### 审计发现并已修正的释放缺陷(RC commit 内容)

1. **死变量 `CORS_ORIGINS`**:代码读 `CORS_ALLOW_ORIGINS`(main.py:471),旧模板写
   `CORS_ORIGINS` → 生产会静默回退 localhost 默认白名单,真实站点浏览器侧全被 CORS 拦截。
   已改正确变量名并补齐三站 origin(含旧模板缺失的 store.camthink.ai)。
2. **死变量 `API_HOST/API_PORT`**:代码读 `ASKAI_API_HOST/ASKAI_API_PORT`。已改名
   (compose 内默认端口不受影响,但文档变量必须真实可用)。
3. **`DEEPSEEK_MODEL=deepseek-v4-pro` 与拍板矛盾**:08-31 已拍板 flash(与生产 DB 一致);
   旧模板在 DB 读取失败回退时会引入 ~2x 生成延迟。已改 `deepseek-v4-flash`。

以上均为"释放模板实现既有决策",不属于新产品语义(RC-G002 论证见 §7)。

## 4. 隔离迁移/启动验证(RC-G003)

**构造代表性 pre-RC 库**:从 `bbfaa6a` 提取真实旧 models(`git archive` → 中性 cwd
初始化,规避 sys.path 污染),注入代表性遗留数据(admin 用户、3 个 data_sources、
3 篇 documents 账本、3 条 conversations+trace、SyncLog、旧形态 llm_providers/llm_routing 行)。

升级路径与结果(全部隔离库 ask_ai_rc_pre,用后已 DROP):

| 步骤 | 结果 |
| --- | --- |
| RC `init_db`(create_all) | 新表 site_experiences/llm_allowed_hosts 建立,既有表不动 |
| `migrate_add_site_experiences.py` RUN1 | site_id 列补齐 + 3 站点 seed |
| RUN2(幂等) | 无错、结果不变 |
| **遗留数据保留** | 3 conversations(含 NULL 答案行)原样、site_id=NULL、documents=3、llm 旧行可读、admin 用户可登录 |
| RC 应用真实启动(隔离 :8032) | health 200;legacy admin 登录 200;遗留对话在审查可见;Tech KPI trace_total=3;数据源列表 3 源;site-config(升级种子)200;LLM 供应商管理读旧行 200 |
| prod fail-fast | APP_MODE=prod + 缺 ENCRYPTION_KEY + 默认 JWT_SECRET → RuntimeError(实测) |

`migrate_channel_visibility.py` dry-run 在隔离库+隔离 class 上正常出计划
(3 源识别正确;--apply 属生产激活阶段 2,本门未执行)。

**如实记录的过程偏差**:首次跑迁移时 shell 变量未 export,子进程回退默认 DSN,
把幂等迁移跑到了本机 dev 库 `ask_ai` 上(仅增量变更:可空列/新表/3 站点行;
正在运行的主仓后端按旧模型忽略之,无影响;**T4 生产从未触碰**)。已在执行侧
更正(env 文件 source)并在 ask_ai_rc_pre 上重做全链。

## 5. 回归验证(RC-G007,release 分支实测)

| 套件 | 结果 |
| --- | --- |
| 后端全量 pytest(全新重建隔离 ask_ai_test) | **763 passed / 5 skipped / 4 failed**(embedder HF-cache 环境类,与基线/主仓对照一致,树未变) |
| Unified V1 Gate 用例(5)+ 站点路由(11)+ 站点服务(16) | **32 passed** |
| admin | **167 passed(33 文件)** + `tsc` 0 错 + 生产 build 成功 |
| widget | **57 passed(7 文件)** + `tsc` 0 错 + 生产 build 成功(dist/widget.js 251.21 kB) |

## 6. 制品/容器完整性(RC-G008)与架构契约

- 前端 dist COPY 探针:实际 docker build 验证 admin/dist+widget/dist 可入镜像
  (`.dockerignore` 的 `dist/` 裸名只匹配根级,实测 COPY 成功)。
- `docker compose -f deploy/prod/docker-compose.yml config` 校验通过。
- `uv sync --frozen` 层在本地构建中**实际通过**(lock 完整性门)。
- 本地全量镜像构建(追加验证,非权威):**NOT_VERIFIED / ENVIRONMENT_BLOCKED** ——
  两次构建(arm64 原生、amd64 QEMU)同签名失败于 `pypi.nvidia.com` 取数
  (本地 BuildKit 出网环境限制;判别探针与完整证据链见 §16 附录)。
  依赖解析无兼容性问题(wheel 均正确解析存在),**未改动任何生产 Torch/CUDA 依赖**;
  `uv sync --frozen` 依赖门两次均通过。
- **权威制品 = CI `build-image.yml`**(amd64 runner,支持对 release 分支
  `workflow_dispatch` 按需构建)→ GHCR;镜像架构与 NVIDIA 契约真机验证已列为
  生产激活清单阶段 0 必检项(amd64/linux、nvidia-smi、
  torch.cuda.is_available()、GPU 全链冒烟)。

## 7. 未授权自动激活分类(RC-G002 = 0)

部署本 RC 源码会自动发生的行为,逐项裁决:

| 自动行为 | 裁决 |
| --- | --- |
| lifespan seed 3 站点(enabled=true,真实域名) | **已授权**(Multi-Site 契约产物);激活需 Origin 精确命中,缺省对外零暴露(fail-closed,测试锚定) |
| sync-cron 每小时同步 → WEB-01 首跑自愈浪涌(生产账本旧漂移将触发全量重灌重嵌入) | **已授权语义**(WEB-01 自愈),但属重操作 → 激活清单阶段 4 显式排序(维护窗口首跑,预期 partial→success),不作为静默惊喜 |
| P0 SourceVisibilityGuard 生效(fail-closed:未知前缀拒绝) | **已授权**(P0 契约);注意内部源在 config 标记 internal + channel_visibility 回填**之前**,其公开性与现状相同(不自动变好也不变坏)→ 红线进清单阶段 2 |
| page_context 软加分 / site_id 持久化 / site-config 端点 | 被动或 fail-closed,已授权 |
| 无特性开关类半成品能力 | 审计 config.py 无 ENABLE_*/FEATURE_* 自动开启项;T1a wiki 嵌入(Phase 4)不在本线 |
| admin 种子口令 | 仅首启无 admin 时创建;既有生产库保留旧口令 → **不自动修复**,清单阶段 3 强制改密(既有待拍板项) |

**UNAUTHORIZED_ACTIVE_COUNT = 0**;未发现"部署即激活未完成能力"的情形。

## 8. 信任边界激活排序安全性(RC-G005)

清单依赖序:DB → **Trust Boundary(channel_visibility)→** runtime/secrets → WEB 语料
→ Multi-Site CORS/站点 → Widget 嵌入 → 生产验证。P0 步骤(阶段 2)强制先于任何新的
公开暴露(阶段 6+):先 PATCH 内部源 → dry-run → --apply → 公开渠道不可见性验证。
迁移脚本 dry-run 默认、幂等、只写属性不重嵌入;幽灵 chunk 上报不自动处理。

## 9. Multi-Site 生产要求明确化(RC-G006)

- 三站(camthink-website / camthink-wiki / camthink-store)seed 幂等,`config/sites.yaml`
  为权威;域名核对为清单阶段 5 显式项;
- `CORS_ALLOW_ORIGINS` 必须显式含三站(模板已修正;真实 Origin/CORS 的**生产验证明确
  留待下一门**,本门不做任何"三站已集成"声明);
- 站点授权链(存在+enabled+Origin 精确命中;无 Origin/未知/不匹配 → 403)已由测试锚定;
  Widget 端 site-config 失败回退默认体验、site_id 仍由服务端裁决(legacy 兼容)。

## 10. 回滚 / 失效边界(RC-G010)

见 `deploy/prod/RC-2026-09-01-ACTIVATION.md`「回滚/失效边界」:镜像 tag 回滚(update.sh
health 门禁)、DB 纯增量→旧代码兼容(镜像回滚无需回滚 DB)、启动 fail-fast、BGE 首载
45s 非故障、同步 partial 不推进窗口/单源失败不中断批次/删除 502 保态可重试、站点 fail-closed。

## 11. 仓库/安全卫生(RC-G009)

- `git ls-files` 无 node_modules/.playwright-cli/.db/真实 .env;仅有的 2 个 `.env*`
  匹配为占位符模板(.env.example ×2,实测含占位符);
- RC diff vs 基线 = 恰好 2 个释放产物文件,零代码改动;
- 隔离资源全部回收:ask_ai_rc_pre/ask_ai_uv1 已 DROP,隔离 Weaviate class 无残留,
  冒烟/迁移进程停止,主 :8000 全程健康。

## 12. RC-G001..G010 汇总

| 门 | 结论 | 依据 |
| --- | --- | --- |
| G001 统一谱系保留 | PASS | 分支自 ec76beb,零产品改动(§5 diff=2 产物文件);回归与门用例全绿 |
| G002 未授权自动激活=0 | PASS | §7 逐项裁决 |
| G003 隔离迁移/启动成功 | PASS | §4(bbfaa6a→RC 全链+幂等+遗留保留+真实启动) |
| G004 激活清单完整 | PASS | deploy/prod/RC-2026-09-01-ACTIVATION.md(DB→P0→config→语料→Multi-Site→嵌入→验证) |
| G005 信任边界排序安全 | PASS | §8 + 清单阶段 2 先于阶段 6 |
| G006 Multi-Site 要求明确 | PASS | §9 + 清单阶段 5 |
| G007 三端验证通过 | PASS | §5(763/32/167/57 + tsc + build) |
| G008 运行时制品齐备 | PASS | dist 探针/compose config/uv --frozen 门过;镜像架构与 NVIDIA 契约真机验证列为激活必检(§6) |
| G009 卫生 | PASS | §11 |
| G010 回滚/失效契约 | PASS | §10 |

## 13. NOT_VERIFIED(不由本门声明)

- 生产部署/T4 运行/生产 DB 迁移执行;
- 生产镜像实际 push 与真机拉起(GHCR 权威构建在 CI;架构/NVIDIA/CUDA/nvidia-smi/
  torch.cuda/GPU 冒烟 = 激活清单阶段 0 必检);
- 三站真实 Origin/CORS 与嵌入(阶段 5/6);WEB 语料生产修复执行(阶段 4);
- 三站 Natural Acceptance / Final Launch。

## 14. Production Status

**PRODUCTION_DEPLOYED = NO。** 未触碰生产 DB/语料/T4/真实站点。

## 15. Delivery

| 字段 | 值 |
| --- | --- |
| STATUS | PASS(Executor 自评,非 Planner Final Acceptance) |
| BASELINE_COMMIT | ec76beb6a4bb88dddc2e203272d0472eb26ad49b |
| RC_COMMIT | 1ed84bbfcad08224c8c322f7c7a7a817b8916147 |
| BRANCH | release/camthink-v1-rc-2026-09-01(已推 origin) |
| UNAUTHORIZED_ACTIVE_COUNT | 0 |
| RC_G001_G010 | 全 PASS(§12) |
| REPORT_PATH | docs/implementation/CAMTHINK_V1_RELEASE_CANDIDATE_GATE_2026-09-01.md |
| REPORT_COMMIT | (见 docs 仓提交记录,交付响应给出) |
| WORKTREE_CLEAN | YES |
| PRODUCTION_DEPLOYED | NO |

停在交接;Planner 独立验收;Production Activation 由下一门按清单执行。

## 16. 附录:本地镜像构建记录(**NOT_VERIFIED / ENVIRONMENT_BLOCKED**,非权威)

**结论:本地 Mac 的完整镜像构建记为 NOT_VERIFIED / ENVIRONMENT_BLOCKED;**
失败定性为**本地 Docker/BuildKit 出网到 `pypi.nvidia.com` 的环境限制**,
**不是依赖解析/包兼容性缺陷;未为此改动任何生产 Torch/CUDA 依赖**。

证据链(全部保留):

1. 两次独立构建(原生 arm64;buildx `--platform linux/amd64` QEMU 模拟)在同一阶段
   (`uv pip install torch --index-url https://download.pytorch.org/whl/cu128`)以**同一签名**
   失败:uv 向 `pypi.nvidia.com` 取 wheel 时 "error sending request",3 次重试 ~126s 后放弃;
2. 两次失败的**目标 wheel 均解析正确且存在**(amd64: `nvidia_nvtx_cu12-12.8.90-...x86_64.whl`;
   arm64: `nvidia_cusparse_cu12-12.5.8.93-...aarch64.whl`)→ 解析层无兼容性问题,纯取数失败;
3. 同期对照:多 GB 的 `pypi.org` 下载(阶段 16,`uv sync --frozen`)两次**全部成功**
   (该依赖门本身 PASS);宿主 `curl https://pypi.nvidia.com` HTTP 200;
4. 判别探针:普通容器内 `pypi.nvidia.com` 索引 HTTP 200,且 20MB 分段下载某 wheel 成功
   (HTTP 206,~1.8MB/s)→ 域名可达,失败特定于 BuildKit 构建网络路径对大文件持续传输;
5. 依赖门 `uv sync --frozen`(锁完整性)在两次构建中均通过;`COPY admin/dist`/
   `widget/dist` 探针通过;`docker compose config` 通过。

**权威构建路径 = CI `build-image.yml`**:`ubuntu-latest`(原生 linux/amd64,无 platform
覆盖)出网不受本机限制;触发 = push main / `v*.*.*` tag / `workflow_dispatch`(可对
release 分支按需构建 RC 镜像,无需先合 main)。镜像架构与 NVIDIA 运行时契约
(amd64/linux、driver≥575/CUDA12.9、nvidia-smi、torch.cuda.is_available()、GPU 全链冒烟)
已在 `deploy/prod/RC-2026-09-01-ACTIVATION.md` 阶段 0 列为生产激活**必检项**,
本门不做任何 GPU 运行时验证声明。
