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
 *   自有文件);观察态 filter/导出卡 = Track E 将来区域(占位说明见
 *   ./analytics/PanelHistory.tsx 头注,本壳零 E 控件实现)。
 * 结论:本文件零 A/D/E/F Wave-1 编辑面残留(纯 Integration 编排+稳定 props)。
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import LoadError from "@/components/LoadError";
import { fetchAnswerGaps, type AnswerGapQuery } from "@/lib/api/techInsight";
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
            AnalyticsWindowControl(A);观察态 filter = Track E Wave 1 将来区域
            (零占位控件,见 PanelHistory 头注) */}
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
                  <TableRow>
                    <TableCell colSpan={7}>
                      <div className="py-6 text-center text-[13px] text-[var(--t3)]">
                        当前筛选条件下无答案缺口证据
                        {window !== "all" && "（可尝试扩大时间范围）"}
                      </div>
                    </TableCell>
                  </TableRow>
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

      {/* 诊断侧板:contextual,仅权威证据(#59 / §5.5) */}
      {active && <GapPanel gap={active} onClose={() => setActiveId(null)} />}
    </div>
  );
}
