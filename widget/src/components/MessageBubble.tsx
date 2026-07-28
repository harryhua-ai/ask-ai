import type { ChatMessage } from "../types";
import { renderMarkdownSafe } from "../utils/sanitize";
import { isAllowedUrl } from "../utils/urlPolicy";

interface Props {
  message: ChatMessage;
  isStreaming: boolean;
  apiUrl: string;
  conversationId: string | null;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
}

const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  wiki: "Wiki",
  website: "官网",
  blog: "博客",
  filesystem: "知识库",
};

export function MessageBubble({ message, isStreaming, apiUrl, conversationId, onFeedback }: Props) {
  const isUser = message.type === "user";
  return (
    <div className={isUser ? "ask-ai-bubble-user" : "ask-ai-bubble-assistant"}>
      <div dangerouslySetInnerHTML={{ __html: renderMarkdownSafe(message.content) }} />
      {!isUser && message.content && !isStreaming && (
        <>
          {message.sources && message.sources.length > 0 && (
            <div style={{ marginTop: "8px", borderTop: "1px solid #f3f4f6", paddingTop: "8px" }}>
              {message.sources.map((src, i) => {
                const safe = isAllowedUrl(src.url);
                return (
                  <a
                    key={i}
                    className="ask-ai-source"
                    href={safe ? src.url : "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => {
                      if (!safe) {
                        e.preventDefault();
                        return;
                      }
                      if (!conversationId) return;
                      fetch(`${apiUrl}/api/click`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          conversation_id: conversationId,
                          source_url: src.url,
                          source_type: src.type,
                          product: src.product,
                        }),
                      });
                    }}
                  >
                    [{SOURCE_LABELS[src.type] || src.type}] {src.title}
                  </a>
                );
              })}
            </div>
          )}
          <div className="ask-ai-feedback">
            <button onClick={() => onFeedback(message.id, "up")}>👍</button>
            <button onClick={() => onFeedback(message.id, "down")}>👎</button>
          </div>
        </>
      )}
    </div>
  );
}
