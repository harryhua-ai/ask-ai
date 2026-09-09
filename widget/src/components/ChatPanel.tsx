import { useState, useRef, useEffect } from "react";
import type { WidgetConfig, ChatMessage, AttachmentRef, TrustedActionRef } from "../types";
import type { UiStrings } from "../i18n";
import type { ThemeTokens } from "../experience/theme";
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
  /** I-UX-001:聊天窗主题 token(落根容器 CSS 变量;不触碰宿主) */
  themeStyle: ThemeTokens;
  /** I-UX-001:主题明暗特征(match/custom 派生结果;驱动结构细节) */
  character: "light" | "dark";
  /** I-UX-001:窗口尺寸预设(default|large) */
  chatSize: "default" | "large";
  /** I-UX-001:冷启动态的 Trusted Actions(最多 3;会话开始后消失) */
  coldActions: TrustedActionRef[];
  /** I-UX-001:动作点击 → 立即开始真实会话(整只动作上交,由 App 唯一路径绑定;绝不直发 query) */
  onColdAction: (action: TrustedActionRef) => void;
  onSend: (text: string, attachmentIds: string[]) => void;
  onClose: () => void;
  onFeedback: (msgId: string, feedback: "up" | "down") => void;
  onUpload: (files: File[]) => Promise<AttachmentRef[]>;
}

/** I-UX-001:桌面 = 右下浮动面(非全高抽屉);移动 = 底部弹层;dialog 语义。 */
export function ChatPanel({
  config,
  strings,
  messages,
  isStreaming,
  conversationId,
  suggestedQuestions,
  welcome,
  themeStyle,
  character,
  chatSize,
  coldActions,
  onColdAction,
  onSend,
  onClose,
  onFeedback,
  onUpload,
}: Props) {
  const [input, setInput] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<AttachmentRef[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const messagesEnd = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 可访问性:打开时焦点入面板;Escape 关闭;关闭后焦点交还触发点
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => previous?.focus?.();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

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

  const cold = messages.length === 0;

  return (
    <div
      ref={panelRef}
      className={`ask-ai-panel${chatSize === "large" ? " ask-ai-panel-large" : ""}`}
      style={themeStyle as React.CSSProperties}
      role="dialog"
      aria-modal="false"
      aria-label={strings.chatTitle}
      data-ask-ai-character={character}
    >
      <div className="ask-ai-header">
        <span className="ask-ai-header-title">{strings.chatTitle}</span>
        <button
          type="button"
          className="ask-ai-header-close"
          onClick={onClose}
          aria-label={strings.minimize}
          title={strings.minimize}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div className="ask-ai-messages">
        {cold && (
          <div className="ask-ai-welcome">{welcome ?? strings.defaultWelcome}</div>
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
        {/* 冻结 §2.8:冷启动欢迎/starter/动作只在空会话;开始后 message-first */}
        {cold && coldActions.length > 0 && (
          <div className="ask-ai-cold-actions" role="group" aria-label={strings.trustedActions}>
            {coldActions.map((action) => (
              <button
                key={action.type + action.label}
                type="button"
                className="ask-ai-cold-action"
                onClick={() => onColdAction(action)}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
        {cold && suggestedQuestions.length > 0 && (
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
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={strings.placeholder}
          disabled={isStreaming}
        />
        <button type="submit" className="ask-ai-send-btn" disabled={isStreaming || (!input.trim() && pendingAttachments.length === 0)}>
          {strings.send}
        </button>
      </form>
    </div>
  );
}
