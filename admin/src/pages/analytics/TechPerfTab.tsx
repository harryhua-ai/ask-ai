/**
 * Ownership: Track A — Wave 1(S1/S2 窗面接线,IF-7 单一共享分析窗状态):
 * - S1 /tech/performance:以页面壳传入的共享窗值请求,from/to 真实发送;
 *   all/任意窗以显式起止表达(禁依赖 range 未知名→静默 7d 回退);
 * - S2 /analytics/source-health:既有 days=30 硬编码 → 以共享窗解析后的
 *   from/to 请求(BC-2);摘要窗标签=响应窗 echo 权威(显式窗)或 days 回显;
 *   DSH-01 历史可靠性语义原样。
 * 其余面板(KPI 三卡/事件区/诊断三列/趋势行/数据源健康摘要挂载)=
 * Integration(Wave 0B)落位,零行为变化。
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import LoadError from "@/components/LoadError";
import KpiCard from "@/components/observability/KpiCard";
import DualTrendBar from "@/components/observability/DualTrendBar";
import DualStageBar from "@/components/observability/DualStageBar";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";
import NodeFlow from "@/components/observability/NodeFlow";
import ServiceHealthBanner from "@/components/observability/ServiceHealthBanner";
import { fetchTechPerformance, fetchSourceHealth } from "@/lib/api/techInsight";
import { resolveAnalysisWindow, windowLabel } from "@/lib/analysisWindow";
import { IncidentSection } from "./IncidentSection";
import { SourceHealthSummary } from "./SourceHealthSummary";

/** 阶段机器名 → 人类可读标签(§15:机器类型经 data-stage 保留)。 */
const STAGE_LABELS: Record<string, string> = {
  intent: "意图识别",
  rewrite: "查询改写",
  retrieve: "检索",
  rerank: "重排",
  generate: "生成",
  output: "输出",
};

// --------------------------------------------------------------------------- //
// 技术性能 Tab(#58:运营可读优先,raw 证据可展开,critical 优先)
// --------------------------------------------------------------------------- //

export default function TechPerfTab({ window: win }: { window: string }) {
  // S1:from/to 真实发送(fetch 内按 IF-7 词表解析;命名窗附 range 供基线等长语义)
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["tech-performance", win],
    queryFn: () => fetchTechPerformance(win),
  });

  // S2:既有 days=30 硬编码 → 绑定共享分析窗(BC-2 显式起止;响应窗字段=实际评估窗)
  const { data: healthData } = useQuery({
    queryKey: ["source-health", win],
    queryFn: () => {
      const w = resolveAnalysisWindow(win);
      return fetchSourceHealth({ from: w.fromISO, to: w.toISO });
    },
  });

  if (isError && !data) return <LoadError error={error} onRetry={refetch} />;
  if (isLoading) return <div className="text-[var(--t2)]">加载中...</div>;
  if (!data) return null;

  const kpi = data.kpi;
  const hasData = kpi.trace_total > 0;
  // 健康横幅窗标签 = 所选共享窗(响应 kpi.window = 请求窗 echo,一致)
  const winLabelText = windowLabel(win);

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
      <ServiceHealthBanner health={data.health} windowLabel={winLabelText}>
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

      {/* #58 事件信号区:critical 优先,运营可读行 + 可展开 raw 证据 */}
      <IncidentSection />

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
        <SourceHealthSummary
          items={healthData.items}
          windowLabel={
            // 窗标签=权威 echo:显式窗请求回显 window(=所选共享窗);days 形态
            // 回显 days。不本地反推,不停留异窗。
            healthData.window ? windowLabel(win) : `近 ${healthData.days} 天`
          }
        />
      )}
    </div>
  );
}
