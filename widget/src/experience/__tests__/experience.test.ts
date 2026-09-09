// I-UX-001:experience 模块确定性单测(入口/时序/会话闸/问候/动作/主题)。

import { describe, it, expect } from "vitest";
import { resolveEntryMode, resolveProactiveTiming, proactiveCapable, proactiveDelayMs, isMobileViewport } from "../entry";
import { resolveEngagement } from "../greeting";
import { selectTrustedActions, buildActionQuery, actionIsBindable } from "../actions";
import {
  resolveChatThemeMode,
  resolveChatSize,
  resolveChatThemeTokens,
  parseHexColor,
  readableForeground,
  relativeLuminance,
  readHostAccentSignal,
  readHostDarkSignal,
} from "../theme";

// ---------------------------------------------------------------- entry ---

describe("entry mode resolution(迁移契约 §3/§5)", () => {
  it("未配置(embed+site 都无)→ legacy(既有站点保持既有行为)", () => {
    expect(resolveEntryMode({}, null)).toBe("legacy");
    expect(resolveEntryMode({}, { entry_mode: undefined })).toBe("legacy");
  });

  it("site-config 显式配置生效(新站点 seed mini_entry → C)", () => {
    expect(resolveEntryMode({}, { entry_mode: "mini_entry" })).toBe("mini_entry");
    expect(resolveEntryMode({}, { entry_mode: "pill" })).toBe("pill");
  });

  it("嵌入覆写 > site-config(显式配置永远权威)", () => {
    expect(resolveEntryMode({ entryMode: "pill" }, { entry_mode: "mini_entry" })).toBe("pill");
  });

  it("非法持久值 fail-safe 回落 legacy", () => {
    expect(resolveEntryMode({}, { entry_mode: "wizard" })).toBe("legacy");
  });

  it("主动展开时序:嵌入 > 站点 > balanced;off → null 延迟", () => {
    expect(resolveProactiveTiming({}, null)).toBe("balanced");
    expect(resolveProactiveTiming({ proactive: "fast" }, { proactive_timing: "gentle" })).toBe("fast");
    expect(proactiveDelayMs("fast")).toBe(3000);
    expect(proactiveDelayMs("balanced")).toBe(6000);
    expect(proactiveDelayMs("gentle")).toBe(10000);
    expect(proactiveDelayMs("off")).toBeNull();
  });

  it("主动展开仅 C 有意义;移动端判定", () => {
    expect(proactiveCapable("mini_entry")).toBe(true);
    expect(proactiveCapable("legacy")).toBe(false);
    expect(proactiveCapable("pill")).toBe(false);
    expect(proactiveCapable("nudge")).toBe(false);
    expect(isMobileViewport({ innerWidth: 390 } as Window)).toBe(true);
    expect(isMobileViewport({ innerWidth: 1280 } as Window)).toBe(false);
  });
});

// -------------------------------------------------------------- greeting ---

describe("contextual greeting(冻结 §2.10:权威序 + 置信衰减)", () => {
  it("1) Site/Admin 覆写最高(HIGH)", () => {
    const ctx = resolveEngagement({
      site: { greeting_override: "Ask me about NeoMind" },
      hostContext: { product: "NE503" },
      url: "https://x.test/",
      title: "X",
      lang: "en",
    });
    expect(ctx.greeting).toBe("Ask me about NeoMind");
    expect(ctx.confidence).toBe("high");
  });

  it("2a) 受信 Page Context 产品 → 产品专名问候(HIGH)", () => {
    const en = resolveEngagement({ site: null, hostContext: { product: "NE503" }, url: "", title: "", lang: "en" });
    expect(en.greeting).toBe("Questions about NE503?");
    expect(en.confidence).toBe("high");
    const zh = resolveEngagement({ site: null, hostContext: { product: "NE503" }, url: "", title: "", lang: "zh" });
    expect(zh.greeting).toBe("关于 NE503 的问题?");
  });

  it("2b) 受信 page_type → 类别模板(HIGH)", () => {
    const ctx = resolveEngagement({ site: null, hostContext: { page_type: "documentation" }, url: "", title: "", lang: "en" });
    expect(ctx.greeting).toBe("Questions about this guide?");
  });

  it("3) URL 启发式只到类别(MEDIUM;永不产生产品专名)", () => {
    const ctx = resolveEngagement({
      site: null,
      hostContext: null,
      url: "https://x.test/docs/ne503-guide/",
      title: "NE503 Guide",
      lang: "en",
    });
    expect(ctx.pageType).toBe("documentation");
    expect(ctx.greeting).toBe("Questions about this guide?");
    expect(ctx.confidence).toBe("medium");
  });

  it("4) 无信号 → 通用兜底(LOW;错误的具体不如正确的通用)", () => {
    const ctx = resolveEngagement({ site: null, hostContext: null, url: "https://x.test/aaa", title: "aaa", lang: "en" });
    expect(ctx.greeting).toBe("How can I help?");
    expect(ctx.confidence).toBe("low");
    const zh = resolveEngagement({ site: null, hostContext: null, url: "", title: "", lang: "zh" });
    expect(zh.greeting).toBe("有什么可以帮你?");
  });

  it("产品专名中出现于 URL/title 也不提升置信(启发式上限 = 类别)", () => {
    const ctx = resolveEngagement({
      site: null,
      hostContext: null,
      url: "https://x.test/blog/ne503-review",
      title: "NE503 review",
      lang: "en",
    });
    expect(ctx.product).toBeNull();
    expect(ctx.confidence).not.toBe("high");
  });
});

// --------------------------------------------------------------- actions ---

const ACTIONS = [
  { type: "PRODUCT_SPECIFICATIONS", label: "Specifications", query: "What are the specifications of {product}?" },
  { type: "SETUP_GUIDE", label: "Setup guide", query: "How do I set up {product}?" },
  { type: "EXPLAIN_PAGE", label: "Explain this page", query: "Explain this page: {page_title}" },
  { type: "TROUBLESHOOT", label: "Troubleshoot", query: "Help me troubleshoot: {page_title}" },
  { type: "PRICING", label: "Pricing", query: "What is the pricing of {product}?" },
];

describe("trusted actions(冻结 §2.13-§2.15)", () => {
  const productCtx = resolveEngagement({ site: null, hostContext: { product: "NE503" }, url: "", title: "", lang: "en" });

  it("按上下文资格选取并保序", () => {
    const picked = selectTrustedActions(ACTIONS, productCtx, 2);
    expect(picked.map((a) => a.label)).toEqual(["Specifications", "Setup guide"]);
  });

  it("C 最多 2、空聊天最多 3(截断由 max 驱动)", () => {
    expect(selectTrustedActions(ACTIONS, productCtx, 2)).toHaveLength(2);
    expect(selectTrustedActions(ACTIONS, productCtx, 3).length).toBeLessThanOrEqual(3);
  });

  it("查询绑定:{product} 按上下文确定性替换;无绑定 → 不发送", () => {
    expect(buildActionQuery(ACTIONS[0], productCtx)).toBe("What are the specifications of NE503?");
    const noProduct = resolveEngagement({ site: null, hostContext: null, url: "https://x.test/docs/a/", title: "A", lang: "en" });
    expect(buildActionQuery(ACTIONS[0], noProduct)).toBeNull();
    expect(buildActionQuery(ACTIONS[2], { ...noProduct, pageTitle: "NE503 Guide" })).toBe(
      "Explain this page: NE503 Guide",
    );
  });

  it("空/缺失动作列表 → 空(服务端未发布 = 主动面无动作)", () => {
    expect(selectTrustedActions(undefined, productCtx, 2)).toEqual([]);
    expect(selectTrustedActions([], productCtx, 2)).toEqual([]);
  });

  it("Role A 修正 A:渲染阶段绑定过滤 —— 谓词适用但不可绑定 → 不选", () => {
    // 产品页 URL(谓词适用)但无产品名:{product} 不可绑定 → 渲染层即排除
    const productPageNoName = resolveEngagement({
      site: null,
      hostContext: null,
      url: "https://x.test/products/mystery/",
      title: "",
      lang: "en",
    });
    expect(actionIsBindable(ACTIONS[0], productPageNoName)).toBe(false);
    expect(selectTrustedActions([ACTIONS[0]], productPageNoName, 2)).toEqual([]);
    // 同一动作,有产品名 → 可绑定、可渲染
    expect(actionIsBindable(ACTIONS[0], productCtx)).toBe(true);
    // {page_title} 缺可信标题 → 不可绑定(即使谓词经 documentation 适用)
    const docNoTitle = resolveEngagement({
      site: null,
      hostContext: null,
      url: "https://x.test/docs/a/",
      title: "",
      lang: "en",
    });
    expect(actionIsBindable(ACTIONS[2], docNoTitle)).toBe(false);
    expect(selectTrustedActions([ACTIONS[2]], docNoTitle, 2)).toEqual([]);
  });
});

// ---------------------------------------------------------------- theme ---

describe("chat theme(冻结 §2.17-§2.19)", () => {
  it("模式解析:嵌入 > 站点 > match;非法值回落", () => {
    expect(resolveChatThemeMode({}, null)).toBe("match");
    expect(resolveChatThemeMode({ chatTheme: "dark" }, { chat_theme: "light" })).toBe("dark");
    expect(resolveChatThemeMode({}, { chat_theme: "sepia" })).toBe("match");
  });

  it("窗口尺寸解析", () => {
    expect(resolveChatSize({}, null)).toBe("default");
    expect(resolveChatSize({ chatSize: "large" }, null)).toBe("large");
    expect(resolveChatSize({}, { chat_size: "huge" })).toBe("default");
  });

  it("light/dark 模式 → 确定性 token;文本/边框 token 恒为 ASK-AI 所有", () => {
    const light = resolveChatThemeTokens("light", {}, null, null);
    expect(light.character).toBe("light");
    expect(light.tokens["--ask-ai-bg"]).toBe("#ffffff");
    const dark = resolveChatThemeTokens("dark", {}, null, null);
    expect(dark.character).toBe("dark");
    expect(dark.tokens["--ask-ai-bg"]).toBe("#16181d");
  });

  it("custom:accent 派生 + 对比度守卫(亮 accent → 深前景)", () => {
    const custom = resolveChatThemeTokens("custom", { chatAccent: "#ffcc00" }, null, null);
    expect(custom.tokens["--ask-ai-primary"]).toBe("#ffcc00");
    expect(custom.tokens["--ask-ai-on-primary"]).toBe("#1a1a1a");
  });

  it("match:读 theme-color meta + 页面明暗特征;无信号回落 ASK-AI 品牌", () => {
    document.head.innerHTML = '<meta name="theme-color" content="#0a7d32">';
    document.body.style.backgroundColor = "#111111";
    const ctx = resolveChatThemeTokens("match", {}, null, document);
    expect(ctx.tokens["--ask-ai-primary"]).toBe("#0a7d32");
    expect(ctx.character).toBe("dark");
    document.head.innerHTML = "";
    document.body.style.backgroundColor = "";
    const fallback = resolveChatThemeTokens("match", {}, null, document);
    expect(fallback.tokens["--ask-ai-primary"]).toBe("#f24a00");
  });

  it("对比度工具:白底低亮 / 深底高亮;非法色解析 null", () => {
    expect(readableForeground([255, 255, 255])).toBe("#1a1a1a");
    expect(readableForeground([10, 10, 10])).toBe("#ffffff");
    expect(parseHexColor("#abc")).toEqual([170, 187, 204]);
    expect(parseHexColor("red")).toBeNull();
    expect(relativeLuminance([0, 0, 0])).toBeLessThan(relativeLuminance([255, 255, 255]));
    expect(readHostAccentSignal(null)).toBeNull();
    expect(readHostDarkSignal(null)).toBeNull();
  });
});
