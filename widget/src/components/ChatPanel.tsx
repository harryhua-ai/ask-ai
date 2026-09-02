import { useState, useRef, useEffect } from "react";
import type { WidgetConfig, ChatMessage, AttachmentRef } from "../types";
import type { UiStrings } from "../i18n";
import { MessageBubble } from "./MessageBubble";
import { SuggestedQuestions } from "./SuggestedQuestions";

interface Props {
  config: WidgetConfig;
  /** ML 闭环(G-L4):界面文案按 UI 语言注入,与答案语言分离 */
  strings: UiStrings;
  messages: ChatMessage[];
  isStreaming: boolean;
  conversationId: string | null;
  suggestedQuestions: string[];
  /** MSW:站点欢迎语;缺省回退内置问候(legacy 行为不变) */
  welcome?: string;
  onSend: (text: string, attachmentIds: string[]) => void;
  onClose: () => void;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
  onUpload: (files: File[]) => Promise<AttachmentRef[]>;
}

export function ChatPanel({ config, strings, messages, isStreaming, conversationId, suggestedQuestions, welcome, onSend, onClose, onFeedback, onUpload }: Props) {
  const [input, setInput] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<AttachmentRef[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const messagesEnd = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if ((input.trim() || pendingAttachments.length) && !isStreaming) {
      onSend(input.trim(), pendingAttachments.map((a) => a.id));
      setInput("");
      setPendingAttachments([]);
      setUploadError(null);
    }
  };

  const handlePickFiles = () => fileInput.current?.click();

  const handleFilesChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // 允许重复选同一文件
    if (!files.length) return;
    setUploadError(null);
    try {
      const uploaded = await onUpload(files);
      setPendingAttachments((prev) => [...prev, ...uploaded]);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : strings.uploadFailed);
    }
  };

  const removeAttachment = (id: string) => {
    setPendingAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div className="ask-ai-panel">
      <div className="ask-ai-header" style={{ backgroundColor: "#000000" }}>
        <span>Ask Camthink.ai</span>
        <button onClick={onClose} style={{ float: "right", background: "none", border: "none", color: "white", cursor: "pointer" }}>✕</button>
      </div>
      <div className="ask-ai-messages">
        {messages.length === 0 && (
          <div style={{ color: "#6b7280", fontSize: "14px", textAlign: "center", marginTop: "20px" }}>
            {welcome ?? strings.defaultWelcome}
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
          <SuggestedQuestions questions={suggestedQuestions} onSelect={(q) => onSend(q, [])} />
        )}
        <div ref={messagesEnd} />
      </div>
      {pendingAttachments.length > 0 && (
        <div className="ask-ai-attachment-chips">
          {pendingAttachments.map((att) => (
            <span key={att.id} className="ask-ai-attachment-chip">
              📎 {att.filename}
              <button
                type="button"
                className="ask-ai-attachment-chip-remove"
                onClick={() => removeAttachment(att.id)}
                aria-label={`Remove ${att.filename}`}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      {uploadError && (
        <div className="ask-ai-upload-error">{uploadError}</div>
      )}
      <form className="ask-ai-input" onSubmit={handleSubmit}>
        <input
          type="file"
          multiple
          accept=".txt,.log"
          ref={fileInput}
          onChange={handleFilesChange}
          style={{ display: "none" }}
        />
        <button
          type="button"
          className="ask-ai-attach-btn"
          onClick={handlePickFiles}
          disabled={isStreaming}
          aria-label="Attach log file"
          title={strings.attachTitle}
        >
          +
        </button>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={strings.placeholder}
          disabled={isStreaming}
        />
        <button type="submit" style={{ backgroundColor: "#000000" }} disabled={isStreaming || (!input.trim() && pendingAttachments.length === 0)}>
          {strings.send}
        </button>
      </form>
    </div>
  );
}
