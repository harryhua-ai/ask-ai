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
import {
  fetchTechPerformance,
  fetchCoverageGaps,
  fetchGapTrends,
  fetchSourceHealth,
} from "@/lib/api/techInsight";
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

  return (
    <div className="space-y-6">
      {/* KPI 4 卡 */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="P95 耗时"
          value={data.kpi.p95_ms}
          unit="ms"
          alarm={data.kpi.p95_ms > 5000}
          baseline={`基线 ${data.kpi.baseline}ms`}
          delta={
            data.kpi.comparison !== 0
              ? {
                  value: Math.round(data.kpi.comparison * 100),
                  dir: data.kpi.comparison > 0 ? "up" : "down",
                }
              : undefined
          }
        />
        <KpiCard
          label="异常率"
          value={Math.round(data.kpi.anomaly_rate * 100)}
          unit="%"
          alarm={data.kpi.anomaly_rate > 0.1}
          baseline={`${data.kpi.anomaly_count} 条`}
          delta={
            data.kpi.anomaly_delta !== 0
              ? {
                  value: Math.round(data.kpi.anomaly_delta * 1000) / 10,
                  dir: data.kpi.anomaly_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
        <KpiCard
          label="重试率"
          value={Math.round(data.kpi.retry_rate * 100)}
          unit="%"
          baseline={`${data.kpi.retry_count} 条`}
          delta={
            data.kpi.retry_delta !== 0
              ? {
                  value: Math.round(data.kpi.retry_delta * 1000) / 10,
                  dir: data.kpi.retry_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
        <KpiCard
          label="失败率"
          value={Math.round(data.kpi.fail_rate * 100)}
          unit="%"
          alarm={data.kpi.fail_rate > 0.05}
          baseline={`${data.kpi.fail_count} 条`}
          delta={
            data.kpi.fail_delta !== 0
              ? {
                  value: Math.round(data.kpi.fail_delta * 1000) / 10,
                  dir: data.kpi.fail_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
      </div>

      {/* trace 覆盖提示 */}
      {data.trace_coverage_from && (
        <div className="text-[12px] text-[var(--t3)]">
          Trace 数据自 {new Date(data.trace_coverage_from).toLocaleDateString()} 起
        </div>
      )}

      {/* P50/P95 趋势 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          P50/P95 趋势
        </h2>
        <DualTrendBar data={data.trends} baseline={data.kpi.baseline} />
      </div>

      {/* 异常 ⊃ 重试 ⊃ 失败 包含图 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          异常 / 重试 / 失败 包含关系
        </h2>
        <ContainmentDiagram
          anomaly={data.kpi.anomaly_count}
          retry={data.kpi.retry_count}
          fail={data.kpi.fail_count}
        />
      </div>

      {/* 技术性能三列:慢在哪 / 什么异常 / 降级到什么 */}
      <div data-tech-grid3 className="grid grid-cols-3 gap-4">
        {/* 慢在哪:阶段表 */}
        <div
          data-col="slow"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            慢在哪(阶段 P50/P95)
          </h2>
          <div className="space-y-2">
            {Object.entries(data.stages).map(([stage, s]) => (
              <DualStageBar
                key={stage}
                stage={stage}
                p50={s.p50}
                p95={s.p95}
                normalMax={s.normal_max}
                p50Pct={s.p50_pct ?? 0}
                p95Pct={s.p95_pct ?? 0}
              />
            ))}
          </div>
        </div>

        {/* 什么异常:异常分布(彩色圆点 + pct) */}
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
              查看对话
            </Link>
          </div>
          {data.anomalies.length > 0 ? (
            <div className="space-y-2">
              {data.anomalies.map((a, i) => {
                const dotColor =
                  a.count > 5 ? "var(--err)" : a.count > 2 ? "var(--warn)" : "var(--t3)";
                return (
                  <div key={i} className="flex items-center gap-2 text-[13px]">
                    <span
                      className="inline-block w-2 h-2 rounded-full"
                      style={{ background: dotColor }}
                      data-anomaly-dot={a.type}
                    />
                    <span className="flex-1">{a.type}</span>
                    <span className="text-[var(--t2)]">{a.count}</span>
                    {a.pct != null && (
                      <span className="text-[var(--t3)] text-[11px]">({a.pct}%)</span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-[12px] text-[var(--t3)]">无异常</div>
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

      {/* 数据源健康度 */}
      {healthData && healthData.items.length > 0 && (
        <div
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            数据源健康度
          </h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>数据源</TableHead>
                <TableHead>产品</TableHead>
                <TableHead>文档数</TableHead>
                <TableHead>同步成功率</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {healthData.items.map((s) => (
                <TableRow key={s.source_id}>
                  <TableCell className="font-medium">{s.source_id}</TableCell>
                  <TableCell>{s.product}</TableCell>
                  <TableCell>{s.doc_count}</TableCell>
                  <TableCell>
                    {Math.round(s.sync_success_rate * 100)}%
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        s.health === "healthy"
                          ? "default"
                          : s.health === "degraded"
                            ? "secondary"
                            : "destructive"
                      }
                    >
                      {s.health === "healthy"
                        ? "健康"
                        : s.health === "degraded"
                          ? "降级"
                          : "严重"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
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

      {/* 澄清漏斗占位(Phase 3 真实数据接入) */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          澄清漏斗
        </h2>
        <div className="text-[12px] text-[var(--t3)]">暂无数据(待接入)</div>
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
