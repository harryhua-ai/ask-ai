import { useCallback } from "react";
import type { ChatMessage, SourceLink } from "../types";

interface SSECallbacks {
  onSources: (sources: SourceLink[], conversationId: string) => void;
  onToken: (token: string) => void;
  onDone: (conversationId: string) => void;
}

// SSE 流式接收 hook:解析 event/data 行,分发到对应回调
export function useSSE(apiUrl: string) {
  const ask = useCallback(async (
    message: string,
    history: ChatMessage[],
    channel: string,
    callbacks: SSECallbacks,
  ) => {
    const conversationHistory = history.map((m) => ({
      role: m.type === "user" ? "user" : "assistant",
      content: m.content,
    }));

    const resp = await fetch(`${apiUrl}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        channel,
        conversation_history: conversationHistory.slice(-10),
      }),
    });

    // 安全检查:提前校验 body 是否存在,避免非空断言
    if (!resp.body) return;

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE 事件以空行分隔
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const lines = event.trim().split("\n");
        let eventType = "";
        let dataStr = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7).trim();
          if (line.startsWith("data: ")) dataStr = line.slice(6);
        }
        if (!dataStr) continue;
        try {
          const data = JSON.parse(dataStr);
          if (eventType === "sources") {
            callbacks.onSources(data.sources || [], data.conversation_id);
          } else if (eventType === "token") {
            callbacks.onToken(data.content || "");
          } else if (eventType === "done") {
            callbacks.onDone(data.conversation_id);
          }
        } catch (e) {
          // 非关键日志:JSON 解析失败时记录,便于排查 SSE 协议问题
          console.warn("SSE JSON 解析失败:", e);
        }
      }
    }
  }, [apiUrl]);

  return { ask };
}
