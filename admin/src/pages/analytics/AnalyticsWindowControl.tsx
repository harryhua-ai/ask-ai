/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track A**(共享 chrome +
 * U-2 技术洞察分析窗)专属 —— TI-10 缺口工具栏窗选择控件
 * (data-filter-window;IF-7 单一共享窗状态的三个控制面呈现之一)。
 *
 * Wave 1 IF-7 落地:词表扩展至全冻结词表 {今日 today, 过去 7 天 7d, 过去 30 天
 * 30d, 全部时间 all, 明确起止 range:from/to};与页面壳共享分析窗状态双向绑定
 * (Provider 在位=共享状态为真相,外部变更经桥接同步入壳 props;隔离渲染=纯
 * 受控组件,既有行为零回归)。序列化值即 S5 window 查询参数值(BC-1)。
 */

import { useEffect, useState } from "react";
import {
  parseExplicitWindow,
  useAnalysisWindowContext,
  windowLabel,
  type AnalysisWindowSerialized,
} from "@/lib/analysisWindow";

/** 分析窗取值(IF-7 全词表序列化形;= S5 window 查询参数值)。 */
export type AnalyticsWindowValue = AnalysisWindowSerialized;

/** 命名快选项(过去 7 天/过去 30 天/全部时间 既有呈现逐字保留;今日 为 IF-7 新增)。 */
const NAMED_OPTIONS: { value: "today" | "7d" | "30d" | "all"; label: string }[] = [
  { value: "today", label: "今日" },
  { value: "7d", label: "过去 7 天" },
  { value: "30d", label: "过去 30 天" },
  { value: "all", label: "全部时间" },
];

/** 显式起止选择入口(select 哨兵值)。 */
const EXPLICIT_SENTINEL = "__explicit__";

export function AnalyticsWindowControl({
  value,
  onChange,
}: {
  value: AnalyticsWindowValue;
  onChange: (value: AnalyticsWindowValue) => void;
}) {
  const ctx = useAnalysisWindowContext();
  // 显式起止草稿(null=未进入;非 null=日期输入可见,两侧齐备才可应用)
  const [draft, setDraft] = useState<{ from: string; to: string } | null>(null);

  // 单一共享窗状态为真相:外部面(顶栏/TimeFilter)改窗 → 桥接同步入壳 props
  // (壳经自身 onChange 触发按窗 refetch,窗口面无停留异窗)。隔离渲染(ctx 缺席)
  // 时本控件为纯受控组件,行为与既有逐字一致。
  useEffect(() => {
    if (ctx && ctx.value !== value) onChange(ctx.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx?.value]);

  const isExplicit = value.startsWith("range:");
  const activeExplicit = isExplicit ? parseExplicitWindow(value) : null;
  const selectValue = draft ? EXPLICIT_SENTINEL : isExplicit ? value : value;

  function commit(v: AnalyticsWindowValue) {
    if (ctx) ctx.setValue(v);
    onChange(v);
  }

  function handleSelect(next: string) {
    if (next === EXPLICIT_SENTINEL) {
      setDraft({ from: "", to: "" });
      return;
    }
    setDraft(null);
    commit(next as AnalyticsWindowValue);
  }

  function applyExplicit() {
    const from = draft?.from ?? activeExplicit?.from ?? "";
    const to = draft?.to ?? activeExplicit?.to ?? "";
    if (!from || !to) return; // 起止不完整 → 不可应用(禁半开窗)
    setDraft(null);
    commit(`range:${from}/${to}`);
  }

  const draftFrom = draft?.from ?? activeExplicit?.from ?? "";
  const draftTo = draft?.to ?? activeExplicit?.to ?? "";
  const canApply = Boolean(draftFrom && draftTo);

  return (
    <div className="flex shrink-0 items-center gap-1" data-window-control>
      <select
        data-filter-window
        value={selectValue}
        onChange={(e) => handleSelect(e.target.value)}
        className="h-9 rounded-md border px-2 text-[13px]"
        style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
        aria-label="分析时间窗"
      >
        {NAMED_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        <option value={EXPLICIT_SENTINEL}>明确起止…</option>
        {isExplicit && !draft && activeExplicit && (
          <option value={value}>{windowLabel(value)}</option>
        )}
      </select>
      {(draft || (isExplicit && activeExplicit)) && (
        <>
          <input
            type="date"
            aria-label="开始日期"
            value={draftFrom}
            onChange={(e) => setDraft({ from: e.target.value, to: draftTo })}
            className="h-9 rounded-md border px-2 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          />
          <input
            type="date"
            aria-label="结束日期"
            value={draftTo}
            onChange={(e) => setDraft({ from: draftFrom, to: e.target.value })}
            className="h-9 rounded-md border px-2 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          />
          <button
            type="button"
            data-window-apply
            onClick={applyExplicit}
            disabled={!canApply}
            className="h-9 rounded-md px-3 text-[13px] font-medium text-white disabled:opacity-40"
            style={{ background: "var(--acc)" }}
          >
            应用
          </button>
        </>
      )}
    </div>
  );
}
