import { useState } from "react";
import type { ChatMessage } from "../types";
import { renderMarkdownSafe } from "../utils/sanitize";

interface Props {
  message: ChatMessage;
  isStreaming: boolean;
  apiUrl: string;
  conversationId: string | null;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
}

export function MessageBubble({ message, isStreaming, apiUrl, conversationId, onFeedback }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.type === "user";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API 不可用时静默降级
    }
  };

  return (
    <div className={isUser ? "ask-ai-bubble-user" : "ask-ai-bubble-assistant"}>
      {!isUser && isStreaming && !message.content ? (
        <div className="ask-ai-typing">
          <span className="ask-ai-typing-dot" />
          <span className="ask-ai-typing-dot" />
          <span className="ask-ai-typing-dot" />
        </div>
      ) : (
        <div dangerouslySetInnerHTML={{ __html: renderMarkdownSafe(message.content, message.sources) }} />
      )}
      {!isUser && message.content && !isStreaming && (
        <div className="ask-ai-feedback">
          <button className="ask-ai-feedback-btn" onClick={handleCopy} title="复制回复">
            {copied ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
            )}
          </button>
          <button className="ask-ai-feedback-btn" onClick={() => onFeedback(message.id, "up")} title="有帮助">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 10v12" /><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z" /></svg>
          </button>
          <button className="ask-ai-feedback-btn" onClick={() => onFeedback(message.id, "down")} title="没帮助">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 14V2" /><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z" /></svg>
          </button>
        </div>
      )}
    </div>
  );
}
