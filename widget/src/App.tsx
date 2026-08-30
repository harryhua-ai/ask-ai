import { useState, useCallback } from "react";
import type { WidgetConfig, ChatMessage } from "./types";
import { useSSE } from "./hooks/useSSE";
import { ChatPanel } from "./components/ChatPanel";
import fabIcon from "./assets/CamThink.ai-black.png";

const SUGGESTED_QUESTIONS = [
  "NE503 支持哪些接口?",
  "如何开始使用 NeoMind?",
  "NE101 的功耗是多少?",
  "AIToolStack 有哪些功能?",
];

export function App({ config }: { config: WidgetConfig }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const { ask, uploadFiles } = useSSE(config.apiUrl);

  const handleSend = useCallback(async (text: string, attachmentIds: string[]) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      type: "user",
      content: text,
      attachments: attachmentIds.length
        ? attachmentIds.map((id) => ({ id, filename: id.slice(0, 8), kind: "log", status: "ready" as const }))
        : undefined,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, type: "assistant", content: "" }]);

    // try/finally 确保 isStreaming 总是被重置,即使 fetch 抛错或 SSE 提前返回(resp.body 为空 / resp.ok 为 false)
    try {
      await ask(text, messages, config.channel ?? "widget", {
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
        onDone: (convId) => {
          setConversationId(convId);
        },
        onError: (errMsg) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: errMsg } : m,
            ),
          );
        },
      }, attachmentIds);
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
    <>
      {!isOpen && (
        <button
          className="ask-ai-fab"
          onClick={() => setIsOpen(true)}
        >
          <img className="ask-ai-fab-icon" src={fabIcon} alt="Ask AI" />
        </button>
      )}
      {isOpen && (
        <ChatPanel
          config={config}
          messages={messages}
          isStreaming={isStreaming}
          conversationId={conversationId}
          suggestedQuestions={messages.length === 0 ? SUGGESTED_QUESTIONS : []}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          onFeedback={handleFeedback}
          onUpload={uploadFiles}
        />
      )}
    </>
  );
}
