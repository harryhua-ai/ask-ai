/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track A**(共享 chrome +
 * U-2 技术洞察分析窗)专属 —— TI-10 缺口工具栏窗选择控件
 * (data-filter-window;IF-7 单一共享窗状态的三个控制面呈现之一)。
 * Wave 1 A 的 IF-7 扩展(接入页面壳共享分析窗状态+IF-7 全词表
 * today/显式起止)只改本文件与 Analytics 页面壳 A 区域,零接触
 * Integration 壳 AnswerGapsTab.tsx 与 Track D/E 的 filter 文件
 * (本壳仅消费稳定 props value/onChange)。
 * 当前:既有 7d/30d/all 词表与呈现逐字保留(零 IF-7 新语义/零新词表值)。
 */

/** 分析窗取值(既有 S5 词表;IF-7 全词表扩展属 Wave 1 Track A,仅改本文件)。 */
export type AnalyticsWindowValue = "7d" | "30d" | "all";

export function AnalyticsWindowControl({
  value,
  onChange,
}: {
  value: AnalyticsWindowValue;
  onChange: (value: AnalyticsWindowValue) => void;
}) {
  return (
    <select
      data-filter-window
      value={value}
      onChange={(e) => onChange(e.target.value as AnalyticsWindowValue)}
      className="h-9 shrink-0 rounded-md border px-2 text-[13px]"
      style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
    >
      <option value="7d">过去 7 天</option>
      <option value="30d">过去 30 天</option>
      <option value="all">全部时间</option>
    </select>
  );
}
