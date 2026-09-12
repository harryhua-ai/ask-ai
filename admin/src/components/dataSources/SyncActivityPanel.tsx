/**
 * v1.6.3 B1(KB-OPS-V163-002 §4.4 / #56):同步状态与活动(硬参考 panel 4)。
 *
 * 冻结语义:
 * - 最近成功 / 最近结果 / 同步可靠性 / 同步周期 全部来自后端权威读面
 *   (sync_runs+sync_log / /data-sources last_sync_* / /analytics/source-health
 *   窗口成功率 / source.sync_interval);「下次同步」后端无权威时间 → 不呈现;
 * - 活动时间线异常优先:失败/部分成功事件视觉高于常规;常规无变更成功运行
 *   压缩为单组节点(可展开逐条核证);技术证据可展开(#56 presentation-only);
 * - 前端零健康重判:可靠性仅本地化 source-health 权威字段,样本不足不给百分比。
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { buildSyncActivity, humanizeInterval, lastSuccessIso, relativeTime } from "@/lib/dataSourceOps";
import { formatSyncTime } from "@/lib/sourceEditorModel";
import type { DataSource, SyncRunList } from "@/types/api";
import type { SourceHealthItem } from "@/lib/api/techInsight";

export interface SyncActivityPanelProps {
  source: DataSource;
  runs: SyncRunList | undefined;
  runsLoading?: boolean;
  runsError?: string | null;
  onRetryRuns?: () => void;
  /** /analytics/source-health 窗口可靠性条目(权威;undefined = 证据不足)。 */
  health?: SourceHealthItem;
  /** 既有授权操作:手动触发同步(存在才渲染)。 */
  onTriggerSync?: () => void;
  syncPending?: boolean;
}

const LATEST_RESULT_META: Record<string, { label: string; variant: "success" | "destructive" | "warning" | "secondary" | "outline" }> = {
  success: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
  partial: { label: "部分成功", variant: "warning" },
};

const TONE_DOT: Record<string, string> = {
  red: "bg-destructive",
  amber: "bg-amber-500",
  green: "bg-green-500",
  gray: "bg-muted-foreground/40",
  info: "bg-blue-500",
};

function reliabilityLine(health: SourceHealthItem | undefined): string {
  if (!health) return "证据不足";
  if (health.health === "insufficient_data") {
    return health.total_syncs > 0
      ? `仅 ${health.total_syncs} 次同步,暂不评估`
      : "暂无同步记录";
  }
  const pct = Math.round(health.sync_success_rate * 100);
  return `${pct}% · 近${health.window_days}天 ${health.total_syncs} 次`;
}

function reliabilityTitle(health: SourceHealthItem | undefined): string | undefined {
  if (!health || health.health === "insufficient_data") return undefined;
  return (
    `近 ${health.window_days} 天 ${health.total_syncs} 次同步:` +
    `${health.success_syncs} 次成功 / ${health.partial_syncs} 次补齐 / ${health.failed_syncs} 次失败` +
    `(成功率按次数计,补齐不计入成功)`
  );
}

export function SyncActivityPanel({
  source,
  runs,
  runsLoading,
  runsError,
  onRetryRuns,
  health,
  onTriggerSync,
  syncPending,
}: SyncActivityPanelProps) {
  const activity = buildSyncActivity(runs?.items, []);
  const lastSuccess = lastSuccessIso(runs?.items);
  const result = source.last_sync_status
    ? LATEST_RESULT_META[source.last_sync_status]
    : undefined;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-base">同步状态与活动</CardTitle>
        {onTriggerSync && (
          <Button size="sm" variant="outline" onClick={onTriggerSync} disabled={syncPending}>
            {syncPending ? "触发中..." : "同步"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-0 text-sm">
        <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
          <p>
            <span className="text-muted-foreground">最近成功:</span>{" "}
            {lastSuccess ? (
              <span title={formatSyncTime(lastSuccess)}>{relativeTime(lastSuccess)}</span>
            ) : (
              <span className="text-muted-foreground">从未成功同步</span>
            )}
          </p>
          <p>
            <span className="text-muted-foreground">最近结果:</span>{" "}
            {result ? <Badge variant={result.variant}>{result.label}</Badge> : (
              <span className="text-muted-foreground">从未同步</span>
            )}
          </p>
          <p>
            <span className="text-muted-foreground">同步可靠性:</span>{" "}
            <span title={reliabilityTitle(health)}>{reliabilityLine(health)}</span>
          </p>
          <p>
            <span className="text-muted-foreground">同步周期:</span>{" "}
            {humanizeInterval(source.sync_interval)}
          </p>
        </div>
        {source.last_sync_status === "failed" && source.last_sync_error && (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            {source.last_sync_error}
          </p>
        )}

        <div className="space-y-1">
          <h4 className="text-sm font-semibold">最近活动</h4>
          {runsLoading && <p className="text-muted-foreground">正在加载活动…</p>}
          {runsError && onRetryRuns && (
            <p className="flex items-center gap-2 text-muted-foreground">
              {runsError}
              <Button size="sm" variant="outline" onClick={onRetryRuns}>重试加载</Button>
            </p>
          )}
          {!runsLoading && !runsError && activity.events.length === 0 && (
            <p className="text-muted-foreground">暂无活动记录</p>
          )}
          <ol className="space-y-2">
            {activity.events.map((ev, idx) => (
              <li key={`${ev.kind}-${ev.timeIso ?? "none"}-${idx}`} className="flex items-start gap-2">
                <span
                  className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${TONE_DOT[ev.tone]}`}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-mono text-xs text-muted-foreground">
                      {ev.timeIso ? formatSyncTime(ev.timeIso) : "—"}
                    </span>
                    <span
                      className={
                        ev.tone === "red"
                          ? "font-medium text-destructive"
                          : ev.tone === "amber"
                            ? "font-medium text-amber-600"
                            : "text-sm"
                      }
                    >
                      {ev.title}
                    </span>
                  </div>
                  {ev.meta && ev.meta.length > 0 && (
                    <p className="truncate text-xs text-muted-foreground" title={ev.meta.join("; ")}>
                      {ev.meta.join(" · ")}
                    </p>
                  )}
                  {ev.kind === "routine-group" && ev.count != null && ev.count > 0 && (
                    <details className="mt-0.5 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">展开常规运行</summary>
                      <ul className="mt-1 space-y-0.5">
                        {(runs?.items ?? [])
                          .filter(
                            (r) =>
                              r.status?.toLowerCase() === "completed" &&
                              r.sync_log?.status === "success" &&
                              (r.sync_log.items_new ?? 0) === 0 &&
                              (r.sync_log.items_deleted ?? 0) === 0,
                          )
                          .map((r) => (
                            <li key={r.id} className="font-mono">
                              {formatSyncTime(r.started_at)} · 未变更 {r.sync_log?.items_unchanged ?? 0} ·
                              触发 {r.triggered_by ?? "—"}
                            </li>
                          ))}
                      </ul>
                    </details>
                  )}
                  {ev.kind === "run" && ev.run && (
                    <details className="mt-0.5 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">技术证据</summary>
                      <div className="mt-1 space-y-0.5 font-mono break-all">
                        <p>run_id: {ev.run.id}</p>
                        {ev.run.request_id != null && <p>request_id: {ev.run.request_id}</p>}
                        {ev.run.duration_seconds != null && <p>用时: {ev.run.duration_seconds}s</p>}
                        {ev.run.fallback_reason && <p>fallback: {ev.run.fallback_reason}</p>}
                        {ev.run.sync_log && (
                          <p>
                            业务结果: {ev.run.sync_log.status} · 新增 {ev.run.sync_log.items_new} ·
                            删除 {ev.run.sync_log.items_deleted} · 未变更{" "}
                            {ev.run.sync_log.items_unchanged}
                          </p>
                        )}
                      </div>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </CardContent>
    </Card>
  );
}
