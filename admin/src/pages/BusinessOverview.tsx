import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import KpiCard from "@/components/observability/KpiCard";
import TimeFilter from "@/components/observability/TimeFilter";
import {
  fetchBusinessOverview,
  fetchBusinessOverviewRange,
} from "@/lib/api/businessOverview";

type TimeRange = { range?: string; from?: string; to?: string };

export default function BusinessOverview() {
  const [timeRange, setTimeRange] = useState<TimeRange>({ range: "7d" });

  const { data, isLoading } = useQuery({
    queryKey: ["business-overview", timeRange],
    queryFn: () => {
      if (timeRange.from && timeRange.to) {
        return fetchBusinessOverviewRange(timeRange.from, timeRange.to);
      }
      return fetchBusinessOverview(timeRange.range ?? "7d");
    },
  });

  return (
    <div className="space-y-6 p-4" style={{ background: "var(--bg)", minHeight: "100%" }}>
      {/* 标题 + 时间筛选 */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--t1)]">业务概览</h1>
        <TimeFilter onChange={setTimeRange} />
      </div>

      {isLoading && <div className="text-[var(--t2)]">加载中...</div>}

      {data && (
        <>
          {/* 服务总览 KPI 行 */}
          <div className="grid grid-cols-4 gap-4">
            <KpiCard label="总服务客户" value={data.service.total} />
            <KpiCard label="销售咨询" value={data.service.intent_dist.commercial} />
            <KpiCard
              label="有效线索"
              value={data.leads.valid}
              baseline={`潜在 ${data.leads.potential}`}
            />
            <KpiCard
              label="满意度"
              value={data.service.satisfaction}
              unit="%"
              alarm={data.service.satisfaction < 80}
            />
          </div>

          {/* 三意图分布 */}
          <div
            className="rounded-lg border p-4"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
          >
            <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
              意图分布
            </h2>
            <div className="flex gap-6">
              {(["commercial", "product", "support", "off_topic"] as const).map(
                (intent) => (
                  <div key={intent} className="text-center">
                    <div className="text-2xl font-semibold text-[var(--t1)]">
                      {data.service.intent_dist[intent]}
                    </div>
                    <div className="text-[12px] text-[var(--t2)]">
                      {INTENT_LABELS[intent]}
                    </div>
                  </div>
                ),
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* 销售线索 */}
            <div
              className="rounded-lg border p-4"
              style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-[14px] font-medium text-[var(--t1)]">
                  销售线索
                </h2>
                <Link
                  to="/conversations?intent=commercial"
                  className="text-[12px] text-[var(--acc)] hover:underline"
                >
                  查看销售对话
                </Link>
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-[13px]">
                  <span className="text-[var(--t2)]">有效线索</span>
                  <span className="font-medium text-[var(--t1)]">
                    {data.leads.valid}
                  </span>
                </div>
                <div className="flex justify-between text-[13px]">
                  <span className="text-[var(--t2)]">潜在客户</span>
                  <span className="font-medium text-[var(--t1)]">
                    {data.leads.potential}
                  </span>
                </div>
                {data.leads.hot_products.length > 0 && (
                  <div className="pt-2">
                    <div className="text-[12px] text-[var(--t3)] mb-1">
                      热门产品
                    </div>
                    {data.leads.hot_products.map((p) => (
                      <div
                        key={p.name}
                        className="flex justify-between text-[13px]"
                      >
                        <span>{p.name}</span>
                        <span className="text-[var(--t2)]">{p.count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* 场景应用 */}
            <div
              className="rounded-lg border p-4"
              style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            >
              <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
                场景应用
              </h2>
              {data.scenes.length > 0 ? (
                <div className="space-y-2">
                  {data.scenes.slice(0, 5).map((s) => (
                    <div
                      key={s.label}
                      className="flex justify-between text-[13px]"
                    >
                      <span>{s.label}</span>
                      <span className="text-[var(--t2)]">
                        {s.count}（{s.pct}%）
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[12px] text-[var(--t3)]">
                  暂无数据，请先运行业务信号提取
                </div>
              )}
            </div>

            {/* 产品需求 */}
            <div
              className="rounded-lg border p-4"
              style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            >
              <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
                产品需求
              </h2>
              {data.requirements.length > 0 ? (
                <div className="space-y-2">
                  {data.requirements.slice(0, 5).map((r) => (
                    <div
                      key={r.label}
                      className="flex justify-between text-[13px]"
                    >
                      <span>{r.label}</span>
                      <span className="text-[var(--t2)]">
                        {r.count}（{r.pct}%）
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[12px] text-[var(--t3)]">
                  暂无数据，请先运行业务信号提取
                </div>
              )}
            </div>

            {/* 热门问题 */}
            <div
              className="rounded-lg border p-4"
              style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-[14px] font-medium text-[var(--t1)]">
                  热门问题
                </h2>
                <Link
                  to="/conversations"
                  className="text-[12px] text-[var(--acc)] hover:underline"
                >
                  查看全部
                </Link>
              </div>
              {data.top_questions.length > 0 ? (
                <div className="space-y-1">
                  {data.top_questions.slice(0, 5).map((q, i) => (
                    <div
                      key={i}
                      className="flex justify-between text-[13px]"
                    >
                      <span className="truncate max-w-[200px]">{q.question}</span>
                      <span className="text-[var(--t2)]">{q.count}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[12px] text-[var(--t3)]">暂无数据</div>
              )}
            </div>
          </div>

          {/* 地域分布 */}
          <div
            className="rounded-lg border p-4"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
          >
            <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
              地域分布
            </h2>
            {data.geo.length > 0 ? (
              <div className="space-y-1">
                {data.geo.map((g) => (
                  <div
                    key={g.name}
                    className="flex justify-between text-[13px]"
                  >
                    <span>{g.name}</span>
                    <span className="text-[var(--t2)]">{g.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[12px] text-[var(--t3)]">{data.geo_note}</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const INTENT_LABELS: Record<string, string> = {
  commercial: "商务咨询",
  product: "产品咨询",
  support: "技术支持",
  off_topic: "无关闲聊",
};
