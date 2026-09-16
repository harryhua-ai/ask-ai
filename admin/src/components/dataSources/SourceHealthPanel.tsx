import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { healthStateLabel, humanizeHealthEvidence, overallRollupExplanation } from "@/lib/dataSourceObservability";
import { relativeTime } from "@/lib/dataSourceOps";
import type { SyncHealthDimension, SyncHealthItem } from "@/types/api";

export interface SourceHealthPanelProps {
  /** W2 /sync-health 权威条目;后端未提供时如实呈现「暂无健康数据」。 */
  health?: SyncHealthItem;
}

/**
 * #11 Health Authority:本面板是 W2 `/sync-health` 的**直呈视图**。
 * state 徽章 = 后端词表本地化;evidence/as_of 的真值原样保留(人类化仅为呈现层,
 * 原文/精确时间收进 title);前端不做任何健康重判(无阈值派生、无状态覆盖、
 * 不从 /sync-status 注入 RECOVERING——恢复中由后端 overall/state 表达)。
 * #54 R3+R4:overall 徽章下的解释行 = 复述后端 _overall_health 文档化优先级,
 * 消除「健康 vs 降级/未知」的表面矛盾;R6:freshness 证据以可理解单位表达
 * 「最近成功 + 允许阈值」;R5:as_of 主呈现人类化,ISO 收进 title。
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
  const unavailable =
    label === "知识可用性" &&
    ["unknown", "insufficient_data"].includes(dimension.state);
  // #54 R6:仅已知权威 freshness 格式本地化;未知透传;原文整串收进 title
  const evidence = humanizeHealthEvidence(dimension);
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="font-medium">{label}</h4>
        <Badge variant={healthVariant(dimension.state)}>{healthStateLabel(dimension.state)}</Badge>
      </div>
      {label === "知识可用性" && (
        <p className="mb-2 text-xs text-muted-foreground">以权威在服状态为准；没有分母时不计算覆盖率。</p>
      )}
      {label === "检索/索引一致性" && (
        <p className="mb-2 text-xs text-muted-foreground">PG 预期 chunk 与向量/索引实际值。</p>
      )}
      {/* 覆盖分母缺失时只呈现诚实不可评估,不从文档数/向量数自行计算百分比。 */}
      {unavailable ? (
        <p className="text-sm font-medium text-muted-foreground">暂不可评估</p>
      ) : dimension.evidence ? (
        <p
          className="text-sm text-muted-foreground"
          title={evidence.humanized ? dimension.evidence : undefined}
        >
          {evidence.text}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">证据不足</p>
      )}
      {/* #54 R5:主呈现 = 相对时间;原样 ISO 收进 title(技术核证仍可得)。 */}
      {dimension.as_of && (
        <p className="mt-2 text-xs text-muted-foreground" title={dimension.as_of}>
          截至 {relativeTime(dimension.as_of) ?? dimension.as_of}
        </p>
      )}
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
          <>
            {/* #54 R3+R4:overall↔维度贡献解释(复述后端文档化优先级),次级样式,不占主位 */}
            <div className="mb-3 space-y-1">
              {overallRollupExplanation(health).map((line) => (
                <p key={line} className="text-xs text-muted-foreground">
                  {line}
                </p>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
              <DimensionCard label="连接状态" dimension={health.connectivity} />
              {/* #21:sync 维是 30 天历史窗口成功率(参考信号),显式标注历史,
                  避免其 critical 态被读成当前严重度;当前态维保持主位不动。 */}
              <DimensionCard label="同步可靠性（历史30天）" dimension={health.sync} />
              <DimensionCard label="知识可用性" dimension={health.coverage} />
              <DimensionCard label="数据新鲜度" dimension={health.freshness} />
              <DimensionCard label="检索/索引一致性" dimension={health.consistency} />
              {/* #71:权威成员货币(持久真值;与一致性严格分维)。
                  旧客户端缓存 / 历史响应可能缺该维,如实缺卡不崩。 */}
              {health.currency && <DimensionCard label="上游成员对账" dimension={health.currency} />}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">暂无健康数据(等待后端 /sync-health 提供)</p>
        )}
      </CardContent>
    </Card>
  );
}
