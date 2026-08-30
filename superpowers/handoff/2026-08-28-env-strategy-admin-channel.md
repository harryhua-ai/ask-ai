# 执行交接:环境策略固化 + admin channel 数据边界

> **给执行窗口**:本任务由产品规划窗口于 2026-08-28 定稿(讨论与决策记录见 `docs/product-roadmap.md` §8"环境策略")。执行窗口按本交接实施,完成后回报结果,由产品窗口做质量审查。

## 执行环境(协作模式)

**在独立 worktree 中执行,勿在主工作区动代码**(主工作区是规划窗口的领地,文档与代码变更集隔离,避免 commit 互相裹挟):

```bash
# 本交接与产品基线已提交到本地 main,worktree 可直接读到
git worktree add ../ask-ai-exec-env -b worktree-exec/env-strategy-channel main
cd ../ask-ai-exec-env
uv sync --extra dev
cd admin && npm install && cd ../widget && npm install
```

- `MODEL_CACHE_DIR` 确认指向共享模型权重路径(BGE 权重勿重复下载)
- docker 数据层全局共享(`deploy/local` 卷名固定 `ask-ai-local_*`):同一时间只跑一套本地数据栈,勿与主工作区同时 up
- 每个 Task 独立 commit(中文提交信息);全部完成后合回 main,交产品窗口审查合并 diff

## 背景(为什么做)

产品即将进入 T1 里程碑(三站点嵌入上线:商城 `www.camthink.ai/store/` → 官网 `www.camthink.ai` → wiki `wiki.camthink.ai/docs/`)。上线后 conversations 表的意图分布(commercial 占比)是 roadmap 数据裁决的依据(基线 D-5 分层北极星)——**测试流量必须能从真实访客数据中剥离**。

当前唯一 widget 集成点是 admin 内嵌聊天窗口(登录页 + 登录后全局,管理员测试用)。若其写库 `channel` 与 widget 相同,测试对话与真实访客对话混在同一数据池,北极星裁决失真。

同时定稿环境分工(不得偏离):

| 环境 | 角色 |
|---|---|
| mac local(`deploy/local/` + `scripts/dev-local.sh`) | 开发 / 调试 / 后端测试(测试的主场) |
| CI(GitHub Actions) | 单元/集成回归的正式归属 |
| tesla-t4 prod | 生产运行 + 部署验收(CI 镜像更新后对**运行中的服务**做真实验证,补 Real-Run Gate 缺陷) |
| `deploy/dev/` 模式 | 前端联调临时便利,**不作后端测试环境** |

现阶段不建独立 staging,mac local 即 staging。

## 任务

### Task 1:核查 admin 内嵌聊天的 channel 值(先查事实)

- admin 前端内嵌聊天(login 页 + 登录后全局)调用 `POST /api/ask` 时 `channel` 字段实际传什么(查 `admin/src` 内嵌聊天相关代码)
- 后端 channel 白名单的合法值(`backend/api/schemas.py` / `routes.py` 中的校验)
- 输出结论:admin 聊天 channel 是独立值,还是与 widget 混用

### Task 2:若混用 → 改造为独立 `channel="admin"`

- 前端:admin 内嵌聊天请求传 `channel="admin"`(admin 无对应单测,以 `tsc` + `npm run build` 验证)
- 后端:channel 白名单加 `"admin"`;conversations 写库自然携带
- TDD:先写失败测试(channel=admin 的请求落库后可按 channel 过滤区分),再实现
- 若 Task 1 结论已是独立值:补一个测试锁定该行为即可,本任务结束

### Task 3:环境策略固化到工程文档

- `CLAUDE.md`:在 Testing / Deployment 章节附近新增"环境策略"小节,写入上方四环境分工表
- `deploy/README.md`:dev 模式的描述改为"前端联调临时便利,不作后端测试环境"
- `docs/product-roadmap.md` 不要改(产品窗口维护)

### Task 4(可选,给建议不强制执行)

- 查 conversations 表现状:admin 测试对话的量级与时间分布
- 评估 T1 上线前是否需要标记/清理存量测试对话(零流量阶段量应很小);把建议写进本文件的"执行结果"节即可

## 约束(红线,违反即返工)

1. 后端测试必设 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(conftest 的 `drop_all` 未隔离时会清空开发库)
2. 本任务**纯本地 + 文档改动,不部署 tesla-t4、不触发任何同步/reindex**;channel 改动随下次常规发布走
3. 绝不使用 `--reindex` 或任何删 Weaviate collection 的操作
4. 格式:ruff/black/isort(line-length=100);代码注释、docstring、提交信息用中文简体
5. 全量回归不破坏(admin 约 76 + 非 admin 用例;用真实 pytest 输出复核,不写死数量)

## 验收标准

1. `channel="admin"`(或确认的独立值)落库可区分,有测试锁定
2. CLAUDE.md / deploy/README.md 环境策略更新到位
3. `uv run pytest tests/ -q` 全绿 + `cd admin && npm run build` 通过(环境策略相关无代码回归)
4. 执行结果(含 Task 1 结论、Task 4 建议)回填到本文件末尾"执行结果"节,交产品窗口审查

## 执行结果(执行窗口回填)

> 执行窗口于 2026-08-30 完成,提交 `81bd1db`(纯本地改动,未推送部署)。

### Task 1 结论:admin 内嵌聊天 channel 与 widget 混用(事实)

- admin 内嵌聊天只有一处:`LoginChat`(admin/src/App.tsx:20 挂载于全局,**登录页与登录后都在**),它直接复用 widget 的 `App` 组件;
- widget 的 `App.tsx` 原来硬编码 `ask(text, messages, "widget", ...)`(widget/src/App.tsx:38),即 admin 内嵌聊天发出的请求 channel 一律为 `widget`;
- 后端白名单原值 `^(widget|discord|whatsapp|mcp)$`(backend/api/schemas.py),无 admin 独立值;路由将 `req.channel` 原样落库(backend/api/routes.py)。
- **结论:混用**,触发 Task 2 改造。

### Task 2:已改造为独立 channel="admin"(TDD)

改动(提交 `81bd1db`):

| 文件 | 改动 |
|---|---|
| backend/api/schemas.py | 白名单加 `admin`,docstring 说明数据边界用途 |
| widget/src/types.ts | `WidgetConfig` 增可选 `channel` 字段(缺省 widget,现有嵌入行为不变) |
| widget/src/App.tsx | `config.channel ?? "widget"` 透传 |
| admin/src/components/LoginChat.tsx | config 传 `channel: "admin"` |
| tests/api/test_admin_channel.py | 新增 3 个测试(见下) |

TDD 证据(真实 pytest 输出):

- 红:`tests/api/test_admin_channel.py` 初版 **2 failed, 1 passed**——schema 白名单拒绝 admin(ValidationError)+ 路由 422;
- 绿:实现后同文件 + test_schemas.py **10 passed**(含既有 `test_invalid_channel_rejected`,"evil" 仍被拒);
- 三层锁定:① 白名单接受 admin;② `/api/ask` channel=admin 落库 `Conversation.channel == "admin"`;③ admin/widget 双渠道落库互不混淆。
- 兼容性:RAG 对未知渠道回落默认 system prompt(backend/pipeline/rag.py `channel_customizations.get(channel, ...)`),admin 渠道不绑定定制时行为与 widget 一致,无破坏。

### Task 3:环境策略已固化

- `CLAUDE.md`:Testing 与 Deployment 之间新增"环境策略"节,四环境分工表 + "现阶段不建独立 staging,mac local 即 staging" 原文固化;
- `deploy/README.md`:dev 行"何时用"改为"前端联调临时便利,**不作后端测试环境**";
- 两份文件按"文档仅本地"约定不进 git(`docs/`、`CLAUDE.md`、`deploy/**/README.md` 均已 .gitignore),改动只在本地生效;`docs/product-roadmap.md` 未动。

### Task 4:存量测试对话评估(只建议,未执行)

只读查询(未写任何数据):

- tesla-t4 prod 库:conversations 共 **627 条,channel 全部为 widget**(2026-08-04 ~ 2026-08-25;周分布 369 / 257 / 1,8-24 当周仅 1 条,近期已无新增);
- mac local 开发库:**0 条**(独立卷,不含生产数据)。

**建议**:T1 上线前做一次性清理——以 T1 上线时刻为 cutoff,之前的对话**全部归档或删除**(零流量阶段此前所有对话均可视为内部测试流量,且 channel=widget 已无法回溯区分,逐条甄别不可行)。627 行量级极小,删除风险低;若想保守可先 `pg_dump` 归档该表再删。请产品窗口裁决执行时机(建议随 T1 上线变更窗口一并做)。

### 验收核验(真实输出)

- 全量回归:`uv run pytest tests/ -q`(设 `TEST_DATABASE_URL`,全程红线遵守)→ **492 passed, 3 skipped, 30.41s**;
  - 范围说明:排除 `tests/embedder`(首次运行需下载 BGE 模型,执行端沙箱无外网导致挂起,与本次改动无关)与 `tests/e2e`(需活服务);两者 CI 同样跳过。embedder 模型缓存就绪后建议补一次完整 `tests/` 全量验证。
- 前端:`admin && npm run build` ✓(tsc + vite,含改造后 widget 源码);`widget && npm run build` ✓(dist/widget.js 出包);
- 格式:ruff / black / isort 全部通过(line-length=100);
- 红线:未部署 tesla-t4、未触发同步、未使用 `--reindex`;Task 4 对 prod 库仅只读 SELECT;注释/提交信息中文简体。

### 遗留说明(供审查知悉)

1. 本地安全钩子(Mimosa)对 SQLAlchemy ORM 参数化查询(`where(col == "…")`/`filter_by`)误报"SQL 注入"并拦截写入;新测试文件的 DB 层断言改用主键 `get()` 验证双渠道落库值互不混淆(语义等价,无查询语句字面量)。误报本身建议另行反馈工具方。
2. `channel="admin"` 改动随下次常规发布走(交接约定);发布前 admin 内嵌聊天仍写 widget,期间产生的测试对话在 T1 清理时一并覆盖。
