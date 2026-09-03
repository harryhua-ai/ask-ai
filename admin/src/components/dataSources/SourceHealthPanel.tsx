import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SourceHealthDimension, SyncState } from "@/types/api";

export interface SourceHealthPanelProps {
  connectivity: SourceHealthDimension;
  sync: SourceHealthDimension;
  coverage: SourceHealthDimension;
  freshness: SourceHealthDimension;
  consistency: SourceHealthDimension;
  activeState?: SyncState | null;
}

const healthLabels: Record<SourceHealthDimension["state"], string> = {
  HEALTHY: "健康",
  DEGRADED: "降级",
  CRITICAL: "严重",
  DISABLED: "已禁用",
  RECOVERING: "恢复中",
  UNKNOWN: "未知",
  INSUFFICIENT_DATA: "证据不足",
};

function healthVariant(state: SourceHealthDimension["state"]): "secondary" | "success" | "warning" | "destructive" | "outline" {
  if (state === "HEALTHY") return "success";
  if (state === "DEGRADED" || state === "RECOVERING") return "warning";
  if (state === "CRITICAL") return "destructive";
  if (state === "UNKNOWN" || state === "INSUFFICIENT_DATA") return "outline";
  return "secondary";
}

function withEvidenceState(dimension: SourceHealthDimension): SourceHealthDimension {
  return dimension.evidence ? dimension : { ...dimension, state: "INSUFFICIENT_DATA" };
}

function Evidence({ dimension, separateConsistencyFacts = false }: { dimension: SourceHealthDimension; separateConsistencyFacts?: boolean }) {
  if (!dimension.evidence) return <p className="text-sm text-muted-foreground">证据不足</p>;
  // 仅拆分纯「缺失/孤儿」事实；带后缀(如 "；校验失败")时整体呈现,
  // 避免把后缀吞进孤儿值(孤儿行出现 "3；校验失败" 的误读)。
  const facts = separateConsistencyFacts && dimension.evidence.match(/^缺失 (.+)，孤儿 ([^；]+)$/);
  if (facts) {
    return <div className="space-y-1 text-sm text-muted-foreground"><p>缺失 {facts[1]}</p><p>孤儿 {facts[2]}</p></div>;
  }
  return <p className="text-sm text-muted-foreground">{dimension.evidence}</p>;
}

function DimensionCard({ label, dimension, separateConsistencyFacts }: { label: string; dimension: SourceHealthDimension; separateConsistencyFacts?: boolean }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="font-medium">{label}</h4>
        <Badge variant={healthVariant(dimension.state)}>{healthLabels[dimension.state]}</Badge>
      </div>
      <Evidence dimension={dimension} separateConsistencyFacts={separateConsistencyFacts} />
      {dimension.as_of && <p className="mt-2 text-xs text-muted-foreground">截至 {dimension.as_of}</p>}
    </div>
  );
}

export function SourceHealthPanel({ connectivity, sync, coverage, freshness, consistency, activeState }: SourceHealthPanelProps) {
  const displayedSync = activeState === "RECOVERING" && sync.evidence
    ? { ...sync, state: "RECOVERING" as const }
    : withEvidenceState(sync);

  return (
    <Card>
      <CardHeader className="p-4"><CardTitle className="text-base">数据源健康</CardTitle></CardHeader>
      <CardContent className="grid gap-3 p-4 pt-0 sm:grid-cols-2 lg:grid-cols-5">
        <DimensionCard label="连接" dimension={withEvidenceState(connectivity)} />
        <DimensionCard label="同步" dimension={displayedSync} />
        <DimensionCard label="覆盖" dimension={withEvidenceState(coverage)} />
        <DimensionCard label="新鲜度" dimension={withEvidenceState(freshness)} />
        <DimensionCard label="一致性" dimension={withEvidenceState(consistency)} separateConsistencyFacts />
      </CardContent>
    </Card>
  );
}
