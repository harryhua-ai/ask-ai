// I-UX-001:入口表面组件 —— A Minimal Pill / B Contextual Nudge / C Mini
// Conversation Entry。信息架构冻结于产品契约 §2.5(C 不放长介绍/页面摘要/
// 大型 starter 清单);全部交互可键盘达;reduced-motion 由 CSS 守卫。

import { useState } from "react";
import type { TrustedActionRef } from "../types";
import type { UiStrings } from "../i18n";

// ---------------------------------------------------------------------------
// A — MINIMAL_PILL
// ---------------------------------------------------------------------------

export function EntryPill({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <button type="button" className="ask-ai-pill" onClick={onOpen} aria-haspopup="dialog">
      <svg
        className="ask-ai-pill-glyph"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
      </svg>
      <span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// B — CONTEXTUAL_NUDGE(轻量页 aware 气泡;点击 → 打开聊天;可暂不)
// ---------------------------------------------------------------------------

export function ContextualNudge({
  greeting,
  dismissLabel,
  onOpen,
  onDismiss,
}: {
  greeting: string;
  dismissLabel: string;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="ask-ai-nudge" role="status">
      <button type="button" className="ask-ai-nudge-body" onClick={onOpen} aria-haspopup="dialog">
        <span className="ask-ai-nudge-identity">Ask AI</span>
        <span className="ask-ai-nudge-greeting">{greeting}</span>
      </button>
      <button
        type="button"
        className="ask-ai-nudge-dismiss"
        onClick={onDismiss}
        aria-label={dismissLabel}
        title={dismissLabel}
      >
        ✕
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// C — MINI_CONVERSATION_ENTRY(紧凑 ~340×200;一次交互即开始真实会话)
// ---------------------------------------------------------------------------

export function MiniConversationEntry({
  identity,
  greeting,
  actions,
  placeholder,
  sendLabel,
  notNowLabel,
  minimizeLabel,
  actionsLabel,
  onAction,
  onSubmit,
  onMinimize,
}: {
  identity: string;
  greeting: string;
  actions: TrustedActionRef[];
  placeholder: string;
  sendLabel: string;
  notNowLabel: string;
  minimizeLabel: string;
  actionsLabel: string;
  onAction: (action: TrustedActionRef, query: string) => void;
  onSubmit: (text: string) => void;
  onMinimize: () => void;
}) {
  const [draft, setDraft] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onSubmit(text);
  };

  return (
    <section className="ask-ai-mini" aria-label={identity}>
      <header className="ask-ai-mini-header">
        <span className="ask-ai-mini-identity" aria-label={identity}>
          <span className="ask-ai-mini-spark" aria-hidden="true">
            ✦
          </span>
          Ask AI
        </span>
        <button
          type="button"
          className="ask-ai-mini-minimize"
          onClick={onMinimize}
          aria-label={minimizeLabel}
          title={minimizeLabel}
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      </header>
      <p className="ask-ai-mini-greeting">{greeting}</p>
      {actions.length > 0 && (
        <div className="ask-ai-mini-actions" role="group" aria-label={actionsLabel}>
          {actions.map((action) => (
            <button
              key={action.type + action.label}
              type="button"
              className="ask-ai-mini-action"
              onClick={() => onAction(action, action.query)}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
      <form className="ask-ai-mini-input" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
        />
        <button type="submit" disabled={!draft.trim()} aria-label={sendLabel}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </form>
      <button type="button" className="ask-ai-mini-notnow" onClick={onMinimize}>
        {notNowLabel}
      </button>
    </section>
  );
}

export type { UiStrings };
