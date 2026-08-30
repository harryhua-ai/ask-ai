# 交接:LLM 模型配置系统实现

> 给另一个 Claude Code 窗口。你接手一份已定稿的 spec + plan,按 plan 逐 Task 实现即可。

## 你的任务

按实现计划逐 Task 实现,**不要再讨论设计**——spec 已过 dual-review 收敛(2 轮,9 处修复),所有架构决策已锁定(见下"决策锁定")。

## 必读文件(按顺序)

1. **实现计划**:`docs/superpowers/plans/2026-08-05-llm-model-config-redesign.md`
   - 16 个 Task,分 5 阶段(A 后端核心 → B 后端端点 → C task 名+迁移 → D 前端组件 → E 页面+风格)
   - 每个 Task 都是 TDD(先写失败测试 → 实现 → 通过 → 提交),步骤已细化到 2-5 分钟
   - **从 Task 1 开始,严格按顺序**(阶段间有依赖)

2. **设计 spec**:`docs/superpowers/specs/2026-08-05-llm-model-config-redesign.md`
   - 实现时遇到"为什么这么设计"的疑问,查这里
   - spec 末尾有 Dual Review Log,记录了已发现并修复的 9 处问题

## 决策锁定(不要再改)

这些是已拍板的决定,plan 基于它们编写,改任何一个都会连锁影响:

| 决策 | 选择 | 理由 |
|---|---|---|
| 热重载方案 | **C**:LLMRouter 加 reconfigure(),reload 只换内部字典 | RAG/Pruner 启动时锁住 router 引用,替换 app.state.llm 对它们无效;reconfigure 让同对象内部可变,零侵入 |
| model 粒度 | 路由 chain 元素从字符串升级为 `{provider, model?}` | 同一供应商凭证多任务复用,各指定 model(生成 v4-pro、意图 v4-flash,凭证共享) |
| provider 类型 | 只 `openai_compatible` 一种 | 不新增 provider 类 |
| 页面主轴 | 6 环节模型职责(向量/排序只读 + 意图/查询/剪枝/生成可配) | 匹配用户心智,覆盖完整流水线 |
| widget 风格 | 全局刷新(合进本 spec) | token 已高度吻合(Manrope/8px 圆角/近黑 primary 均已是现状),主要加软阴影+统一 lucide |
| 路由 path | `/llm-providers` 不改,只改侧边栏 label 为"模型配置" | bookmark 不失效 |
| task 名 | `query_decomposition`→`intent`;query_rewrite 从 generation 拆出 | 修正 intent_tagger 的历史命名错误 |

## 必须注意的坑

1. **测试库隔离** — 后端测试必设环境变量,否则 conftest 的 `drop_all` 会清空开发库:
   ```
   TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test
   ```
   这条在 memory `test-db-isolation` 里有记录,曾出过事。

2. **admin API 测试惯例** — `tests/api/admin/test_llm_providers.py` 已有测试,新测试沿用它的惯例:
   - 共享 session 级事件循环:`pytestmark = pytest.mark.asyncio(loop_scope="session")`
   - 只用 `test-prov` / `test-` 前缀的 id/task,绝不碰迁移的 deepseek / generation
   - `auth_headers` fixture 已有,直接用

3. **循环 import 风险** — Task 5 里 reload 端点要调 `main.py` 的 `_build_llm_state`,但 main 已 import llm_providers。**必须用函数级 import**(在 reload_providers 函数体内 `from backend.main import _build_llm_state`),不能用模块级,否则循环。plan Task 5 Step 3 已明确。

4. **chain 归一化是地基** — Task 1 最先做。`load_llm_config_from_db` 返回的 routing 必须是归一化后的 `dict[str, list[dict]]`,否则 Task 2 的 LLMRouter 会炸。旧字符串数据靠归一化向后兼容。

5. **迁移脚本要先 dry-run** — Task 7 的 `scripts/migrate_llm_chain_format.py` 对着开发库先跑 `--dry-run` 确认计划,再正式跑。**绝对不要带 `--reindex`**(那是 sync 脚本的参数,会删整个 collection,memory `reindex-deletes-entire-collection` 有记录)。

## 执行方式

plan 开头已标注推荐执行方式:
- **推荐**:用 `superpowers:subagent-driven-development` skill,每个 Task 派一个新 subagent,两阶段 review 后进下一个
- 或:`superpowers:executing-plans`,本会话内批量执行带检查点

## 当前代码状态(commit 基线)

- spec 已提交:`ab4928f`(dual-review 收敛后)
- plan 已提交:`b4b1716`
- **代码尚未改动**——所有 Task 都是待实现。从干净的 `main` 开始即可。

## 关键代码位置(实现时对照)

| 要改的地方 | 文件:行 | 现状 |
|---|---|---|
| LLMRouter 类 | `backend/llm/registry.py:37-82` | 字符串 chain,无 reconfigure |
| chain 加载 | `backend/services/config_loader.py:36` | `routing = {r.task: list(r.chain)}` 原样 |
| LLM 启动构造 | `backend/main.py:211-249` | 内联,需抽 `_build_llm_state` |
| admin 端点 | `backend/api/admin/llm_providers.py` | 有 CRUD/test,缺 reload+fetch-models |
| query_rewrite task | `backend/pipeline/query_rewrite.py:70,119` | `task="generation"` |
| intent_tagger task | `backend/services/intent_tagger.py:52` | `task="query_decomposition"` |
| 前端页面 | `admin/src/pages/LLMProviders.tsx` | 旧结构(供应商清单+手敲路由) |
| 前端 hooks | `admin/src/hooks/useLLMProviders.ts` | 有 create/toggle/test,缺 update/reload/fetch |

plan 里每个 Task 的 Files 段都有精确行号,直接照着改。
