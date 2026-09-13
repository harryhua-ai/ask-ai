import type { WidgetConfig } from "@widget/types";
import { App } from "@widget/App";
import "@widget/styles/widget.css";
import { useLocation } from "react-router-dom";

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
 *
 * V-2(Role A 终局裁决):浮动 FAB 不在 KB-OPS-V163-002 知识运营面呈现——
 * 两张权威设计参考均无该元素。仅抑制数据源列表/详情与技术洞察三个路由,
 * 其余页面(含 Login)行为不变。
 */
const FAB_SUPPRESSED_PATHS = [/^\/data-sources$/, /^\/data-sources\//, /^\/analytics$/];

export function LoginChat() {
  const { pathname } = useLocation();
  if (FAB_SUPPRESSED_PATHS.some((re) => re.test(pathname))) {
    return null;
  }
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
