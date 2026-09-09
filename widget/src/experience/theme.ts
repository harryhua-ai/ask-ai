// I-UX-001:聊天窗主题系统(冻结 §2.17-§2.19)。
//
// - Match Website(默认):只从宿主读取**可信信号**(theme-color meta、
//   公认品牌 CSS 变量、页面明暗特征),推导 ASK-AI 自有 token;
//   绝不继承宿主任意 CSS,绝不向宿主泄漏样式;
// - Light/Dark:固定 ASK-AI 调色板;Custom:站点强调色派生;
// - 对比度守卫:accent 上前景色按 WCAG 相对亮度选黑/白;token 只落
//   #ask-ai-widget-root 作用域 CSS 变量,不影响宿主。

import type { SiteExperienceConfig, WidgetConfig } from "../types";

export type ChatThemeMode = "match" | "light" | "dark" | "custom";

export const CHAT_THEMES: readonly ChatThemeMode[] = ["match", "light", "dark", "custom"] as const;

/** ASK-AI 自有主题 token(全部落根容器作用域)。 */
export type ThemeTokens = Record<string, string>;

function pickEnum<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

export function resolveChatThemeMode(
  config: Pick<WidgetConfig, "chatTheme">,
  site: Pick<SiteExperienceConfig, "chat_theme"> | null,
): ChatThemeMode {
  return (
    pickEnum(config.chatTheme, CHAT_THEMES) ??
    pickEnum(site?.chat_theme, CHAT_THEMES) ??
    "match"
  );
}

/** 聊天窗尺寸预设(default|large;未知/非法值回落 default)。 */
export function resolveChatSize(
  config: Pick<WidgetConfig, "chatSize">,
  site: Pick<SiteExperienceConfig, "chat_size"> | null,
): "default" | "large" {
  const value = config.chatSize ?? site?.chat_size;
  return value === "large" ? "large" : "default";
}

// ---------------------------------------------------------------------------
// 色彩工具(确定性;相对亮度 = WCAG)
// ---------------------------------------------------------------------------

export function parseHexColor(value: string | null | undefined): [number, number, number] | null {
  if (!value) return null;
  let text = value.trim();
  if (text.startsWith("#")) text = text.slice(1);
  if (text.length === 3) {
    text = text
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(text)) return null;
  return [
    parseInt(text.slice(0, 2), 16),
    parseInt(text.slice(2, 4), 16),
    parseInt(text.slice(4, 6), 16),
  ];
}

function toHex([r, g, b]: [number, number, number]): string {
  const h = (n: number) => n.toString(16).padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}

/** WCAG 相对亮度(0 深 — 1 亮)。 */
export function relativeLuminance(rgb: [number, number, number]): number {
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

/** 对比度守卫:按 accent 亮度选黑/白前景(WCAG ≥4.5 目标)。 */
export function readableForeground(rgb: [number, number, number]): string {
  return relativeLuminance(rgb) > 0.35 ? "#1a1a1a" : "#ffffff";
}

/** accent 派生浅表面(与 accent 同族、保证浅色文本可读)。 */
function tintedSurface(rgb: [number, number, number], dark: boolean): string {
  const mix = (v: number) => Math.round(dark ? v * 0.25 + 26 : v * 0.12 + 242);
  return toHex([mix(rgb[0]), mix(rgb[1]), mix(rgb[2])]);
}

// ---------------------------------------------------------------------------
// Match Website 信号读取(只读公认信号;try/catch 全程 fail-safe)
// ---------------------------------------------------------------------------

const RECOGNIZED_BRAND_VARS = [
  "--ask-ai-primary",
  "--primary",
  "--brand-color",
  "--brand",
  "--accent-color",
  "--accent",
];

/** 宿主 brand accent 信号:theme-color meta → 公认品牌 CSS 变量 → null。 */
export function readHostAccentSignal(doc: Document | null): string | null {
  if (!doc) return null;
  try {
    const meta = doc.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (meta?.content && parseHexColor(meta.content)) return meta.content.trim();
  } catch {
    /* ignore */
  }
  try {
    const rootStyle = doc.defaultView?.getComputedStyle(doc.documentElement);
    if (rootStyle) {
      for (const name of RECOGNIZED_BRAND_VARS) {
        const raw = rootStyle.getPropertyValue(name)?.trim();
        if (raw && parseHexColor(raw)) return raw;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

/** 页面明暗特征:body/html 背景亮度 → true=dark;信号缺失 → null(→ light)。 */
export function readHostDarkSignal(doc: Document | null): boolean | null {
  if (!doc) return null;
  try {
    for (const el of [doc.body, doc.documentElement]) {
      const bg = el && doc.defaultView ? doc.defaultView.getComputedStyle(el).backgroundColor : "";
      const m = bg.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
      if (m) {
        const alpha = bg.includes("rgba") && /,\s*0\s*\)$/.test(bg);
        if (alpha) continue; // 完全透明 → 看下一层
        return relativeLuminance([
          Number(m[1]),
          Number(m[2]),
          Number(m[3]),
        ]) < 0.2;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

const FALLBACK_ACCENT_RGB: [number, number, number] = [242, 74, 0]; // ASK-AI 品牌橙

// ASK-AI 自有明暗调色板(Match/Light/Dark 的确定性基座;accent 派生只覆盖
// 品牌面 token,文本/边框/输入等结构 token 恒为 ASK-AI 所有,不受宿主污染)
const LIGHT_TOKENS: ThemeTokens = {
  "--ask-ai-bg": "#ffffff",
  "--ask-ai-surface": "#f7f7f8",
  "--ask-ai-text": "#1f2328",
  "--ask-ai-text-secondary": "#6b7280",
  "--ask-ai-border": "#e5e7eb",
  "--ask-ai-input-bg": "#ffffff",
  "--ask-ai-link": "#1f2328",
  "--ask-ai-focus": "rgba(242, 74, 0, 0.4)",
};

const DARK_TOKENS: ThemeTokens = {
  "--ask-ai-bg": "#16181d",
  "--ask-ai-surface": "#1f232b",
  "--ask-ai-text": "#e6e8eb",
  "--ask-ai-text-secondary": "#9aa1ab",
  "--ask-ai-border": "#2c313a",
  "--ask-ai-input-bg": "#16181d",
  "--ask-ai-link": "#e6e8eb",
  "--ask-ai-focus": "rgba(255, 255, 255, 0.4)",
};

function accentOrFallback(value: string | null | undefined): [number, number, number] {
  return parseHexColor(value) ?? FALLBACK_ACCENT_RGB;
}

function withAccent(base: ThemeTokens, character: "light" | "dark", accent: [number, number, number]): ThemeTokens {
  return {
    ...base,
    "--ask-ai-primary": toHex(accent),
    "--ask-ai-on-primary": readableForeground(accent),
    "--ask-ai-surface": tintedSurface(accent, character === "dark"),
  };
}

/**
 * 解析聊天窗主题 token(纯组装 + 宿主信号只读)。
 * 返回值作为根容器 style(CSS 变量)下发,作用域 = #ask-ai-widget-root,
 * 不触碰宿主样式;所有宿主信号读取失败都有确定性 ASK-AI 回落。
 */
export function resolveChatThemeTokens(
  mode: ChatThemeMode,
  config: Pick<WidgetConfig, "chatAccent">,
  site: Pick<SiteExperienceConfig, "chat_accent_color"> | null,
  hostDoc: Document | null,
): { tokens: ThemeTokens; character: "light" | "dark" } {
  const customAccent = config.chatAccent ?? site?.chat_accent_color ?? null;

  if (mode === "light") {
    return { tokens: withAccent(LIGHT_TOKENS, "light", accentOrFallback(customAccent)), character: "light" };
  }
  if (mode === "dark") {
    return { tokens: withAccent(DARK_TOKENS, "dark", accentOrFallback(customAccent)), character: "dark" };
  }
  if (mode === "custom") {
    const accent = accentOrFallback(customAccent);
    // Custom = 站点强调色身份 + 按亮度选明暗底(对比度守卫)
    const character: "light" | "dark" = relativeLuminance(accent) > 0.6 ? "light" : "dark";
    return {
      tokens: withAccent(character === "light" ? LIGHT_TOKENS : DARK_TOKENS, character, accent),
      character,
    };
  }

  // match(默认):宿主品牌 accent + 页面明暗特征 → ASK-AI 自有 token
  const hostAccent = parseHexColor(readHostAccentSignal(hostDoc));
  const darkSignal = readHostDarkSignal(hostDoc) ?? false;
  const character: "light" | "dark" = darkSignal ? "dark" : "light";
  const accent = hostAccent ?? FALLBACK_ACCENT_RGB;
  return {
    tokens: withAccent(character === "light" ? LIGHT_TOKENS : DARK_TOKENS, character, accent),
    character,
  };
}
