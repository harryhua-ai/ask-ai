// Issue #24:launcher 风格/主题验收(S1-S7 / T1-T7)。
//
// 渲染断言用 renderToString(与 multilingualGate.test.tsx 同纪律);
// 主题解析为纯函数(resolveEffectiveTheme / subscribeSystemTheme),T6 用
// 假 MediaQueryList 验证运行时跟随, T5 用无 matchMedia 的窗口验证回退。

import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { Launcher } from "../launcher/Launcher";
import {
  LAUNCHER_STYLES,
  resolveLauncherStyle,
  resolveEffectiveTheme,
  subscribeSystemTheme,
} from "../launcher/registry";
import type { LauncherStyle } from "../types";


function renderLauncher(style: LauncherStyle, theme: "light" | "dark"): string {
  return renderToString(
    <Launcher style={style} theme={theme} label="打开 Ask AI 助手" onOpen={() => {}} />,
  );
}

// ------------------------------------------------------- STYLE(S1-S7)

describe("S1-S4:内置风格渲染", () => {
  const cases: Array<[LauncherStyle, RegExp]> = [
    ["current", /<img /],
    ["assistant-spark", /<svg/],
    ["chat-bubble", /<svg/],
    ["orbit-neural", /<svg/],
  ];
  for (const [style, pattern] of cases) {
    it(`S: ${style} 渲染(data-launcher-style + 图标)`, () => {
      const html = renderLauncher(style, "light");
      expect(html).toContain(`data-launcher-style="${style}"`);
      expect(html).toMatch(pattern);
    });
  }
});

describe("S5-S7:风格解析(语义身份)", () => {
  it("S1 前置:current 在注册表且为语义 id(非资产路径)", () => {
    expect(LAUNCHER_STYLES).toContain("current");
  });

  it("S5:缺失/undefined → current", () => {
    expect(resolveLauncherStyle(undefined)).toBe("current");
    expect(resolveLauncherStyle(null)).toBe("current");
  });

  it("S6:非法值(旧资产名/任意串/非字符串)→ current", () => {
    expect(resolveLauncherStyle("logo1.svg")).toBe("current");
    expect(resolveLauncherStyle("style3.svg")).toBe("current");
    expect(resolveLauncherStyle("spark")).toBe("current");
    expect(resolveLauncherStyle(42)).toBe("current");
  });

  it("S7:语义 id 稳定且不含实现资产后缀(冻结公开身份)", () => {
    expect([...LAUNCHER_STYLES]).toEqual([
      "current",
      "assistant-spark",
      "chat-bubble",
      "orbit-neural",
    ]);
    for (const id of LAUNCHER_STYLES) {
      expect(id).not.toMatch(/\.(svg|png|jpg)$/);
      expect(id).not.toContain("/");
    }
  });
});

// ------------------------------------------------------- THEME(T1-T7)

describe("T1-T7:主题解析", () => {
  it("T1:显式 light → light(无视系统信号)", () => {
    expect(resolveEffectiveTheme("light", true)).toBe("light");
    expect(resolveEffectiveTheme("light", false)).toBe("light");
    expect(resolveEffectiveTheme("light", null)).toBe("light");
  });

  it("T2:显式 dark → dark(无视系统信号)", () => {
    expect(resolveEffectiveTheme("dark", false)).toBe("dark");
    expect(resolveEffectiveTheme("dark", true)).toBe("dark");
    expect(resolveEffectiveTheme("dark", null)).toBe("dark");
  });

  it("T3:auto + prefers dark → dark", () => {
    expect(resolveEffectiveTheme("auto", true)).toBe("dark");
  });

  it("T4:auto + prefers light → light", () => {
    expect(resolveEffectiveTheme("auto", false)).toBe("light");
  });

  it("T5:auto + matchMedia 不可用(null)→ light(确定性回退)", () => {
    expect(resolveEffectiveTheme("auto", null)).toBe("light");
  });

  it("T6:subscribeSystemTheme 随系统变化回调;显式主题不订阅(T7)", () => {
    let matches = false;
    const listeners = new Set<(e: { matches: boolean }) => void>();
    const fakeWin = {
      matchMedia: (query: string) => ({
        matches,
        addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
          if (query === "(prefers-color-scheme: dark)") listeners.add(cb);
        },
        removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
          listeners.delete(cb);
        },
      }),
    } as unknown as Window;

    // T6:订阅后系统翻转到 dark → 回调 true
    const seen: boolean[] = [];
    const unsub = subscribeSystemTheme((dark) => seen.push(dark), fakeWin);
    expect(unsub).toBeTypeOf("function");
    matches = true;
    for (const cb of listeners) cb({ matches });
    expect(seen).toEqual([true]);
    unsub?.();
    // 取消订阅后不再收到
    matches = false;
    for (const cb of listeners) cb({ matches });
    expect(seen).toEqual([true]);

    // T7:显式主题不需要订阅(由 useResolvedTheme 分支保证;此处验证订阅器可整体不可用)
    const nullWin = {} as Window;
    expect(subscribeSystemTheme(() => {}, nullWin)).toBeNull();
  });

  it("渲染层:主题落地值写入 data-ask-ai-theme", () => {
    const html = renderLauncher("assistant-spark", "dark");
    expect(html).toContain('data-ask-ai-theme="dark"');
  });
});

// ------------------------------------------------------- 可访问名(§11)

describe("launcher 可访问名", () => {
  it("按钮级 aria-label 承担可访问名;图标不重复命名", () => {
    const html = renderLauncher("current", "light");
    expect(html).toContain('aria-label="打开 Ask AI 助手"');
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).toContain('alt=""');
  });
});
