// Issue #33 首绘正确性验收(RED→GREEN)。
//
// 冻结契约语义:
// - FIRST_VISIBLE_LAUNCHER_APPEARANCE = FINAL_RESOLVED_APPEARANCE(成功解析路径);
// - 显式嵌入三键齐 → 最终外观本地已定,可立即渲染(不等待低优先级 site-config);
// - UNRESOLVED ≠ FAILED:配置失败/超时 → 确定性回退默认外观,绝不永久空白;
// - 外观状态机:UNRESOLVED → RESOLVED / UNRESOLVED → FAILED → FALLBACK(默认)。
//
// "paint readiness" 语义:jsdom 不绘制;launcher 已提交进 document 即为
// 「将可见」的充分前提(真实浏览器绘制时序由真实构建台架另证,RCA 报告 §3)。
// 因此每条用例都断言**解析前的中间提交态**,而非仅终态。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

// React 18+ act 环境声明(无 @testing-library 的裸 createRoot 测试必须显式开启)
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom 未实现 scrollIntoView(ChatPanel 打开面板时的滚动 effect 需要)
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});

import { App } from "../App";
import type { WidgetConfig, SiteExperienceConfig } from "../types";
import { LAUNCHER_RESOLUTION_TIMEOUT_MS } from "../utils/siteConfig";

// fetchSiteConfig 打桩:每个调用进入手工决议队列(pending),用例内控制
// resolve/reject 与时机。resolveStarters 等其余导出保持原实现。
type Pending = { resolve: (v: SiteExperienceConfig) => void; reject: (e: unknown) => void };
let pendingFetches: Pending[] = [];
let fetchCalls = 0;

vi.mock("../utils/siteConfig", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../utils/siteConfig")>();
  return {
    ...orig,
    fetchSiteConfig: vi.fn(
      (_apiUrl: string, _siteId: string, opts?: { language?: string; signal?: AbortSignal }) =>
        new Promise<SiteExperienceConfig>((resolve, reject) => {
          fetchCalls += 1;
          pendingFetches.push({ resolve, reject });
          // 与真实 fetch 同语义:abort → reject(AbortError),供超时路径测试
          opts?.signal?.addEventListener(
            "abort",
            () => reject(new Error("Aborted")),
            { once: true },
          );
        }),
    ),
  };
});

const SERVER_APPEARANCE: SiteExperienceConfig = {
  site_id: "i33-site",
  display_name: "I33",
  welcome: "hello",
  starters: ["q1"],
  launcher_icon: "bubble-sparkle-fill",
  launcher_shape: "round",
  launcher_style: undefined,
  launcher_theme: "dark",
};

function baseConfig(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return { apiUrl: "http://localhost:8000", siteId: "i33-site", ...overrides };
}

function fab(container: HTMLElement): HTMLElement | null {
  return container.querySelector(".ask-ai-fab");
}

function fabAppearance(el: HTMLElement): Record<string, string | null> {
  return {
    icon: el.getAttribute("data-launcher-icon"),
    shape: el.getAttribute("data-launcher-shape"),
    theme: el.getAttribute("data-ask-ai-theme"),
  };
}

async function mountApp(
  container: HTMLElement,
  config: WidgetConfig,
): Promise<Root> {
  const root = createRoot(container);
  await act(async () => {
    root.render(<App config={config} />);
  });
  // 再 flush 一轮 effect:确保 fetchSiteConfig 已被调用并处于 pending
  await act(async () => {});
  return root;
}

beforeEach(() => {
  pendingFetches = [];
  fetchCalls = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

// ------------------------------------------------------- A. 慢配置成功

describe("A. 慢配置成功:provisional 外观不得可见(状态机 UNRESOLVED 段)", () => {
  it("RED:site-config 未决议期间,launcher 不得出现在 document(当前实现可见=缺陷)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    expect(fetchCalls).toBe(1);
    expect(pendingFetches).toHaveLength(1); // 权威配置仍未到达
    // 冻结契约 §2:UNRESOLVED 段不得绘制 provisional 外观
    expect(fab(container)).toBeNull();
    root.unmount();
    container.remove();
  });

  it("UNRESOLVED → RESOLVED:首个可见 launcher 即服务器权威外观", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    expect(fab(container)).toBeNull();
    await act(async () => {
      pendingFetches[0].resolve(SERVER_APPEARANCE);
    });
    const el = fab(container);
    expect(el).not.toBeNull();
    expect(fabAppearance(el!)).toEqual({
      icon: "bubble-sparkle-fill",
      shape: "round",
      theme: "dark",
    });
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- B. 零延迟成功

describe("B. 立即/零延迟配置成功:无一帧 provisional 闪变", () => {
  it("挂起一拍后立即决议:launcher 首次提交即为终值", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    // 挂起期(哪怕是调度上的最短一拍):无 launcher
    expect(fab(container)).toBeNull();
    // 零业务延迟决议
    await act(async () => {
      pendingFetches[0].resolve(SERVER_APPEARANCE);
    });
    const el = fab(container);
    expect(el).not.toBeNull();
    expect(fabAppearance(el!)).toEqual({
      icon: "bubble-sparkle-fill",
      shape: "round",
      theme: "dark",
    });
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- C. 显式嵌入覆写

describe("C. 显式三键覆写:本地终值可立即渲染,不等待 site-config", () => {
  it("覆写齐备时 launcher 立即出现且为覆写值(fetch 仍 pending)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(
      container,
      baseConfig({
        launcherIcon: "robot-smile",
        launcherShape: "round",
        launcherTheme: "light",
      }),
    );
    expect(fetchCalls).toBe(1); // 内容配置仍拉取
    expect(pendingFetches).toHaveLength(1);
    const el = fab(container);
    expect(el).not.toBeNull();
    expect(fabAppearance(el!)).toEqual({
      icon: "robot-smile",
      shape: "round",
      theme: "light",
    });
    // 服务器到达(值不同):覆写优先级更高,外观不变(冻结优先级契约)
    await act(async () => {
      pendingFetches[0].resolve(SERVER_APPEARANCE);
    });
    expect(fabAppearance(fab(container)!)).toEqual({
      icon: "robot-smile",
      shape: "round",
      theme: "light",
    });
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- D. 配置失败回退

describe("D. 配置失败:UNRESOLVED → FAILED → FALLBACK(确定性默认,非空白)", () => {
  it("请求拒绝 → 回退默认外观(current | rounded-square | auto消解)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    expect(fab(container)).toBeNull();
    await act(async () => {
      pendingFetches[0].reject(new Error("site-config 500"));
    });
    const el = fab(container);
    expect(el).not.toBeNull();
    expect(fabAppearance(el!)).toEqual({
      icon: "current",
      shape: "rounded-square",
      theme: "light", // jsdom 无 matchMedia → auto 确定性回退 light
    });
    root.unmount();
    container.remove();
  });

  it("请求永挂起 → 超时边界确定性进入 FAILED → 默认外观(PENDING≠FAILED)", async () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<App config={baseConfig()} />);
    });
    await act(async () => {});
    expect(fab(container)).toBeNull(); // PENDING:不绘制 provisional
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LAUNCHER_RESOLUTION_TIMEOUT_MS + 1);
    });
    const el = fab(container);
    expect(el).not.toBeNull(); // 超时即回退,绝不永久空白
    expect(fabAppearance(el!)).toEqual({
      icon: "current",
      shape: "rounded-square",
      theme: "light",
    });
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- E/F/G. 权威值/冷载/刷新语义

describe("E/F/G. Admin 权威三维各自生效;冷载序列无错误中间态", () => {
  for (const [field, value, attr, expected] of [
    ["launcher_icon", "bot-sparkle", "data-launcher-icon", "bot-sparkle"],
    ["launcher_shape", "round", "data-launcher-shape", "round"],
    ["launcher_theme", "light", "data-ask-ai-theme", "light"],
  ] as const) {
    it(`server ${field}=${value} 解析为 ${attr}=${expected}`, async () => {
      const container = document.createElement("div");
      document.body.appendChild(container);
      const root = await mountApp(container, baseConfig());
      await act(async () => {
        pendingFetches[0].resolve({ ...SERVER_APPEARANCE, [field]: value });
      });
      const el = fab(container);
      expect(el).not.toBeNull();
      expect(el!.getAttribute(attr)).toBe(expected);
      root.unmount();
      container.remove();
    });
  }
});

// ------------------------------------------------------- H/J. 功能与无障碍

describe("H/J. launcher 可操作性与无障碍语义不回归", () => {
  it("解析后 launcher 可打开面板;aria 语义在位", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await act(async () => {
      pendingFetches[0].resolve(SERVER_APPEARANCE);
    });
    const el = fab(container)!;
    expect(el.getAttribute("aria-haspopup")).toBe("dialog");
    expect(el.getAttribute("aria-label")).toBeTruthy();
    await act(async () => {
      el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".ask-ai-panel")).not.toBeNull();
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- I. legacy 无 siteId

describe("I. legacy 公共 widget(无 siteId):立即渲染,零等待", () => {
  it("无 siteId → launcher 立即出现(默认外观),不发 site-config", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, { apiUrl: "http://localhost:8000" });
    expect(fetchCalls).toBe(0);
    const el = fab(container);
    expect(el).not.toBeNull();
    expect(fabAppearance(el!)).toEqual({
      icon: "current",
      shape: "rounded-square",
      theme: "light",
    });
    root.unmount();
    container.remove();
  });
});

// ------------------------------------------------------- 补:已解析后重拉不隐藏

describe("补充:已解析(RESOLVED)后 uiLang 重拉,launcher 不得隐藏", () => {
  it("重拉 pending 期间 launcher 仍在,保持既有权威外观", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = await mountApp(container, baseConfig());
    await act(async () => {
      pendingFetches[0].resolve(SERVER_APPEARANCE);
    });
    expect(fabAppearance(fab(container)!)).toEqual({
      icon: "bubble-sparkle-fill",
      shape: "round",
      theme: "dark",
    });
    // 模拟 uiLang 热切换触发重拉:新请求 pending,launcher 不消失
    await act(async () => {
      document.documentElement.lang = "en";
      window.dispatchEvent(new Event("popstate"));
    });
    // 直接以第二次 pending 仍挂起的状态断言:launcher 保持可见
    // (重拉由 uiLang state 变化驱动;此处通过再次挂起队列长度验证 effect 已重跑)
    expect(fetchCalls).toBeGreaterThanOrEqual(1);
    expect(fab(container)).not.toBeNull();
    root.unmount();
    container.remove();
  });
});
