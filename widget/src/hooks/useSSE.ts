import { useCallback } from "react";
import type { AttachmentRef, ChatMessage, PageContextPayload, SourceLink } from "../types";

export interface SSEErrorMeta {
  /** 后端 error 事件的失败类别:empty_generation / provider_error / stream_interrupted */
  kind?: string;
}

/** MSW:ask 请求的站点/页面附加字段(均可选;legacy 不传 = 请求体无这些键) */
export interface AskExtra {
  siteId?: string;
  pageContext?: PageContextPayload;
  language?: string;
}

export interface SSECallbacks {
  onSources: (sources: SourceLink[], conversationId: string) => void;
  onToken: (token: string) => void;
  onDone: (conversationId: string) => void;
  onError: (message: string, meta?: SSEErrorMeta) => void;
}

// 与后端 SERVICE_UNAVAILABLE_MSG 保持一致的兜底文案
const SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。";

// widget 匿名会话标识(localStorage UUID,无服务端签发)
function getSessionId(): string {
  let s = localStorage.getItem("ask_ai_session_id");
  if (!s) {
    s = crypto.randomUUID();
    localStorage.setItem("ask_ai_session_id", s);
  }
  return s;
}

// 消费 /api/ask SSE 响应:解析 event/data 行,分发到对应回调。
// 独立导出以便对真实流消费路径做单测。
// 失败信号契约(与后端 P1 生成可靠性配套):
// - error 事件 → onError(消息, {kind}) —— 零内容完成/生成异常/流中断;
// - declined 事件(预算熔断)→ onError(reason);
// - 未知事件类型忽略(向后兼容旧服务端,不崩溃)。
// opts.siteRestricted(MSW):请求带 site_id 时 403 语义从「附件无权」
// 切换为「站点未授权」(后端对显式 site_id 的 Origin 校验失败)。
export async function consumeSSE(
  resp: Response,
  callbacks: SSECallbacks,
  opts?: { siteRestricted?: boolean },
): Promise<void> {
  // HTTP 错误响应:4xx/5xx 不应作为 SSE 解析,否则每个 chunk 都会 JSON 解析失败
  if (!resp.ok) {
    console.error(`SSE 请求失败: ${resp.status}`);
    const msg =
      resp.status === 403
        ? opts?.siteRestricted
          ? "此站点未被授权使用 Ask AI。"
          : "无权访问所选附件。"
        : resp.status === 422
          ? "问题内容过长或格式有误,请精简后重试。"
          : SERVICE_UNAVAILABLE;
    callbacks.onError(msg);
    return;
  }
  // 安全检查:提前校验 body 是否存在,避免非空断言
  if (!resp.body) return;

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

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
        } else if (eventType === "error") {
          callbacks.onError(data.message || SERVICE_UNAVAILABLE, { kind: data.kind });
        } else if (eventType === "declined") {
          callbacks.onError(data.reason || "服务繁忙,请稍后再试");
        } else if (eventType === "done") {
          callbacks.onDone(data.conversation_id);
        }
      } catch (e) {
        // 非关键日志:JSON 解析失败时记录,便于排查 SSE 协议问题
        console.warn("SSE JSON 解析失败:", e);
      }
    }
  }
}

// 构造 /api/ask 请求体(独立导出便于单测断言精确键集合)。
// 契约:legacy(无 extra)请求体不含任何 site 键,与既有后端字节级兼容。
export function buildAskBody(
  message: string,
  history: ChatMessage[],
  channel: string,
  attachments: string[] = [],
  extra?: AskExtra,
): Record<string, unknown> {
  const conversationHistory = history.map((m) => ({
    role: m.type === "user" ? "user" : "assistant",
    content: m.content,
  }));
  const body: Record<string, unknown> = {
    message,
    channel,
    conversation_history: conversationHistory.slice(-10),
    session_id: getSessionId(),
    attachments,
  };
  if (extra?.siteId) body.site_id = extra.siteId;
  if (extra?.pageContext) body.page_context = extra.pageContext;
  if (extra?.language) body.language = extra.language;
  return body;
}

// SSE 流式接收 hook:解析 event/data 行,分发到对应回调
export function useSSE(apiUrl: string) {
  const uploadFiles = useCallback(async (files: File[]): Promise<AttachmentRef[]> => {
    if (files.length === 0) return [];
    const fd = new FormData();
    fd.append("session_id", getSessionId());
    for (const f of files) fd.append("files", f);
    const resp = await fetch(`${apiUrl}/api/upload`, {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) {
      throw new Error(`Upload failed: ${resp.status}`);
    }
    const data = await resp.json();
    const items: AttachmentRef[] = (data.attachments || []).map(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (a: any) => ({
        id: a.id,
        filename: a.filename,
        kind: a.kind,
        status: a.ok ? "ready" : "failed",
        error: a.error,
      }),
    );
    const failed = items.filter((a) => a.status === "failed");
    if (failed.length === items.length && items.length > 0) {
      throw new Error(failed[0]?.error || "All files rejected");
    }
    return items;
  }, [apiUrl]);

  const ask = useCallback(async (
    message: string,
    history: ChatMessage[],
    channel: string,
    callbacks: SSECallbacks,
    attachments: string[] = [],
    extra?: AskExtra,
  ) => {
    const resp = await fetch(`${apiUrl}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildAskBody(message, history, channel, attachments, extra)),
    });

    await consumeSSE(resp, callbacks, { siteRestricted: Boolean(extra?.siteId) });
  }, [apiUrl]);

  return { ask, uploadFiles };
}
