import { describe, it, expect, beforeEach } from "vitest";
import { collectPageContext } from "../pageContext";
import { buildAskBody } from "../../hooks/useSSE";

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
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/neoeyes-503/"));
    expect(ctx).toMatchObject({ page_type: "product", product: "NE503", sku: "NE503" });
  });

  it("官方 Store 配件声明兼容多个系列时不派生产品身份", () => {
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "OV5640 Camera Module", sku: "OV5640",
      isAccessoryOrSparePartFor: [{ name: "NE101" }, { name: "NE301" }],
    })}</script>`;
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/ov5640/"));
    expect(ctx.page_type).toBe("accessory");
    expect(ctx.product).toBeUndefined();
    expect(ctx.sku).toBeUndefined();
  });

  it.each([
    ["missing target name", { "@id": "#unknown-target" }],
    ["empty target name", { "@id": "#unknown-target", name: " " }],
  ])("单个配件关系的目标 %s 时不回退到配件自身身份", (_label, relation) => {
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "NE101 Camera Accessory", sku: "ACCESSORY-1",
      isAccessoryOrSparePartFor: relation,
    })}</script>`;
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/ov5640/"));
    expect(ctx.page_type).toBe("accessory");
    expect(ctx.product).toBeUndefined();
    expect(ctx.sku).toBeUndefined();
  });

  it("配件仅有自身 name/SKU、没有可信目标关系时 abstain", () => {
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "OV5640 5MP Camera Module for NE101", sku: "OV5640",
    })}</script>`;
    const ctx = collectPageContext(pageWindow("https://www.camthink.ai/store/ov5640/"));
    expect(ctx.page_type).toBe("accessory");
    expect(ctx.product).toBeUndefined();
    expect(ctx.sku).toBeUndefined();
  });

  it("官方真实样本矩阵按合格页面类型计数并达到 95%", () => {
    // 真实官方页面结构采样 (2026-10-13):
    // Store: /store/neoeyes-503/、/store/neoeyes-ne101/、/store/ne301/、
    // /store/ne301-poe/、/store/ne101-dev-kit/；配件 /store/ov5640/、
    // /store/usb-camera-module/、/store/mounting-ne101/；
    // Wiki: /docs/{neoedge-ng4500,neoeyes-ne101,neoeyes-ne301,
    // neoeyes-ne302,neoeyes-ne503}-series/{overview}/ 与 /docs/neomind/。
    // Product JSON-LD 节点为直接抓取的公开 JSON-LD；仅独立关系字段为受控正/负 fixture。
    const storeProducts = [
      ["neoeyes-503", "NeoEyes NE503 4K PoE Edge AI Camera", 5110],
      ["neoeyes-ne101", "NeoEyes NE101 Modular Sensing Camera", 319],
      ["ne301", "NeoEyes NE301 Wireless Edge AI Camera", 2092],
      ["ne301-poe", "NeoEyes NE301 PoE Edge AI Camera", 4271],
      ["ne101-dev-kit", "NeoEyes NE101 Dev Kit - ESP32-S3 Modular Vision Camera Kit", "73.001.000011"],
    ] as const;
    const productRows = storeProducts.map(([slug, name, sku]) => {
      document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
        "@context": "https://schema.org/", "@type": "Product", name, sku,
      })}</script>`;
      return collectPageContext(pageWindow(`https://www.camthink.ai/store/${slug}/`));
    });
    const storeProductSuccesses = productRows.filter((row) => row.page_type === "product" && !!row.product).length;
    expect({ successes: storeProductSuccesses, denominator: productRows.length }).toEqual({ successes: 5, denominator: 5 });
    expect(storeProductSuccesses / productRows.length).toBeGreaterThanOrEqual(0.95);

    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "OV5640 5MP Camera Module for NE101", sku: "OV5640",
      isAccessoryOrSparePartFor: { "@type": "Product", name: "NeoEyes NE101" },
    })}</script>`;
    const uniqueAccessory = collectPageContext(pageWindow("https://www.camthink.ai/store/ov5640/"));
    expect({ successes: Number(uniqueAccessory.page_type === "accessory" && uniqueAccessory.product === "NE101"), denominator: 1 })
      .toEqual({ successes: 1, denominator: 1 });

    const accessoryAbstainRows = [
      ["ov5640", undefined], // 官方 Product JSON-LD:只有自身 name/SKU，无目标关系
      ["usb-camera-module", undefined],
      ["mounting-ne101", undefined],
      ["ov5640", [{ name: "NE101" }, { name: "NE301" }]],
      ["ov5640", { "@id": "#unknown-target" }],
      ["ov5640", { name: " " }],
    ] as const;
    const abstainRows = accessoryAbstainRows.map(([slug, relation]) => {
      const product: Record<string, unknown> = {
        "@type": "Product", name: "OV5640 5MP Camera Module for NE101", sku: "OV5640",
      };
      if (relation !== undefined) product.isAccessoryOrSparePartFor = relation;
      document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify(product)}</script>`;
      return collectPageContext(pageWindow(`https://www.camthink.ai/store/${slug}/`));
    });
    const safeAccessoryAbstains = abstainRows.filter(
      (row) => row.page_type === "accessory" && !row.product && !row.sku,
    ).length;
    expect({ safeAbstains: safeAccessoryAbstains, denominator: abstainRows.length })
      .toEqual({ safeAbstains: 6, denominator: 6 });

    const wikiSeries = [
      ["neoedge-ng4500-series", "NG4500"], ["neoeyes-ne101-series", "NE101"],
      ["neoeyes-ne301-series", "NE301"], ["neoeyes-ne302-series", "NE302"],
      ["neoeyes-ne503-series", "NE503"], ["neomind", "NeoMind"],
    ] as const;
    const wikiRows = wikiSeries.map(([slug, product]) => ({
      product,
      context: collectPageContext(pageWindow(`https://wiki.camthink.ai/docs/${slug}/overview/`)),
    }));
    const wikiSuccesses = wikiRows.filter(({ product, context }) => context.page_type === "product" && context.product === product).length;
    expect({ successes: wikiSuccesses, denominator: wikiRows.length }).toEqual({ successes: 6, denominator: 6 });
    expect(wikiSuccesses / wikiRows.length).toBeGreaterThanOrEqual(0.95);
  });

  it("派生或 abstain 的 Widget 上下文按现有请求体契约传给 API", () => {
    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "NeoEyes NE503 4K PoE Edge AI Camera", sku: 5110,
    })}</script>`;
    const derived = collectPageContext(pageWindow("https://www.camthink.ai/store/neoeyes-503/"));
    expect(buildAskBody("Tell me about this product", [], "widget", [], { pageContext: derived }).page_context)
      .toMatchObject({ page_type: "product", product: "NE503" });

    document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({
      "@type": "Product", name: "OV5640 Camera Module", sku: "OV5640",
    })}</script>`;
    const abstained = collectPageContext(pageWindow("https://www.camthink.ai/store/ov5640/"));
    expect(buildAskBody("What about this product?", [], "widget", [], { pageContext: abstained }).page_context)
      .toMatchObject({ page_type: "accessory" });
    expect(buildAskBody("What about this product?", [], "widget", [], { pageContext: abstained }).page_context)
      .not.toHaveProperty("product");
  });

  it("只从有界已知型号匹配营销名；数字 SKU 忽略，零/多匹配 abstain", () => {
    const samples = [
      ["NeoEyes NE503 4K PoE Edge AI Camera", 5110, "NE503"],
      ["CamThink premium smart camera", 5110, undefined],
      ["NE503 and NE301 camera bundle", 5110, undefined],
    ] as const;
    const contexts = samples.map(([name, sku, expected]) => {
      document.body.innerHTML = `<script type="application/ld+json">${JSON.stringify({ "@type": "Product", name, sku })}</script>`;
      const context = collectPageContext(pageWindow("https://www.camthink.ai/store/special-offer/"));
      expect(context.product).toBe(expected);
      expect(context.sku).toBeUndefined();
      return context;
    });
    expect(buildAskBody("Tell me about this product", [], "widget", [], { pageContext: contexts[0] }).page_context)
      .toMatchObject({ page_type: "product", product: "NE503" });
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
