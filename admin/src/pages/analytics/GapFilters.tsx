/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track D**(原因分类学)
 * Wave 1 专属 —— 队列工具栏 status/cause filter 控件
 * (data-filter-status / data-filter-cause;plan §3.2「status/cause filter=D」)。
 * Wave 1 扩展(track-d-contract「filter 选项=权威全集+未分类」)经
 * @/lib/gapCause 单一词表源挂载,扩展时只改本文件与词表模块,
 * 不编辑 AnswerGapsTab(Integration 壳仅消费稳定 props)。
 * 边界:IF-1 观察中选项(E 语义)/观察态 filter 控件属 Track E —— 本文件
 * 零 E 语义预设;若 Wave 1 E 的过滤选项落位于 status filter 区域,
 * 由 Integration 轨按 IF-6 文件内区域互斥仲裁。零新词表值(§3.0.1)。
 */

import { GAP_CAUSE_OPTIONS } from "@/lib/gapCause";

/** status filter 取值(空串=全部既有两态;值域单一来源=@/lib/gapCause)。 */
export type GapStatusFilterValue = "" | "open" | "resolved";

export function GapFilters({
  status,
  onStatusChange,
  cause,
  onCauseChange,
}: {
  status: GapStatusFilterValue;
  onStatusChange: (value: GapStatusFilterValue) => void;
  cause: string;
  onCauseChange: (value: string) => void;
}) {
  return (
    <>
      {/* Track D 区域:status/cause filter(词表随 IF-2/IF-1 Wave 1 扩展) */}
      <select
        data-filter-status
        value={status}
        onChange={(e) => onStatusChange(e.target.value as GapStatusFilterValue)}
        className="h-9 shrink-0 rounded-md border px-2 text-[13px]"
        style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
      >
        <option value="">全部状态</option>
        <option value="open">需要处理</option>
        <option value="resolved">已解决</option>
      </select>
      <select
        data-filter-cause
        value={cause}
        onChange={(e) => onCauseChange(e.target.value)}
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
    </>
  );
}
