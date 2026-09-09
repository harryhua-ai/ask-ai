// I-UX-001:入口呈现模式 + 主动展开时序解析(确定性;语义集合与后端
// backend/services/widget_experience.py 同一冻结契约)。
//
// 迁移契约(冻结 §3/§5):
// - 既有站点 experience 列未配置(undefined)→ legacy = 既有入口行为
//   (launcher-only,无主动展开);
// - 新站点 → 服务端 seed 已置 mini_entry;此处只做归一化,不做推断;
// - 显式嵌入覆写(data-entry-mode / data-proactive)> site-config > 默认。
// Mobile(冻结 §2.3):主动呈现一律为 nudge(B)表面 —— 不因站点配置 C 而
// 自动展开完整 C/聊天窗;完整聊天只在显式交互后打开。

import type { SiteExperienceConfig, WidgetConfig } from "../types";

export type EntryMode = "legacy" | "pill" | "nudge" | "mini_entry";
export type ProactiveTiming = "off" | "fast" | "balanced" | "gentle";

export const ENTRY_MODES: readonly EntryMode[] = ["legacy", "pill", "nudge", "mini_entry"] as const;
export const PROACTIVE_TIMINGS: readonly ProactiveTiming[] = [
  "off",
  "fast",
  "balanced",
  "gentle",
] as const;

/** 时序预设 → 延迟 ms(冻结近似值:Fast≈3s / Balanced≈6s / Gentle≈10s)。 */
export const PROACTIVE_DELAYS_MS: Record<Exclude<ProactiveTiming, "off">, number> = {
  fast: 3000,
  balanced: 6000,
  gentle: 10000,
};

const DEFAULT_PROACTIVE: ProactiveTiming = "balanced";

function pickEnum<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** 入口模式解析:嵌入覆写 > site-config > legacy(未配置 = 既有行为)。 */
export function resolveEntryMode(
  config: Pick<WidgetConfig, "entryMode">,
  site: Pick<SiteExperienceConfig, "entry_mode"> | null,
): EntryMode {
  return (
    pickEnum(config.entryMode, ENTRY_MODES) ??
    pickEnum(site?.entry_mode, ENTRY_MODES) ??
    "legacy"
  );
}

/** 主动展开时序解析:嵌入覆写 > site-config > balanced。 */
export function resolveProactiveTiming(
  config: Pick<WidgetConfig, "proactive">,
  site: Pick<SiteExperienceConfig, "proactive_timing"> | null,
): ProactiveTiming {
  return (
    pickEnum(config.proactive, PROACTIVE_TIMINGS) ??
    pickEnum(site?.proactive_timing, PROACTIVE_TIMINGS) ??
    DEFAULT_PROACTIVE
  );
}

/** 主动展开是否对该入口模式有意义(C 专属;A/B/legacy 无自动展开)。 */
export function proactiveCapable(mode: EntryMode): boolean {
  return mode === "mini_entry";
}

/** 时序 → 延迟 ms(off → null)。 */
export function proactiveDelayMs(timing: ProactiveTiming): number | null {
  return timing === "off" ? null : PROACTIVE_DELAYS_MS[timing];
}

/** 窄视口判定(移动端主动呈现 = B;SSR/无 win 时按桌面处理)。 */
export function isMobileViewport(win: Window | null, breakPoint = 640): boolean {
  try {
    return !!win && win.innerWidth <= breakPoint;
  } catch {
    return false;
  }
}
