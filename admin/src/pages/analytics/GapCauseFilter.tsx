/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track D**(原因分类学)
 * 专属 —— 队列工具栏 cause filter 控件(data-filter-cause;plan §3.2
 * 「status/cause filter=D」)。Wave 1 扩展(track-d-contract
 * 「filter 选项=权威全集+未分类」)经 @/lib/gapCause 单一词表源挂载,
 * 扩展时只改本文件与词表模块,不编辑 AnswerGapsTab(Integration 壳仅消费
 * 稳定 props value/onChange)。
 * 边界:status filter = Track E 专属文件 ./analytics/GapStatusFilter.tsx,
 * 本文件零 E 语义(状态词表/观察态 filter 均不在本文件,IF-1 观察中选项
 * 也不落位本文件)。零新词表值(§3.0.1)。
 */

import { GAP_CAUSE_OPTIONS } from "@/lib/gapCause";

export function GapCauseFilter({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      data-filter-cause
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 shrink-0 rounded-md border px-2 text-[13px]"
      style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
    >
      <option value="">全部原因</option>
      {GAP_CAUSE_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
