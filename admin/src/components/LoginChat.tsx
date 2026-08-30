import type { WidgetConfig } from "@widget/types";
import { App } from "@widget/App";
import "@widget/styles/widget.css";

/**
 * Login 页嵌入的聊天窗口(共享 widget 的完整 App 组件)。
 *
 * 复用 widget 的 FAB(右下角浮动按钮)+ 点击弹出面板交互,
 * 与 widget.js 嵌外部站点完全一致的体验,单一聊天窗口来源。
 *
 * 免登录即可聊:连 /api/ask(channel="admin",匿名),不走 admin 鉴权。
 * 独立渠道值使管理员测试对话落库可区分,不污染真实访客(widget)数据。
 *
 * 包裹 #ask-ai-widget-root:复用 widget.css 已有的定位规则
 * (position:fixed; z-index:99999),确保 FAB 浮在 admin 之上不被遮挡。
 */
export function LoginChat() {
  const config: WidgetConfig = {
    apiUrl: "",  // useSSE 内部拼 /api/ask;vite proxy → backend 8000
    primaryColor: "#000000",
    channel: "admin",  // 数据边界:与管理员测试流量和访客流量分离
  };
  return (
    <div id="ask-ai-widget-root">
      <App config={config} />
    </div>
  );
}
