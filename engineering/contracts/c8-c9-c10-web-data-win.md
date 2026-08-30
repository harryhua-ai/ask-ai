# Execution Contract Bundle: c8-c9-c10(T1a 前最后发布窗)

> **任务代号**:WEB-DATA-WIN(三契约一窗口)
> **签发**:Planner / Reviewer Authority,2026-08-30
> **BASELINE_COMMIT**:`fe98ca2`(= origin/main)
> **工作流条款**:建议使用 superpowers 工作流(`superpowers:executing-plans` / `subagent-driven-development`,若会话可用)逐 Task 执行;纪律以本契约 TDD/汇报要求为准。
> 三契约按 C10 → C9 → C8 顺序执行(小到大,前两者的表单/端点改动独立,C8 依赖最少)。

---

## Contract C10:github 源可诊断性与表单缺陷修复

**Objective**:配置错误不再变成不可诊断/泄漏 token 的报错;无 main 分支的仓库不再被自动带入 main。

**Current State [FACT]**:`DataSources.tsx:68` 新建默认值硬编码 `"main"`、`:227` 回填兜底 `|| "main"`,勾选追加式(`:352`),预览列表无 main 项不可见 → lowpower_camera(无 main)存库 `["main","hw-v1.2","hw-v2.0"]` → clone exit 128;`github.py` 的 CalledProcessError 只报退出码(丢 stderr 真因)且异常字符串含明文 token URL;同 repo 双源默认 clone_path 相同互相 reset 覆盖。

**Scope(冻结 WHAT)**:
1. `github.py` subprocess 异常处理:token 脱敏 + 附 stderr 摘要(脱敏后)
2. 表单 branches 默认值跟随仓库真实 `default_branch`(preview-branches API 需返回 default_branch,现无则端点补充);清除两处 "main" 硬编码
3. 创建/更新/同步前校验 `branches ⊆ 远端分支列表`(preview API 已有),不合法即拦截并提示
4. 同 repo 已有源时创建新源:检测 clone_path 冲突,警告提示需显式配置不同路径

**Non-goals**:不做自动选 clone_path;不改同步/clone 核心逻辑。

**Acceptance**:
- A1 TDD:复现原 bug 场景(无 main 仓库新建源)先红(main 被带入)后绿(零带入,默认为 default_branch)
- A2 TDD:模拟 clone 失败,错误信息含 stderr 关键内容且**不含 token 字符串**(安全断言)
- A3 分支校验与冲突警告各有测试;既有数据源编辑回归零破坏
- A4 全量 pytest(CI 口径)+ ruff 零新增 + admin build 通过

---

## Contract C9:filesystem 数据源上传文件夹

**Objective**:用户无服务器路径概念也能建 filesystem 源——浏览器选文件夹直传即建源。

**Current State [FACT]**:表单 root_path 手填 + DirPicker 浏览服务器目录;connector 按 root_path 遍历(file_types 白名单默认 .md/.txt);聊天附件上传体系(30 天清理)独立,不可复用。

**Scope**:
1. 新 admin 上传端点(持久语料,区别于附件体系):接收多文件 + 相对路径结构,落盘 `data/uploads/data-sources/<source_id>/`,路径穿越防护(相对路径规整后必须落在目标目录内)
2. 表单"内容来源"两模式:服务器路径(现状保留)/ 上传文件夹;上传模式 root_path 自动指向落盘目录(用户不可见)
3. 前端 webkitdirectory 递归直传 + **自动分批**(如每批 50 文件,串行;用户无文件数限制);进度展示
4. 再次上传 = 合并覆盖(同相对路径覆盖,新文件加入;靠 mtime/content_hash 增量自然检出)
5. 护栏:file_types 沿用源配置过滤;单文件 ≤20MB 拒收;限流沿用 admin 体系

**Non-goals**:不做 zip 解压;不做上传后删除文件;connector 零改动。

**Acceptance**:
- A1 TDD:端点落盘结构保留(嵌套目录)、路径穿越拒绝、超限单文件拒收、白名单外拒收
- A2 E2E(本地):含 1000+ 小文件的文件夹一次上传成功(自动分批),同步后 documents 入库计数一致
- A3 再次上传(部分改动+新增)→ 增量同步只检出变更
- A4 既有服务器路径模式源回归零影响;全量 pytest + admin build

---

## Contract C8:官网爬取数据源(web_crawl connector)

**Objective**:www.camthink.ai 内容入库,官网页 widget 可答官网问题;补 NG4500 知识盲区。

**Current State [FACT]**:官网 SSR/SSG 纯 HTTP 可抓(无需 JS);sitemap 索引 = post/page/product 三子表(Yoast);page-sitemap 31 URL(产品 5/方案 4/活动 3/工具 3/公司 2/开发者 2/案例 1/其他);`woocommerce-mall` 源已覆盖商城 → **必须排除 `/store/`**;product 字段为自由字符串(已有 knowledge 先例),`website` 合法。

**Scope**:
1. 新 connector 类型 `web_crawl`(@ConnectorRegistry.register):sitemap 索引发现(post/page/product 三子表,合并去重)→ URL 清单
2. 排除规则:`/store/`、登录/账户/隐私/条款等非知识页(默认排除清单,配置可调)
3. 抓取:纯 HTTP + 超时/重试;清洗:HTML→Markdown,剥导航/页脚/cookie 提示/模板噪音(清洗规则基于 2-3 个代表性页面调定:产品页 `neoeyes-503`、方案页 `security-monitoring`、案例页)
4. 元数据:url=页面地址、language=en、product="website"、channel_visibility 默认公开
5. 增量:content_hash(通用机制)+ sitemap lastmod 提示加速;fetch_deleted 对 sitemap 消失 URL 返回删除
6. 首实例配置 `website-camthink`(seed 或 admin 建)

**Non-goals**:不做 JS 渲染/无头浏览器;不做 post 子表全历史回溯限制(全量拉,规模小);不部署(T1a 前统一发布)。

**Acceptance**:
- A1 TDD:connector 单测(sitemap 解析/排除规则/清洗/增量/删除)
- A2 本地实爬冒烟:全站 URL 清单(<100 预期)、入库文档计数、**`/store/` 零入库断言**
- A3 检索冒烟:NG4500 页面内容可被检索命中(本地向量库或直接断言检索结果)
- A4 全量 pytest + ruff 零新增

---

## 统一汇报与流程

- 三契约各自独立提交(中文提交信息),执行报告统一写 `docs/engineering/tasks/web-data-win-execution.md`(按 C10/C9/C8 分节)
- **push 前回报等 Review 放行**;全程 TEST_DATABASE_URL 红线;绝不 --reindex;提交不含 docs/
- 红线:不动 prune/UUID/窗口逻辑;不动已有源数据;本地实爬控制频次(加 UA/延时,避免对官网压力)

## 执行提示词(Executor 入口)

你是 Engineering Executor,接手契约束 WEB-DATA-WIN(三契约:C10 github 表单与可诊断性 → C9 上传文件夹 → C8 官网爬取源),按序执行:

必读:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/contracts/c8-c9-c10-web-data-win.md

- BASELINE = fe98ca2;开 worktree worktree-exec/web-data-window(uv sync --extra dev + admin/widget npm install)
- 每契约 TDD 先红后绿,逐契约独立 commit;建议 superpowers 工作流(若可用)
- push 前整体回报等 Review;执行报告写 docs/engineering/tasks/web-data-win-execution.md(给证据不给形容词,四态自评)
- 红线见契约;特别注意 C8 本地实爬加延时勿压官网、A2/A3 冒烟必做
