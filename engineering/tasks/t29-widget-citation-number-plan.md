# T29-WIDGET-CITATION-NUMBER Execution Contract(引用徽标:logo → 数字)

- **Task ID**:t29-widget-citation-number | **Parent Initiative**:widget 体验 / 通用化(T1b 方向)
- **Baseline Commit**:`bbfaa6a`(main = origin/main)
- **Risk Level**:**L1**(widget 纯前端渲染层,后端零改动;渲染管线含 XSS 清洗,需守安全用例)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——用户新增需求:"回答后引用原文档的图标(camthink logo)换成 1,2,3 字样"。纯 UI 语义变更,含悬停标题补全。

## 1. Objective

widget 答案中的行内引用徽标由 CamThink logo 背景图改为**数字徽标**(对应 `[n]` 标记的 n),悬停显示来源标题;移除引用位的品牌图元素。

## 2. Current State / Evidence(Inspect @ bbfaa6a)

| # | 事实 | 级别 |
|---|---|---|
| E1 | LLM 答案含行内 `[n]` 标记;`renderMarkdownSafe`(`widget/src/utils/sanitize.ts:60-79`)剥离 `[n]` 并在句尾追加**空锚点** `<a class="ask-ai-ref"></a>`(href=来源链接) | FACT |
| E2 | `.ask-ai-ref` 样式(`widget/src/styles/widget.css:176-183`)= 12×12px inline-block + `background-image: url("../assets/CamThink.ai-black.png")` ——即用户所见 logo 图标 | FACT |
| E3 | 锚点无文字内容、无 title;来源 `SourceLink{url,title,type,product}` 由 SSE `sources` 事件附带(`useSSE.ts:115`),title 字段已可用但未被渲染 | FACT |
| E4 | `ALLOWED_ATTR = ["href","target","rel","class"]`(`sanitize.ts:9`)——`title` 不在白名单,加了也会被末道 DOMPurify 剥掉 | FACT |
| E5 | `.ask-ai-sources` / `.ask-ai-source-link` CSS 存在但无任何代码生成该标记(死样式);widget 无来源列表渲染 | FACT |
| E6 | fab 角标 logo(`App.tsx:5` + css)与引用徽标相互独立,不在本任务范围 | FACT |

## 3. Scope

- 引用锚点渲染为数字徽标:锚点文本内容 = 引用编号 n(即 sources 下标+1),同行多引用按出现顺序排列;替换背景图方案;
- 徽标悬停显示来源标题(锚点 `title` 属性),`title` 加入 DOMPurify 白名单;
- `.ask-ai-ref` 样式重做(数字徽标视觉:轻量小徽章,尺寸/配色/圆角 HOW 归 B,设计意图=清晰可读、与正文区分、可点击);
- sanitize 既有测试同步更新 + 新增安全/行为用例(数字文本不被清洗、title 保留、恶意 title 注入安全);
- 死样式 `.ask-ai-sources`/`.ask-ai-source-link` **保留不动**(留给将来来源列表功能,非本任务清理项——如执行端顺手清理须记 Deviation)。

## 4. Non-goals

fab 角标 logo;答案下方来源列表(独立后续项);admin 聊天渲染;后端 prompt/`[n]` 标记格式;`SourceLink` 结构;primaryColor 消费(T1b)。

## 5. Change Boundary

**Product**:允许 = 引用徽标视觉由 logo 换数字 + 悬停标题;必须不变 = `[n]` 剥离与锚点追加机制、链接打开行为(新标签)、XSS 三层防护强度、超出范围的 `[n]` 静默移除。
**Code EXPECTED**:`widget/src/utils/sanitize.ts`、`widget/src/styles/widget.css`、`widget/src/__tests__/`(sanitize 相关测试)。
**CONDITIONAL**:若徽标需 React 层配合(仅当现有锚点方案不够)——原则上禁,保持纯渲染层方案。
**FORBIDDEN**:`widget/src/App.tsx`(fab logo)、assets 删除、admin/**、backend/**、`useSSE.ts`、types.ts。
**Regression**:widget vitest 全量(27+)全绿 + `tsc --noEmit`;真实浏览器截图。

## 6. Frozen Contract

1. 引用徽标显示数字 n(来自 `[n]`),无 CamThink logo 图;点击行为不变(新标签打开原文档);
2. 悬停徽标显示对应来源 title;
3. DOMPurify 防护不削弱:数字/title 均经白名单显式放行,新增注入用例通过;
4. `[n]` 超出 sources 范围仍静默移除(现状语义)。

## 7. Acceptance Criteria

- **AC1**:真实浏览器(本地测试页跨 origin)提问得到带 `[1][2]` 的流式答案:句尾渲染数字徽标 1、2,无 logo 图,截图证据;
- **AC2**:悬停任一徽标出现来源标题气泡;点击新标签打开对应文档;
- **AC3**:widget vitest 全量绿 + tsc 干净;新增用例 ≥3(数字文本保留、title 白名单、title 含引号/HTML 的注入安全);
- **AC4**:sanitize 既有 XSS 用例(脚本注入/事件属性)不削弱;
- **AC5**:报告落 `docs/engineering/tasks/t29-widget-citation-number-execution.md`,CANDIDATE READY,不 push。

## 8. Parallel / 依赖

widget 渲染层域,与 C8B / T25A / T26 / T27 / T28 文件互斥,可并行;不依赖 T1a Phase 4。

---

## 9. Executor Prompt(可拷贝)

```markdown
# Role B 执行任务:T29-WIDGET-CITATION-NUMBER(引用徽标 logo → 数字)

先完整阅读:
1. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
2. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
3. 契约:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t29-widget-citation-number-plan.md

## 任务
按契约把 widget 答案的行内引用徽标从 CamThink logo 背景图改为数字徽标:
① sanitize.ts 引用锚点(sanitize.ts:60-79,现为空锚点 + css 背景图 widget.css:176-183)改为
   锚点文本 = 引用编号 n;② 锚点加 title=来源标题,并把 "title" 加入 ALLOWED_ATTR 白名单
   (不加白名单会被末道 DOMPurify 剥掉);③ 重做 .ask-ai-ref 样式为轻量数字徽章;
④ 更新/新增 sanitize 测试:数字文本保留、title 保留、title 注入安全(引号/HTML)、
   既有 XSS 用例不削弱、[n] 越界静默移除保持。

## 环境与边界
- 主仓:/Users/harryhua/Documents/GitHub/ask-ai(baseline = main = origin/main = bbfaa6a,开工前自行核实)
- worktree:/Users/harryhua/Documents/GitHub/ask-ai-t29-citation,分支 worktree-exec/t29-widget-citation-number
- Change Boundary 以契约 §5 为准:EXPECTED sanitize.ts + widget.css + widget 测试;
  FORBIDDEN App.tsx(fab logo)、assets 删除、admin、backend、useSSE.ts、types.ts
- 不 push、不部署;后端复用主仓本地 :8000(不改后端码,无需重启)

## 验证(全部实际执行,给证据)
1. widget `npx vitest run` 全量 + `tsc --noEmit`
2. 真实浏览器 AC1-2:本地测试页(独立 origin,参考 /tmp/t1a-review-pages 或自建)连本地后端,
   真实提问 → 流式答案句尾数字徽标截图(无 logo 图);悬停出现来源标题;点击新标签打开原文档
3. 若来源不足两个,可连发两问或用已知多引用问题确认多徽标同行按出现顺序排列

## 交付
- 报告:docs/engineering/tasks/t29-widget-citation-number-execution.md(协议模板:Worktree/Branch、
  Baseline/Final Commit、Files Changed、Implementation、Verification actually executed、
  Runtime/Self-Check、Deviations/Risks、Status)
- 最终回复必须含:报告路径 + final commit + 状态(仅 CANDIDATE READY / PARTIAL / FAIL / BLOCKED)
- Gate 停等:本任务不 push,等 A Review 放行
```
