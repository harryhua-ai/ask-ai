import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  deviceLabel,
  extractConsistencyFacts,
  fallbackLabel,
  formatDuration,
  stateLabel,
  syncRunDisplayState,
} from "@/lib/dataSourceObservability";
import type { SyncRun, SyncRunList, SyncState } from "@/types/api";

export interface SyncHistoryPanelProps {
  runs: SyncRunList | undefined;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

const SYNC_LOG_STATUS_LABELS: Record<string, string> = {
  success: "成功",
  partial: "补齐",
  failed: "失败",
};

function stateVariant(state: SyncState | null): "secondary" | "success" | "warning" | "destructive" | "outline" {
  if (state === "COMPLETED") return "success";
  if (state === "RUNNING" || state === "RECOVERING") return "warning";
  if (state === "FAILED" || state === "INTERRUPTED") return "destructive";
  if (state === "IDLE") return "outline";
  return "secondary";
}

function TechnicalEvidence({ run }: { run: SyncRun }) {
  return (
    <details className="rounded-md border border-border p-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium text-foreground">技术证据</summary>
      <div className="mt-2 space-y-1 font-mono break-all">
        <p>run_id: {run.id}</p>
        {run.request_id != null && <p>request_id: {run.request_id}</p>}
        {run.attempt != null && <p>attempt: {run.attempt}</p>}
        {run.recovery != null && <p>recovery: {String(run.recovery)}</p>}
        {run.error_summary && <p>{run.error_summary}</p>}
        {run.fallback_detail && <p>{run.fallback_detail}</p>}
        {run.sync_log?.error_detail && <p>{run.sync_log.error_detail}</p>}
      </div>
    </details>
  );
}

function RunCard({ run }: { run: SyncRun }) {
  const counters = run.counters;
  const syncLog = run.sync_log;
  const facts = extractConsistencyFacts(run);
  const duration = run.duration_seconds != null
    ? formatDuration(run.duration_seconds * 1000)
    : formatDuration(run.started_at, run.finished_at);
  const fallback = fallbackLabel(run.fallback_reason);
  const displayState = syncRunDisplayState(run.status);
  const businessStatus = syncLog?.status
    ? (SYNC_LOG_STATUS_LABELS[syncLog.status] ?? syncLog.status)
    : null;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-sm">同步记录</CardTitle>
        <Badge variant={stateVariant(displayState)}>{stateLabel(displayState)}</Badge>
      </CardHeader>
      <CardContent className="space-y-2 p-4 pt-0 text-sm">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
          {run.started_at && <span>开始 {run.started_at}</span>}
          {run.triggered_by && <span>触发 {run.triggered_by}</span>}
          {businessStatus && <span>{`业务结果：${businessStatus}`}</span>}
          {syncLog?.items_new != null && <span>新增文档 {syncLog.items_new}</span>}
          {syncLog?.items_deleted != null && <span>删除文档 {syncLog.items_deleted}</span>}
          {syncLog?.items_unchanged != null && <span>未变更文档 {syncLog.items_unchanged}</span>}
          {syncLog?.chunks_written != null && <span>分块 {syncLog.chunks_written}</span>}
          {counters?.chunks_deleted != null && <span>已删除分块 {counters.chunks_deleted}</span>}
          {facts.missing != null && <span>缺失 {facts.missing}</span>}
          {facts.orphan != null && <span>孤儿 {facts.orphan}</span>}
          {run.execution_device && <span>{deviceLabel(run.execution_device)}</span>}
          {duration !== "未知" && <span>用时 {duration}</span>}
        </div>
        {fallback && <p className="text-muted-foreground">{fallback}</p>}
        <TechnicalEvidence run={run} />
      </CardContent>
    </Card>
  );
}

export function SyncHistoryPanel({ runs, isLoading = false, error, onRetry }: SyncHistoryPanelProps) {
  if (isLoading) return <Card><CardContent className="p-4 text-sm text-muted-foreground">正在加载同步历史…</CardContent></Card>;
  if (error) {
    return (
      <Card><CardContent className="flex items-center gap-3 p-4 text-sm">
        <span>{error}</span>{onRetry && <Button size="sm" variant="outline" onClick={onRetry}>重试加载</Button>}
      </CardContent></Card>
    );
  }
  if (!runs || runs.items.length === 0) return <Card><CardContent className="p-4 text-sm text-muted-foreground">暂无同步记录</CardContent></Card>;

  return (
    <section className="space-y-3" aria-label="同步历史">
      <h3 className="text-base font-semibold">最近同步</h3>
      {runs.items.map((run) => <RunCard key={run.id} run={run} />)}
    </section>
  );
}
