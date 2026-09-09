// I-UX-001:启动器动效/尺寸/品牌解析(独立配置维度;语义集合与后端
// backend/services/widget_experience.py 同一冻结契约)。
//
// - Motion = 注意力提示(Static / Subtle Glow 默认 / Soft Pulse / Sparkle),
//   不是常驻装饰动画;prefers-reduced-motion 下由 CSS 全部静止(状态语义不变);
// - Size = Small / Medium(默认,=既有 52px 逐像素兼容)/ Large;内部字形等比;
// - Brand = askai(默认,可发现性)/ match(站点品牌)/ custom(自定义色);
//   独立于聊天窗主题(冻结 §2.18)。

import type { SiteExperienceConfig, WidgetConfig } from "../types";

export type LauncherMotion = "static" | "subtle_glow" | "soft_pulse" | "sparkle";
export type LauncherSize = "small" | "medium" | "large";
export type LauncherBrand = "askai" | "match" | "custom";

export const LAUNCHER_MOTIONS: readonly LauncherMotion[] = [
  "static",
  "subtle_glow",
  "soft_pulse",
  "sparkle",
] as const;
export const LAUNCHER_SIZES: readonly LauncherSize[] = ["small", "medium", "large"] as const;
export const LAUNCHER_BRANDS: readonly LauncherBrand[] = ["askai", "match", "custom"] as const;

const DEFAULT_MOTION: LauncherMotion = "subtle_glow";
const DEFAULT_SIZE: LauncherSize = "medium";
const DEFAULT_BRAND: LauncherBrand = "askai";

/** reduced-motion 信号;不可用 → false(动画默认开,CSS 侧同样有守卫)。 */
export function prefersReducedMotion(win: Window | null): boolean {
  try {
    return !!win?.matchMedia("(prefers-reduced-motion: reduce)")?.matches;
  } catch {
    return false;
  }
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

export function resolveLauncherMotion(
  config: Pick<WidgetConfig, "launcherMotion">,
  site: Pick<SiteExperienceConfig, "launcher_motion"> | null,
): LauncherMotion {
  return pick(config.launcherMotion ?? site?.launcher_motion, LAUNCHER_MOTIONS, DEFAULT_MOTION);
}

export function resolveLauncherSize(
  config: Pick<WidgetConfig, "launcherSize">,
  site: Pick<SiteExperienceConfig, "launcher_size"> | null,
): LauncherSize {
  return pick(config.launcherSize ?? site?.launcher_size, LAUNCHER_SIZES, DEFAULT_SIZE);
}

export function resolveLauncherBrand(
  config: Pick<WidgetConfig, "launcherBrand">,
  site: Pick<SiteExperienceConfig, "launcher_brand"> | null,
): LauncherBrand {
  return pick(config.launcherBrand ?? site?.launcher_brand, LAUNCHER_BRANDS, DEFAULT_BRAND);
}

/** 自定义品牌色(仅 brand=custom 消费;非法值 → null → 回落 askai 品牌处理)。 */
export function resolveLauncherCustomColor(
  config: Pick<WidgetConfig, "launcherColor">,
  site: Pick<SiteExperienceConfig, "launcher_color"> | null,
): string | null {
  const raw = config.launcherColor ?? site?.launcher_color ?? null;
  return raw && /^#[0-9a-fA-F]{6}$/.test(raw.trim()) ? raw.trim() : null;
}
