import { useState, useCallback, useEffect } from "react";
import type { WidgetConfig, ChatMessage, SiteExperienceConfig } from "./types";
import { useSSE } from "./hooks/useSSE";
import { fetchSiteConfig, resolveStarters } from "./utils/siteConfig";
import { collectPageContext } from "./utils/pageContext";
import { ChatPanel } from "./components/ChatPanel";
import fabIcon from "./assets/CamThink.ai-black.png";

const SUGGESTED_QUESTIONS = [
  "NE503 支持哪些接口?",
  "如何开始使用 NeoMind?",
  "NE101 的功耗是多少?",
  "AIToolStack 有哪些功能?",
];

// 与后端 SERVICE_UNAVAILABLE_MSG 保持一致的失败兜底文案
const SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。";

export function App({ config }: { config: WidgetConfig }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // MSW:站点体验配置(启动时按 siteId 拉取;失败 fail-safe 回退默认体验,
  // site_id 仍随 ask 发送,由服务端裁决 → SSE 层可见「站点未授权」失败)
  const [siteConfig, setSiteConfig] = useState<SiteExperienceConfig | null>(null);
  const { ask, uploadFiles } = useSSE(config.apiUrl);

  useEffect(() => {
    if (!config.siteId) return;
    let cancelled = false;
    fetchSiteConfig(config.apiUrl, config.siteId)
      .then((cfg) => {
        if (!cancelled) setSiteConfig(cfg);
      })
      .catch(() => {
        /* 保持默认体验;不做二次降级提示,失败在 ask 时服务端可见 */
      });
    return () => {
      cancelled = true;
    };
  }, [config.apiUrl, config.siteId]);

  const starters =
    messages.length === 0 ? resolveStarters(siteConfig, SUGGESTED_QUESTIONS) : [];
  const welcome = messages.length === 0 ? siteConfig?.welcome : undefined;

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
          // PC-01 客户端最后防线:流结束仍无任何内容(如旧版后端零内容完成)
          // → 显示失败文案,绝不留空白气泡伪装成功
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId && !m.content ? { ...m, content: SERVICE_UNAVAILABLE } : m,
            ),
          );
        },
        onError: (errMsg, meta) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m;
              // 流中断(PC-03):部分内容保留,失败提示追加其后,不覆盖已有输出
              if (meta?.kind === "stream_interrupted") {
                return { ...m, content: m.content ? `${m.content}\n\n${errMsg}` : errMsg };
              }
              return { ...m, content: errMsg };
            }),
          );
        },
      }, attachmentIds, {
        siteId: config.siteId,
        pageContext: collectPageContext(),
        language: config.language ?? siteConfig?.language,
      });
    } finally {
      setIsStreaming(false);
    }
  }, [messages, ask, config.siteId, config.language, siteConfig]);

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
          suggestedQuestions={starters}
          welcome={welcome}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          onFeedback={handleFeedback}
          onUpload={uploadFiles}
        />
      )}
    </>
  );
}
