/**
 * Ownership(IF-6 附录,文件内区域互斥)— 回答缺口队列 Tab(Integration 壳):
 * - 共享壳/布局/队列表/排序/分页/选择/查询状态 = **Integration**(Wave 0B 落位;
 *   Wave 1 各轨只消费稳定 props,不编辑本文件);
 * - 工具栏 status filter 控件 = **Track E** 专属文件
 *   ./analytics/GapStatusFilter.tsx(本文件零 E 控件实现);
 * - 工具栏 cause filter 控件 = **Track D** 专属文件
 *   ./analytics/GapCauseFilter.tsx(本文件零 D 控件实现);
 * - 工具栏窗选择(data-filter-window)= **Track A** 专属文件
 *   ./analytics/AnalyticsWindowControl.tsx(Wave 1 IF-7 扩展只改该文件,
 *   本文件零 A 控件实现,仅经稳定 props 传窗值);
 * - 队列行「问题/主题」列 = **Track F** 专属文件 ./analytics/GapTopicCell.tsx;
 * - 队列行 cause chip = Track D 呈现组件 ./analytics/CauseBadge.tsx;
 *   状态徽章 = Track E 呈现组件 ./analytics/StatusBadge.tsx(词表扩展各改
 *   自有文件);观察工作流/导出卡挂载面 = 侧板概览推荐操作区(INT-E-01,
 *   GapPanel;历史记录 tab = 纯流转时间线)。
 * 结论:本文件零 A/D/E/F Wave-1 编辑面残留(纯 Integration 编排+稳定 props)。
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import LoadError from "@/components/LoadError";
import { fetchAnswerGaps, type AnswerGapQuery } from "@/lib/api/techInsight";
import { resolveAnalysisWindow } from "@/lib/analysisWindow";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { CauseBadge } from "./CauseBadge";
import { StatusBadge } from "./StatusBadge";
import { relTime } from "./relTime";
import { GapStatusFilter, type GapStatusFilterValue } from "./GapStatusFilter";
import { GapCauseFilter } from "./GapCauseFilter";
import { AnalyticsWindowControl, type AnalyticsWindowValue } from "./AnalyticsWindowControl";
import { GapTopicCell } from "./GapTopicCell";
import GapPanel from "./GapPanel";

// 空态四态区分(#59 G1,C2+C3;§7 视觉语法)。判定只消费客户端筛选真值与
// 服务端 availability 真值(全量聚类计数 + 分类覆盖上界),不制造零、不发明
// 刷新溯源(不区分「从未聚类」与「聚类零缺口」)、不重加趋势/分布。
// 互斥分支,确定性优先级:
//   no-data  聚类总数为 0 → 「暂无缺口聚类证据」(可能尚未执行聚类,或最近
//            一次聚类未发现缺口;不得暗示无缺口);
//   stale    窗口有起点且分类覆盖上界早于窗口起点 → 琥珀色陈旧横幅(证据
//            尚未聚合到当前窗,不暗示无缺口);
//   filtered 显式筛选(status/cause/q)或窗口收窄后为空 → 既有文案 + 扩大提示;
//   zero     全部时间 + 无任何筛选而队列为空 → 真实零态。
type GapEmptyStateKind = "filtered" | "zero" | "no-data" | "stale";

function resolveGapEmptyState(opts: {
  hasFieldFilters: boolean;
  window: AnalyticsWindowValue;
  gapClustersTotal: number | undefined;
  classificationCoveredThrough: string | null;
}): GapEmptyStateKind {
  const {
    hasFieldFilters,
    window: winValue,
    gapClustersTotal,
    classificationCoveredThrough,
  } = opts;
  if (gapClustersTotal === 0) return "no-data";
  if (winValue !== "all" && !hasFieldFilters && classificationCoveredThrough) {
    const winStart = new Date(
      `${resolveAnalysisWindow(winValue).fromISO}Z`,
    ).getTime();
    const covered = new Date(classificationCoveredThrough).getTime();
    if (
      !Number.isNaN(winStart) &&
      !Number.isNaN(covered) &&
      covered < winStart
    ) {
      return "stale";
    }
  }
  if (hasFieldFilters || winValue !== "all") return "filtered";
  return "zero";
}

export default function AnswerGapsTab() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<GapStatusFilterValue>("");
  const [cause, setCause] = useState("");
  const [window, setWindow] = useState<AnalyticsWindowValue>("7d");
  const [order, setOrder] = useState<NonNullable<AnswerGapQuery["order"]>>("last_seen");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(10);

  const query: AnswerGapQuery = {
    status: status || undefined,
    cause: cause || undefined,
    q: search || undefined,
    window,
    order,
    dir: "desc",
    page,
    size,
  };
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["answer-gaps", query],
    queryFn: () => fetchAnswerGaps(query),
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);

  const items = data?.items ?? [];
  const active = items.find((it) => it.id === activeId) ?? null;

  function selectRow(id: string) {
    setActiveId(id);
    setSelected(new Set([id]));
  }

  function toggleCheck(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className="flex gap-4 items-start">
      <div className="min-w-0 flex-1 space-y-3">
        {/* 工具行:搜索(Integration)+ GapStatusFilter(E)+ GapCauseFilter(D)+
            AnalyticsWindowControl(A) */}
        <div className="flex items-center gap-2 flex-wrap" data-gap-toolbar>
          <input
            data-gap-search
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="搜索问题/主题、产品名称或关键词（如：NE101、价格、安装）"
            className="h-9 min-w-[260px] flex-1 rounded-md border px-3 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          />
          <GapStatusFilter
            value={status}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
          />
          <GapCauseFilter
            value={cause}
            onChange={(value) => {
              setCause(value);
              setPage(1);
            }}
          />
          {/* Track A 专属文件:窗选择(Wave 1 IF-7 扩展只改 AnalyticsWindowControl.tsx) */}
          <AnalyticsWindowControl
            value={window}
            onChange={(value) => {
              setWindow(value);
              setPage(1);
            }}
          />
        </div>

        {isError && !data ? (
          <LoadError error={error} onRetry={refetch} />
        ) : isLoading ? (
          <div className="text-[var(--t2)]">加载中...</div>
        ) : (
          <div
            className="overflow-x-auto rounded-lg border [&_td]:px-3 [&_th]:whitespace-nowrap [&_th]:px-3"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            data-answer-gaps-queue
          >
            <Table className="table-fixed w-full">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[6%]" />
                  <TableHead className="w-[32%]">问题 / 主题</TableHead>
                  <TableHead
                    className="w-[10%] cursor-pointer select-none whitespace-nowrap"
                    data-sort-key="questions"
                    onClick={() => setOrder("questions")}
                  >
                    {`相关提问${order === "questions" ? " ↕" : ""}`}
                  </TableHead>
                  <TableHead
                    className="w-[10%] cursor-pointer select-none whitespace-nowrap"
                    data-sort-key="impacted"
                    onClick={() => setOrder("impacted")}
                  >
                    {`影响回答${order === "impacted" ? " ↕" : ""}`}
                  </TableHead>
                  <TableHead className="w-[13%]">原因</TableHead>
                  <TableHead className="w-[14%] whitespace-nowrap">状态</TableHead>
                  <TableHead
                    className="w-[15%] cursor-pointer select-none whitespace-nowrap"
                    data-sort-key="last_seen"
                    onClick={() => setOrder("last_seen")}
                  >
                    {`最近发生${order === "last_seen" ? " ↕" : ""}`}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  (() => {
                    const availability = data?.availability;
                    const coveredThrough =
                      availability?.classification_covered_through ?? null;
                    const kind = resolveGapEmptyState({
                      hasFieldFilters: Boolean(status || cause || search),
                      window,
                      gapClustersTotal: availability?.gap_clusters_total,
                      classificationCoveredThrough: coveredThrough,
                    });
                    // §7 视觉语法:stale=琥珀(中间/陈旧),zero=绿(健康/真实零),
                    // filtered/no-data=中性灰阶(信息性,非异常)。
                    const tone =
                      kind === "stale"
                        ? "var(--warn)"
                        : kind === "zero"
                          ? "var(--ok)"
                          : "var(--t3)";
                    return (
                      <TableRow>
                        <TableCell colSpan={7}>
                          <div
                            data-gap-empty-state={kind}
                            className="py-6 text-center text-[13px]"
                            style={{ color: tone }}
                          >
                            {kind === "no-data" ? (
                              <>
                                暂无缺口聚类证据：可能尚未执行聚类，或最近一次聚类未发现缺口；出现未回答问题聚合后会在此呈现
                              </>
                            ) : kind === "stale" ? (
                              <>
                                聚类证据覆盖至{" "}
                                {coveredThrough ? coveredThrough.slice(0, 10) : ""}，此后数据尚未聚合
                              </>
                            ) : kind === "zero" ? (
                              <>当前没有答案缺口</>
                            ) : (
                              <>
                                当前筛选条件下无答案缺口证据
                                {window !== "all" && "（可尝试扩大时间范围）"}
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })()
                ) : (
                  items.map((gap) => (
                    <TableRow
                      key={gap.id}
                      data-gap-row
                      data-gap-id={gap.id}
                      data-selected={selected.has(gap.id) ? "true" : "false"}
                      onClick={() => selectRow(gap.id)}
                      className="cursor-pointer"
                      style={
                        selected.has(gap.id)
                          ? {
                              background:
                                "color-mix(in srgb, var(--acc) 8%, transparent)",
                              boxShadow: `inset 3px 0 0 var(--acc)`,
                            }
                          : undefined
                      }
                    >
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          data-gap-check
                          checked={selected.has(gap.id)}
                          onChange={() => toggleCheck(gap.id)}
                          className="h-4 w-4 cursor-pointer"
                          style={{ accentColor: "var(--acc)" }}
                        />
                      </TableCell>
                      <GapTopicCell gap={gap} />
                      <TableCell data-gap-questions className="tabular-nums">
                        {gap.question_count}
                      </TableCell>
                      <TableCell data-gap-impacted className="tabular-nums">
                        {gap.impacted_answer_count}
                      </TableCell>
                      <TableCell>
                        <CauseBadge missType={gap.miss_type} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={gap.status} />
                      </TableCell>
                      <TableCell data-gap-recency className="whitespace-nowrap text-[var(--t2)]">
                        {relTime(gap.last_seen_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            {/* 底部:已选择 N 项 + 分页 + 条/页 */}
            <div
              data-gap-pagination
              className="flex items-center justify-between border-t px-3 py-2 text-[12px] text-[var(--t2)]"
              style={{ borderColor: "var(--bd)" }}
            >
              <span data-selection-count>
                已选择 {selected.size} 项
              </span>
              <div className="flex items-center gap-2">
                {/* A-B2-03(audit):参考 = 页码按钮「‹ 1 2 ›」+当前页高亮;单页保持诚实简洁(不造第 2 页) */}
                {(() => {
                  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / size));
                  if (totalPages <= 1) return null;
                  return (
                    <>
                      <button
                        type="button"
                        data-gap-page-prev
                        disabled={page <= 1}
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        className="rounded border px-2 py-1 disabled:opacity-40"
                        style={{ borderColor: "var(--bd)" }}
                        aria-label="上一页"
                      >
                        &lt;
                      </button>
                      {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                        <button
                          key={p}
                          type="button"
                          data-gap-page-number
                          data-page={p}
                          aria-current={p === page ? "page" : undefined}
                          onClick={() => setPage(p)}
                          className="min-w-[26px] rounded border px-2 py-1 tabular-nums"
                          style={{
                            borderColor: p === page ? "var(--acc)" : "var(--bd)",
                            background: p === page ? "color-mix(in srgb, var(--acc) 12%, transparent)" : "transparent",
                            color: p === page ? "var(--acc)" : "var(--t2)",
                            fontWeight: p === page ? 600 : 400,
                          }}
                        >
                          {p}
                        </button>
                      ))}
                      <button
                        type="button"
                        data-gap-page-next
                        disabled={page >= totalPages}
                        onClick={() => setPage((p) => p + 1)}
                        className="rounded border px-2 py-1 disabled:opacity-40"
                        style={{ borderColor: "var(--bd)" }}
                        aria-label="下一页"
                      >
                        &gt;
                      </button>
                    </>
                  );
                })()}
                <select
                  data-gap-page-size
                  value={size}
                  onChange={(e) => {
                    setSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="ml-2 rounded border px-2 py-1"
                  style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
                >
                  <option value={10}>10 条/页</option>
                  <option value={20}>20 条/页</option>
                  <option value={50}>50 条/页</option>
                </select>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 诊断侧板:contextual,仅权威证据(#59 / §5.5);window=共享分析窗
          (IF-7 贯通:PanelStats U-17 聚合窗继承队列激活窗) */}
      {active && (
        <GapPanel
          gap={active}
          window={window}
          onClose={() => setActiveId(null)}
        />
      )}
    </div>
  );
}
