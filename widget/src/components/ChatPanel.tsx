import { useState, useRef, useEffect } from "react";
import type { WidgetConfig, ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";
import { SuggestedQuestions } from "./SuggestedQuestions";

interface Props {
  config: WidgetConfig;
  messages: ChatMessage[];
  isStreaming: boolean;
  conversationId: string | null;
  suggestedQuestions: string[];
  onSend: (text: string) => void;
  onClose: () => void;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
}

export function ChatPanel({ config, messages, isStreaming, conversationId, suggestedQuestions, onSend, onClose, onFeedback }: Props) {
  const [input, setInput] = useState("");
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isStreaming) {
      onSend(input.trim());
      setInput("");
    }
  };

  return (
    <div className="ask-ai-panel">
      <div className="ask-ai-header" style={{ backgroundColor: "#000000" }}>
        <span>Ask AI</span>
        <button onClick={onClose} style={{ float: "right", background: "none", border: "none", color: "white", cursor: "pointer" }}>✕</button>
      </div>
      <div className="ask-ai-messages">
        {messages.length === 0 && (
          <div style={{ color: "#6b7280", fontSize: "14px", textAlign: "center", marginTop: "20px" }}>
            你好!我是 Ask AI,有什么可以帮你?
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isStreaming={isStreaming}
            apiUrl={config.apiUrl}
            conversationId={conversationId}
            onFeedback={onFeedback}
          />
        ))}
        {suggestedQuestions.length > 0 && (
          <SuggestedQuestions questions={suggestedQuestions} onSelect={onSend} />
        )}
        <div ref={messagesEnd} />
      </div>
      <form className="ask-ai-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的问题..."
          disabled={isStreaming}
        />
        <button type="submit" style={{ backgroundColor: "#000000" }} disabled={isStreaming || !input.trim()}>
          发送
        </button>
      </form>
    </div>
  );
}
