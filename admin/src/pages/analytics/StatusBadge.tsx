/**
 * Ownership: Track E (observation) — Wave 1。
 * 状态徽章 = 状态词表呈现面(IF-1:open|resolved 既有两态;运营词映射
 * 单一来源 = @/lib/gapCause 的 gapStatusLabel,未知状态原样透传)。
 * Wave 1 边界:OBSERVING/观察中 为 Track E 新状态语义 —— 本 Wave 零实现、
 * 零占位 UI;圈形图标语法(A-B2-02 audit)随状态词表由 Track E 延续。
 */

import { gapStatusLabel } from "@/lib/gapCause";

export function StatusBadge({ status }: { status: string }) {
  const resolved = status === "resolved";
  return (
    <span
      data-gap-status
      data-status={status}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-[12px] font-medium"
      style={{
        background: resolved
          ? "color-mix(in srgb, var(--ok) 14%, transparent)"
          : "color-mix(in srgb, var(--err) 12%, transparent)",
        color: resolved ? "var(--ok)" : "var(--err)",
      }}
    >
      {/* A-B2-02(audit):圈形图标语法 = 需要处理 ⓘ(红)/ 已解决 ✓(绿);观察中不存在,不造 */}
      {resolved ? (
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5 shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="8" cy="8" r="6.2" />
          <path d="M5.2 8.2l2 2 3.6-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5 shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="8" cy="8" r="6.2" />
          <line x1="8" y1="7.2" x2="8" y2="11.2" strokeLinecap="round" />
          <circle cx="8" cy="4.8" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      )}
      {gapStatusLabel(status)}
    </span>
  );
}
