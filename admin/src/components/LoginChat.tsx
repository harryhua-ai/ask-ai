import { useState, useCallback } from "react";
import type { WidgetConfig, ChatMessage } from "@widget/types";
import { useSSE } from "@widget/hooks/useSSE";
import { ChatPanel } from "@widget/components/ChatPanel";
import "@widget/styles/widget.css";

const SUGGESTED_QUESTIONS = [
  "NE503 支持哪些接口?",
  "如何开始使用 NeoMind?",
  "NE101 的功耗是多少?",
  "AIToolStack 有哪些功能?",
];

/**
 * Login 页嵌入的聊天窗口(共享 widget 的 ChatPanel 组件,单一聊天窗口来源)。
 *
 * 免登录即可聊:连 /api/ask(channel=widget,匿名),不走 admin 鉴权。
 * 与 widget.js 嵌外部站点共用同一套聊天 UI 组件(ChatPanel/MessageBubble/useSSE),
 * 不重复实现。
 *
 * 与 widget 部署形态的区别:
 * - widget:FAB 浮动按钮 + 展开面板,嵌外部站点
 * - login chat:直接展开面板(login 页内嵌,无 FAB,无关闭)
 */
export function LoginChat() {
  const config: WidgetConfig = { apiUrl: "/api" };  // vite proxy → backend 8000
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const { ask } = useSSE(config.apiUrl);

  const handleSend = useCallback(async (text: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      type: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, type: "assistant", content: "" }]);

    try {
      await ask(text, messages, "widget", {
        onSources: (sources, convId) => {
          setConversationId(convId);
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)),
          );
        },
        onToken: (token) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + token } : m,
            ),
          );
        },
        onDone: (convId) => setConversationId(convId),
        onError: (errMsg) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: errMsg } : m,
            ),
          );
        },
      });
    } finally {
      setIsStreaming(false);
    }
  }, [messages, ask]);

  const handleFeedback = useCallback(async (_msgId: string, feedback: "up" | "down") => {
    if (!conversationId) return;
    await fetch(`${config.apiUrl}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, feedback }),
    });
  }, [conversationId, config.apiUrl]);

  return (
    <div className="login-chat-wrapper" style={{ width: "100%", maxWidth: "420px", margin: "0 auto" }}>
      <ChatPanel
        config={config}
        messages={messages}
        isStreaming={isStreaming}
        conversationId={conversationId}
        suggestedQuestions={messages.length === 0 ? SUGGESTED_QUESTIONS : []}
        onSend={handleSend}
        onClose={() => { /* login 页无关闭按钮,ChatPanel 内关闭按钮保留但 no-op */ }}
        onFeedback={handleFeedback}
      />
    </div>
  );
}
