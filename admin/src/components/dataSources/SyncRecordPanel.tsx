import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { documentDeltaSummary } from "@/lib/syncDeltaPresentation";
import { formatSyncTime } from "@/lib/sourceEditorModel";
import { syncRunDisplayState, stateLabel } from "@/lib/dataSourceObservability";
import type { SyncRunList } from "@/types/api";

export interface SyncRecordPanelProps {
  runs: SyncRunList | undefined;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

const RESULT_LABELS: Record<string, string> = {
  success: "成功",
  partial: "部分成功",
  failed: "失败",
};

function resultVariant(status: string | null | undefined): "success" | "warning" | "destructive" | "outline" {
  if (status === "success") return "success";
  if (status === "partial") return "warning";
  if (status === "failed") return "destructive";
  return "outline";
}

export function SyncRecordPanel({ runs, isLoading = false, error, onRetry }: SyncRecordPanelProps) {
  if (isLoading) {
    return <Card><CardContent className="p-3 text-sm text-muted-foreground">正在加载同步记录…</CardContent></Card>;
  }
  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-3 text-sm">
          <span>{error}</span>
          {onRetry && <button type="button" className="underline" onClick={onRetry}>重试</button>}
        </CardContent>
      </Card>
    );
  }
  const recentRuns = runs?.items.slice(0, 3) ?? [];
  return (
    <Card>
      <CardHeader className="p-3 pb-2">
        <CardTitle className="text-sm">同步记录</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 p-3 pt-0">
        {recentRuns.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无同步记录</p>
        ) : (
          <ul className="space-y-2" aria-label="最近同步记录">
            {recentRuns.map((run) => {
              const displayState = syncRunDisplayState(run.status);
              const result = run.sync_log?.status;
              return (
                <li key={run.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b pb-2 last:border-b-0 last:pb-0">
                  <span className="font-mono text-xs text-muted-foreground">
                    {run.started_at ? formatSyncTime(run.started_at) : "时间未知"}
                  </span>
                  <Badge variant={resultVariant(result)}>
                    {result ? (RESULT_LABELS[result] ?? result) : stateLabel(displayState)}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {documentDeltaSummary(run.sync_log).join(" · ")}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-[11px] text-muted-foreground">列表仅展示最近 3 次；完整活动与技术证据请进入详情。</p>
      </CardContent>
    </Card>
  );
}
