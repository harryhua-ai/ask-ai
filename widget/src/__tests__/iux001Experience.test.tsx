// I-UX-001:App 集成验收(RED→GREEN;jsdom)。
//
// 覆盖(冻结契约):
// - 入口:A/B/C 可配置;legacy(未配置)= 仅 launcher;
// - 桌面 C 主动展开:延迟 ≈6s(balanced)后 C 自动出现;每站点会话一次;
//   minimize/not-now 后本会话尊重;
// - 移动端 mini_entry:主动呈现 = B nudge(绝不自动展开 C/聊天);
// - 单交互契约:C 动作点击 / C 文本提交 → 立即打开聊天并发出真实 /ask;
// - 冷启动清理:会话开始后 C/nudge/starter/动作全部退场(message-first);
// - SPA:导航不重触发主动展开;
// - 证据 UX:行内引用保留;默认不渲染重复 Sources 清单;
// - 预览模式:复用真实渲染路径,绝不产生 /ask 流量。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});

import { App } from "../App";
import type { WidgetConfig, SiteExperienceConfig } from "../types";

type Pending = { resolve: (v: SiteExperienceConfig) => void; reject: (e: unknown) => void };
let pendingFetches: Pending[] = [];

vi.mock("../utils/siteConfig", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../utils/siteConfig")>();
  return {
    ...orig,
    fetchSiteConfig: vi.fn(
      (_apiUrl: string, _siteId: string, opts?: { language?: string; signal?: AbortSignal }) =>
        new Promise<SiteExperienceConfig>((resolve, reject) => {
          pendingFetches.push({ resolve, reject });
          opts?.signal?.addEventListener("abort", () => reject(new Error("Aborted")), { once: true });
        }),
    ),
  };
});

const C_SITE: SiteExperienceConfig = {
  site_id: "iux-site",
  display_name: "CamThink 官网",
  entry_mode: "mini_entry",
  proactive_timing: "balanced",
  trusted_actions: [
    { type: "PRODUCT_SPECIFICATIONS", label: "Specifications", query: "What are the specifications of NE503?" },
    { type: "SETUP_GUIDE", label: "Setup guide", query: "How do I set up NE503?" },
    { type: "TROUBLESHOOT", label: "Troubleshoot", query: "Help me troubleshoot: {page_title}" },
  ],
};

function sseResponse(chunks: string[]): Response {
  const stream = new ReadableStream({
    start(controller) {
      const enc = new TextEncoder();
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

let askCalls: { url: string; body: Record<string, unknown> }[] = [];

function mockAskNetwork() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/ask")) {
        askCalls.push({ url, body: JSON.parse(String(init?.body ?? "{}")) });
        return sseResponse(["event: done\ndata: {\"conversation_id\": \"c-1\"}\n\n"]);
      }
      return new Response("{}", { status: 200 });
    }),
  );
}

function baseConfig(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return { apiUrl: "http://localhost:8000", siteId: "iux-site", ...overrides };
}

async function mountApp(container: HTMLElement, config: WidgetConfig): Promise<Root> {
  const root = createRoot(container);
  await act(async () => {
    root.render(<App config={config} />);
  });
  await act(async () => {});
  return root;
}

async function resolveSite(cfg: Partial<SiteExperienceConfig> = {}) {
  await act(async () => {
    pendingFetches[0].resolve({ site_id: "iux-site", ...cfg });
  });
  await act(async () => {});
}

beforeEach(() => {
  pendingFetches = [];
  askCalls = [];
  sessionStorage.clear();
  mockAskNetwork();
  window.innerWidth = 1280; // 桌面
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("I-UX-001 入口模式", () => {
  it("legacy(未配置 experience)= 仅 launcher;点击打开浮动聊天(非全高抽屉)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite({});
    expect(container.querySelector(".ask-ai-fab")).not.toBeNull();
    expect(container.querySelector(".ask-ai-pill")).toBeNull();
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-fab")!.click();
    });
    const panel = container.querySelector<HTMLElement>(".ask-ai-panel");
    expect(panel).not.toBeNull();
    root.unmount();
  });

  it("A pill:pill 入口 + 点击进聊天", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig({ entryMode: "pill" }));
    await resolveSite({ entry_mode: "pill" });
    const pill = container.querySelector<HTMLElement>(".ask-ai-pill");
    expect(pill).not.toBeNull();
    expect(container.querySelector(".ask-ai-fab")).toBeNull(); // A 模式无图标 fab
    await act(async () => {
      pill!.click();
    });
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    root.unmount();
  });

  it("B nudge:上下文问候气泡;dismiss 后回落 pill(可发现性兜底)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig({ entryMode: "nudge" }));
    await resolveSite({ entry_mode: "nudge" });
    const nudge = container.querySelector<HTMLElement>(".ask-ai-nudge");
    expect(nudge).not.toBeNull();
    expect(nudge!.textContent).toContain("How can I help?"); // 无信号 → 通用兜底
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-nudge-dismiss")!.click();
    });
    expect(container.querySelector(".ask-ai-nudge")).toBeNull();
    expect(container.querySelector(".ask-ai-pill")).not.toBeNull();
    root.unmount();
  });
});

describe("I-UX-001 桌面 C 主动展开(§2.2)", () => {
  it("balanced ≈6s 后 C 自动展开(每站点会话一次);动作点击 = 单交互真实请求", async () => {
    vi.useFakeTimers();
    history.replaceState({}, "", "/products/ne503"); // 产品页上下文 → 规格/安装两动作适用
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite(C_SITE);
    // 期限前:仅 launcher
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(6100);
    });
    // C 自动展开
    const mini = container.querySelector<HTMLElement>(".ask-ai-mini");
    expect(mini).not.toBeNull();
    // 冷启动 IA:问候 + ≤2 动作 + 输入(产品页上下文 → 类别问候,永不伪造专名)
    expect(mini!.textContent).toContain("Questions about this product?");
    const chips = mini!.querySelectorAll(".ask-ai-mini-action");
    expect(chips.length).toBe(2); // 上限 2
    // 单交互:动作点击 → 聊天开 + 真实 /ask 立即发出
    await act(async () => {
      chips[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    expect(askCalls).toHaveLength(1);
    expect(askCalls[0].body.message).toBe("What are the specifications of NE503?");
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    root.unmount();
  });

  it("C minimize → 本会话尊重(不二次主动展开)", async () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite(C_SITE);
    await act(async () => {
      vi.advanceTimersByTime(6100);
    });
    expect(container.querySelector(".ask-ai-mini")).not.toBeNull();
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-mini-minimize")!.click();
    });
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(60000);
    });
    expect(container.querySelector(".ask-ai-mini")).toBeNull(); // 不再主动
    // launcher 点击仍可手动展开 C(入口保留)
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-fab")!.click();
    });
    expect(container.querySelector(".ask-ai-mini")).not.toBeNull();
    root.unmount();
  });

  it("SPA 导航不重触发主动展开(会话闸)", async () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite(C_SITE);
    await act(async () => {
      vi.advanceTimersByTime(6100);
    });
    expect(container.querySelector(".ask-ai-mini")).not.toBeNull();
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-mini-minimize")!.click();
    });
    // 模拟 SPA 导航(history.pushState 触发 pageWatch → engagement 重算)
    await act(async () => {
      history.pushState({}, "", "/products/ne503");
    });
    await act(async () => {
      vi.advanceTimersByTime(12000);
    });
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    root.unmount();
  });
});

describe("I-UX-001 移动端(§2.3)", () => {
  it("mini_entry 移动端:主动呈现 = B nudge,绝不自动展开 C/聊天", async () => {
    vi.useFakeTimers();
    window.innerWidth = 390;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite(C_SITE);
    await act(async () => {
      vi.advanceTimersByTime(6100);
    });
    expect(container.querySelector(".ask-ai-mini")).toBeNull(); // 不自动展开 C
    const nudge = container.querySelector<HTMLElement>(".ask-ai-nudge");
    expect(nudge).not.toBeNull(); // 主动呈现 = B
    // nudge 点击(显式交互)→ 完整聊天
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-nudge-body")!.click();
    });
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    root.unmount();
  });
});

describe("I-UX-001 冷启动清理与证据 UX(§2.8/§2.9)", () => {
  it("会话开始后:C/nudge 退场,聊天窗 message-first(冷动作消失)", async () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite(C_SITE);
    await act(async () => {
      vi.advanceTimersByTime(6100);
    });
    const input = container.querySelector<HTMLInputElement>(".ask-ai-mini-input input")!;
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      nativeSetter.call(input, "What interfaces does NE503 support?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-mini-input button")!.click();
    });
    await act(async () => {});
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    expect(askCalls).toHaveLength(1); // C 文本提交 = 真实请求立即发出
    expect(container.querySelector(".ask-ai-mini")).toBeNull();
    expect(container.querySelector(".ask-ai-cold-actions")).toBeNull();
    root.unmount();
  });

  it("行内引用徽标保留;默认无重复 Sources 清单", async () => {
    const { renderMarkdownSafe } = await import("../utils/sanitize");
    const html = renderMarkdownSafe(
      "The NE503 supports CAN.[1]\n[2] is another.",
      [
        { url: "https://x.test/a", title: "A", type: "wiki" },
        { url: "https://x.test/b", title: "B", type: "wiki" },
      ],
    );
    expect(html).toContain("ask-ai-ref"); // 行内引用徽标
    expect(html).not.toMatch(/Sources/i); // 默认无 Sources 清单
  });

  it("预览模式:真实渲染路径 + 零 /ask 流量", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(
      container,
      baseConfig({
        previewMode: true,
        previewPageType: "product",
        previewProduct: "NE503",
        previewActions: [
          { type: "PRODUCT_SPECIFICATIONS", label: "Specifications", query: "Specs of NE503" },
        ],
      }),
    );
    await resolveSite(C_SITE);
    // 高置信产品问候(预览上下文)
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-fab")!.click();
    });
    const mini = container.querySelector<HTMLElement>(".ask-ai-mini");
    expect(mini).not.toBeNull();
    expect(mini!.textContent).toContain("Questions about NE503?");
    await act(async () => {
      mini!.querySelector<HTMLElement>(".ask-ai-mini-action")!.click();
    });
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    expect(askCalls).toHaveLength(0); // 预览绝不产生真实请求
    expect(container.querySelector(".ask-ai-panel")!.textContent).toContain("Preview mode");
    root.unmount();
  });
});
