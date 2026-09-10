// Issue #47 验收测试:用户问题右对齐(视觉契约冻结)。
//
// 覆盖(冻结契约):
// - 用户问题 → 右对齐:shrink-to-fit(width: fit-content)+ margin-left:auto
//   在块级格式化上下文中把气泡锚到内容区右缘;短问题不再因块盒撑满而
//   视觉上漂在会话区中部;
// - 长问题 → max-width:85% 封顶换行(word-break: break-word 防溢出);
// - ASK-AI 回答 → 保持左/内容对齐(无水平 auto 外距,无格式化上下文变更);
// - 不重新引入每条消息的 You / ASK-AI 标签(V2.3 §3.6 冻结);
// - mini 与完整会话共用唯一渲染路径(ChatPanel → MessageBubble),
//   单条 CSS 规则同时覆盖桌面/移动(640px 媒体查询不覆写气泡)。
//
// 说明:对齐几何由 widget.css 承载(jsdom 不做真实布局),故几何契约以
// 样式表规则为断言对象;DOM 断言验证类名接线与无标签回归。

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});

import { MessageBubble } from "../components/MessageBubble";
import type { ChatMessage } from "../types";

// jsdom 环境下 import.meta.url 非 file: 协议 → file: 时按测试文件定位,
// 否则回落 widget 包根(process.cwd() = npm test 运行目录)。
const cssPath = import.meta.url.startsWith("file:")
  ? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../styles/widget.css")
  : path.resolve(process.cwd(), "src/styles/widget.css");
const css = readFileSync(cssPath, "utf-8");

/** 提取顶层规则体(样式表为扁平规则,无嵌套)。 */
function ruleFor(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  expect(match, `widget.css 必须存在规则 ${selector}`).toBeTruthy();
  return match![1];
}

describe("#47 用户问题右对齐 —— 样式表几何契约", () => {
  it("用户气泡 shrink-to-fit:auto 左距把短问题锚到右缘", () => {
    const rule = ruleFor(".ask-ai-bubble-user");
    expect(rule).toMatch(/width:\s*fit-content/);
    // 右缘锚定 = 左距 auto;右距必须为 0(auto 右距会退化成居中)
    expect(rule).toMatch(/margin:\s*12px 0 4px auto/);
    expect(rule).not.toMatch(/margin-right:\s*auto/);
    expect(rule).not.toMatch(/text-align:\s*center/);
  });

  it("长问题仍以 max-width:85% 封顶换行,不横贯面板", () => {
    const rule = ruleFor(".ask-ai-bubble-user");
    expect(rule).toMatch(/max-width:\s*85%/);
    expect(rule).toMatch(/word-break:\s*break-word/);
  });

  it("ASK-AI 回答保持左/内容对齐(无水平 auto 外距)", () => {
    const rule = ruleFor(".ask-ai-bubble-assistant");
    expect(rule).not.toMatch(/margin:[^;]*auto/);
  });

  it("对齐机制依赖块级上下文 + auto 左距,不被新格式化上下文破坏", () => {
    const messages = ruleFor(".ask-ai-messages");
    expect(messages).not.toMatch(/display:\s*(flex|grid)/);
  });

  it("移动端媒体查询不覆写用户气泡对齐(桌面/移动一致)", () => {
    const media = css.match(/@media \(max-width: 640px\)\s*\{([\s\S]*?)\n\}/);
    expect(media).toBeTruthy();
    expect(media![1]).not.toContain(".ask-ai-bubble-user");
    expect(media![1]).not.toContain(".ask-ai-bubble-assistant");
  });
});

describe("#47 消息渲染路径 —— 类名接线与无标签回归", () => {
  let container: HTMLDivElement;
  let root: Root | null = null;

  const userMessage: ChatMessage = {
    id: "m1",
    type: "user",
    content: "what's the price of NE503",
  };
  const assistantMessage: ChatMessage = {
    id: "m2",
    type: "assistant",
    content: "The NE503 is priced at ¥1,299.",
  };

  const mount = (message: ChatMessage) => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root!.render(
        <MessageBubble
          message={message}
          isStreaming={false}
          apiUrl="http://localhost:8000"
          conversationId={null}
          preparingLabel="Preparing an answer…"
          onFeedback={() => {}}
        />,
      );
    });
  };

  const unmount = () => {
    act(() => root?.unmount());
    container.remove();
    root = null;
  };

  it("用户问题渲染进 ask-ai-bubble-user,内容逐字保留", () => {
    mount(userMessage);
    const bubble = container.querySelector(".ask-ai-bubble-user");
    expect(bubble).toBeTruthy();
    expect(bubble!.textContent).toBe("what's the price of NE503");
    expect(container.querySelector(".ask-ai-bubble-assistant")).toBeNull();
    unmount();
  });

  it("回答渲染进 ask-ai-bubble-assistant,与用户气泡互斥", () => {
    mount(assistantMessage);
    const bubble = container.querySelector(".ask-ai-bubble-assistant");
    expect(bubble).toBeTruthy();
    expect(bubble!.textContent).toContain("priced at");
    expect(container.querySelector(".ask-ai-bubble-user")).toBeNull();
    unmount();
  });

  it("不重新引入每条消息的 You / ASK-AI 角色标签(V2.3 §3.6 冻结)", () => {
    mount(userMessage);
    expect(container.textContent).not.toContain("You");
    unmount();
    mount(assistantMessage);
    expect(container.textContent).not.toContain("ASK-AI");
    unmount();
  });
});
