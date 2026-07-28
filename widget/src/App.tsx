// 占位 App 组件 —— Task 18 会替换为完整的聊天 UI
import type { WidgetConfig } from "./types";

interface AppProps {
  config: WidgetConfig;
}

export function App({ config }: AppProps) {
  return (
    <div
      className="ask-ai-fab"
      style={{ background: config.primaryColor ?? "#2563eb" }}
    >
      💬
    </div>
  );
}
