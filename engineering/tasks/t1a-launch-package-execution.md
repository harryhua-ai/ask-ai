# T1a-LAUNCH-PACKAGE Execution Report

- **Task ID**:t1a-launch-package | **Parent Initiative**:T1a 实例最小上线包
- **Worktree / Branch**:`/Users/harryhua/Documents/GitHub/ask-ai-t1a-launch` / `worktree-exec/t1a-launch`
- **Baseline Commit**:`4db4c41`(main = origin/main)
- **Final Commit**:`bbfaa6a`(Phase 1;逐 Phase commit,本报告覆盖 Phase 1)
- **Status**:**CANDIDATE READY**(Executor 自评,待 A 独立 Review;Gate-1 停等)

---

## Phase 1:widget 代码包(T1 / T2 / T3)

### Files Changed(全部 EXPECTED,7 files +317/-30)

| File | 变更 |
|---|---|
| widget/src/bootstrap.tsx(新) | `WIDGET_ROOT_ID` / `resolveConfig`(逐键四级 fallback)/ `mountWidget`(容器复用+防双注入) |
| widget/src/index.tsx | 32 行顶层副作用 → 3 行入口(调 `mountWidget(document, document.currentScript)`) |
| widget/src/__tests__/bootstrap.test.ts(新) | 10 用例:三级 fallback、逐键混拼、容器复用、双注入防重 |
| backend/main.py | `CachedStaticFiles`(固定 Cache-Control)+ `_mount_widget_static`(镜像 admin 模式,无 html=True) |
| tests/test_widget_hosting.py(新) | 4 用例:200+缓存头、目录根 404 无列表、缺文件 404、dist 缺失不挂载 |
| .github/workflows/build-image.yml | Build 步骤增加 `widget && npm ci && npm run build` |
| Dockerfile | `COPY widget/dist /app/widget/dist`(对齐 :65 admin 写法) |

### Implementation Summary

- **T1 配置引导修复**:契约 E4 缺陷实证(index.tsx 自建 div 读 data-*,script 传参不可达)。新 bootstrap 模块按契约冻结顺序逐键解析:currentScript dataset → 预置 `#ask-ai-widget-root` dataset(存在则复用不新建)→ window.AskAIConfig → 默认值(apiUrl=http://localhost:8000,primaryColor=#f24a00)。防双浮窗:容器已有子元素即跳过挂载(复用既有 id 判定,契约 §11)。
- **T2 托管**:`_mount_widget_static` 在 `widget/dist` 存在时挂 `/widget`;`CachedStaticFiles` 注入 `Cache-Control: public, max-age=300`;无 SPA 回退(html=True 禁用),目录路径 404。dist 缺失时不挂载(与 admin 同语义,CI/本地无产物不炸)。独立函数导出便于契约测试。
- **T3 构建链**:CI `Build admin & widget SPA`(widget 先 build);Dockerfile 增加 widget/dist COPY。

### Supporting Changes

无。backend/main.py 为契约 Change Boundary 的 EXPECTED 面(挂载段);CORS 中间件零改动;pipeline/retrieval/connectors/api/、admin/、schema 零触碰(见 Diff Audit)。

### Verification actually executed(全部实际运行)

**TDD 红→绿**:
- T1:10 用例先红(ERR_MODULE_NOT_FOUND)→ 实现后 10/10 绿
- T2:4 用例先红(AttributeError: _mount_widget_static)→ 实现后 4/4 绿

**静态/单测全量**:
- widget vitest 全量:**2 文件 27/27 通过**(既有 sanitize 套件无削弱);widget `tsc --noEmit` 干净
- admin vitest 全量:**30 文件 113/113 通过**(零波及);admin `tsc --noEmit` 干净
- 后端 CI 口径:`pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e` → **447 passed**(含新增 4 个托管用例)
- 后端 tests/api/admin + tests/scripts/test_sync_db.py → **90 passed / 3 skipped / 1 failed**

**环境预存失败如实记录(非本任务回归)**:`test_llm_providers.py::test_list_providers_includes_deepseek_and_masks_key` 失败原因=测试库 deepseek 行 api_key 为空('' ≠ '********')。已用主仓 baseline(4db4c41)同环境复现相同失败 → 环境数据状态问题,与本变更无关。12 个初始失败中其余 11 个为 ENCRYPTION_KEY 未注入,注入后全绿(CI 忽略该目录的原因即注释所载"需 ENCRYPTION_KEY")。

### Runtime Verification + Real-World Self-Check(AC1 / AC2,真实浏览器)

环境:worktree 后端(main venv + worktree 代码)起于 :8000,`.env` 复制并注入测试页 origin(`http://localhost:8901`);widget dist 实际构建(249KB);测试页由独立 origin `http://localhost:8901`(python http.server)提供,与 API origin(8000)真实跨域。

**AC1 路径 1(data-* 一等公民)**:`data-attr.html` 以 `<script src="…/widget/widget.js" data-api-url="http://127.0.0.1:8000" defer>` 加载 → 真实点击浮窗 → 真实提问("NE301采集器是什么?")→ 流式回答 405 字 + 来源链接渲染。**判别器**:performance entries 实证 `/api/ask` 请求命中 `127.0.0.1:8000`(非默认 localhost)→ 证明 script data-api-url 被消费(修复前该路径不可达,此为 E4 缺陷关闭的直接证据)。

**AC1 路径 2(window.AskAIConfig)**:`global-config.html` 预置 `window.AskAIConfig={apiUrl:"http://127.0.0.1:8000"}`,script 无 data-* → 点击建议问题真实提问 → 回答 414 字 + 来源链接,`/api/ask` 命中 `127.0.0.1:8000` ✓

**AC1 路径 3(默认值)**:`default.html` 无任何配置 → 真实提问 → 回答 419 字 + 来源链接,`/api/ask` 命中 `localhost:8000`(默认)✓

**对抗性(双注入防重)**:`double-inject.html` 同页两个 widget script → DOM 实证 `roots:1 / fabs:1`;点击后 `panels:1` ✓ 无双浮窗。

**AC2 托管与缓存**(curl 原始输出):
- `GET /widget/widget.js` → `status:200 content-type:text/javascript`,`cache-control: public, max-age=300`(另有全局 `x-content-type-options: nosniff`)
- `GET /widget/` → `status:404`,响应体 0 处 widget.js 字样(无目录列表)
- `GET /widget` → 307(StaticFiles 规整斜杠,随根路径 404)

**回归(Runtime)**:重启后端(挂载判定在启动时)后 `/admin/` 200、`/admin/data-sources` 深链 200(SPA 回退未受影响);`/health` 200。截图证据:`/tmp/t1a-evidence-ac1-data-attr.png`、`/tmp/t1a-evidence-double-inject.png`。

### Deviations

1. 契约 Code Boundary 写 `backend/tests/*`,仓库实际布局为根级 `tests/`,测试置于 `tests/test_widget_hosting.py`(事实性路径差异,HOW 范畴,已按实际布局执行)。
2. black 曾顺手重排 main.py 一行无关注释缩进,已回滚——最终 diff 仅含 widget 挂载块(+28 行,无删改既有行)。
3. 判别器设计:AC1 用 `data-api-url=http://127.0.0.1:8000` 与默认 `localhost:8000` 形成可观测差异(请求主机名),primaryColor 因既有组件硬编码 `#000000`(FORBIDDEN 视觉区,不动)不作为判别器。

### Remaining Risks

- AC3 的容器内实证(`ls /app/widget/dist`)需真实镜像构建,随 Phase 2 部署执行;本 Phase 已以 CI 配置 + Dockerfile 变更 + 本地 build 产物(249KB)佐证。
- 测试库 deepseek api_key 数据状态问题(见上)建议另开任务修测试数据,未动(越界)。
- worktree 内遗留 AC1 环境工件:`.env`(含 8901 origin 注入)、`models` 软链、`widget/dist`、`admin/dist`——均已 gitignore/本地 exclude,不进版本库。

---

## Status

**CANDIDATE READY** —— Gate-1 停等 A Review 放行 push(本任务不 push、不部署、不碰数据)。

---

## Phase 2:T4 发布(Gate-2 前半)

- **推送(Step 1)**:`git push origin worktree-exec/t1a-launch:main` → `4db4c41..bbfaa6a worktree-exec/t1a-launch -> main`(快进);本地 main 已 ff 至 `bbfaa6a`,main = origin/main = **bbfaa6a**
- **CI**:run **33360499079** conclusion **success** https://github.com/harryhua-ai/ask-ai/actions/runs/33360499079
- **磁盘预检**:`/dev/vda2 1.3T 277G 952G 23%`(可用 77%,远超 20% 红线)
- **部署**:`./deploy/prod/update.sh` → 镜像拉取 + backend 重建;health 首验失败(BGE 慢启动,契约预期)→ 约 10 秒后 200,容器 `Up (healthy)`
- **版本双验证(容器内原始输出)**:
  - `cat /app/.git-sha` → `git_sha=bbfaa6a3adc977165d74db96738bec258d3a736d`
  - `grep -c "_mount_widget_static\|CachedStaticFiles" /app/backend/main.py` → `4`
- **AC3 容器内实证**:`ls -la /app/widget/dist` → `widget.js`(249364 字节,与本地构建逐字节同大小)+ `ask-ai-widget.css`
- **CORS(事实修正,如实记录)**:任务指示"追加两 origin 并保留既有 localhost 行";实测 T4 `.env:35` **本就为** `CORS_ALLOW_ORIGINS=https://www.camthink.ai,https://wiki.camthink.ai`(两生产 origin 已在列,无 localhost 行)——契约冻结点 3 的目标状态已满足。首次 sed 追加造成行内 origin 重复,即以 `.env.bak` 恢复原状并 diff 核验一致;运行容器加载的正是该内容,无需重启。localhost 三件套"不回归"指代码默认值(`main.py` `_cors` 默认),未触碰。
- **AC5 CORS 预检(运行中后端)**:`OPTIONS /api/ask` + `Origin: https://wiki.camthink.ai` → `access-control-allow-origin: https://wiki.camthink.ai` ✓(allow-methods GET, POST)
- **公网验证**:`https://wiki-data.camthink.ai/widget/widget.js` → `HTTP/2 200`,`content-type: text/javascript`,`cache-control: public, max-age=300`,249364 字节;`/widget/` → `404` 无目录列表

## Phase 3:P-1 清洗(不可逆,备份前置)

- **before 计数(实测)**:conversations=**632**(契约 E7 的 627 为 08-30 推断值,以执行时实测为准)/ traces=261 / source_clicks=0 / business_signals=31
- **事实修正**:E7 所列 `feedback[CASCADE]` 表不存在——feedback 为 conversations 表的**列**(`conversations.feedback`),随行删除;级联表实为 traces + source_clicks。business_signals 无 conversation_id 外键,仅有 `sample_conversation_ids` 采样列(无级联语义,行自然留存)
- **备份**:`pg_dump --table=conversations --table=traces --table=source_clicks`(单文件含 schema+data)→ T4 `/home/ubuntu/ask-ai-p1-conversations-backup-20260831.sql`(2,025,109 字节,已留存不删)
- **备份对账(金标准:实际恢复进一次性库 `p1_verify` 后计数)**:conversations=**632** / traces=**261** / source_clicks=**0**,与 before 完全一致 → 备份可独立恢复 ✓(验证库已删)
- **删除**:`DELETE FROM conversations;` → **DELETE 632**(单语句,级联由 DB 语义处理,未手删子表)
- **after 计数**:conversations=**0** / traces=**0** / source_clicks=**0** / business_signals=**31**(不变,无孤儿外键)
- **删除后健康**:`/health` → `{"status":"ok"}`
- **有意不做**:删除后未发起真实问答冒烟——任何冒烟对话会向"零基线"写入 1 行,违背 P-1 目的(北极星自灰度日起干净);生产写路径由 Phase 4 AC7(对话落库 channel=widget)在 wiki 灰度时点验证

## Gate-2 状态

**CANDIDATE READY**(Executor 自评)——Phase 2 + Phase 3 完成,证据如上;**停点**,Phase 4(wiki 嵌入)等用户确认上线时刻后执行。
