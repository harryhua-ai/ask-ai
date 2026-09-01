import { describe, it, expect, beforeEach } from "vitest";
import { WIDGET_ROOT_ID, resolveConfig } from "../bootstrap";

function makeDoc(body: string = ""): Document {
  const dom = new DOMParser().parseFromString(
    `<!doctype html><html><body>${body}</body></html>`,
    "text/html",
  );
  Object.defineProperty(dom, "defaultView", { value: window, configurable: true });
  return dom;
}

function makeScript(dataset: Record<string, string> = {}): HTMLScriptElement {
  const s = document.createElement("script");
  for (const [k, v] of Object.entries(dataset)) s.dataset[k] = v;
  return s;
}

describe("resolveConfig:siteId(MSW data-site-id)进入四级 fallback", () => {
  beforeEach(() => {
    delete (window as { AskAIConfig?: unknown }).AskAIConfig;
  });

  it("第一级:script data-site-id 优先", () => {
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-site-id="camthink-wiki"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    const cfg = resolveConfig(
      makeScript({ siteId: "camthink-store" }),
      preset,
      window,
    );
    expect(cfg.siteId).toBe("camthink-store");
  });

  it("第二级:preset root data-site-id 次之", () => {
    const doc = makeDoc(`<div id="${WIDGET_ROOT_ID}" data-site-id="camthink-wiki"></div>`);
    const preset = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement;
    const cfg = resolveConfig(makeScript(), preset, window);
    expect(cfg.siteId).toBe("camthink-wiki");
  });

  it("第三级:window.AskAIConfig.siteId", () => {
    (window as { AskAIConfig?: unknown }).AskAIConfig = { siteId: "camthink-website" };
    const cfg = resolveConfig(makeScript(), null, window);
    expect(cfg.siteId).toBe("camthink-website");
  });

  it("缺省:siteId 为 undefined(legacy 公共 widget,不发站点字段)", () => {
    const cfg = resolveConfig(makeScript(), null, window);
    expect(cfg.siteId).toBeUndefined();
  });
});
