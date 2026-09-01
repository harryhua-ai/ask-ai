import { describe, it, expect, beforeEach } from "vitest";
import { collectPageContext } from "../pageContext";

describe("collectPageContext(自动收集:URL/标题/语言 + AskAIConfig 结构化补充)", () => {
  beforeEach(() => {
    document.title = "NE503 Product Page";
    delete (window as { AskAIConfig?: unknown }).AskAIConfig;
  });

  it("自动收集 url/title/language", () => {
    const ctx = collectPageContext();
    expect(ctx.url).toBe(window.location.href);
    expect(ctx.title).toBe("NE503 Product Page");
    expect(ctx.language).toBe(window.navigator.language);
  });

  it("window.AskAIConfig.pageContext 提供结构化字段(宿主可选增强)", () => {
    (window as { AskAIConfig?: unknown }).AskAIConfig = {
      pageContext: { page_type: "product", product: "NE503", sku: "CM-NE503" },
    };
    const ctx = collectPageContext();
    expect(ctx.page_type).toBe("product");
    expect(ctx.product).toBe("NE503");
    expect(ctx.sku).toBe("CM-NE503");
    expect(ctx.url).toBe(window.location.href);
  });

  it("结构化字段不覆盖自动收集的 url/title", () => {
    document.title = "Auto Title";
    (window as { AskAIConfig?: unknown }).AskAIConfig = {
      pageContext: { title: "Injected Title", url: "https://evil.example" },
    };
    const ctx = collectPageContext();
    expect(ctx.title).toBe("Auto Title");
    expect(ctx.url).toBe(window.location.href);
  });
});
