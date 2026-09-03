import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  deviceLabel,
  progressPercent,
  shortCircuitSummary,
  stageLabel,
  stateLabel,
} from "@/lib/dataSourceObservability";
import type { SyncStatusItem } from "@/types/api";

export interface SyncStatusPanelProps {
  status: SyncStatusItem;
  onRetry?: () => void;
  technicalEvidence?: unknown;
}

function stateVariant(state: SyncStatusItem["state"]): "secondary" | "success" | "warning" | "destructive" | "outline" {
  if (state === "COMPLETED") return "success";
  if (state === "RUNNING" || state === "RECOVERING") return "warning";
  if (state === "FAILED" || state === "INTERRUPTED") return "destructive";
  if (state === "IDLE") return "outline";
  return "secondary";
}

function serialiseEvidence(evidence: unknown): string {
  try {
    return JSON.stringify(evidence, null, 2);
  } catch {
    return "无法序列化原始证据";
  }
}

export function SyncStatusPanel({ status, onRetry, technicalEvidence }: SyncStatusPanelProps) {
  const percent = progressPercent(status.stage_current, status.stage_total);
  const shortCircuit = shortCircuitSummary(status.counters);
  const hasTechnicalEvidence = status.request_id != null || status.run_id != null || status.error_summary || technicalEvidence !== undefined;
  const canRetry = status.state === "FAILED" || status.state === "INTERRUPTED";
  const counters = status.counters;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-base">当前同步</CardTitle>
        <Badge variant={stateVariant(status.state)}>{stateLabel(status.state)}</Badge>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-0 text-sm">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>当前阶段：<span>{stageLabel(status.stage)}</span></span>
          {percent !== null ? (
            <span>{status.stage_current}/{status.stage_total} · {percent}%</span>
          ) : status.stage_current != null ? (
            <span>已处理 {status.stage_current} 项</span>
          ) : (
            <span className="text-muted-foreground">进度待确认</span>
          )}
        </div>

        {shortCircuit && <p className="text-muted-foreground">{shortCircuit}</p>}

        <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
          {counters?.docs_total != null && <span>文档 {counters.docs_total}</span>}
          {counters?.docs_processed != null && <span>已处理文档 {counters.docs_processed}</span>}
          {counters?.chunks_written != null && <span>分块 {counters.chunks_written}</span>}
          {status.device && <span>执行设备：{deviceLabel(status.device)}</span>}
        </div>

        {canRetry && onRetry && <Button size="sm" variant="outline" onClick={onRetry}>重新同步</Button>}

        {hasTechnicalEvidence && (
          <details className="rounded-md border border-border p-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium text-foreground">技术证据</summary>
            <div className="mt-2 space-y-1 font-mono break-all">
              {status.run_id != null && <p>run_id: {status.run_id}</p>}
              {status.request_id != null && <p>request_id: {status.request_id}</p>}
              {status.error_summary && <p>{status.error_summary}</p>}
              {technicalEvidence !== undefined && <pre className="whitespace-pre-wrap">{serialiseEvidence(technicalEvidence)}</pre>}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
