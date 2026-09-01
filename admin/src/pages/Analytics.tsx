import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import KpiCard from "@/components/observability/KpiCard";
import DualTrendBar from "@/components/observability/DualTrendBar";
import DualStageBar from "@/components/observability/DualStageBar";
import GapTypeBadge from "@/components/observability/GapTypeBadge";
import TimeFilter from "@/components/observability/TimeFilter";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";
import NodeFlow from "@/components/observability/NodeFlow";
import ServiceHealthBanner from "@/components/observability/ServiceHealthBanner";
import {
  fetchTechPerformance,
  fetchCoverageGaps,
  fetchGapTrends,
  fetchSourceHealth,
} from "@/lib/api/techInsight";
import type { TechKpi } from "@/lib/api/techInsight";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

type Tab = "tech" | "gaps";

const RANGE_LABELS: Record<string, string> = {
  today: "今日",
  "7d": "近 7 天",
  "30d": "近 30 天",
};

/** 阶段机器名 → 人类可读标签(§15:机器类型经 data-stage 保留)。 */
const STAGE_LABELS: Record<string, string> = {
  intent: "意图识别",
  rewrite: "查询改写",
  retrieve: "检索",
  rerank: "重排",
  generate: "生成",
  output: "输出",
};

function windowLabel(kpi: TechKpi): string {
  return RANGE_LABELS[rangeOf(kpi)] ?? kpi.window.from.slice(0, 10);
}

function rangeOf(kpi: TechKpi): string {
  const days =
    (new Date(kpi.window.to).getTime() - new Date(kpi.window.from).getTime()) /
    86400000;
  if (days <= 1.5) return "today";
  if (days <= 8) return "7d";
  return "30d";
}

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("tech");
  const [range, setRange] = useState<string>("7d");

  return (
    <div className="space-y-6 p-4" style={{ background: "var(--bg)", minHeight: "100%" }}>
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--t1)]">技术洞察</h1>
        <TimeFilter onChange={(c) => setRange(c.range ?? range)} />
      </div>

      <div className="flex gap-2">
        <Button
          variant={tab === "tech" ? "default" : "outline"}
          onClick={() => setTab("tech")}
        >
          技术性能
        </Button>
        <Button
          variant={tab === "gaps" ? "default" : "outline"}
          onClick={() => setTab("gaps")}
        >
          知识缺口
        </Button>
      </div>

      {tab === "tech" && <TechPerfTab range={range} />}
      {tab === "gaps" && <KnowledgeGapsTab />}
    </div>
  );
}

function TechPerfTab({ range }: { range: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["tech-performance", range],
    queryFn: () => fetchTechPerformance(range),
  });

  const { data: healthData } = useQuery({
    queryKey: ["source-health"],
    queryFn: () => fetchSourceHealth(30),
  });

  if (isLoading) return <div className="text-[var(--t2)]">加载中...</div>;
  if (!data) return null;

  const kpi = data.kpi;
  const hasData = kpi.trace_total > 0;

  // 主导瓶颈:超阈值 trace 数最多的阶段(仅在有超阈值证据时呈现)
  const dominant = Object.entries(data.stages)
    .filter(([, s]) => s.over_count > 0)
    .sort((a, b) => b[1].over_count - a[1].over_count)[0];

  const baselineLabel =
    kpi.baseline_source === "previous_window"
      ? `基线 ${kpi.baseline.toLocaleString()}ms(上一周期 P95)`
      : `无上一周期数据,基线 ${kpi.baseline.toLocaleString()}ms = 本窗 P50(诊断参考,非历史对比)`;

  return (
    <div className="space-y-6">
      {/* PRIMARY:服务健康横幅(后端确定性推导,前端不做二次推断) */}
      <ServiceHealthBanner health={data.health} windowLabel={windowLabel(kpi)}>
        {kpi.fail_count > 0 && (
          <Link
            to="/conversations?failure=true"
            data-action="inspect-failures"
            className="rounded-md px-3 py-1.5 text-[13px] font-medium text-center"
            style={{ background: "var(--err)", color: "#fff" }}
          >
            查看失败对话 →
          </Link>
        )}
        {hasData && (kpi.anomaly_count > 0 || kpi.fail_count > 0) && (
          <div className="max-w-[190px] text-right">
            <Link
              to="/conversations"
              data-action="inspect-window"
              className="text-[12px] text-[var(--acc)] hover:underline"
            >
              在对话审查中排查 →
            </Link>
            <div className="text-[10px] text-[var(--t3)] mt-0.5">
              异常类型过滤暂不支持,可按时间窗检索
            </div>
          </div>
        )}
      </ServiceHealthBanner>

      {/* SECONDARY:关键信号三卡(分子/分母 + 语义说明,无裸百分比) */}
      <div className="grid grid-cols-3 gap-4" data-signal-cards>
        <KpiCard
          label="真实失败"
          value={hasData ? Math.round(kpi.fail_rate * 100) : null}
          unit="%"
          tone={kpi.fail_count > 0 ? "critical" : "neutral"}
          footnote={
            hasData
              ? `${kpi.fail_count} / ${kpi.trace_total} 条 trace · 生成失败,用户收到错误提示`
              : "无 trace 数据"
          }
        />
        <KpiCard
          label="诊断异常"
          value={hasData ? Math.round(kpi.anomaly_rate * 100) : null}
          unit="%"
          tone={kpi.anomaly_rate > 0.1 ? "warning" : "neutral"}
          footnote={
            hasData
              ? `${kpi.anomaly_count} / ${kpi.trace_total} 条 · 超性能阈值或含错误,≠服务失败`
              : "无 trace 数据"
          }
        />
        <KpiCard
          label="降级恢复"
          value={hasData ? Math.round(kpi.recovered_rate * 100) : null}
          unit="%"
          tone="neutral"
          footnote={
            hasData
              ? `${kpi.recovered_count} / ${kpi.trace_total} 条 · 性能降级但已恢复,用户仍获回答`
              : "无 trace 数据"
          }
        />
      </div>

      {/* trace 覆盖提示 */}
      {data.trace_coverage_from && (
        <div className="text-[12px] text-[var(--t3)]">
          Trace 数据自 {new Date(data.trace_coverage_from).toLocaleDateString()} 起
        </div>
      )}

      {/* DIAGNOSTIC:慢在哪 / 什么异常 / 降级到什么 */}
      <div data-tech-grid3 className="grid grid-cols-3 gap-4">
        {/* 瓶颈在哪:阶段表 + 主导瓶颈高亮 */}
        <div
          data-col="slow"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <div className="flex items-baseline justify-between mb-1">
            <h2 className="text-[14px] font-medium text-[var(--t1)]">瓶颈在哪</h2>
            <span className="text-[12px] text-[var(--t2)] tabular-nums">
              P95 {kpi.p95_ms.toLocaleString()}ms
            </span>
          </div>
          <div className="text-[11px] text-[var(--t3)] mb-3">{baselineLabel}</div>
          {dominant && (
            <div
              data-dominant-stage
              className="mb-2 rounded px-2 py-1 text-[12px]"
              style={{ background: "color-mix(in srgb, var(--warn) 12%, transparent)" }}
            >
              主导瓶颈:{STAGE_LABELS[dominant[0]] ?? dominant[0]}(
              {dominant[1].over_count} 条超阈值)
            </div>
          )}
          <div className="space-y-2">
            {Object.entries(data.stages).map(([stage, s]) => (
              <div
                key={stage}
                data-stage={stage}
                data-dominant={dominant ? dominant[0] === stage : false}
              >
                <DualStageBar
                  stage={STAGE_LABELS[stage] ?? stage}
                  p50={s.p50}
                  p95={s.p95}
                  normalMax={s.normal_max}
                  p50Pct={s.p50_pct ?? 0}
                  p95Pct={s.p95_pct ?? 0}
                />
              </div>
            ))}
          </div>
        </div>

        {/* 什么异常:语义着色(error=红 / slow=琥珀),不按计数着色 */}
        <div
          data-col="anomaly"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[14px] font-medium text-[var(--t1)]">什么异常</h2>
            <Link
              to="/conversations"
              className="text-[12px] text-[var(--acc)] hover:underline"
            >
              在对话审查中排查 →
            </Link>
          </div>
          {data.anomalies.length > 0 ? (
            <div className="space-y-2">
              {data.anomalies.map((a) => (
                <div
                  key={a.type}
                  data-anomaly-item={a.type}
                  data-severity={a.severity}
                  title={a.type}
                  className="flex items-center gap-2 text-[13px]"
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{
                      background:
                        a.severity === "error" ? "var(--err)" : "var(--warn)",
                    }}
                  />
                  <span className="flex-1">{a.label}</span>
                  <span className="text-[var(--t2)]">{a.count}</span>
                  {a.pct != null && (
                    <span className="text-[var(--t3)] text-[11px]">({a.pct}%)</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[12px] text-[var(--t3)]">无异常信号</div>
          )}
        </div>

        {/* 降级到什么:降级链路 NodeFlow */}
        <div
          data-col="degrade"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            降级到什么
          </h2>
          {data.degradations.length > 0 ? (
            <div className="space-y-2">
              {data.degradations.map((d, i) => (
                <div key={i} className="space-y-1">
                  <NodeFlow
                    nodes={[
                      { label: d.from, tone: "ok" },
                      { label: d.to, tone: "warn" },
                    ]}
                  />
                  <div className="text-[11px] text-[var(--t3)]">{d.reason}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[12px] text-[var(--t3)]">无降级</div>
          )}
        </div>
      </div>

      {/* DIAGNOSTIC:趋势 + 信号关系 */}
      <div className="grid grid-cols-5 gap-4">
        <div
          className="col-span-3 rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-[14px] font-medium text-[var(--t1)]">
              P50/P95 趋势
            </h2>
            <span className="text-[11px] text-[var(--t3)]">{baselineLabel}</span>
          </div>
          <DualTrendBar data={data.trends} baseline={data.kpi.baseline} />
        </div>

        <div
          className="col-span-2 rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            信号关系
          </h2>
          <ContainmentDiagram
            anomaly={data.kpi.anomaly_count}
            fail={data.kpi.fail_count}
            recovered={data.kpi.recovered_count}
          />
        </div>
      </div>

      {/* 数据源健康(DSH-02:主展示位在「数据源管理」,此处仅保留指向性摘要,
          不再呈现与数据源页重复竞争的健康表格) */}
      {healthData && healthData.items.length > 0 && (
        <SourceHealthSummary items={healthData.items} />
      )}
    </div>
  );
}

/** 数据源健康摘要:一行计数 + 跳转链接;逐源明细与操作见数据源管理页。 */
function SourceHealthSummary({
  items,
}: {
  items: { health: string }[];
}) {
  const counts = items.reduce<Record<string, number>>((acc, s) => {
    acc[s.health] = (acc[s.health] ?? 0) + 1;
    return acc;
  }, {});
  const parts: string[] = [];
  if (counts.healthy) parts.push(`正常 ${counts.healthy}`);
  if (counts.degraded) parts.push(`不稳定 ${counts.degraded}`);
  if (counts.critical) parts.push(`严重 ${counts.critical}`);
  if (counts.insufficient_data) parts.push(`样本不足 ${counts.insufficient_data}`);
  if (counts.disabled) parts.push(`已禁用 ${counts.disabled}`);

  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      data-source-health-summary
    >
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-[14px] font-medium text-[var(--t1)]">
          数据源健康(近 30 天)
        </h2>
        <Link
          to="/data-sources"
          className="text-[12px] text-[var(--acc)] hover:underline"
        >
          明细与操作 → 数据源管理
        </Link>
      </div>
      <div className="text-[13px] text-[var(--t2)]">
        {parts.length > 0 ? parts.join(" · ") : "暂无数据源"}
      </div>
    </div>
  );
}

function KnowledgeGapsTab() {
  const [status, setStatus] = useState<string | undefined>();
  const { data, isLoading } = useQuery({
    queryKey: ["coverage-gaps", status],
    queryFn: () => fetchCoverageGaps(status),
  });

  const { data: trendData } = useQuery({
    queryKey: ["gap-trends"],
    queryFn: () => fetchGapTrends(30),
  });

  const missSummary = data?.miss_type_summary ?? {};

  return (
    <div className="space-y-4">
      {/* 未回答率趋势 */}
      {trendData && trendData.trends.length > 0 && (
        <div
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            未回答率趋势(30 天)
          </h2>
          <div className="flex items-end gap-1 h-24">
            {trendData.trends.map((d) => {
              const maxRate = Math.max(
                ...trendData.trends.map((t) => t.unanswered_rate),
                0.01,
              );
              const h = (d.unanswered_rate / maxRate) * 100;
              return (
                <div
                  key={d.date}
                  className="flex-1 flex flex-col items-center justify-end"
                  title={`${d.date}: ${d.unanswered}/${d.total} (${Math.round(d.unanswered_rate * 100)}%)`}
                >
                  <div
                    className="w-full rounded-t"
                    style={{
                      height: `${h}%`,
                      background:
                        d.unanswered_rate > 0.3
                          ? "var(--err)"
                          : d.unanswered_rate > 0.1
                            ? "var(--warn)"
                            : "var(--ok)",
                      minHeight: d.total > 0 ? "2px" : "0",
                    }}
                  />
                  <div className="text-[9px] text-[var(--t3)] mt-1">{d.date}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 缺口类型分布 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          缺口类型分布
        </h2>
        {Object.keys(missSummary).length > 0 ? (
          <div className="flex gap-6">
            {Object.entries(missSummary).map(([type, count]) => (
              <div key={type} className="text-center">
                <div className="text-2xl font-semibold text-[var(--warn)]">
                  {count}
                </div>
                <div className="text-[12px] text-[var(--t2)]">{type}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[12px] text-[var(--t3)]">
            暂无缺口数据，请先执行聚类刷新
          </div>
        )}
      </div>

      {/* 覆盖缺口 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[14px] font-medium text-[var(--t1)]">覆盖缺口</h2>
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={status ?? ""}
            onChange={(e) => setStatus(e.target.value || undefined)}
          >
            <option value="">全部</option>
            <option value="open">未解决</option>
            <option value="resolved">已解决</option>
          </select>
        </div>
        {isLoading ? (
          <div className="text-[var(--t2)]">加载中...</div>
        ) : data && data.items.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>代表问题</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>数量</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((cluster) => (
                <TableRow key={cluster.id}>
                  <TableCell className="font-medium">
                    {cluster.representative_question}
                  </TableCell>
                  <TableCell>
                    {cluster.miss_type && <GapTypeBadge type={cluster.miss_type} />}
                  </TableCell>
                  <TableCell>{cluster.question_count}</TableCell>
                  <TableCell>
                    <Badge
                      variant={cluster.status === "resolved" ? "default" : "secondary"}
                    >
                      {cluster.status === "resolved" ? "已解决" : "未解决"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-center text-[var(--t3)] py-4">暂无数据</div>
        )}
      </div>
    </div>
  );
}
