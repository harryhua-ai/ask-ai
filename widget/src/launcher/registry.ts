// Issue #24 REV1:launcher 统一外观解析(icon × shape × theme 语义注册表 +
// 确定性主题消解 + REV0 遗留桥)。
//
// 冻结契约(REV1 Execution Contract §4-§7 + Amendment #2 §1/§3):
// - icon/shape = 封闭语义枚举,两个独立配置维度(不做 8 个组合硬编码 id);
//   未知/非法持久值一律回落 current | rounded-square(fail-safe,不破坏 bootstrap);
// - REV0 遗留风格 id(assistant-spark 等)已被权威视觉设计取代 → 遗留值
//   一律退役为 current(不静默映射到新图稿);
// - 主题偏好 = auto|light|dark;auto 仅用 matchMedia('(prefers-color-scheme: dark)')
//   消解,不可用/无匹配 → light(确定性回退;禁止宿主背景采样/类名启发);
// - auto 在 Widget 存活期间跟随系统主题变化(change 事件)。

import { useEffect, useState } from "react";
import type {
  LauncherIcon,
  LauncherShape,
  LauncherTheme,
  LauncherThemePref,
} from "../types";

/** 内置图标语义身份(顺序 = Admin 卡片展示顺序;current 恒为兼容默认)。 */
export const LAUNCHER_ICONS: readonly LauncherIcon[] = [
  "current",
  "bot-sparkle",
  "bubble-sparkle-fill",
  "robot-smile",
  "bubble-sparkle-outline",
] as const;

export const DEFAULT_LAUNCHER_ICON: LauncherIcon = "current";

/** 按钮形状语义身份(独立于 icon 的配置维度;仅对 REV1 矢量图标生效)。 */
export const LAUNCHER_SHAPES: readonly LauncherShape[] = ["round", "rounded-square"] as const;

export const DEFAULT_LAUNCHER_SHAPE: LauncherShape = "rounded-square";

/** REV0 遗留风格 id(已被权威视觉设计取代;识别用,不再可写)。 */
export const LEGACY_LAUNCHER_STYLES: readonly string[] = [
  "current",
  "assistant-spark",
  "chat-bubble",
  "orbit-neural",
] as const;

/** 主题偏好封闭枚举。 */
export const LAUNCHER_THEME_PREFS: readonly LauncherThemePref[] = ["auto", "light", "dark"] as const;

export const DEFAULT_LAUNCHER_THEME_PREF: LauncherThemePref = "auto";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** 持久/配置值 → 有效 icon;未知/非法回落 current(I8;不抛错)。 */
export function resolveLauncherIcon(value: unknown): LauncherIcon {
  return typeof value === "string" && (LAUNCHER_ICONS as readonly string[]).includes(value)
    ? (value as LauncherIcon)
    : DEFAULT_LAUNCHER_ICON;
}

/**
 * REV0 遗留桥:launcher_style / data-launcher-style 值 → 有效 icon。
 * 任何非空遗留值(含退役风格)→ current(§6E:不静默迁移到新图稿);
 * 空/未设置 → undefined(表示「未设置」,交给后续优先级链)。
 */
export function legacyStyleToIcon(value: unknown): LauncherIcon | undefined {
  return typeof value === "string" && value !== "" ? DEFAULT_LAUNCHER_ICON : undefined;
}

/** 持久/配置值 → 有效 shape;未知/非法回落 rounded-square(S9)。 */
export function resolveLauncherShape(value: unknown): LauncherShape {
  return typeof value === "string" && (LAUNCHER_SHAPES as readonly string[]).includes(value)
    ? (value as LauncherShape)
    : DEFAULT_LAUNCHER_SHAPE;
}

/** 持久/配置值 → 有效主题偏好;未知/非法回落 auto。 */
export function resolveLauncherThemePref(value: unknown): LauncherThemePref {
  return typeof value === "string" && (LAUNCHER_THEME_PREFS as readonly string[]).includes(value)
    ? (value as LauncherThemePref)
    : DEFAULT_LAUNCHER_THEME_PREF;
}

/**
 * 纯函数:主题偏好 + 系统深色信号 → 落地主题。
 * `prefersDark === null` 表示 matchMedia 不可用 → light(T5 确定性回退)。
 * 显式 light/dark 忽略信号(T7)。
 */
export function resolveEffectiveTheme(
  pref: LauncherThemePref,
  prefersDark: boolean | null,
): LauncherTheme {
  if (pref === "light") return "light";
  if (pref === "dark") return "dark";
  return prefersDark === null ? "light" : prefersDark ? "dark" : "light";
}

/** 读取当前系统深色信号;不可用 → null。 */
export function prefersDarkSignal(win: Window | null): boolean | null {
  try {
    if (typeof win?.matchMedia !== "function") return null;
    return win.matchMedia(DARK_QUERY).matches;
  } catch {
    return null;
  }
}

/**
 * 订阅系统主题变化(T6;仅 auto 使用)。返回取消订阅函数;
 * matchMedia 不可用 → 返回 null(不订阅)。
 */
export function subscribeSystemTheme(
  onChange: (prefersDark: boolean) => void,
  win: Window | null,
): (() => void) | null {
  try {
    if (typeof win?.matchMedia !== "function") return null;
    const mql = win.matchMedia(DARK_QUERY);
    const listener = (event: MediaQueryListEvent) => onChange(event.matches);
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", listener);
      return () => mql.removeEventListener("change", listener);
    }
    const legacy = mql as MediaQueryList & {
      addListener?: (cb: (event: MediaQueryListEvent) => void) => void;
      removeListener?: (cb: (event: MediaQueryListEvent) => void) => void;
    };
    if (typeof legacy.addListener === "function" && typeof legacy.removeListener === "function") {
      legacy.addListener(listener);
      return () => legacy.removeListener(listener);
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 主题偏好 → 落地主题(auto 消解 + T6 运行时跟随;T5 不可用回退 light;
 * T7 显式 light/dark 忽略系统变化 —— 不订阅 matchMedia)。
 */
export function useResolvedTheme(
  pref: LauncherThemePref,
  win: Window | null = typeof window === "undefined" ? null : window,
): LauncherTheme {
  const signal = prefersDarkSignal(win);
  const [theme, setTheme] = useState<LauncherTheme>(() => resolveEffectiveTheme(pref, signal));

  useEffect(() => {
    if (pref !== "auto") {
      setTheme(pref);
      return;
    }
    const apply = () => setTheme(resolveEffectiveTheme("auto", prefersDarkSignal(win)));
    apply();
    const unsubscribe = subscribeSystemTheme(
      (prefersDark) => setTheme(prefersDark ? "dark" : "light"),
      win,
    );
    return () => {
      unsubscribe?.();
    };
  }, [pref, win]);

  return theme;
}
