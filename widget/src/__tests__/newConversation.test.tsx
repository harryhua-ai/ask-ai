// #87 REPLAN(a):「新对话」供属 RED→GREEN。
//
// 冻结语义(A 2026-09-18,PR #98 评论 5729885652):
// - Widget 提供轻量「新对话」动作:调用即轮换 ask_ai_session_id + 清空 transcript;
// - 仅会话开始后出现(冷启动无意义);流式进行中禁用;
// - 轮换本身无网络动作;下一个 ask 携带新 session_id 与空 history。

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom 未实现 scrollIntoView(messages effect 需要)
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});

import { ChatPanel } from "../components/ChatPanel";
import { uiStrings } from "../i18n";
import type { WidgetConfig, ChatMessage } from "../types";

const CONFIG: WidgetConfig = { apiUrl: "http://test" };
const STRINGS = uiStrings("zh");
const THEME = {};

function msg(id: string, content: string): ChatMessage {
  return { id, type: "user", content };
}

const BASE_PROPS = {
  config: CONFIG,
  strings: STRINGS,
  isStreaming: false,
  conversationId: null,
  suggestedQuestions: [],
  themeStyle: THEME,
  character: "dark" as const,
  chatSize: "default" as const,
  coldActions: [],
  onColdAction: vi.fn(),
  onSend: vi.fn(),
  onNewConversation: vi.fn(),
  onClose: vi.fn(),
  onFeedback: vi.fn(),
  onUpload: vi.fn(async () => []),
};

let host: HTMLDivElement | null = null;
let root: Root | null = null;

function renderPanel(props: Partial<typeof BASE_PROPS> & { messages: ChatMessage[] }) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  const merged = { ...BASE_PROPS, ...props };
  act(() => {
    root!.render(<ChatPanel {...merged} />);
  });
}

let cleanups: Array<() => void> = [];
beforeEach(() => {
  cleanups.push(() => {
    act(() => root?.unmount());
    host?.remove();
    host = null;
    root = null;
  });
});

// 每个用例结束后统一卸载(保持单一 act 语义)
import { afterEach } from "vitest";
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

describe("ChatPanel 新对话供属(#87 REPLAN a)", () => {
  it("会话开始后渲染「新对话」,点击恰好回调一次 onNewConversation", () => {
    const spy = vi.fn();
    renderPanel({ messages: [msg("m1", "第一问")], onNewConversation: spy });
    const btn = document.querySelector('[data-testid="new-conversation"]');
    expect(btn).not.toBeNull();
    act(() => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("冷启动(无消息)不渲染「新对话」", () => {
    renderPanel({ messages: [] });
    expect(document.querySelector('[data-testid="new-conversation"]')).toBeNull();
  });

  it("流式进行中禁用「新对话」(不得在生成中途轮换身份)", () => {
    renderPanel({ messages: [msg("m1", "第一问")], isStreaming: true });
    const btn = document.querySelector('[data-testid="new-conversation"]') as HTMLButtonElement;
    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(true);
  });

  it("可访问名来自 i18n(zh=新对话)", () => {
    renderPanel({ messages: [msg("m1", "第一问")] });
    const btn = document.querySelector('[data-testid="new-conversation"]') as HTMLElement;
    expect(btn.getAttribute("aria-label")).toBe("新对话");
  });
});
