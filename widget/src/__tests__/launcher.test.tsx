// Issue #24 REV1:launcher 统一外观验收(icon I1-I8 / shape S1-S10 / theme T1-T7)。
//
// 渲染断言用 renderToString;主题解析为纯函数(resolveEffectiveTheme /
// subscribeSystemTheme),T6 用假 MediaQueryList 验证运行时跟随,T5 用无
// matchMedia 的窗口验证回退;SVG 几何断言取权威设计参考的路径签名(I6)。

import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { Launcher } from "../launcher/Launcher";
import {
  LAUNCHER_ICONS,
  LAUNCHER_SHAPES,
  resolveLauncherIcon,
  resolveLauncherShape,
  legacyStyleToIcon,
  resolveEffectiveTheme,
  subscribeSystemTheme,
} from "../launcher/registry";
import { resolveConfig } from "../bootstrap";
import type { LauncherIcon, LauncherShape } from "../types";

const NEW_ICONS: LauncherIcon[] = [
  "bot-sparkle",
  "bubble-sparkle-fill",
  "robot-smile",
  "bubble-sparkle-outline",
];

function renderLauncher(icon: LauncherIcon, shape: LauncherShape, theme: "light" | "dark"): string {
  return renderToString(
    <Launcher icon={icon} shape={shape} theme={theme} label="打开 Ask AI 助手" onOpen={() => {}} />,
  );
}

// ------------------------------------------------------- ICON(I1-I8)

describe("I1-I5:内置图标渲染(icon × shape 独立)", () => {
  const glyphs: Array<[LauncherIcon, RegExp]> = [
    ["current", /<img /],
    ["bot-sparkle", /<svg/],
    ["bubble-sparkle-fill", /<svg/],
    ["robot-smile", /<svg/],
    ["bubble-sparkle-outline", /<svg/],
  ];
  for (const [icon, pattern] of glyphs) {
    it(`I: ${icon} 渲染(data-launcher-icon + 图标)`, () => {
      const html = renderLauncher(icon, "rounded-square", "light");
      expect(html).toContain(`data-launcher-icon="${icon}"`);
      expect(html).toMatch(pattern);
    });
  }
});

describe("I6:权威 SVG 几何逐路径保真(设计参考路径签名)", () => {
  const signatures: Array<[LauncherIcon, string]> = [
    ["bot-sparkle", "M9 11v2m6-2v2m-2-9H7a4 4 0 0 0-4 4v12h14"],
    ["bubble-sparkle-fill", "M12 2c.863 0 1.701.11 2.5.315"],
    ["robot-smile", "M9.238 9.451"],
    ["bubble-sparkle-outline", "M15.8 40A18 18 0 1 0 8 32.2L4 44Z"],
  ];
  for (const [icon, signature] of signatures) {
    it(`${icon} 含权威设计路径签名`, () => {
      expect(renderLauncher(icon, "round", "light")).toContain(signature);
    });
  }
});

describe("I7:零外链请求(内联矢量/打包资产)", () => {
  it("新图标为内联 svg,不产生 <img> 外链", () => {
    for (const icon of NEW_ICONS) {
      const html = renderLauncher(icon, "round", "light");
      expect(html).toContain("<svg");
      expect(html).not.toContain("<img");
    }
  });

  it("current 为打包资产(无 http 外链)", () => {
    const html = renderLauncher("current", "rounded-square", "light");
    expect(html).toContain("<img");
    expect(html).not.toMatch(/src="http/);
  });
});

describe("I8 + 遗留桥:图标解析(fail-safe)", () => {
  it("I8:缺失/undefined/null → current", () => {
    expect(resolveLauncherIcon(undefined)).toBe("current");
    expect(resolveLauncherIcon(null)).toBe("current");
  });

  it("I8:非法值(任意串/非字符串)→ current", () => {
    expect(resolveLauncherIcon("logo1.svg")).toBe("current");
    expect(resolveLauncherIcon("spark")).toBe("current");
    expect(resolveLauncherIcon(42)).toBe("current");
  });

  it("语义 id 封闭集合(冻结公开身份;current 恒在)", () => {
    expect([...LAUNCHER_ICONS]).toEqual([
      "current",
      "bot-sparkle",
      "bubble-sparkle-fill",
      "robot-smile",
      "bubble-sparkle-outline",
    ]);
    for (const id of LAUNCHER_ICONS) {
      expect(id).not.toMatch(/\.(svg|png|jpg)$/);
      expect(id).not.toContain("/");
    }
  });

  it("遗留桥:REV0 风格 id 一律退役为 current(不静默迁移新图稿);空值=未设置", () => {
    expect(legacyStyleToIcon("assistant-spark")).toBe("current");
    expect(legacyStyleToIcon("chat-bubble")).toBe("current");
    expect(legacyStyleToIcon("orbit-neural")).toBe("current");
    expect(legacyStyleToIcon("current")).toBe("current");
    expect(legacyStyleToIcon("garbage")).toBe("current");
    expect(legacyStyleToIcon(undefined)).toBeUndefined();
    expect(legacyStyleToIcon("")).toBeUndefined();
  });
});

// ------------------------------------------------------- SHAPE(S1-S10)

describe("S1-S8:4 图标 × 2 形状 全组合(shape 独立生效)", () => {
  for (const icon of NEW_ICONS) {
    for (const shape of LAUNCHER_SHAPES) {
      it(`S: ${icon} + ${shape}`, () => {
        const html = renderLauncher(icon, shape, "light");
        expect(html).toContain(`data-launcher-icon="${icon}"`);
        expect(html).toContain(`data-launcher-shape="${shape}"`);
      });
    }
  }
});

describe("S9-S10:形状解析与独立性", () => {
  it("S9:非法/缺失 shape → rounded-square(fail-safe)", () => {
    expect(resolveLauncherShape(undefined)).toBe("rounded-square");
    expect(resolveLauncherShape(null)).toBe("rounded-square");
    expect(resolveLauncherShape("circle")).toBe("rounded-square");
    expect(resolveLauncherShape(7)).toBe("rounded-square");
  });

  it("S10:shape 解析不依赖 icon(独立配置维度)", () => {
    expect(resolveLauncherShape("round")).toBe("round");
    expect([...LAUNCHER_SHAPES]).toEqual(["round", "rounded-square"]);
  });

  it("current 保持遗留几何(12px 圆角方由基线 CSS 拥有;data-launcher-shape 不改变兼容契约)", () => {
    // current 渲染路径与 shape 值无关(基线 CSS 仅对非 current 应用形状规则)
    const html = renderLauncher("current", "round", "light");
    expect(html).toContain('data-launcher-icon="current"');
    expect(html).toContain("<img");
  });
});

// ------------------------------------------------------- THEME(T1-T7)

describe("T1-T7:主题解析(语义不变)", () => {
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

  it("渲染层:主题落地值写入 data-ask-ai-theme(新图标 dark 组合)", () => {
    const html = renderLauncher("robot-smile", "round", "dark");
    expect(html).toContain('data-ask-ai-theme="dark"');
  });
});

// ------------------------------------------------------- 可访问名 + 覆盖链

describe("launcher 可访问名(按钮级;装饰图标不命名)", () => {
  it("aria-label/haspopup 承担可访问名;新图标 svg aria-hidden", () => {
    const html = renderLauncher("bot-sparkle", "round", "light");
    expect(html).toContain('aria-label="打开 Ask AI 助手"');
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).toContain("aria-hidden=\"true\"");
  });

  it("current 的 img alt 为空(可访问名由按钮承担)", () => {
    const html = renderLauncher("current", "rounded-square", "light");
    expect(html).toContain('alt=""');
  });
});

describe("嵌入覆盖链(Amendment #2 §3:explicit > legacy > site > default)", () => {
  function el(attrs: Record<string, string>): HTMLScriptElement {
    const node = { dataset: {} } as unknown as HTMLScriptElement;
    for (const [k, v] of Object.entries(attrs)) {
      const camel = k
        .replace(/^data-/, "")
        .replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
      (node.dataset as Record<string, string>)[camel] = v;
    }
    return node;
  }

  it("data-launcher-icon 规范属性生效", () => {
    const cfg = resolveConfig(el({ "data-launcher-icon": "robot-smile", "data-launcher-shape": "round" }), null, null);
    expect(cfg.launcherIcon).toBe("robot-smile");
    expect(cfg.launcherShape).toBe("round");
  });

  it("同源内规范属性压过遗留 data-launcher-style", () => {
    const cfg = resolveConfig(
      el({ "data-launcher-icon": "bot-sparkle", "data-launcher-style": "chat-bubble" }),
      null,
      null,
    );
    expect(cfg.launcherIcon).toBe("bot-sparkle");
    expect(cfg.launcherStyle).toBe("chat-bubble"); // App 层经遗留桥退役为 current
  });

  it("script 属性 > 预置元素属性;缺省 undefined", () => {
    const script = el({ "data-launcher-theme": "dark" });
    const preset = el({ "data-launcher-theme": "light", "data-launcher-icon": "robot-smile" });
    const cfg = resolveConfig(script, preset, null);
    expect(cfg.launcherTheme).toBe("dark");
    expect(cfg.launcherIcon).toBe("robot-smile");
    const none = resolveConfig(null, null, null);
    expect(none.launcherIcon).toBeUndefined();
    expect(none.launcherShape).toBeUndefined();
    expect(none.launcherTheme).toBeUndefined();
  });
});
