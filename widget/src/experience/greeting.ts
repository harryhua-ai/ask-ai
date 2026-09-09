// I-UX-001:上下文问候 + 参与上下文解析(确定性,零 LLM;冻结 §2.10-§2.12)。
//
// 权威序(冻结):
//   1. Site/Admin 显式覆写(greeting_override)
//   2. 受信 Page Context(宿主经 AskAIConfig.pageContext 显式提供的结构化字段
//      / Admin 预览上下文)
//   3. 安全 page-type 模板(URL/title 启发式,只到「类别」粒度)
//   4. 通用兜底
// 置信语义(冻结):HIGH=产品专名;MEDIUM=类别措辞;LOW/未知=通用。
// 冻结原则:「错误的具体比正确的通用更糟」—— 启发式永不产生产品专名问候。
// 问候与 Trusted Action 资格必须出自同一份解析结果(resolveEngagement)。

import type { PageContextPayload, SiteExperienceConfig } from "../types";

export type GreetingConfidence = "high" | "medium" | "low";

/** 参与上下文(问候与动作资格的唯一真相;每次页面上下文变化重算)。 */
export interface EngagementContext {
  pageType: PageType;
  product: string | null;
  pageTitle: string | null;
  greeting: string;
  confidence: GreetingConfidence;
}

export type PageType =
  | "product"
  | "documentation"
  | "integration"
  | "support"
  | "pricing"
  | "comparison"
  | "unknown";

export interface EngagementInput {
  /** 站点配置(可能含 greeting_override) */
  site: Pick<SiteExperienceConfig, "greeting_override"> | null;
  /** 宿主显式提供的受信结构化上下文(可能为 null = 未提供) */
  hostContext: PageContextPayload | null;
  /** 当前 URL/title(SPA 下实时取) */
  url: string;
  title: string;
  /** UI 语言(zh/en;模板双语) */
  lang: "en" | "zh";
  /** Admin 预览覆写(仅 previewMode;作为受信上下文消费) */
  previewPageType?: string;
  previewProduct?: string;
  previewTitle?: string;
}

type Lang = "en" | "zh";

const TEMPLATES: Record<Exclude<PageType, "unknown">, Record<Lang, string>> = {
  product: { en: "Questions about this product?", zh: "关于这个产品的问题?" },
  documentation: { en: "Questions about this guide?", zh: "关于这篇文档的问题?" },
  integration: { en: "Need help with this integration?", zh: "需要集成方面的帮助?" },
  support: { en: "Need help troubleshooting?", zh: "需要排障帮助?" },
  pricing: { en: "Questions about pricing or plans?", zh: "关于价格或方案的问题?" },
  comparison: { en: "Need help comparing these options?", zh: "需要对比这些选项?" },
};

const PRODUCT_TEMPLATE: Record<Lang, (product: string) => string> = {
  en: (p) => `Questions about ${p}?`,
  zh: (p) => `关于 ${p} 的问题?`,
};

const GENERIC: Record<Lang, string> = { en: "How can I help?", zh: "有什么可以帮你?" };

const KNOWN_PAGE_TYPES: readonly string[] = [
  "product",
  "documentation",
  "docs",
  "integration",
  "support",
  "pricing",
  "comparison",
  "shopping",
  "store",
];

/** 宿主/预览提供的 page_type → 规范 PageType(未知值不猜测 → null)。 */
function normalizePageType(raw: string | undefined | null): Exclude<PageType, "unknown"> | null {
  if (!raw) return null;
  const v = raw.trim().toLowerCase();
  switch (v) {
    case "product":
      return "product";
    case "documentation":
    case "docs":
      return "documentation";
    case "integration":
      return "integration";
    case "support":
      return "support";
    case "pricing":
    case "shopping":
    case "store":
      return "pricing";
    case "comparison":
      return "comparison";
    default:
      return null;
  }
}

/** URL/title 启发式 → page-type(只识别类别,永不识别产品专名;MEDIUM 上限)。 */
function heuristicPageType(url: string, title: string): PageType {
  let path = "";
  try {
    path = new URL(url, "https://example.invalid").pathname.toLowerCase();
  } catch {
    path = url.toLowerCase();
  }
  const hay = `${path} ${title.toLowerCase()}`;
  if (/\/docs\//.test(hay) || /\/wiki\//.test(hay) || /\/guide/.test(hay) || /\/documentation/.test(hay)) {
    return "documentation";
  }
  if (/\/products?\//.test(hay)) return "product";
  if (/\/pricing/.test(hay) || /\/store/.test(hay) || /\/shop/.test(hay)) return "pricing";
  if (/\/support/.test(hay) || /\/troubleshoot/.test(hay) || /\/help/.test(hay)) return "support";
  if (/\/compare/.test(hay) || /-vs-/.test(hay)) return "comparison";
  if (/\/integration/.test(hay) || /\/api\//.test(hay)) return "integration";
  return "unknown";
}

/**
 * 解析参与上下文(纯函数;SPA 导航/上下文变化时重算)。
 * 同一份结果同时驱动问候文案与 Trusted Action 资格(冻结 §2.10)。
 */
export function resolveEngagement(input: EngagementInput): EngagementContext {
  const { lang } = input;

  // 上下文事实(与问候权威解耦;动作资格依赖它,不依赖问候来源)
  const product = input.hostContext?.product?.trim() || input.previewProduct?.trim() || null;
  const pageTitle = input.hostContext?.title ?? input.previewTitle ?? null;
  const hostType =
    normalizePageType(input.hostContext?.page_type) ?? normalizePageType(input.previewPageType);

  // 1) Site/Admin 显式覆写(HIGH;显式配置即权威)
  const override = input.site?.greeting_override?.trim();
  if (override) {
    return finalize(hostType ?? heuristicPageType(input.url, input.title), product, pageTitle, override, "high");
  }

  // 2) 受信 Page Context(宿主显式提供;Admin 预览同级)
  if (product) {
    return finalize(hostType ?? "product", product, pageTitle, PRODUCT_TEMPLATE[lang](product), "high");
  }
  if (hostType) {
    return finalize(hostType, null, pageTitle, TEMPLATES[hostType][lang], "high");
  }

  // 3) 安全 page-type 启发式(只到类别;MEDIUM —— 启发式永不产生产品专名)
  const heuristics = heuristicPageType(input.url, input.title);
  if (heuristics !== "unknown") {
    return finalize(heuristics, null, pageTitle, TEMPLATES[heuristics][lang], "medium");
  }

  // 4) 通用兜底(LOW;错误的具体不如正确的通用)
  return finalize("unknown", null, pageTitle, GENERIC[lang], "low");
}

function finalize(
  pageType: PageType,
  product: string | null,
  pageTitle: string | null,
  greeting: string,
  confidence: GreetingConfidence,
): EngagementContext {
  return { pageType, product, pageTitle, greeting, confidence };
}

export { KNOWN_PAGE_TYPES };
