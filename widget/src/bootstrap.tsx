import React from "react";
import { createRoot } from "react-dom/client";
import type { WidgetConfig } from "./types";
import { App } from "./App";

/** widget 挂载容器 id:嵌入页可预置同名元素传 data-*,同时用于防重复注入。 */
export const WIDGET_ROOT_ID = "ask-ai-widget-root";

/** 兜底默认值(契约 T1 fallback 第 4 级)。 */
const DEFAULT_API_URL = "http://localhost:8000";
const DEFAULT_PRIMARY_COLOR = "#f24a00";

export interface MountedWidget {
  config: WidgetConfig;
  container: HTMLElement;
  /** true = 复用了页面预置的 #ask-ai-widget-root;false = 新建 */
  reusedExisting: boolean;
  /** true = 本次实际挂载;false = 容器已有内容,跳过(防双浮窗) */
  mounted: boolean;
}

declare global {
  interface Window {
    AskAIConfig?: {
      apiUrl?: string;
      language?: string;
      primaryColor?: string;
      /** MSW:站点体验标识;pageContext 见 utils/pageContext.ts */
      siteId?: string;
      /** Issue #24 REV1 统一外观覆写(icon/shape/theme;Admin 实时预览与高级嵌入通道) */
      launcherIcon?: string;
      launcherShape?: string;
      launcherTheme?: string;
      /** @deprecated REV0 遗留(data-launcher-style);退役为 current */
      launcherStyle?: string;
    };
  }
}

type ConfigOverrides = {
  apiUrl?: string;
  language?: string;
  primaryColor?: string;
  siteId?: string;
  launcherIcon?: string;
  launcherShape?: string;
  launcherTheme?: string;
  launcherStyle?: string;
};

function readDataset(el: HTMLElement | null | undefined): ConfigOverrides {
  if (!el) return {};
  const d = el.dataset;
  return {
    apiUrl: d.apiUrl || undefined,
    language: d.language || undefined,
    primaryColor: d.primaryColor || undefined,
    siteId: d.siteId || undefined,
    launcherIcon: d.launcherIcon || undefined,
    launcherShape: d.launcherShape || undefined,
    launcherTheme: d.launcherTheme || undefined,
    launcherStyle: d.launcherStyle || undefined,
  };
}

/**
 * 配置解析(契约 T1 冻结的逐键 fallback 顺序):
 * 1. document.currentScript 的 data-*(嵌入页 <script data-api-url> 一等公民)
 * 2. 页面预置 #ask-ai-widget-root 元素的 data-*
 * 3. window.AskAIConfig(旧路径,兼容保留)
 * 4. 默认值
 * MSW:data-site-id 走同一条链(缺省 undefined = legacy 公共 widget)。
 * REV1 外观:launcherIcon 规范属性优先于遗留 launcherStyle(同源内);
 * 跨源优先级 = 显式嵌入覆写 > site-config 持久值 > 兼容默认(App 消解)。
 */
export function resolveConfig(
  script: HTMLScriptElement | null | undefined,
  presetEl: HTMLElement | null | undefined,
  win: Window | null = typeof window === "undefined" ? null : window,
): WidgetConfig {
  const fromScript = readDataset(script);
  const fromPreset = readDataset(presetEl);
  const fromGlobal = (win?.AskAIConfig ?? {}) as ConfigOverrides;
  return {
    apiUrl:
      fromScript.apiUrl ?? fromPreset.apiUrl ?? fromGlobal.apiUrl ?? DEFAULT_API_URL,
    language:
      fromScript.language ?? fromPreset.language ?? fromGlobal.language ?? undefined,
    primaryColor:
      fromScript.primaryColor ??
      fromPreset.primaryColor ??
      fromGlobal.primaryColor ??
      DEFAULT_PRIMARY_COLOR,
    siteId:
      fromScript.siteId ?? fromPreset.siteId ?? fromGlobal.siteId ?? undefined,
    // REV1 统一外观覆写(Admin 实时预览/高级嵌入);真实站点外观由 site-config 承载。
    launcherIcon:
      fromScript.launcherIcon ?? fromPreset.launcherIcon ?? fromGlobal.launcherIcon ?? undefined,
    launcherShape:
      fromScript.launcherShape ?? fromPreset.launcherShape ?? fromGlobal.launcherShape ?? undefined,
    launcherTheme:
      fromScript.launcherTheme ?? fromPreset.launcherTheme ?? fromGlobal.launcherTheme ?? undefined,
    // @deprecated REV0 遗留通道:仅当规范属性缺位时才生效(App 侧退役为 current)
    launcherStyle:
      fromScript.launcherStyle ?? fromPreset.launcherStyle ?? fromGlobal.launcherStyle ?? undefined,
  };
}

/**
 * 挂载入口:容器复用(预置元素优先,否则新建)+ 防重复注入。
 * 同一页面注入两次 script 时,第二次发现容器已有内容即跳过,不产生双浮窗。
 */
export function mountWidget(
  doc: Document,
  script: HTMLScriptElement | null | undefined,
): MountedWidget {
  let container = doc.getElementById(WIDGET_ROOT_ID) as HTMLElement | null;
  const reusedExisting = container != null;
  if (!container) {
    container = doc.createElement("div");
    container.id = WIDGET_ROOT_ID;
    doc.body.appendChild(container);
  }
  if (container.childElementCount > 0) {
    return { config: resolveConfig(script, container, doc.defaultView), container, reusedExisting, mounted: false };
  }
  const config = resolveConfig(script, container, doc.defaultView);
  createRoot(container).render(React.createElement(App, { config }));
  return { config, container, reusedExisting, mounted: true };
}
