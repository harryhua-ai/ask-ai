import { describe, it, expect, beforeEach } from "vitest";
import { collectPageContext } from "../pageContext";

const pageWindow = (href: string) => Object.assign(Object.create(window), {
  location: { href }, document, navigator: window.navigator,
}) as Window;

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

  it("官方 Store 商品页从唯一 Product JSON-LD 派生产品身份和页面类型", () => {
    document.title = "NE503 Edge AI Camera";
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "NeoEyes NE503 Edge AI Camera", sku: "NE503",
    })}</script>`;
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/product/neoeyes-ne503/"));
    expect(ctx).toMatchObject({ page_type: "product", product: "NeoEyes NE503 Edge AI Camera", sku: "NE503" });
  });

  it("官方 Store 配件声明兼容多个系列时不派生产品身份", () => {
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "OV5640 Camera Module", sku: "OV5640",
      isAccessoryOrSparePartFor: [{ name: "NE101" }, { name: "NE301" }],
    })}</script>`;
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/product/ov5640-camera-module/"));
    expect(ctx.page_type).toBe("accessory");
    expect(ctx.product).toBeUndefined();
    expect(ctx.sku).toBeUndefined();
  });

  it("官方 Wiki 产品系列路由派生规范产品名，其他宿主不读页面元数据", () => {
    const wiki = collectPageContext(pageWindow("https://wiki.camthink.ai/docs/neoeyes-ne503-series/"));
    expect(wiki).toMatchObject({ page_type: "product", product: "NE503" });

    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "NE503",
    })}</script>`;
    const thirdParty = collectPageContext(pageWindow("https://untrusted.example/store/product/ne503/"));
    expect(thirdParty.product).toBeUndefined();
  });
});
