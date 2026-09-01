# T29-WIDGET-CITATION-NUMBER Execution Report

- **Task / Initiative**:t29-widget-citation-number / widget 体验 / 通用化(T1b 方向)
- **Worktree / Branch**:`/Users/harryhua/Documents/GitHub/ask-ai-t29-citation` / `worktree-exec/t29-widget-citation-number`
- **Baseline → Final Commit**:`bbfaa6a` → `d85cb83`
- **Status**:**CANDIDATE READY**(不 push,等 A Review)

## Files Changed

| 文件 | 变更 |
|---|---|
| `widget/src/utils/sanitize.ts` | ① `ALLOWED_ATTR` 增 `title`;② 引用锚点由空锚点改为:`<a href title class="ask-ai-ref" target rel>{n}</a>` —— 文本=引用编号 n,title=escapeHtml(来源标题),href 亦过 escapeHtml(属性边界加固) |
| `widget/src/styles/widget.css` | `.ask-ai-ref` 重做:logo 背景图 → 轻量数字徽章(14px 高圆角胶囊,`var(--ask-ai-primary, #2563eb)` 蓝底白字 10px,hover 提亮+去下划线);assets 未删(fab 仍用) |
| `widget/src/utils/__tests__/sanitize.test.ts` | 更新引用合并用例 + 新增 3:数字文本/顺序、title 白名单(直测 sanitizeHtml)、恶意 title 注入(序列化层+DOM 层双断言) |

3 files,+73/−12。FORBIDDEN 域零触碰:App.tsx(fab logo)、assets、admin、backend、useSSE.ts、types.ts(git diff 可证)。死样式 `.ask-ai-sources`/`.ask-ai-source-link` 按契约保留未动。

## Implementation

- 编号语义:`[n]` → idx=n-1 → 徽标文本 n(= sources 下标+1),与既有剥离逻辑同一 idx;同行多引用按出现顺序(`Set` 插入序)排列。
- 安全链保持三层:锚点构建时 title/url 显式 `escapeHtml`(引号→`&quot;`,属性边界不可逃逸)→ 末道 DOMPurify(`title` 已入白名单)。DOMPurify 序列化对属性值内 `<>` 保留原样属其安全序列化行为(引号必转义),测试以 **DOM 挂载层**断言真实安全性:无 img 元素、title 为字面文本、href/textContent 不受影响。
- `[n]` 越界静默移除:逻辑未动,既有用例原样通过。

## Verification actually executed

1. **TDD 红**:4 个新/改用例先行失败(空锚点无数字、无 title)→ 实现后 **30/30 全绿**(27 基线 +3 净增);既有 XSS 用例(script/img onerror 注入)原样通过不削弱(AC4)。
2. **tsc --noEmit**:exit 0。
3. **AC1 真实浏览器**(独立 origin 测试页 `http://localhost:3000` → 本地后端 `:8000/widget/widget.js`,widget 构建产物替换主仓 dist 后实测):
   - 真实提问「NE503 支持哪些接口?」→ 流式答案句尾渲染**数字徽标 1**(蓝底白字胶囊,computed style 实测 `bg=rgb(37,99,235)/color=#fff/radius=7px`),**无 logo 图**;截图 `/tmp/t29-e2e/ac1-badges.png`(无 CSS 版)、`/tmp/t29-e2e/ac1-badge-style.png`、`/tmp/t29-e2e/ac2-hover.png`(悬停态,徽标清晰可见);
   - DOM 实测徽标属性:`text="1"`,`title="When to Add an Edge AI Camera Instead of Another IPC · Blog"`,`href=https://www.camthink.ai/blog/...`;
4. **AC2**:①hover 后截图 + `title` 属性 DOM 证据(原生 tooltip 为浏览器合成层,截图通常不捕获,以属性存在性+悬停截图组合为证);②点击徽标 → **新标签打开原文档**:`tab-list` 实测新增 tab「When to Add an Edge AI Camera Instead of Another IPC · Blog」@ camthink.ai/blog ✓。
5. **多徽标同行按出现顺序**:契约回退口径——本地语料 4 次真实提问检索来源事件均 ≤1(对比型问题「对比 NE503 与 NG4500」答案出现裸 `[4][5][10]` 但后端未随附 sources 事件),真实多源引用未复现;**同行多徽标编号与出现顺序由单测锁定**(输入 `[2]…[1]` → 断言 `>2</a>` 先于 `>1</a>`、越界静默移除、恶意 title 注入),渲染管线与浏览器实测为同一条代码路径。

## Runtime / Real-World Self-Check 与环境清理

- 主仓 `widget/dist` 已用备份**逐字节还原**(E2E 期间临时替换为 t29 构建产物;`:8000/widget/widget.js` 复核 200),无需重启后端(后端零改动);
- 测试页 http.server :3000 已停;浏览器标签已清理;worktree 无未提交变更;主仓 main 仍为 `bbfaa6a` 零提交。

## Deviations / Risks

1. **多徽标真实数据未复现**(上述第 5 条):受本地语料检索限制,4 问均 ≤1 来源;契约回退条款适用,排序/编号语义以单测 + 同管线 DOM 断言为证。若 A 认为需真实浏览器双徽标截图,可在有多源问答数据的环境(如 T4)复核——本任务渲染层代码对来源数量无假设。
2. DOMPurify 对属性值内 `<>` 的序列化保持原样(引号转义保证不可逃逸),故恶意 title 在最终 HTML 字符串中呈字面 `<img`,安全断言落在 DOM 层(无元素注入)——测试写法比字符串断言更贴近真实安全属性,已在用例注释说明。
3. 测试页需 `<link>` 显式引入 `ask-ai-widget.css`(widget.js 不自动注 CSS)——属嵌入方集成约定,非缺陷;记录供后续 E2E 复用。

## Parallel/依赖状态

widget 渲染层域,与 C8B/T25A/T26/T27/T28 文件互斥;不依赖 T1a Phase 4。
