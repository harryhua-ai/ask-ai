import type { WidgetConfig } from "@widget/types";
import { App } from "@widget/App";
import "@widget/styles/widget.css";

/**
 * Login 页嵌入的聊天窗口(共享 widget 的完整 App 组件)。
 *
 * 复用 widget 的 FAB(右下角浮动按钮)+ 点击弹出面板交互,
 * 与 widget.js 嵌外部站点完全一致的体验,单一聊天窗口来源。
 *
 * 免登录即可聊:连 /api/ask(channel=widget,匿名),不走 admin 鉴权。
 */
export function LoginChat() {
  const config: WidgetConfig = {
    apiUrl: "/api",  // vite proxy → backend 8000
    primaryColor: "#000000",
  };
  return <App config={config} />;
}
