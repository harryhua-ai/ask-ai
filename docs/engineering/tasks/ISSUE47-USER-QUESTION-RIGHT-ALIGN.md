# Issue #47 执行报告 —— Widget 用户问题右对齐(Candidate Ready)

- **Issue**:harryhua-ai/ask-ai#47(Widget chat: user question should be right-aligned instead of centered)
- **Sprint**:Bug Fix Sprint — 2026-09(Wave 1 / P0)
- **候选分支**:`fix/47-user-question-right-align`(自 authoritative main d59027e 切出)
- **候选 SHA**:见分支 tip;提交信息含 `#47` 引用
- **结论**:CANDIDATE READY(未并 main、未部署;待 Role A 独立评审)

## 1. RCA(实现前完成,非盲改)

### 1.1 渲染路径盘点(权威 main @ d59027e)

| 路径 | 是否渲染用户消息 | 说明 |
| --- | --- | --- |
| `ChatPanel` → `MessageBubble` | **是(唯一路径)** | `.ask-ai-messages` 容器内逐条渲染;launcher 打开与 mini 生长叙事进入的是同一表面(App.tsx 仅挂载一处 ChatPanel) |
| `MiniConversationEntry`(EntrySurfaces) | 否 | 冷启动 mini 表面只有问候/动作/输入,不含消息列表 |
| Admin 实时预览(#36/#37) | 复用同一 bundle | 无第二套渲染实现 |

结论:用户消息只在一处渲染,一条 CSS 规则同时覆盖 mini/full、桌面/移动
(`@media (max-width:640px)` 只重定位面板/启动器,不覆写气泡;`prefers-reduced-motion` 只管动效)。

### 1.2 为什么生产上的问题看起来「居中」

生产 v1.4.0(41278f07,已验证为 d59027e 祖先)的规则:

```css
.ask-ai-bubble-user {
  background: var(--ask-ai-surface, #f9f9f9);
  border-radius: 10px;
  padding: 8px 12px;
  margin: 12px 0 4px auto;   /* 意图为右对齐 */
  max-width: 85%;
  ...
}
```

`margin-left:auto` 只对**宽度小于包含块**的盒子产生右锚效果。`.ask-ai-bubble-user`
是普通块级盒(父容器 `.ask-ai-messages` 为默认块格式化上下文),块盒会撑满可用宽度
—— `max-width:85%` 因此变成了**实际宽度**。结果是:

- 气泡灰色底板恒定占 85% 宽、被 auto 左距推到右侧;
- 短问题(如 `what's the price of NE503`)的文字贴在这块宽底板的**左缘**;
- 视觉呈现 = 文字悬在会话区中部、右侧拖着一长条空白底板 —— 即 issue 描述的
  「渲染在会话区中部附近」。长问题时文字被撑到接近满宽,问题反而不明显
  (v1.4.0 验收 frame 05 的长问题恰属此类)。

根因一句话:**块盒撑满 × max-width 封顶,吞掉了 auto 左距的右锚前提;缺 shrink-to-fit。**

## 2. 修复(最窄正确)

`widget/src/styles/widget.css` — `.ask-ai-bubble-user` 增加一行:

```css
width: fit-content;
```

- 短问题:气泡收缩到内容宽,`margin-left:auto` 吸收剩余空间 → **右缘锚定**;
- 长问题:`max-width:85%` 继续封顶,`word-break:break-word` 保证换行不溢出;
- 回答侧(`.ask-ai-bubble-assistant`)零改动 → 保持左/内容对齐;
- 无结构/类名/DOM 变更,无 API/检索/流式/引用语义触碰;不支持 `fit-content`
  的老浏览器回落为现状(auto 宽),不会更糟。

## 3. 变更文件

| 文件 | 变更 |
| --- | --- |
| `widget/src/styles/widget.css` | `.ask-ai-bubble-user` + `width: fit-content`(含 RCA 注释) |
| `widget/src/__tests__/issue47UserBubbleAlignment.test.tsx` | 新增:5 条样式表几何契约 + 3 条 DOM 接线/无标签回归 |

## 4. 测试与验证

- **widget 全量**:`npm test` → **183/183 绿**(175 存量 + 8 新增,0 失败);
- **生产构建**:`npm run build` → 成功;产物 `dist/ask-ai-widget.css` 中
  `.ask-ai-bubble-user` 含 `width:fit-content`(已 grep 验证);
- 新测试断言面:
  1. `width: fit-content` + `margin: 12px 0 4px auto`(auto 在左)且无 auto 右距/居中文本;
  2. `max-width:85%` + `word-break:break-word`(长问题封顶换行);
  3. `.ask-ai-bubble-assistant` 无水平 auto 外距(回答保持左对齐);
  4. `.ask-ai-messages` 不被改成 flex/grid(右锚机制依赖块级上下文);
  5. 640px 移动媒体查询不覆写气泡(桌面/移动一致);
  6–8. 用户/回答类名接线互斥、内容逐字保留、无 `You`/`ASK-AI` 标签回归(V2.3 §3.6 冻结)。

## 5. 契约符合性核对(#47 冻结行为)

| 冻结项 | 状态 |
| --- | --- |
| user question → right-aligned | ✅ shrink-to-fit + auto 左距 |
| answer/evidence → left/content aligned | ✅ 回答规则零改动 + 回归断言 |
| 不重新引入 You / ASK-AI 标签 | ✅ DOM 回归断言 |
| 短消息不居中 | ✅ 根因消除 |
| 长消息干净换行、合理最大宽 | ✅ 85% 封顶保留 + 断言 |
| 桌面/移动一致 | ✅ 单规则覆盖 + 媒体查询断言 |
| mini/full 渲染路径一致 | ✅ 唯一路径(RCA §1.1) |
| 不改答案语义/API/检索/流式/引用 | ✅ 纯呈现 CSS,单属性 |

## 6. 边界与后续

- 本报告与代码均**未**并 main、未部署、未触碰生产;
- 真实浏览器几何验证(生产同貌)按 Sprint 完成定义在 Review/Acceptance 阶段执行;
- 硬边界遵守:未重开 v1.4.0,未混入其他 Widget 重设计。
