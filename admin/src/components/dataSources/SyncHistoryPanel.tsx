import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  deviceLabel,
  extractConsistencyFacts,
  fallbackLabel,
  formatDuration,
  stateLabel,
} from "@/lib/dataSourceObservability";
import type { SyncRun, SyncRunList } from "@/types/api";

export interface SyncHistoryPanelProps {
  runs: SyncRunList | undefined;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

function stateVariant(state: SyncRun["state"]): "secondary" | "success" | "warning" | "destructive" | "outline" {
  if (state === "COMPLETED") return "success";
  if (state === "RUNNING" || state === "RECOVERING") return "warning";
  if (state === "FAILED" || state === "INTERRUPTED") return "destructive";
  if (state === "IDLE") return "outline";
  return "secondary";
}

function TechnicalEvidence({ run }: { run: SyncRun }) {
  if (run.id == null && run.request_id == null && !run.error_summary) return null;
  return (
    <details className="rounded-md border border-border p-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium text-foreground">技术证据</summary>
      <div className="mt-2 space-y-1 font-mono break-all">
        <p>run_id: {run.id}</p>
        {run.request_id != null && <p>request_id: {run.request_id}</p>}
        {run.error_summary && <p>{run.error_summary}</p>}
      </div>
    </details>
  );
}

function RunCard({ run }: { run: SyncRun }) {
  const counters = run.counters;
  const facts = extractConsistencyFacts(run);
  const duration = formatDuration(run.started_at, run.finished_at);
  const fallback = fallbackLabel(run.fallback_reason);
  const documentSummary = counters?.docs_total != null
    ? `文档 ${counters.docs_total}`
    : counters?.docs_processed != null
      ? `已处理文档 ${counters.docs_processed}`
      : null;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-sm">同步记录</CardTitle>
        <Badge variant={stateVariant(run.state)}>{stateLabel(run.state)}</Badge>
      </CardHeader>
      <CardContent className="space-y-2 p-4 pt-0 text-sm">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
          {documentSummary && <span>{documentSummary}</span>}
          {counters?.chunks_written != null && <span>分块 {counters.chunks_written}</span>}
          {counters?.chunks_deleted != null && <span>已删除分块 {counters.chunks_deleted}</span>}
          {facts.missing != null && <span>缺失 {facts.missing}</span>}
          {facts.orphan != null && <span>孤儿 {facts.orphan}</span>}
          {run.device && <span>{deviceLabel(run.device)}</span>}
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
