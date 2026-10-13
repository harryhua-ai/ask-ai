// 宿主页面上下文自动收集(非信任语义提示;后端消毒后仅作软加分/背景段)。
// 产品身份只从官方 Store 的 JSON-LD 或官方 Wiki 的已知系列路由派生；
// 不抓取页面正文，也不把页面 metadata 提升为事实来源。
import type { PageContextPayload } from "../types";

const WIKI_SERIES: Record<string, string> = {
  "neoedge-ng4500-series": "NG4500",
  "neoeyes-ne101-series": "NE101",
  "neoeyes-ne301-series": "NE301",
  "neoeyes-ne302-series": "NE302",
  "neoeyes-ne503-series": "NE503",
  neomind: "NeoMind",
};

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasType(value: unknown, type: string): boolean {
  const types = Array.isArray(value) ? value : [value];
  return types.some((item) => typeof item === "string" && item.toLowerCase().split(/[\/#]/).pop() === type.toLowerCase());
}

function productNodes(value: unknown): JsonRecord[] {
  if (Array.isArray(value)) return value.flatMap(productNodes);
  if (!isRecord(value)) return [];
  const own = hasType(value["@type"], "Product") ? [value] : [];
  return [...own, ...productNodes(value["@graph"])];
}

function relatedProducts(value: unknown): JsonRecord[] {
  if (Array.isArray(value)) return value.filter(isRecord);
  return isRecord(value) ? [value] : [];
}

function storeProductContext(doc: Document): PageContextPayload {
  const products: JsonRecord[] = [];
  for (const script of Array.from(doc.querySelectorAll('script[type="application/ld+json"]'))) {
    try {
      products.push(...productNodes(JSON.parse(script.textContent || "")));
    } catch {
      // 忽略格式错误或非 JSON-LD 内容，保持页面可用。
    }
  }
  // 多个 Product 节点时无法证明哪个是当前页面主体。
  if (products.length !== 1) return { page_type: "product" };

  const item = products[0];
  const relationDeclared = item.isAccessoryOrSparePartFor !== undefined && item.isAccessoryOrSparePartFor !== null;
  const rawRelated = item.isAccessoryOrSparePartFor;
  const related = relatedProducts(rawRelated);
  if ((Array.isArray(rawRelated) && rawRelated.length > 1) || (relationDeclared && related.length !== 1)) {
    return { page_type: "accessory" };
  }

  const target = related[0];
  const product = typeof target?.name === "string" ? target.name.trim()
    : typeof item.name === "string" ? item.name.trim() : "";
  if (!product) return { page_type: relationDeclared ? "accessory" : "product" };
  return {
    page_type: relationDeclared ? "accessory" : "product",
    product,
    // 商品 SKU 是身份辅助字段；兼容配件时不传配件自身 SKU 作为目标产品线索。
    ...(!relationDeclared && typeof item.sku === "string" && item.sku.trim() ? { sku: item.sku.trim() } : {}),
  };
}

function deriveOfficialContext(url: string, doc: Document): PageContextPayload {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return {};
  }
  const path = parsed.pathname.toLowerCase();
  if (parsed.protocol !== "https:") return {};

  if (parsed.hostname === "www.camthink.ai" && /^\/store(?:\/|$)/.test(path)) {
    if (/^\/store\/product\//.test(path)) return storeProductContext(doc);
    return { page_type: "store" };
  }
  if (parsed.hostname === "wiki.camthink.ai" && /^\/(?:[a-z-]+\/)?docs(?:\/|$)/.test(path)) {
    const segments = path.split("/").filter(Boolean);
    const product = segments.map((segment) => WIKI_SERIES[segment]).find(Boolean);
    return product ? { page_type: "product", product } : { page_type: "documentation" };
  }
  return {};
}

export function collectPageContext(win: Window = window): PageContextPayload {
  const auto: PageContextPayload = {
    url: win.location?.href || undefined,
    title: win.document?.title || undefined,
    language: win.navigator?.language || undefined,
    ...deriveOfficialContext(win.location?.href || "", win.document),
  };
  const hostExtra = (
    win as Window & { AskAIConfig?: { pageContext?: PageContextPayload } }
  ).AskAIConfig?.pageContext;
  if (!hostExtra) return auto;
  // 宿主显式结构化字段优先；url/title/language 始终从浏览器自动收集。
  return { ...auto, ...hostExtra, url: auto.url, title: auto.title, language: auto.language };
}
