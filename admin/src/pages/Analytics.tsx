import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import KpiCard from "@/components/observability/KpiCard";
import TrendChart from "@/components/observability/TrendChart";
import TimeFilter from "@/components/observability/TimeFilter";
import { fetchTechPerformance, fetchCoverageGaps } from "@/lib/api/techInsight";
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
        />
        <KpiCard
          label="异常率"
          value={Math.round(data.kpi.anomaly_rate * 100)}
          unit="%"
          alarm={data.kpi.anomaly_rate > 0.1}
        />
        <KpiCard
          label="重试率"
          value={Math.round(data.kpi.retry_rate * 100)}
          unit="%"
        />
        <KpiCard
          label="失败率"
          value={Math.round(data.kpi.fail_rate * 100)}
          unit="%"
          alarm={data.kpi.fail_rate > 0.05}
        />
      </div>

      {/* P50/P95 趋势 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          P50/P95 趋势
        </h2>
        <TrendChart data={data.trends} baseline={3000} />
      </div>

      {/* 阶段表 */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          阶段 P50/P95（超标标橙）
        </h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>阶段</TableHead>
              <TableHead>P50 (ms)</TableHead>
              <TableHead>P95 (ms)</TableHead>
              <TableHead>正常上限</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(data.stages).map(([stage, s]) => {
              const over = s.p95 > s.normal_max;
              return (
                <TableRow key={stage}>
                  <TableCell
                    data-over={over}
                    className={over ? "text-[var(--warn)] font-medium" : ""}
                  >
                    {stage}
                  </TableCell>
                  <TableCell>{s.p50.toLocaleString()}</TableCell>
                  <TableCell>{s.p95.toLocaleString()}</TableCell>
                  <TableCell className="text-[var(--t2)]">
                    {s.normal_max.toLocaleString()}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* 异常分布 */}
      {data.anomalies.length > 0 && (
        <div
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            异常分布
          </h2>
          <div className="space-y-1">
            {data.anomalies.map((a, i) => (
              <div
                key={i}
                className="flex justify-between text-[13px]"
              >
                <span>{a.type}</span>
                <span className="text-[var(--t2)]">{a.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 降级链路 */}
      {data.degradations.length > 0 && (
        <div
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            降级链路
          </h2>
          <div className="space-y-2">
            {data.degradations.map((d, i) => (
              <div key={i} className="text-[13px]">
                <span className="text-[var(--warn)]">{d.from}</span>
                {" → "}
                <span className="text-[var(--t1)]">{d.to}</span>
                <span className="text-[var(--t3)] ml-2">({d.reason})</span>
              </div>
            ))}
          </div>
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

  return (
    <div className="space-y-4">
      {/* 澄清漏斗(暂无数据) */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          澄清漏斗
        </h2>
        <div className="text-[12px] text-[var(--t3)]">暂无数据（待接入）</div>
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
