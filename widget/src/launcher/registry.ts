// Issue #24:launcher 风格/主题解析(语义身份注册表 + 确定性主题消解)。
//
// 冻结契约(Execution Contract §5/§7):
// - 风格 = 封闭语义枚举;未知/非法持久值一律回落 `current`(兼容默认);
// - 主题偏好 = auto|light|dark;auto 仅用 matchMedia('(prefers-color-scheme: dark)')
//   消解,不可用/无匹配 → light(确定性回退;禁止宿主背景采样/类名启发);
// - auto 在 Widget 存活期间跟随系统主题变化(change 事件)。

import { useEffect, useState } from "react";
import type { LauncherStyle, LauncherTheme, LauncherThemePref } from "../types";

/** 内置风格语义身份(顺序 = Admin 卡片展示顺序;current 恒为兼容默认)。 */
export const LAUNCHER_STYLES: readonly LauncherStyle[] = [
  "current",
  "assistant-spark",
  "chat-bubble",
  "orbit-neural",
] as const;

export const DEFAULT_LAUNCHER_STYLE: LauncherStyle = "current";

/** 主题偏好封闭枚举。 */
export const LAUNCHER_THEME_PREFS: readonly LauncherThemePref[] = ["auto", "light", "dark"] as const;

export const DEFAULT_LAUNCHER_THEME_PREF: LauncherThemePref = "auto";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** 持久/配置值 → 有效风格;未知/非法回落 current(S5/S6;不抛错、不破坏 bootstrap)。 */
export function resolveLauncherStyle(value: unknown): LauncherStyle {
  return typeof value === "string" && (LAUNCHER_STYLES as readonly string[]).includes(value)
    ? (value as LauncherStyle)
    : DEFAULT_LAUNCHER_STYLE;
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
