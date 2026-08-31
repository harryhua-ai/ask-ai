import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  WIDGET_ROOT_ID,
  resolveConfig,
  mountWidget,
  type MountedWidget,
} from "../bootstrap";
import type { WidgetConfig } from "../types";

const DEFAULTS = { apiUrl: "http://localhost:8000", primaryColor: "#f24a00" };

function makeDoc(body: string = ""): Document {
  const dom = new DOMParser().parseFromString(
    `<!doctype html><html><body>${body}</body></html>`,
    "text/html",
  );
  // DOMParser 文档无 defaultView 的脚本执行语义,补最小 window 桩
  Object.defineProperty(dom, "defaultView", { value: window, configurable: true });
  return dom;
}

function makeScript(dataset: Record<string, string> = {}): HTMLScriptElement {
  const s = document.createElement("script");
  for (const [k, v] of Object.entries(dataset)) s.dataset[k] = v;
  return s;
}

describe("resolveConfig:契约 T1 冻结的 fallback 顺序", () => {
  it("第一级:currentScript dataset 优先于一切", () => {
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-api-url="http://preset"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    (window as { AskAIConfig?: Record<string, string> }).AskAIConfig = {
      apiUrl: "http://global",
    };
    const cfg = resolveConfig(makeScript({ apiUrl: "http://script" }), preset, window);
    expect(cfg.apiUrl).toBe("http://script");
    delete (window as { AskAIConfig?: unknown }).AskAIConfig;
  });

  it("第二级:页面预置 #ask-ai-widget-root 的 data-* 次之", () => {
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-api-url="http://preset"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    (window as { AskAIConfig?: Record<string, string> }).AskAIConfig = {
      apiUrl: "http://global",
    };
    const cfg = resolveConfig(makeScript(), preset, window);
    expect(cfg.apiUrl).toBe("http://preset");
    delete (window as { AskAIConfig?: unknown }).AskAIConfig;
  });

  it("第三级:window.AskAIConfig 再次之", () => {
    (window as { AskAIConfig?: Record<string, string> }).AskAIConfig = {
      apiUrl: "http://global",
      primaryColor: "#112233",
    };
    const cfg = resolveConfig(makeScript(), null, window);
    expect(cfg.apiUrl).toBe("http://global");
    expect(cfg.primaryColor).toBe("#112233");
    delete (window as { AskAIConfig?: unknown }).AskAIConfig;
  });

  it("兜底:默认 apiUrl=http://localhost:8000,primaryColor=#f24a00", () => {
    const cfg = resolveConfig(makeScript(), null, window);
    expect(cfg.apiUrl).toBe(DEFAULTS.apiUrl);
    expect(cfg.primaryColor).toBe(DEFAULTS.primaryColor);
    expect(cfg.language).toBeUndefined();
  });

  it("逐键 fallback:script 只给 primaryColor 时,apiUrl 仍可来自预置元素", () => {
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-api-url="http://preset"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    const cfg = resolveConfig(makeScript({ primaryColor: "#ff0000" }), preset, window);
    expect(cfg.apiUrl).toBe("http://preset");
    expect(cfg.primaryColor).toBe("#ff0000");
  });

  it("language 三级透传", () => {
    expect(resolveConfig(makeScript({ language: "en" }), null, window).language).toBe("en");
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-language="ja"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    expect(resolveConfig(makeScript(), preset, window).language).toBe("ja");
  });
});

describe("mountWidget:容器复用与防双浮窗", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    document.querySelectorAll(`#${WIDGET_ROOT_ID}`).forEach((n) => n.remove());
  });

  async function mountTwice(scriptDataset: Record<string, string>): Promise<MountedWidget[]> {
    const first = mountWidget(document, makeScript(scriptDataset));
    await vi.waitFor(() => {
      const c = document.getElementById(WIDGET_ROOT_ID);
      if (!c || c.childElementCount === 0) throw new Error("first mount not ready");
    });
    const before = document.getElementById(WIDGET_ROOT_ID)!.innerHTML;
    const second = mountWidget(document, makeScript(scriptDataset));
    await new Promise((r) => setTimeout(r, 20));
    const after = document.getElementById(WIDGET_ROOT_ID)!.innerHTML;
    // 第二次注入不得改变已渲染 DOM(无第二个浮窗实例)
    expect(after).toBe(before);
    expect(document.querySelectorAll(`#${WIDGET_ROOT_ID}`).length).toBe(1);
    return [first, second];
  }

  it("注入两次 script:复用同一容器,不产生第二个浮窗", async () => {
    const [a, b] = await mountTwice({ apiUrl: "http://x" });
    expect(a.container).toBe(b.container);
  });

  it("页面预置 #ask-ai-widget-root 时复用该元素而非新建", () => {
    document.body.innerHTML = `<div id="${WIDGET_ROOT_ID}" data-api-url="http://preset"></div>`;
    const preset = document.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    const m = mountWidget(document, makeScript());
    expect(m.container).toBe(preset);
    expect(m.config.apiUrl).toBe("http://preset");
  });

  it("无预置元素时新建容器挂到 body", () => {
    const m = mountWidget(document, makeScript());
    expect(document.getElementById(WIDGET_ROOT_ID)).toBe(m.container);
    expect(document.body.contains(m.container)).toBe(true);
  });

  it("配置解析走完整 fallback 链(script dataset 优先)", () => {
    document.body.innerHTML = `<div id="${WIDGET_ROOT_ID}" data-api-url="http://preset"></div>`;
    const preset = document.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    const m = mountWidget(document, makeScript({ apiUrl: "http://script" }));
    expect(m.container).toBe(preset);
    expect((m.config as WidgetConfig).apiUrl).toBe("http://script");
  });
});
