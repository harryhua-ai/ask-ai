# LLM 模型配置系统重设计

> 日期:2026-08-05
> 状态:设计定稿,待写实现计划
> 范围:LLM 供应商编辑 + 路由 model 粒度 + 热重载 + admin 全局 widget 风格刷新

---

## 1. 背景与问题

当前 LLM 供应商页面(`admin/src/pages/LLMProviders.tsx`)存在以下问题:

1. **没有编辑入口** — 后端 `PATCH /llm-providers/{id}` 已就绪,但前端只有新增/停用/测试,改不了 api_base/model/api_key/参数。
2. **改配置需重启容器** — `app.state.llm` 在 `lifespan` 启动时一次性构造,RAG/Pruner 锁住引用,改完要 `docker restart`。
3. **路由手敲 id** — 路由配置是文本框,用户手敲 `deepseek, openrouter`,易拼错。
4. **model 粒度不足** — 同一供应商在生成用 v4-pro、查询用 v4-flash 做不到(`config.model` 单值,chain 只引用 provider)。
5. **职责主轴错位** — 页面以"供应商清单 + 路由"组织,用户心智是"每个环节用什么模型"。
6. **流水线覆盖不全** — 漏了意图分类(`task=intent`);"查询分解"实为 `intent_tagger.py` 的 task 名误导,代码里不存在查询分解逻辑。
7. **视觉风格陈旧** — admin 用 shadcn 默认 neutral 风格,与 widget 的现代感(Manrope/大圆角/软阴影)不一致。

---

## 2. 目标

- LLM 供应商凭证(api_base/api_key/available_models)可在 UI 编辑,改完**点按钮热重载**,无需重启。
- 同一供应商凭证在多个任务复用,各任务可独立指定 model。
- 页面按**模型职责**(向量/排序/意图/查询处理/剪枝/生成)组织,完整覆盖检索流水线。
- admin 全局刷新为 widget 风格。
- 向后兼容现有 DB 数据(chain 字符串格式 → 对象格式平滑迁移)。

---

## 3. 架构设计

### 3.1 热重载(方案 C:router 内部可变)

**核心思路**:`LLMRouter` 从"构造即固定"改为"可重配"。`app.state.llm` 永远是同一个对象,reload 只换它内部的 `_providers`/`_routing` 字典。

**为什么选方案 C(而非替换 app.state.llm)**:

审计 `app.state.llm` 消费点后发现:

| 消费点 | 取用方式 | 替换 app.state.llm 后 |
|---|---|---|
| `RAGOrchestrator(llm=router_llm)` | 启动时传入,内部持有 | ❌ 锁住旧引用 |
| `LLMPruner(router_llm)` | 启动时传入 | ❌ 锁住旧引用 |
| `api/admin/conversations.py` | `request.app.state.llm` 现取 | ✅ |

方案 C 让 RAG/Pruner 持有的**同一对象**内部字典可变,reconfigure 后它们自然看到新配置。零侵入消费点。

**改造**:

```python
# backend/llm/registry.py — LLMRouter
class LLMRouter:
    def __init__(self, providers: dict[str, LLMProvider], routing: dict[str, list[dict]]):
        self._providers = providers
        self._routing = routing

    def reconfigure(self, providers: dict, routing: dict) -> None:
        """整 dict 替换(不改旧 dict 内容),并发期间正在跑的请求用旧或新 dict 快照,不混。"""
        self._providers = providers
        self._routing = routing

    async def generate(self, messages, task="generation", **kwargs):
        last_error = None
        for item in self._get_chain(task):  # item = {provider, model?}
            pid, model = item["provider"], item.get("model")
            provider = self._providers.get(pid)
            if provider is None:
                continue
            try:
                if await provider.health_check():
                    call_kwargs = {**kwargs, "model": model} if model else kwargs
                    return await provider.generate(messages, **call_kwargs)
            except Exception as e:  # noqa: BLE001 - 故障切换需捕获所有异常
                last_error = e
                continue
        raise RuntimeError(f"All LLM providers unavailable for task={task}: {last_error}")
```

> 注:`generate` 在循环内逐迭代通过 `self._providers.get()` 读取 providers 字典。reconfigure 整体替换 dict 引用,每次 `.get()` 原子无损坏;但若 reconfigure 恰好落在两次迭代之间的 await 处,单次 generate 可能跨新旧 providers 快照(无数据损坏,仅是 provider 可能中途变化)。异步单线程下该窗口极短,风险可忽略。

**main.py 抽公共函数**:

```python
async def _build_llm_state(settings, factory) -> tuple[dict, dict]:
    """从 DB 读 providers/routing → 解密 → LLMRegistry.create。
    返回 (providers_dict, routing_dict),不 new router。启动和 reload 复用。"""
```

### 3.2 数据模型变更

#### `llm_providers.config` 新增 `available_models`

```jsonc
// 旧
{ "api_base": "...", "api_key": "enc:...", "model": "deepseek-v4-pro", "max_tokens": 4096, "temperature": 0.3 }

// 新(加 available_models,model 保留为默认=available_models[0])
{
  "api_base": "...", "api_key": "enc:...",
  "model": "deepseek-v4-pro",           // 默认 model(向后兼容)
  "available_models": [                  // 新增:该供应商可用模型列表
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-reasoner"
  ],
  "max_tokens": 4096, "temperature": 0.3
}
```

#### `llm_routing.chain` 元素对象化

```jsonc
// 旧(字符串数组)
{ "task": "generation", "chain": ["deepseek", "openrouter"] }

// 新(对象数组,model 可选)
{
  "task": "generation",
  "chain": [
    { "provider": "deepseek", "model": "deepseek-v4-pro" },
    { "provider": "openrouter", "model": null }   // null = 用 provider 默认
  ]
}
```

#### 向后兼容(归一化)

`load_llm_config_from_db` 加载 chain 时归一化:

```python
def _normalize_chain_item(item) -> dict:
    """str → {provider: str, model: None};dict → 原样(补默认 key)。"""
    if isinstance(item, str):
        return {"provider": item, "model": None}
    return {"provider": item["provider"], "model": item.get("model")}
```

写入时统一存对象格式。旧字符串数据读取时自动升级,下次写回即为对象。

#### 迁移脚本

新增 `scripts/migrate_llm_chain_format.py`(幂等,dry-run):

1. `llm_providers`:available_models 为空 → 从 config.model 初始化 `[config.model]`。若 config.model 不在 available_models 中(用户编辑后漂移),强制纳入并作为默认;两者皆空则跳过该 provider,记 skipped。
2. `llm_routing`:chain 元素是 str → 转成 `{provider: str, model: null}`。
3. `llm_routing`:task=`query_decomposition` → 删除(intent_tagger 的历史命名错误)。
4. `llm_routing`:确保 `intent` 路由存在(实时 `intent.py` + 离线 `intent_tagger.py` 都走它)。不存在则从 generation chain 复制一份(若 generation 也不存在则 skip + 记 skipped,不凭空创建),让用户后续在 UI 改成 flash。
5. `llm_routing`:确保 `query_rewrite` 路由存在(查询提取/改写)。同上,不存在则复制 generation chain。

### 3.3 task 名统一与独立路由

| 流水线环节 | 代码 task 名 | 处理 |
|---|---|---|
| 意图分类(实时) | `intent` (`intent.py:65`) | ✅ 已正确,补进路由表 |
| 意图分类(离线标注) | `query_decomposition` (`intent_tagger.py:52`) | ❌ **改名 → `intent`** |
| 查询提取 | `generation` (`query_rewrite.py:119`) | **拆出 → `query_rewrite`** |
| 查询改写 | `generation` (`query_rewrite.py:70`) | **拆出 → `query_rewrite`** |
| 剪枝 | `pruning` (`pruner.py:75`) | ✅ 已正确 |
| 生成 | `generation` (`rag.py:454,604`) | ✅ 已正确 |

**后端改动**:
- `query_rewrite.py:70,119`:`task="generation"` → `task="query_rewrite"`。
- `intent_tagger.py:52`:`task="query_decomposition"` → `task="intent"`。
- 回退安全:LLMRouter._get_chain 缺 task 时回退 generation,拆出后若 DB 无 query_rewrite/intent 路由,自动用 generation。

### 3.4 模型自动拉取

`DeepseekProvider` 新增 `list_models()`:

```python
async def list_models(self) -> list[str]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{self._api_base}/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
```

新端点 `POST /llm-providers/{provider_id}/fetch-models`(admin/editor):
- 解密 DB 中 api_key → 构造临时 provider → 调 list_models → 返回模型 id 列表。
- 失败返回脱敏错误(不泄露 key/内部异常,同 test 端点策略)。
- **前端用途**:编辑弹窗"从 API 拉取"按钮(图标用 lucide `RefreshCw`,非 emoji)→ 候选列表 → 用户勾选 → 存入 available_models。手填兜底(供应商不支持 `/models` 时)。

---

## 4. 后端 API 变更清单

### 新增端点

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/llm-providers/reload` | POST | admin/editor | 从 DB 重读 → `app.state.llm.reconfigure()`。返回 `{status, providers_count, routing, skipped:[...]}`。DB 全空时返回 400(避免清空线上 router)。 |
| `/llm-providers/{id}/fetch-models` | POST | admin/editor | 调供应商 `/models` 拉取可用模型列表。 |

### 现有端点(无 breaking change)

- `PATCH /llm-providers/{id}`:已支持 config 部分更新 + api_key 防覆盖(`********` 占位符剔除)。无需改。
- `POST/DELETE/GET /llm-providers`:无需改。
- `PUT /llm-routing/{task}`:chain 现在接受对象数组,后端归一化后存。前端传新格式。

### reload 端点错误处理

- 单个 provider 构造失败(未注册 type/配置非法):跳过,记 `skipped`,reload 仍成功。
- DB 全空(所有 provider disabled):返回 400,保留旧配置,不清空 router。
- reload 不创建 LLMPruner(启动时创建):UI 明确提示"首次启用剪枝需重启"。

---

## 5. 前端设计

### 5.1 页面结构:按模型职责 6 环节网格

**主轴** = 检索流水线的 6 个模型职责,统一 2×3 网格,尺寸一致:

| | 列 1 | 列 2 |
|---|---|---|
| **行 1**(检索基础,只读灰底) | 向量模型 `embedding` — BAAI/bge-m3 · cuda · dim 1024 | 排序模型 `rerank` — BAAI/bge-reranker-v2-m3 · cuda |
| **行 2**(LLM 处理,白底可配) | ① 意图分类 `intent` | ② 查询处理 `query_rewrite` |
| **行 3**(LLM 处理,白底可配) | ③ 剪枝 `pruning`(首启需重启) | ④ 生成 `generation` |

**只读卡**(向量/排序):灰底 + "只读"badge + 右上角 ⓘ tooltip("本地模型,代码固定,如需更换改后端代码")。

**可配卡**(意图/查询处理/剪枝/生成):白底,供应商用 chip 平铺(编号 + 名 + model pill),底部"+ 从已有供应商添加"。

**流水线顺序提示**(网格下方小字):`意图分类(1) → 查询处理(2) → 向量+排序检索 → 剪枝(3) → 生成(4)`

### 5.2 页头

- 标题"模型配置" + 副标题"按流水线环节配置各阶段模型 · 改完点应用变更生效"
- **"供应商凭证"按钮**(outline)— 打开供应商凭证管理弹窗。
- **"应用变更"按钮**(primary 黑底白字 + RefreshCw 图标)— 调 reload 端点。**不显示"待应用计数"**(后端无状态,不可靠)。reload 成功后 toast 反馈。

### 5.3 chip(供应商链路项)

选中态:**2px 黑描边** + 左侧编号圆点 + model pill(浅灰小标签)。**不用实心填充**(避免连选成黑坨)。

- model pill:显示真实 model 名 + 可选"默认"小标签(不再只写孤零零的"默认")。点击 ▾ 从该 provider 的 available_models 切换。
- 点击 chip → 弹出 popover:切 model(单选)+ 移出链路(红,需确认)+ 调顺序(上下箭头)。

### 5.4 子弹窗

#### ① 供应商凭证管理弹窗(点"供应商凭证")

列出全部供应商(●启用/○停用),每行:id + 类型/模型数 + 编辑/测试/删除。底部"+ 新增供应商"。凭证改完回主页应用变更。

#### ② 凭证编辑弹窗(点"编辑")

字段:
- **类型**:只读 badge(`openai_compatible`,只有这一种)。
- **API Base**:输入框(等宽)。
- **API Key**:回显 `********` + 加密说明("显示 ******** = 已加密,清空后粘贴新 key 才更换")。后端防覆盖逻辑保留。
- **可用模型**(新增):列表式编辑,★ 标默认(第 1 个),可增/删/拖序。
  - "从 API 拉取"按钮(图标 lucide `RefreshCw`)→ 候选列表(带过滤搜索)→ 勾选加入。前提:已填 api_base + api_key。
  - "手动添加"兜底(不支持 `/models` 的供应商)。
- **底部**:"测试连通"按钮(配完 key 即时验证)+ 取消/保存。

#### ③ 添加供应商到任务(任务卡点"+添加")

radio 列表选已有供应商(停用的灰显)+ "新建..."入口。选完指定用哪个 model(从该供应商 available_models)。确认 → 加入链路。

#### ④ chip popover(点已有 chip)

切 model(单选列表)+ 移出链路(红,二次确认)+ 调顺序(上下箭头)。原地编辑。

### 5.5 复用机制

供应商凭证共享:deepseek 配一次(base/key/available_models),意图分类/查询处理/剪枝/生成都能选它,各自指定 model。添加供应商时从已有凭证池选,不重填 key。改 api_key 只改一处。

### 5.6 图标规范

统一 `lucide-react` 线性图标(stroke 1.5–2px,无填色):

| 操作 | 图标 |
|---|---|
| 应用变更 | `RefreshCw` |
| 供应商凭证管理 | `SlidersHorizontal` |
| 新增/添加 | `Plus` |
| 编辑凭证 | `Pencil` |
| 移除 | `X`(hover 变红) |
| 测试 | `Activity` |
| 只读说明 | `Info`(tooltip) |

**禁用 emoji 占位**。

---

## 6. admin 全局 widget 风格刷新

用户决策:全局主题刷新合进本 spec(不另起 spec)。

### 6.1 design token

从 `widget/src/styles/widget.css` 提取,注入 admin shadcn 主题变量(`admin/src/index.css`):

| token | 值 | 现有值 |
|---|---|---|
| 字体 | Manrope(已全局,`index.css` L24) | Manrope ✓ 无需改 |
| `--radius` | `0.5rem`(8px) | 0.5rem ✓ 无需改 |
| `--primary` | `0 0% 9%`(近黑 #111) | 0 0% 9% ✓ 已是 |
| `--border` | `0 0% 89.8%`(#dbdbdb 系) | 0 0% 89.8% ✓ 已是 |
| 卡片圆角 | `rounded-lg`(8px) | ✓ 已用 |
| 卡片 padding | `p-4`(16px) | ✓ 已用 |
| 网格 gap | `gap-3`(12px) | ✓ 已用 |
| 按钮主操作 | `default`(primary 实心) | ✓ |
| 按钮次操作 | `outline`(描边) | ✓ |

**发现**:admin 全局 token 与 widget 风格**已高度吻合**(Manrope/8px 圆角/近黑 primary/outline 次按钮均已是现状)。主要差异在:
- widget 的软阴影(widget.css 实际值:FAB `box-shadow: 0 4px 12px rgba(0,0,0,0.15)`)→ 给 primary 按钮和弹窗加上。
- 统一图标用 lucide(部分页面已用,需全量走查)。

### 6.2 走查范围

所有 admin 页面需走查风格一致性:DataSources / SyncLogs / Customizations / LLMProviders(重构)/ Conversations / AnswerOverrides / Analytics / Users。重点:按钮 variant 一致、图标体系统一 lucide、弹窗用 shadcn Dialog。

### 6.3 侧边栏

- label "LLM 供应商" → "**模型配置**"。
- 路由 path `/llm-providers` **不改**(bookmark 不失效)。
- 图标 `Cpu` 保留或换 `Settings`/`SlidersHorizontal`(可选)。

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| reload 时某 provider 构造失败 | 跳过,记 skipped,reload 成功,响应返回 skipped 列表 |
| reload 时 DB 全空 | 返回 400,保留旧配置 |
| fetch-models 网络/key 错误 | 返回脱敏错误(同 test 端点),完整异常仅 server 日志 |
| api_key 编辑留 `********` | 后端剔除占位符,保留 DB 旧密文(现有逻辑) |
| available_models 为空 | chain item model 回退 provider.config.model |
| available_models 与 config.model 同时为空(迁移前异常数据) | provider.generate 不传 model 参数(交由供应商 API 报错或用其默认);UI 标红该 provider 提示"未配置模型" |
| 剪枝首次启用 | LLMPruner 启动时创建,reload 不创建。UI 黄色警告 badge"首启需重启" |
| 移除链路项 | 二次确认 popover |
| query_rewrite/intent 路由未配 | LLMRouter 回退 generation(现有逻辑) |

---

## 8. 测试策略

### 后端(pytest)

- **LLMRouter 单元**:reconfigure 后 generate 用新 providers/routing;chain 对象 {provider,model} 的 model 透传;旧字符串 chain 归一化兼容。
- **迁移脚本**:幂等(跑两次结果一致)、dry-run、旧数据正确升级。
- **reload 端点**:成功路径;skipped provider;DB 全空 400;RAG 持有的 router 引用 reconfigure 后看到新配置(集成测试)。
- **fetch-models 端点**:成功返回列表;key 无效脱敏错误;mock httpx。
- **task 名**:query_rewrite/intent 路由缺失时回退 generation。

### 前端(组件测试 + Playwright E2E)

- 编辑弹窗:api_key `********` 占位符不覆盖;available_models 增删拖序;从 API 拉取候选勾选。
- 路由多选:chip 选中/取消;顺序调整;model 切换;移除确认。
- 热重载:点应用变更 → reload → toast。

### 覆盖率

≥ 80%(遵循全局测试规则)。

---

## 9. 文件影响清单

### 后端(新增/修改)

| 文件 | 改动 |
|---|---|
| `backend/llm/registry.py` | LLMRouter 加 reconfigure;generate 解析 {provider,model} |
| `backend/llm/deepseek.py` | 新增 list_models() |
| `backend/main.py` | 抽 `_build_llm_state()`;lifespan 复用 |
| `backend/services/config_loader.py` | chain 归一化(_normalize_chain_item) |
| `backend/api/admin/llm_providers.py` | 新增 reload、fetch-models 端点 |
| `backend/pipeline/query_rewrite.py` | task → `query_rewrite`(2 处) |
| `backend/services/intent_tagger.py` | task → `intent` |
| `scripts/migrate_llm_chain_format.py` | 新增:chain 对象化 + available_models 初始化 + query_decomposition 清理 |
| `config/llm_providers.yaml` | seed 加 available_models |

### 前端(新增/修改)

| 文件 | 改动 |
|---|---|
| `admin/src/pages/LLMProviders.tsx` | **重构**:6 环节网格 + chip 多选 + model 选择 |
| `admin/src/hooks/useLLMProviders.ts` | 加 useUpdateProvider / useReloadProviders / useFetchModels |
| `admin/src/components/ProviderCredentialDialog.tsx` | 新增:凭证管理弹窗 |
| `admin/src/components/ProviderEditDialog.tsx` | 新增:凭证编辑弹窗(含 available_models + 拉取) |
| `admin/src/components/AddToTaskDialog.tsx` | 新增:添加供应商到任务 |
| `admin/src/components/ChainChip.tsx` | 新增:chip + popover |
| `admin/src/components/Sidebar.tsx` | label → "模型配置" |
| `admin/src/index.css` | 微调 token(软阴影等) |
| 其他 admin 页面 | 风格走查(按钮 variant / 图标统一) |

---

## 10. 验收标准

- [ ] 在 UI 编辑 deepseek 的 api_key/model,保存后点"应用变更",RAG 立即用新配置(不重启)。
- [ ] 同一 deepseek 在生成选 v4-pro、意图分类选 v4-flash,凭证共享。
- [ ] 新增供应商(如 openrouter),编辑弹窗"从 API 拉取"模型列表,勾选存入。
- [ ] 路由多选 chip,选多个定故障切换顺序,切 model,移除有确认。
- [ ] 页面 6 环节网格,向量/排序只读,4 个 LLM 环节可配。
- [ ] admin 全局 widget 风格统一(软阴影/lucide 图标/按钮 variant 一致)。
- [ ] 旧 DB 数据(chain 字符串格式)迁移后正常工作。
- [ ] reload 不中断正在进行的流式生成。
- [ ] 后端测试覆盖率 ≥ 80%。

---

## 附录:关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 热重载方案 | C(router 内部可变) | RAG/Pruner 锁引用,替换 app.state.llm 无效;reconfigure 零侵入 |
| model 粒度 | 方案 A(路由里可选 model) | 凭证与模型解耦,改 key 一处;LLMProvider.generate 已支持 kwargs |
| 复用粒度 | 供应商(凭证共享) | 不引入预设抽象,数据模型最小 |
| 页面主轴 | 6 环节模型职责(2 只读 + 4 可配) | 匹配用户心智,覆盖完整流水线 |
| 布局 | 6 环节 2×3 网格 | 尺寸统一,紧凑 |
| 模型来源 | 拉取+勾选+手填兜底 | 自动拉取做候选池,手填应对不支持 /models 的供应商 |
| widget 风格范围 | 合进本 spec(全局) | 用户选择不拆分;token 已高度吻合,改动小 |
| 路由 path | 不改(`/llm-providers`) | bookmark 不失效 |
| 范围拆分 | 不拆(单 spec) | 用户选择 |
| intent task 名 | 统一为 `intent` | 修正 intent_tagger 的 query_decomposition 误导 |

---

## 修订记录

- 2026-08-05 初稿。基于代码核查 + 可视化审核定稿(8 轮 mockup 迭代)。
- 2026-08-05 Dual Review Round 1 修复(见下方审核日志)。

<!-- 以上为文档正文,以下为审核修复记录 -->

---

## Dual Review Log

### Round 1 — 2026-08-05 · 单路两阶段(独立 sub-agent)

| # | 级别 | 阶段 | 标准性质 | 位置 | 问题 | 修复动作 |
|---|------|------|---------|------|------|---------|
| 1 | MEDIUM | P1 | 事实核查 | §6.1 正文 | widget 软阴影引用值 `0 2px 8px rgba(0,0,0,0.12)` 在 widget.css 中不存在(实际 FAB 是 `0 4px 12px rgba(0,0,0,0.15)`) | 改为引用真实值 |
| 2 | MEDIUM | P2 | 机械检测 | §3.4 + §5.4② vs §5.6 | "🔄 从 API 拉取"emoji 与 §5.6"禁用 emoji 占位"自相矛盾 | 改为 lucide `RefreshCw` 图标 + 文字 |
| 3 | LOW | P1 | 事实核查 | §6.1 表"字体"行 | Manrope 标注 `index.css L20`,实际 L24(偏差 4 行) | 改为 L24 |
| 4 | LOW | P2 | 主观意见 | §3.1 reconfigure | 两行赋值理论并发窗口 | 不改(GIL 下单 dict 赋值原子,风险可忽略;注释已说明) |
| 5 | LOW | P2 | 主观意见 | §7 错误处理表 | available_models 与 config.model 同时为空未定义 | 补一行边界处理 |
| 6 | LOW | P2 | 主观意见 | 附录"方案 C" | 未列方案 A/B 对比 | 不改(决策记录已自洽,3.1 消费点审计表已隐含否决理由) |

**本轮修复**: 4 个(#1/#2/#3/#5)| **保留不改**: 2 个(#4/#6,主观且可接受)| **累计修复**: 4 个

**Phase 1 事实核查**: 34 项可证伪声明,32 项已核实一致,2 项不符已修(阴影值/行号)
**Phase 2 质量判断**: UI 图标位 emoji 矛盾已修;主观建议 2 条保留

---

### Round 2 — 2026-08-05 · 单路两阶段(独立 sub-agent 复审)

**Round 1 修复验证**: 4 项全部落地正确(逐一对代码核实)。

| # | 级别 | 阶段 | 标准性质 | 位置 | 问题 | 修复动作 |
|---|------|------|---------|------|------|---------|
| 1 | MEDIUM | P1 | 事实核查 | §6.1 L301 | `--border` 行标"接近,微调",实际已是 `0 0% 89.8%`(与目标完全相等),体例矛盾 | 改为 `✓ 已是` |
| 2 | LOW | P2 | 主观意见 | §3.1 generate 片段 | 丢弃 last_error 上下文(现状 registry.py:67 有),故障根因被吞 | 补 `last_error = e` + 终态带上下文 |
| 3 | LOW | P2 | 主观意见 | §3.1 reconfigure 注释 | "不混"过度宣称;generate 跨迭代重读 _providers,reconfigure 落 await 间隙时单次调用可见新旧交替 | 改注释为准确描述(跨迭代可能交替但无损坏)。Round 1 判"不改",Round 2 部分不同意——注释是可证伪的不准确陈述,修成本极低,采纳 |
| 4 | LOW | P2 | 机械检测 | 审核日志标题 | `## 🔍 Dual Review Log` 的 🔍 是 Round 1 追加日志时引入的 emoji | 改纯文字 `Dual Review Log` |
| 5 | LOW | P2 | 边界遗漏 | §3.2 迁移步骤 | (a) config.model 不在 available_models 时默认未定义;(b) 复制 generation chain 时 generation 缺失未定义 | 步骤 1 补"强制纳入/两者皆空 skip";步骤 4 补"generation 不存在则 skip + 记 skipped" |
| 6 | LOW | P2 | 机械检测 | §3.1/§3.3 表格符号 | ❌/✅/★ 为状态标记 | 不改(文档惯例的状态符号,非 UI 图标 emoji,与 §5.6"禁用 emoji 占位"本义不冲突) |

**本轮修复**: 5 个(#1/#2/#3/#4/#5)| **保留不改**: 1 个(#6)| **累计修复**: 9 个

**Phase 1 事实核查**: 新查 DeepseekProvider kwargs 支持、7 个 lucide 图标名真实性、6 处 task 行号复验、PATCH 占位符逻辑、RAG/Pruner 引用锁定 — 全部一致;border 行事实矛盾已修
**Phase 2 质量判断**: 修复 Round 1 遗留的注释不准确 + 边界遗漏;机械检测仅剩文档惯例状态符号

---

### 汇总

- **收敛轮次**: 2
- **累计修复**: 9 个(CRITICAL 0 / HIGH 0 / MEDIUM 3 / LOW 6;按标准性质:事实核查 4 / 机械检测 2 / 主观意见 3)
- **审核模式**: 单路两阶段(独立 sub-agent)
- **Phase 1 事实核查**: ✅ 通过(34+ 项声明核实,关键代码引用全部精确命中)
- **Phase 2 质量判断**: ✅ 通过
- **完成时间**: 2026-08-05
