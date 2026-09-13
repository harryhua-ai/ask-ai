/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track E**(观察与导出)
 * 专属 —— 队列工具栏 status filter 控件(data-filter-status;状态词表权威
 * 单一真相源 = backend/services/gap_status.py,前端呈现词经
 * @/lib/gapCause gapStatusLabel)。
 * Wave 1 扩展(IF-1「观察中」过滤选项)只改本文件——经 gap_status 词表模块
 * 挂载 observing 选项,零接触 Track D 的 ./analytics/GapCauseFilter.tsx,
 * 零接触 Integration 壳 AnswerGapsTab.tsx(仅消费稳定 props value/onChange)。
 * 当前值域 = 既有两态 ""|open|resolved(空串=全部);零 observing、
 * 零新词表值(§3.0.1)。
 */

/** status filter 取值(空串=全部既有两态;值域单一来源=gap_status.py 词表)。 */
export type GapStatusFilterValue = "" | "open" | "resolved";

export function GapStatusFilter({
  value,
  onChange,
}: {
  value: GapStatusFilterValue;
  onChange: (value: GapStatusFilterValue) => void;
}) {
  return (
    <select
      data-filter-status
      value={value}
      onChange={(e) => onChange(e.target.value as GapStatusFilterValue)}
      className="h-9 shrink-0 rounded-md border px-2 text-[13px]"
      style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
    >
      <option value="">全部状态</option>
      <option value="open">需要处理</option>
      <option value="resolved">已解决</option>
    </select>
  );
}
