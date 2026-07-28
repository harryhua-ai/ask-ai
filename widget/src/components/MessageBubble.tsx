import type { ChatMessage } from "../types";

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
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
      {!isUser && message.content && !isStreaming && (
        <>
          {message.sources && message.sources.length > 0 && (
            <div style={{ marginTop: "8px", borderTop: "1px solid #f3f4f6", paddingTop: "8px" }}>
              {message.sources.map((src, i) => (
                <a
                  key={i}
                  className="ask-ai-source"
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => {
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
              ))}
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

function renderMarkdown(text: string): string {
  // 先转义 HTML 特殊字符,防止 XSS(因为 LLM 输出可能包含 <script> 等)
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  // 然后应用 Markdown 变换(转义后 ``` 仍是三个反引号,正则仍能匹配)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^## (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
  html = html.replace(/\n/g, "<br>");
  return html;
}
