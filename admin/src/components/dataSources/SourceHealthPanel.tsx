import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { healthStateLabel } from "@/lib/dataSourceObservability";
import type { SyncHealthDimension, SyncHealthItem } from "@/types/api";

export interface SourceHealthPanelProps {
  /** W2 /sync-health 权威条目;后端未提供时如实呈现「暂无健康数据」。 */
  health?: SyncHealthItem;
}

/**
 * #11 Health Authority:本面板是 W2 `/sync-health` 的**直呈视图**。
 * state 徽章 = 后端词表本地化;evidence/as_of 原样展示;
 * 前端不做任何健康重判(无 regex 分类、无阈值派生、无状态覆盖、
 * 不从 /sync-status 注入 RECOVERING——恢复中由后端 overall/state 表达)。
 */

function healthVariant(state: string): "secondary" | "success" | "warning" | "destructive" | "outline" {
  // 仅配色映射(呈现层),不改状态语义
  if (["ok", "healthy", "fresh"].includes(state)) return "success";
  if (["degraded", "partial", "stale"].includes(state)) return "warning";
  if (["failed", "critical"].includes(state)) return "destructive";
  if (["unknown", "insufficient_data"].includes(state)) return "outline";
  return "secondary";
}

function overallVariant(state: string): "secondary" | "success" | "warning" | "destructive" | "outline" {
  if (state === "HEALTHY") return "success";
  if (["RECOVERING", "STALE", "PARTIAL", "DEGRADED"].includes(state)) return "warning";
  if (state === "ACTION_REQUIRED") return "destructive";
  if (["INSUFFICIENT_DATA", "EXCLUDED", "EMPTY_UNEXPECTED", "EMPTY_EXPECTED"].includes(state)) return "outline";
  return "secondary";
}

function DimensionCard({ label, dimension }: { label: string; dimension: SyncHealthDimension }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="font-medium">{label}</h4>
        <Badge variant={healthVariant(dimension.state)}>{healthStateLabel(dimension.state)}</Badge>
      </div>
      {/* evidence 原样直呈;为空时仅占位提示,不改写状态徽章 */}
      {dimension.evidence ? (
        <p className="text-sm text-muted-foreground">{dimension.evidence}</p>
      ) : (
        <p className="text-sm text-muted-foreground">证据不足</p>
      )}
      {dimension.as_of && <p className="mt-2 text-xs text-muted-foreground">截至 {dimension.as_of}</p>}
    </div>
  );
}

export function SourceHealthPanel({ health }: SourceHealthPanelProps) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-base">数据源健康</CardTitle>
        {health && (
          <Badge variant={overallVariant(health.overall)}>{healthStateLabel(health.overall)}</Badge>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-0">
        {health ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <DimensionCard label="连接" dimension={health.connectivity} />
            <DimensionCard label="同步" dimension={health.sync} />
            <DimensionCard label="覆盖" dimension={health.coverage} />
            <DimensionCard label="新鲜度" dimension={health.freshness} />
            <DimensionCard label="一致性" dimension={health.consistency} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">暂无健康数据(等待后端 /sync-health 提供)</p>
        )}
      </CardContent>
    </Card>
  );
}
