// I-UX-001 POST-PRODUCTION CORRECTIVE(V2.3)验收测试。
//
// 覆盖(冻结契约):
// - #39 launcher 呈现方式:pill(品牌「✦ Ask AI」)= 新站点默认;NULL = icon
//   (既有站点 legacy 不变);嵌入覆写优先;迟到的 site-config 不二次闪变;
// - Greeting 模板:静态模板原样;受控变量({product_name}/{page_title}/
//   {page_type})确定性解析;变量缺失 → 安全回落自动问候链(绝不泄漏占位符);
// - #40 等待态:「✦ Preparing an answer…」真实状态;禁三点打字指示器;
//   首个真实 token 原位替换;
// - Mini Conversation 头部 = ASK-AI 品牌身份(✦ Ask AI);
// - 全程零 LLM 调用(问候/呈现纯确定性)。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});

import { App } from "../App";
import {
  resolveGreetingTemplate,
  resolveEngagement,
} from "../experience/greeting";
import { resolveLauncherPresentation } from "../experience/launcher";
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
let askResolvers: ((resp: Response) => void)[] = [];

function mockAskNetwork() {
  askCalls = [];
  askResolvers = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/ask")) {
        askCalls.push({ url, body: JSON.parse(String(init?.body ?? "{}")) });
        return new Promise<Response>((resolve) => askResolvers.push(resolve));
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
    pendingFetches[pendingFetches.length - 1].resolve({ site_id: "iux-site", ...cfg });
  });
  await act(async () => {});
}

beforeEach(() => {
  pendingFetches = [];
  mockAskNetwork();
  sessionStorage.clear();
  window.innerWidth = 1280; // 桌面
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (window as unknown as { AskAIConfig?: unknown }).AskAIConfig;
  document.title = "";
  document.body.innerHTML = "";
});

// ---------------------------------------------------------------------------
// #39 launcher 呈现方式
// ---------------------------------------------------------------------------

describe("launcher presentation(V2.3 #39)", () => {
  it("presentation=pill → 品牌「✦ Ask AI」胶囊;非 FAB", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite({ launcher_presentation: "pill" });
    const pill = container.querySelector<HTMLElement>(".ask-ai-launcher-pill");
    expect(pill).not.toBeNull();
    expect(pill!.textContent).toContain("Ask AI");
    expect(pill!.textContent).toContain("✦");
    expect(container.querySelector(".ask-ai-fab")).toBeNull();
    expect(pill!.getAttribute("aria-label")).toContain("Ask AI");
    root.unmount();
  });

  it("未配置(NULL)→ icon FAB(既有站点 legacy 行为不变)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite({});
    expect(container.querySelector(".ask-ai-fab")).not.toBeNull();
    expect(container.querySelector(".ask-ai-launcher-pill")).toBeNull();
    root.unmount();
  });

  it("嵌入覆写 data-launcher-presentation=icon 压过站点 pill 配置", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(
      container,
      baseConfig({ launcherPresentation: "icon" }),
    );
    await resolveSite({ launcher_presentation: "pill" });
    expect(container.querySelector(".ask-ai-fab")).not.toBeNull();
    expect(container.querySelector(".ask-ai-launcher-pill")).toBeNull();
    root.unmount();
  });

  it("resolveLauncherPresentation:未知值/NULL → undefined(legacy)", () => {
    expect(resolveLauncherPresentation({ launcherPresentation: undefined }, { launcher_presentation: "pill" })).toBe("pill");
    expect(resolveLauncherPresentation({ launcherPresentation: undefined }, { launcher_presentation: "banner" })).toBeUndefined();
    expect(resolveLauncherPresentation({ launcherPresentation: undefined }, null)).toBeUndefined();
    expect(resolveLauncherPresentation({ launcherPresentation: "icon" }, { launcher_presentation: "pill" })).toBe("icon");
  });

  it("pill 点击 → mini_entry 桌面展开 C(与 FAB 同一交互契约)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite({ entry_mode: "mini_entry", launcher_presentation: "pill" });
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-launcher-pill")!.click();
    });
    expect(container.querySelector(".ask-ai-mini")).not.toBeNull();
    expect(container.querySelector(".ask-ai-launcher-pill")).toBeNull();
    root.unmount();
  });
});

// ---------------------------------------------------------------------------
// Greeting 模板(确定性;零 LLM)
// ---------------------------------------------------------------------------

describe("greeting template resolution(V2.3)", () => {
  const BASE = {
    hostContext: null,
    url: "https://example.invalid/",
    title: "",
    lang: "en" as const,
  };

  it("静态模板(无变量)原样使用(显式 Admin 权威)", () => {
    expect(resolveGreetingTemplate("Questions about NE503?", { product: "NE503", pageTitle: "t", pageType: "product" })).toBe(
      "Questions about NE503?",
    );
  });

  it("{product_name} 受信上下文解析", () => {
    expect(resolveGreetingTemplate("Questions about {product_name}?", { product: "NE503", pageTitle: null, pageType: "product" })).toBe(
      "Questions about NE503?",
    );
    // {product} 遗留别名同语义
    expect(resolveGreetingTemplate("关于 {product} 的问题?", { product: "NE503", pageTitle: null, pageType: "product" })).toBe(
      "关于 NE503 的问题?",
    );
  });

  it("{page_type}/{page_title} 解析(类别级安全)", () => {
    expect(resolveGreetingTemplate("About this {page_type}", { product: null, pageTitle: "Setup", pageType: "documentation" })).toBe(
      "About this documentation",
    );
  });

  it("变量缺失 → null(回落自动链;绝不暴露占位符)", () => {
    expect(resolveGreetingTemplate("Questions about {product_name}?", { product: null, pageTitle: null, pageType: "unknown" })).toBeNull();
    expect(resolveGreetingTemplate("Help with {page_title}?", { product: null, pageTitle: null, pageType: "product" })).toBeNull();
    expect(resolveGreetingTemplate("About the {page_type}", { product: null, pageTitle: null, pageType: "unknown" })).toBeNull();
  });

  it("engagement:模板变量缺失回落自动问候(不泄漏 {product_name})", () => {
    const ctx = resolveEngagement({
      ...BASE,
      site: { greeting_override: "Questions about {product_name}?" },
      previewProduct: undefined,
    });
    expect(ctx.greeting).not.toContain("{");
    expect(ctx.greeting).toBe("How can I help?"); // 无其它信号 → 通用兜底
  });

  it("engagement:模板解析成功 = HIGH 置信问候", () => {
    const ctx = resolveEngagement({
      ...BASE,
      site: { greeting_override: "Questions about {product_name}?" },
      previewProduct: "NE503",
    });
    expect(ctx.greeting).toBe("Questions about NE503?");
    expect(ctx.confidence).toBe("high");
  });

  it("engagement:启发式 page_type 可填 {page_type}(类别级;永不产生专名)", () => {
    const ctx = resolveEngagement({
      ...BASE,
      url: "https://example.invalid/docs/setup",
      site: { greeting_override: "About this {page_type}" },
    });
    expect(ctx.greeting).toBe("About this documentation");
    expect(ctx.greeting).not.toContain("setup");
  });
});

// ---------------------------------------------------------------------------
// #40 等待态 + Mini 头部品牌
// ---------------------------------------------------------------------------

describe("waiting state(#40)", () => {
  it("发送后等待 = 「✦ + Preparing an answer…」;无三点打字指示器;首 token 原位替换", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig({ channel: "widget" }));
    await resolveSite({});
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-fab")!.click();
    });
    const input = container.querySelector<HTMLInputElement>(".ask-ai-input input[type='text']")!;
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      nativeSetter.call(input, "What is NE503?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-send-btn")!.click();
    });
    // 等待态:品牌星点 + 真实文案;三点指示器绝不允许
    const preparing = container.querySelector<HTMLElement>(".ask-ai-preparing");
    expect(preparing).not.toBeNull();
    expect(preparing!.textContent).toContain("✦");
    expect(preparing!.textContent).toContain("Preparing an answer");
    expect(container.querySelector(".ask-ai-typing-dot")).toBeNull();
    expect(container.querySelectorAll(".ask-ai-preparing")).toHaveLength(1);
    // 首个真实 token 到达 → 等待态让位,答案内容主导,无重复指示器
    await act(async () => {
      askResolvers[0](
        sseResponse([
          "event: token\ndata: {\"content\": \"NE503 is \"}\n\n",
          "event: done\ndata: {\"conversation_id\": \"c-9\"}\n\n",
        ]),
      );
    });
    expect(container.querySelector(".ask-ai-preparing")).toBeNull();
    const assistant = container.querySelector<HTMLElement>(".ask-ai-bubble-assistant")!;
    expect(assistant.textContent).toContain("NE503 is");
    expect(assistant.querySelector(".ask-ai-typing-dot")).toBeNull();
    root.unmount();
  });
});

describe("mini conversation identity(V2.3)", () => {
  it("C 头部 = ASK-AI 品牌身份(✦ Ask AI);站点名保留为可访问名", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await resolveSite({
      display_name: "CamThink 官网",
      entry_mode: "mini_entry",
      trusted_actions: [],
    });
    await act(async () => {
      container.querySelector<HTMLElement>(".ask-ai-launcher-pill, .ask-ai-fab")!.click();
    });
    const identity = container.querySelector<HTMLElement>(".ask-ai-mini-identity");
    expect(identity).not.toBeNull();
    expect(identity!.textContent).toContain("✦");
    expect(identity!.textContent).toContain("Ask AI");
    expect(identity!.getAttribute("aria-label")).toBe("CamThink 官网");
    root.unmount();
  });
});
