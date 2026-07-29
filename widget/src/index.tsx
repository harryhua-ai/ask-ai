import React from "react";
import { createRoot } from "react-dom/client";
import type { WidgetConfig } from "./types";
import { App } from "./App";
import "./styles/widget.css";

// 声明全局 window 类型,避免使用 (window as any)
declare global {
  interface Window {
    AskAIConfig?: { apiUrl?: string };
  }
}

// 创建挂载容器
const container = document.createElement("div");
container.id = "ask-ai-widget-root";
document.body.appendChild(container);

// 从 data-* 属性或全局变量读取配置
const config: WidgetConfig = {
  apiUrl:
    (container.getAttribute("data-api-url") as string | null) ??
    window.AskAIConfig?.apiUrl ??
    "http://localhost:8000",
  language: container.getAttribute("data-language") ?? undefined,
  primaryColor: container.getAttribute("data-primary-color") ?? "#f24a00",
};

const root = createRoot(container);
root.render(React.createElement(App, { config }));
