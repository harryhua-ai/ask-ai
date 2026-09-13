/**
 * Ownership: Track A — Wave 1(IF-7 单一共享分析窗状态:词表/解析/上下文)。
 *
 * 冻结词表(IF-7,remediation plan §3.5「TECHNICAL INSIGHTS WINDOW CAPABILITY
 * MATRIX」):{今日 today, 近7天 7d, 近30天 30d, 全部 all, 显式起止 from/to};
 * 默认 近 7 天(7d)。SH-09 顶栏范围控件、TI-10 缺口工具栏窗选择、tech tab
 * TimeFilter 为同一窗状态的三个呈现面(改动任一 → 整页窗口面真实联动)。
 *
 * 语义定案(单一真相,跨 S1/S2/S5 一致):
 * - today  = UTC 日历日 [当日 00:00:00Z, now];
 * - 7d/30d = [now-Nd, now](与 /tech/performance 既有 range 语义一致);
 * - all    = 显式起止表达:[2000-01-01T00:00:00Z, now](ALL_TIME_FROM 锚点);
 * - 显式起止 = [起日 00:00:00Z, 结束日 23:59:59.999Z](结束日全天含)。
 *
 * 序列化形("AnalysisWindowSerialized")同时是 S5 window 查询参数值
 * (BC-1:today|7d|30d|all|range:YYYY-MM-DD/YYYY-MM-DD)与三控制面的受控值;
 * from/to 以无时区后缀的 UTC ISO 传输(后端 fromisoformat+UTC 语义确定,无偏移歧义)。
 *
 * Provider 挂载于 Layout(admin shell);`useAnalysisWindow` 在无 Provider 的
 * 隔离渲染(既有测试/单组件)下回退为局部状态,保证既有行为零回归。
 */

import { createContext, useContext, useState, type ReactNode } from "react";

/** 全部时间(all)的显式起止锚点(远早于任何业务数据)。 */
export const ALL_TIME_FROM = "2000-01-01";

/** IF-7 默认分析窗 = 近 7 天。 */
export const ANALYSIS_WINDOW_DEFAULT = "7d";

/** 显式起止序列化前缀。 */
const RANGE_PREFIX = "range:";

/** IF-7 全冻结词表的序列化形(同时 = S5 window 查询参数值)。 */
export type AnalysisWindowSerialized =
  | "today"
  | "7d"
  | "30d"
  | "all"
  | `range:${string}/${string}`;

export type AnalysisWindowKind = "today" | "7d" | "30d" | "all" | "explicit";

export interface ResolvedAnalysisWindow {
  value: AnalysisWindowSerialized;
  kind: AnalysisWindowKind;
  /** 无时区后缀的 UTC ISO(起界)。 */
  fromISO: string;
  /** 无时区后缀的 UTC ISO(止界,显式起止=结束日全天含)。 */
  toISO: string;
  /** YYYY-MM-DD(展示用)。 */
  fromDate: string;
  toDate: string;
  /** 人类可读标签(今日/过去 7 天/过去 30 天/全部时间/起 → 止)。 */
  label: string;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isDateStr(s: string): boolean {
  if (!DATE_RE.test(s)) return false;
  const d = new Date(`${s}T00:00:00.000Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** 解析显式起止序列化值;非法 → null(调用方必须显式失败,禁静默回退)。 */
export function parseExplicitWindow(
  v: string,
): { from: string; to: string } | null {
  if (!v.startsWith(RANGE_PREFIX)) return null;
  const body = v.slice(RANGE_PREFIX.length);
  const idx = body.indexOf("/");
  if (idx <= 0) return null;
  const from = body.slice(0, idx);
  const to = body.slice(idx + 1);
  if (!isDateStr(from) || !isDateStr(to)) return null;
  return { from, to };
}

function isoNaiveUTC(d: Date): string {
  // "2026-09-09T23:59:59.999Z" → "2026-09-09T23:59:59.999"(去 Z,UTC 语义由传输约定承载)
  return d.toISOString().slice(0, 23);
}

function dateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function resolveExplicit(from: string, to: string): ResolvedAnalysisWindow {
  const start = new Date(`${from}T00:00:00.000Z`);
  const end = new Date(new Date(`${to}T00:00:00.000Z`).getTime() + 86400000 - 1);
  return {
    value: `range:${from}/${to}`,
    kind: "explicit",
    fromISO: isoNaiveUTC(start),
    toISO: isoNaiveUTC(end),
    fromDate: from,
    toDate: to,
    label: `${from} → ${to}`,
  };
}

/** 分析窗序列化值 → 实际评估窗 [fromISO, toISO] + 标签(三控制面共享的唯一解析)。 */
export function resolveAnalysisWindow(
  value: AnalysisWindowSerialized | string,
  now: Date = new Date(),
): ResolvedAnalysisWindow {
  const v = value as AnalysisWindowSerialized;
  if (v === "today") {
    const start = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
    );
    return {
      value: v,
      kind: "today",
      fromISO: isoNaiveUTC(start),
      toISO: isoNaiveUTC(now),
      fromDate: dateStr(start),
      toDate: dateStr(now),
      label: "今日",
    };
  }
  if (v === "7d" || v === "30d") {
    const days = v === "7d" ? 7 : 30;
    const start = new Date(now.getTime() - days * 86400000);
    return {
      value: v,
      kind: v,
      fromISO: isoNaiveUTC(start),
      toISO: isoNaiveUTC(now),
      fromDate: dateStr(start),
      toDate: dateStr(now),
      label: v === "7d" ? "过去 7 天" : "过去 30 天",
    };
  }
  if (v === "all") {
    const start = new Date(`${ALL_TIME_FROM}T00:00:00.000Z`);
    return {
      value: v,
      kind: "all",
      fromISO: isoNaiveUTC(start),
      toISO: isoNaiveUTC(now),
      fromDate: ALL_TIME_FROM,
      toDate: dateStr(now),
      label: "全部时间",
    };
  }
  const ex = parseExplicitWindow(value);
  if (!ex) {
    throw new Error(`analysisWindow: 未知的分析窗值「${value}」(禁静默回退)`);
  }
  return resolveExplicit(ex.from, ex.to);
}

/** 词表人类可读标签。 */
export function windowLabel(value: AnalysisWindowSerialized | string): string {
  return resolveAnalysisWindow(value).label;
}

/** 由起止日期构造显式起止序列化值(两侧均为 YYYY-MM-DD 才合法)。 */
export function explicitWindowValue(from: string, to: string): AnalysisWindowSerialized | null {
  if (!isDateStr(from) || !isDateStr(to)) return null;
  return `range:${from}/${to}`;
}

// --------------------------------------------------------------------------- //
// 单一共享窗状态(Provider 挂载于 admin shell Layout;三控制面/窗口面消费)
// --------------------------------------------------------------------------- //

export interface AnalysisWindowCtx {
  value: AnalysisWindowSerialized;
  setValue: (v: AnalysisWindowSerialized) => void;
}

const AnalysisWindowContext = createContext<AnalysisWindowCtx | null>(null);

export function AnalysisWindowProvider({ children }: { children: ReactNode }) {
  const [value, setValue] =
    useState<AnalysisWindowSerialized>(ANALYSIS_WINDOW_DEFAULT);
  return (
    <AnalysisWindowContext.Provider value={{ value, setValue }}>
      {children}
    </AnalysisWindowContext.Provider>
  );
}

/** Provider 在位(真实运行时)→ 共享状态;隔离渲染(既有测试/单组件)→ 局部回退。 */
export function useAnalysisWindowContext(): AnalysisWindowCtx | null {
  return useContext(AnalysisWindowContext);
}

export function useAnalysisWindow(): AnalysisWindowCtx {
  const ctx = useContext(AnalysisWindowContext);
  const [value, setValue] =
    useState<AnalysisWindowSerialized>(ANALYSIS_WINDOW_DEFAULT);
  return ctx ?? { value, setValue };
}
