/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track E**(观察与导出)
 * Wave 1 专属 —— 历史记录 tab 内容(data-panel-history)与观察/导出区域的
 * E 内组合挂载面(U-15 历史时间线 + U-16 导出卡;Integration 壳仅消费稳定
 * props=gap,零壳编辑)。
 *
 * Wave 1(track-e-contract「历史 Tab 渲染全部流转事件」U-15):时间线数据源 =
 * GET /tech/answer-gaps/{id}/observation/events(gap_observation_events
 * append-only 持久化事件;时间戳/actor/from→to 权威投影,前端零推断)。
 * 事件词表:start(进入观察)/ recurrence(复现回待处理)/ abort(中止)/
 * resolve(满窗已解决)。无事件时诚实呈现「暂无流转记录」。
 * 观察区(U-15 CTA/中止)与导出卡(U-16)在 E 自有子组件内实现:
 * ./analytics/GapObservationSection.tsx、./analytics/GapExportCard.tsx。
 */

import { useQuery } from "@tanstack/react-query";
import {
  fetchGapObservationEvents,
  type AnswerGapItem,
  type GapObservationEventItem,
} from "@/lib/api/techInsight";
import { GapObservationSection } from "./GapObservationSection";
import { GapExportCard } from "./GapExportCard";

export interface PanelHistoryProps {
  /** 诊断侧板当前缺口(观察/流转历史数据挂载面)。 */
  gap: AnswerGapItem;
}

/** 流转事件词表 → 运营描述(机器 event_type 的忠实转述,不发明语义)。 */
const EVENT_LABELS: Record<string, string> = {
  start: "内容已补充,开始观察(进入观察中)",
  recurrence: "观察期内证据复现,回到待处理",
  abort: "操作者中止观察,回到待处理",
  resolve: "观察期满无复现,标记为已解决",
};

function eventLabel(ev: GapObservationEventItem): string {
  return EVENT_LABELS[ev.event_type] ?? ev.event_type;
}

export function PanelHistory({ gap }: PanelHistoryProps) {
  const eventsQuery = useQuery({
    queryKey: ["gap-observation-events", gap.id],
    queryFn: () => fetchGapObservationEvents(gap.id),
  });

  const items = eventsQuery.data?.items ?? [];

  return (
    <section data-panel-history className="space-y-4">
      <GapObservationSection gap={gap} />
      <GapExportCard gap={gap} />

      <div>
        <h3 className="mb-2 text-[13px] font-medium text-[var(--t1)]">流转历史</h3>
        {eventsQuery.isLoading ? (
          <div className="text-[12px] text-[var(--t3)]">加载中...</div>
        ) : eventsQuery.isError ? (
          <div className="text-[12px] text-[var(--err)]">流转历史读取失败</div>
        ) : items.length === 0 ? (
          <div className="text-[12px] leading-5 text-[var(--t3)]">
            暂无流转记录:该缺口尚未发生观察/状态转移,系统不做推断。
          </div>
        ) : (
          <ol data-gap-history-timeline className="space-y-2">
            {[...items].reverse().map((ev) => (
              <li
                key={ev.id}
                data-history-event={ev.event_type}
                className="rounded-md border p-2"
                style={{ borderColor: "var(--bd)" }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] text-[var(--t1)]">{eventLabel(ev)}</span>
                  <span className="shrink-0 text-[11px] tabular-nums text-[var(--t3)]">
                    {ev.created_at ? new Date(ev.created_at).toLocaleString() : "—"}
                  </span>
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--t3)]">
                  {ev.from_status} → {ev.to_status}
                  {ev.actor ? ` · 操作者 ${ev.actor}` : " · 系统评估"}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
