/**
 * Ownership: Track E (observation) — Wave 1。
 * 状态徽章 = 状态词表呈现面(IF-1:open|observing|resolved 三态;运营词映射
 * 单一来源 = @/lib/gapCause 的 gapStatusLabel,未知状态原样透传)。
 * Wave 1 U-15:OBSERVING/观察中 = 观察期蓝态(参考 PNG 权威:淡彩蓝底 +
 * 蓝字 + 蓝圈形图标,延续 A-B2-02 audit 的圈形图标语法系:ⓘ 需要处理(红)/
 * ◎ 观察中(蓝)/ ✓ 已解决(绿))。
 */

import { gapStatusLabel } from "@/lib/gapCause";

export function StatusBadge({ status }: { status: string }) {
  const resolved = status === "resolved";
  const observing = status === "observing";
  const tone = resolved ? "var(--ok)" : observing ? "var(--acc)" : "var(--err)";
  const bg = resolved
    ? "color-mix(in srgb, var(--ok) 14%, transparent)"
    : observing
      ? "color-mix(in srgb, var(--acc) 14%, transparent)"
      : "color-mix(in srgb, var(--err) 12%, transparent)";
  return (
    <span
      data-gap-status
      data-status={status}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-[12px] font-medium"
      style={{ background: bg, color: tone }}
    >
      {/* A-B2-02(audit)+ Wave 1 U-15:圈形图标语法 = 需要处理 ⓘ(红)/
          观察中 ◎(蓝,观察窗语义)/ 已解决 ✓(绿) */}
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
      ) : observing ? (
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5 shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="8" cy="8" r="6.2" />
          <circle cx="8" cy="8" r="2.6" />
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
