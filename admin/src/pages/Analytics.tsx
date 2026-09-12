import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import LoadError from "@/components/LoadError";
import KpiCard from "@/components/observability/KpiCard";
import DualTrendBar from "@/components/observability/DualTrendBar";
import DualStageBar from "@/components/observability/DualStageBar";
import TimeFilter from "@/components/observability/TimeFilter";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";
import NodeFlow from "@/components/observability/NodeFlow";
import ServiceHealthBanner from "@/components/observability/ServiceHealthBanner";
import {
  fetchTechPerformance,
  fetchSourceHealth,
  fetchAnswerGaps,
  fetchGapConversations,
  fetchSyncIncidents,
  fetchGenerationEvents,
  type AnswerGapItem,
  type AnswerGapQuery,
  type GenerationEventItem,
} from "@/lib/api/techInsight";
import type { TechKpi } from "@/lib/api/techInsight";
import {
  syncIncidentSeverity,
  syncIncidentTypeLabel,
  generationEventSeverity,
  generationEventTypeLabel,
  type IncidentSeverity,
} from "@/lib/generationStatus";
import {
  gapCauseLabel,
  gapCauseTone,
  gapCauseConclusion,
  gapCauseAvailable,
  gapStatusLabel,
  GAP_CAUSE_OPTIONS,
  type GapCauseTone as CauseTone,
} from "@/lib/gapCause";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

// ===========================================================================
// v1.6.3 B2 — Technical Insights Convergence(KB-OPS-V163-002 / #57 #58 #59)
// 共享壳:技术性能 + 回答缺口 为同一 技术洞察 域的 sibling tabs。
// 回答缺口 = 只读操作者投影(GET /tech/answer-gaps),无 OBSERVING/导出/修复语义。
// ===========================================================================

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

/** 相对时间(权威 last_seen_at → 「N 小时前」;null → 证据不可用)。 */
function relTime(iso: string | null): string {
  if (!iso) return "证据不可用";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "证据不可用";
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}

// --------------------------------------------------------------------------- //
// 共享壳
// --------------------------------------------------------------------------- //

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("tech");
  const [range, setRange] = useState<string>("7d");

  return (
    <div
      className="space-y-5 p-4"
      style={{ background: "var(--bg)", minHeight: "100%" }}
    >
      <div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="text-[26px] font-bold text-[var(--t1)]">技术洞察</h1>
            <span className="text-[13px] text-[var(--t2)]">
              从真实用户对话中发现回答问题，定位原因，并形成知识补充和优化闭环。
            </span>
          </div>
          {tab === "tech" && (
            <TimeFilter onChange={(c) => setRange(c.range ?? range)} />
          )}
        </div>

        {/* 域内双 Tab:强选中态(蓝色下划线),不拆分顶层域(#57) */}
        <div
          role="tablist"
          data-shell-tabs
          className="mt-3 flex gap-6 border-b"
          style={{ borderColor: "var(--bd)" }}
        >
          <ShellTab active={tab === "tech"} onClick={() => setTab("tech")}>
            技术性能
          </ShellTab>
          <ShellTab active={tab === "gaps"} onClick={() => setTab("gaps")}>
            回答缺口
          </ShellTab>
        </div>
      </div>

      {tab === "tech" && <TechPerfTab range={range} />}
      {tab === "gaps" && <AnswerGapsTab />}
    </div>
  );
}

function ShellTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      role="tab"
      type="button"
      aria-selected={active}
      data-active={active ? "true" : "false"}
      onClick={onClick}
      className="-mb-px pb-2 text-[14px] border-b-2"
      style={{
        borderColor: active ? "var(--acc)" : "transparent",
        color: active ? "var(--acc)" : "var(--t2)",
        fontWeight: active ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------- //
// 技术性能 Tab(#58:运营可读优先,raw 证据可展开,critical 优先)
// --------------------------------------------------------------------------- //

function TechPerfTab({ range }: { range: string }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["tech-performance", range],
    queryFn: () => fetchTechPerformance(range),
  });

  const { data: healthData } = useQuery({
    queryKey: ["source-health"],
    queryFn: () => fetchSourceHealth(30),
  });

  if (isError && !data) return <LoadError error={error} onRetry={refetch} />;
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
        <SourceHealthSummary items={healthData.items} />
      )}
    </div>
  );
}

/** #58 事件行模型:运营可读主行 + raw 证据行内折叠;症状 → 源详情下钻。
 *  洞察页零源清单:行内只呈现事件事实(源归属/类型/时间/严重度),
 *  源的全部事实经链接进入 /data-sources/{id}(#50 FROZEN INTERFACE)。
 *  raw HTTP/内部 stage/attempt/failure JSON 一律收进 <details> 可展开证据,
 *  不主导默认层级(#58)。 */
interface IncidentRow {
  key: string;
  sourceId: string;
  /** 机器类型:sync_failed / sync_interrupted / generation_failed / generation_retired。 */
  typeKey: string;
  typeLabel: string;
  severity: IncidentSeverity;
  eventAt: string | null;
  /** 运营可读摘要(仅当确属事实性描述;raw 错误串只进证据区)。 */
  operatorNote: string | null;
  /** 可展开证据行(内部 stage/attempt/摘要等)。 */
  evidenceLines: string[];
}

const SEVERITY_COLOR: Record<IncidentSeverity, string> = {
  error: "var(--err)",
  warning: "var(--warn)",
  info: "var(--t3)",
};

const SEVERITY_RANK: Record<IncidentSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2,
};

/** 同步/索引/生成事件信号区(复用优先,#51/#58):
 *  - 同步级事件:既有 GET /sync-runs(failed/interrupted 跨源,零新增后端);
 *  - 生成级事件:只读 GET /tech/generation-events(failed/retired)。
 *  排序 = critical/abnormal 优先(error > warning > info),同级时间倒序;
 *  每行 react-router Link 下钻 /data-sources/{source_id}(encodeURIComponent)。 */
function IncidentSection() {
  const syncQuery = useQuery({
    queryKey: ["sync-incidents"],
    queryFn: () => fetchSyncIncidents(10),
  });
  const genQuery = useQuery({
    queryKey: ["generation-events"],
    queryFn: () => fetchGenerationEvents(10),
  });

  if (syncQuery.isLoading || genQuery.isLoading) {
    return (
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        data-incident-section
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)]">
          同步 / 索引 / 生成事件
        </h2>
        <div className="mt-1 text-[12px] text-[var(--t3)]">加载中...</div>
      </div>
    );
  }

  const rows: IncidentRow[] = [];
  const sync = syncQuery.data;
  if (sync) {
    for (const r of sync.failed.items) {
      rows.push(syncRunRow(r, "sync_failed"));
    }
    for (const r of sync.interrupted.items) {
      rows.push(syncRunRow(r, "sync_interrupted"));
    }
  }
  const gen = genQuery.data;
  if (gen) {
    for (const e of gen.items) {
      rows.push(generationEventRow(e));
    }
  }
  // #58:critical/abnormal 盖过 routine —— 严重度优先,同级最近在前
  rows.sort((a, b) => {
    const rank = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
    if (rank !== 0) return rank;
    return (
      new Date(b.eventAt ?? 0).getTime() - new Date(a.eventAt ?? 0).getTime()
    );
  });
  const visible = rows.slice(0, 10);

  if (!sync && !gen) {
    // 两路读面都失败:显式请求失败态(不渲染为空态)
    return (
      <div data-incident-section>
        <LoadError
          error={syncQuery.error ?? genQuery.error}
          onRetry={() => {
            void syncQuery.refetch();
            void genQuery.refetch();
          }}
        />
      </div>
    );
  }

  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      data-incident-section
    >
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-[14px] font-medium text-[var(--t1)]">
          同步 / 索引 / 生成事件
        </h2>
        <span className="text-[11px] text-[var(--t3)]">
          异常优先 · 点击行查看归属数据源 · 证据可展开
        </span>
      </div>
      {visible.length === 0 ? (
        <div className="text-[12px] text-[var(--t3)]">
          无同步 / 索引 / 生成失败事件
        </div>
      ) : (
        <div className="space-y-1" data-incident-list>
          {visible.map((row) => (
            <Link
              key={row.key}
              to={`/data-sources/${encodeURIComponent(row.sourceId)}`}
              data-incident-row
              data-incident-type={row.typeKey}
              data-severity={row.severity}
              data-source-id={row.sourceId}
              title="查看归属数据源详情"
              className="flex items-center gap-2 rounded px-2 py-1.5 text-[13px] hover:bg-black/5"
            >
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{ background: SEVERITY_COLOR[row.severity] }}
              />
              <span className="shrink-0">{row.typeLabel}</span>
              <span className="shrink-0 text-[var(--t1)]">{row.sourceId}</span>
              {row.operatorNote && (
                <span className="flex-1 truncate text-[var(--t2)]">
                  {row.operatorNote}
                </span>
              )}
              {!row.operatorNote && <span className="flex-1" />}
              {row.eventAt && (
                <span className="shrink-0 text-[11px] text-[var(--t3)] tabular-nums">
                  {new Date(row.eventAt).toLocaleString()}
                </span>
              )}
              {/* raw 内部证据:默认折叠,展开不触发导航(#58 渐进披露) */}
              <details
                data-incident-evidence
                className="shrink-0"
                onClick={(e) => {
                  // 阻止 <a> 导航与默认 toggle,手动翻转 open
                  e.preventDefault();
                  e.stopPropagation();
                  const d = e.currentTarget as HTMLDetailsElement;
                  d.open = !d.open;
                }}
              >
                <summary className="cursor-pointer list-none text-[11px] text-[var(--acc)]">
                  证据
                </summary>
                <div
                  className="mt-1 rounded border p-2 text-left text-[11px] text-[var(--t2)]"
                  style={{ borderColor: "var(--bd)", background: "var(--bg)" }}
                >
                  {row.evidenceLines.map((line, i) => (
                    <div key={i} className="whitespace-pre-wrap break-all">
                      {line}
                    </div>
                  ))}
                </div>
              </details>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function syncRunRow(
  r: {
    id: number | string;
    source_id: string;
    status: string;
    started_at: string | null;
    attempt?: number | null;
    stage?: string | null;
    error_summary?: string | null;
    fallback_reason?: string | null;
    sync_log?: { error_detail?: string | null } | null;
    duration_seconds?: number | null;
  },
  typeKey: "sync_failed" | "sync_interrupted",
): IncidentRow {
  const evidence = [
    `status: ${r.status}`,
    `attempt: ${r.attempt ?? 1}${r.stage ? ` · stage: ${r.stage}` : ""}`,
    r.duration_seconds != null ? `duration: ${r.duration_seconds}s` : null,
    r.error_summary ? `error: ${r.error_summary}` : null,
    !r.error_summary && r.fallback_reason ? `reason: ${r.fallback_reason}` : null,
    !r.error_summary && r.sync_log?.error_detail
      ? `detail: ${r.sync_log.error_detail}`
      : null,
  ].filter((x): x is string => Boolean(x));
  return {
    key: `sync-${r.id}`,
    sourceId: r.source_id,
    typeKey,
    typeLabel: syncIncidentTypeLabel(r.status),
    severity: syncIncidentSeverity(r.status),
    eventAt: r.started_at,
    operatorNote: null,
    evidenceLines: evidence,
  };
}

function generationEventRow(e: GenerationEventItem): IncidentRow {
  const evidence = [
    `generation_id: ${e.generation_id}`,
    `ordinal: ${e.ordinal} · status: ${e.status}`,
    `docs: ${e.doc_count} · chunks: ${e.chunk_count}`,
    e.reason_summary ? `summary: ${e.reason_summary}` : null,
    e.failure ? `failure: ${JSON.stringify(e.failure)}` : null,
  ].filter((x): x is string => Boolean(x));
  const isFailed = e.status === "failed";
  return {
    key: `generation-${e.generation_id}`,
    sourceId: e.source_id,
    typeKey: `generation_${e.status}`,
    typeLabel: generationEventTypeLabel(e.status),
    severity: generationEventSeverity(e.status),
    eventAt: e.event_at,
    // retired 的运营摘要是事实性描述可直接上主行;failed 的摘要可能含 raw
    // 错误串,只进证据区(#58 raw 不主导默认层级)
    operatorNote: isFailed ? null : e.reason_summary,
    evidenceLines: evidence,
  };
}

/** 数据源健康摘要:一行计数 + 跳转链接;逐源明细与操作见数据源管理页。
 *  #21:导出仅为测试 — 内容是历史窗口可靠性(signal=historical_reliability)。 */
export function SourceHealthSummary({
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
  if (counts.degraded) parts.push(`偏低 ${counts.degraded}`);
  // #21:此处是历史窗口可靠性(/analytics/source-health,signal=
  // historical_reliability),不是当前知识健康 —— 低成功率不称「严重」。
  if (counts.critical) parts.push(`历史低成功率 ${counts.critical}`);
  if (counts.insufficient_data) parts.push(`样本不足 ${counts.insufficient_data}`);
  if (counts.disabled) parts.push(`已禁用 ${counts.disabled}`);

  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      data-source-health-summary
      data-source-health-signal="historical_reliability"
    >
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-[14px] font-medium text-[var(--t1)]">
          数据源历史可靠性(近 30 天)
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

// --------------------------------------------------------------------------- //
// 回答缺口 Tab(#59:只读操作者队列 + 诊断侧板)
// --------------------------------------------------------------------------- //

const CAUSE_TONE_STYLE: Record<CauseTone, { bg: string; fg: string }> = {
  critical: { bg: "color-mix(in srgb, var(--err) 12%, transparent)", fg: "var(--err)" },
  warning: { bg: "color-mix(in srgb, var(--warn) 15%, transparent)", fg: "var(--warn)" },
  accent: { bg: "color-mix(in srgb, var(--acc) 12%, transparent)", fg: "var(--acc)" },
  neutral: { bg: "color-mix(in srgb, var(--t3) 15%, transparent)", fg: "var(--t2)" },
};

/** 原因徽章:data-gap-type 恒为权威机器值;运营词为忠实映射(lib/gapCause)。 */
function CauseBadge({ missType }: { missType?: string | null }) {
  const tone = gapCauseTone(missType);
  const style = CAUSE_TONE_STYLE[tone];
  return (
    <span
      data-gap-cause-badge
      data-gap-type={missType ?? "未分类"}
      className="inline-flex items-center whitespace-nowrap rounded px-2 py-0.5 text-[12px] font-medium"
      style={{ background: style.bg, color: style.fg }}
    >
      {gapCauseLabel(missType)}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const resolved = status === "resolved";
  return (
    <span
      data-gap-status
      data-status={status}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-[12px] font-medium"
      style={{
        background: resolved
          ? "color-mix(in srgb, var(--ok) 14%, transparent)"
          : "color-mix(in srgb, var(--err) 12%, transparent)",
        color: resolved ? "var(--ok)" : "var(--err)",
      }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: resolved ? "var(--ok)" : "var(--err)" }}
      />
      {gapStatusLabel(status)}
    </span>
  );
}

const PANEL_TABS = ["概览", "典型问题", "相关对话", "诊断详情", "历史记录"] as const;
type PanelTab = (typeof PANEL_TABS)[number];

function AnswerGapsTab() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | "open" | "resolved">("");
  const [cause, setCause] = useState("");
  const [window, setWindow] = useState<"7d" | "30d" | "all">("7d");
  const [order, setOrder] = useState<NonNullable<AnswerGapQuery["order"]>>("last_seen");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(10);

  const query: AnswerGapQuery = {
    status: status || undefined,
    cause: cause || undefined,
    q: search || undefined,
    window,
    order,
    dir: "desc",
    page,
    size,
  };
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["answer-gaps", query],
    queryFn: () => fetchAnswerGaps(query),
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);

  const items = data?.items ?? [];
  const active = items.find((it) => it.id === activeId) ?? null;

  function selectRow(id: string) {
    setActiveId(id);
    setSelected(new Set([id]));
  }

  function toggleCheck(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className="flex gap-4 items-start">
      <div className="min-w-0 flex-1 space-y-3">
        {/* 工具行:搜索(问题/主题、产品名称或关键词)+ 状态/原因/时间窗筛选 */}
        <div className="flex items-center gap-2 flex-wrap" data-gap-toolbar>
          <input
            data-gap-search
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="搜索问题/主题、产品名称或关键词（如：NE101、价格、安装）"
            className="h-9 min-w-[260px] flex-1 rounded-md border px-3 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          />
          <select
            data-filter-status
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as "" | "open" | "resolved");
              setPage(1);
            }}
            className="h-9 rounded-md border px-2 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          >
            <option value="">全部状态</option>
            <option value="open">需要处理</option>
            <option value="resolved">已解决</option>
          </select>
          <select
            data-filter-cause
            value={cause}
            onChange={(e) => {
              setCause(e.target.value);
              setPage(1);
            }}
            className="h-9 rounded-md border px-2 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          >
            <option value="">全部原因</option>
            {GAP_CAUSE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            data-filter-window
            value={window}
            onChange={(e) => {
              setWindow(e.target.value as "7d" | "30d" | "all");
              setPage(1);
            }}
            className="h-9 rounded-md border px-2 text-[13px]"
            style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
          >
            <option value="7d">过去 7 天</option>
            <option value="30d">过去 30 天</option>
            <option value="all">全部时间</option>
          </select>
        </div>

        {isError && !data ? (
          <LoadError error={error} onRetry={refetch} />
        ) : isLoading ? (
          <div className="text-[var(--t2)]">加载中...</div>
        ) : (
          <div
            className="rounded-lg border"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
            data-answer-gaps-queue
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead>问题 / 主题</TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    data-sort-key="questions"
                    onClick={() => setOrder("questions")}
                  >
                    {`相关提问${order === "questions" ? " ↕" : ""}`}
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    data-sort-key="impacted"
                    onClick={() => setOrder("impacted")}
                  >
                    {`影响回答${order === "impacted" ? " ↕" : ""}`}
                  </TableHead>
                  <TableHead>原因</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    data-sort-key="last_seen"
                    onClick={() => setOrder("last_seen")}
                  >
                    {`最近发生${order === "last_seen" ? " ↕" : ""}`}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <div className="py-6 text-center text-[13px] text-[var(--t3)]">
                        当前筛选条件下无答案缺口证据
                        {window !== "all" && "（可尝试扩大时间范围）"}
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((gap) => (
                    <TableRow
                      key={gap.id}
                      data-gap-row
                      data-gap-id={gap.id}
                      data-selected={selected.has(gap.id) ? "true" : "false"}
                      onClick={() => selectRow(gap.id)}
                      className="cursor-pointer"
                      style={
                        selected.has(gap.id)
                          ? {
                              background:
                                "color-mix(in srgb, var(--acc) 8%, transparent)",
                              boxShadow: `inset 3px 0 0 var(--acc)`,
                            }
                          : undefined
                      }
                    >
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          data-gap-check
                          checked={selected.has(gap.id)}
                          onChange={() => toggleCheck(gap.id)}
                          className="h-4 w-4 cursor-pointer"
                          style={{ accentColor: "var(--acc)" }}
                        />
                      </TableCell>
                      <TableCell>
                        <div
                          data-gap-question
                          className="text-[13px] font-semibold text-[var(--t1)]"
                        >
                          {gap.representative_question}
                        </div>
                        {gap.sample_questions.filter(
                          (s) => s !== gap.representative_question,
                        ).length > 0 && (
                          <div
                            data-gap-sample
                            className="mt-0.5 truncate text-[12px] text-[var(--t3)]"
                          >
                            {
                              gap.sample_questions.filter(
                                (s) => s !== gap.representative_question,
                              )[0]
                            }
                          </div>
                        )}
                      </TableCell>
                      <TableCell data-gap-questions className="tabular-nums">
                        {gap.question_count}
                      </TableCell>
                      <TableCell data-gap-impacted className="tabular-nums">
                        {gap.impacted_answer_count}
                      </TableCell>
                      <TableCell>
                        <CauseBadge missType={gap.miss_type} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={gap.status} />
                      </TableCell>
                      <TableCell data-gap-recency className="whitespace-nowrap text-[var(--t2)]">
                        {relTime(gap.last_seen_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            {/* 底部:已选择 N 项 + 分页 + 条/页 */}
            <div
              data-gap-pagination
              className="flex items-center justify-between border-t px-3 py-2 text-[12px] text-[var(--t2)]"
              style={{ borderColor: "var(--bd)" }}
            >
              <span data-selection-count>
                已选择 {selected.size} 项
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="rounded border px-2 py-1 disabled:opacity-40"
                  style={{ borderColor: "var(--bd)" }}
                >
                  &lt;
                </button>
                <span className="tabular-nums">
                  {page} / {Math.max(1, Math.ceil((data?.total ?? 0) / size))}
                </span>
                <button
                  type="button"
                  disabled={page >= Math.ceil((data?.total ?? 0) / size)}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border px-2 py-1 disabled:opacity-40"
                  style={{ borderColor: "var(--bd)" }}
                >
                  &gt;
                </button>
                <select
                  data-gap-page-size
                  value={size}
                  onChange={(e) => {
                    setSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="ml-2 rounded border px-2 py-1"
                  style={{ borderColor: "var(--bd)", background: "var(--panel)" }}
                >
                  <option value={10}>10 条/页</option>
                  <option value={20}>20 条/页</option>
                  <option value={50}>50 条/页</option>
                </select>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 诊断侧板:contextual,仅权威证据(#59 / §5.5) */}
      {active && <GapPanel gap={active} onClose={() => setActiveId(null)} />}
    </div>
  );
}

/** 诊断侧板。v1.6.3 边界(合同 Forbidden + §10):
 *  - 无 导出相关对话/CSV(新导出语义 NOT authorized);
 *  - 无 内容已补充，开始观察(OBSERVING/remediation 语义 NOT authorized);
 *  - 无 涉及 N 个用户(无权威用户聚合证据);
 *  - 相关数据源仅在后端存在权威 gap→source 关联时呈现(v1.6.3 无该关联 → 省略);
 *  - 诊断结论仅当权威原因分类存在,否则明确 证据不可用。 */
function GapPanel({ gap, onClose }: { gap: AnswerGapItem; onClose: () => void }) {
  const [tab, setTab] = useState<PanelTab>("概览");
  const hasCause = gapCauseAvailable(gap.miss_type);

  const convQuery = useQuery({
    queryKey: ["gap-conversations", gap.id],
    queryFn: () => fetchGapConversations(gap.id, 20),
    enabled: tab === "相关对话",
  });

  const typical = gap.sample_questions;
  const typicalPreview = typical.slice(0, 5);

  return (
    <div
      data-gap-panel
      className="w-[400px] shrink-0 rounded-lg border"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="border-b p-4" style={{ borderColor: "var(--bd)" }}>
        <div className="flex items-start justify-between gap-2">
          <h2 data-panel-title className="text-[16px] font-semibold text-[var(--t1)]">
            {gap.representative_question}
          </h2>
          <div className="flex shrink-0 items-center gap-2">
            <StatusBadge status={gap.status} />
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="text-[var(--t3)] hover:text-[var(--t1)]"
            >
              ✕
            </button>
          </div>
        </div>
        <div data-panel-stats className="mt-2 text-[12px] text-[var(--t2)]">
          {gap.question_count} 次相关提问 · {gap.impacted_answer_count} 次受影响回答
          <div className="mt-0.5 text-[var(--t3)]">
            最近发生:{relTime(gap.last_seen_at)}
          </div>
        </div>
        <div className="mt-3 flex gap-3 border-b" style={{ borderColor: "var(--bd)" }}>
          {PANEL_TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              data-panel-tab
              onClick={() => setTab(t)}
              className="-mb-px pb-1.5 text-[13px] border-b-2"
              style={{
                borderColor: tab === t ? "var(--acc)" : "transparent",
                color: tab === t ? "var(--acc)" : "var(--t2)",
                fontWeight: tab === t ? 600 : 400,
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-4 p-4">
        {tab === "概览" && (
          <>
            <section>
              <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">问题描述</h3>
              <p data-panel-description className="text-[13px] leading-6 text-[var(--t2)]">
                用户围绕「{gap.representative_question}」等主题多次提问,当前窗口内共
                {" "}{gap.question_count} 个相关提问、{gap.impacted_answer_count} 个受影响回答
                {gap.status === "resolved" ? ",已标记为已解决。" : "。"}
              </p>
            </section>

            <section
              data-panel-conclusion
              data-conclusion-kind={hasCause ? "authoritative" : "unavailable"}
              className="rounded-md p-3"
              style={{
                background: hasCause
                  ? "color-mix(in srgb, var(--err) 8%, transparent)"
                  : "color-mix(in srgb, var(--t3) 10%, transparent)",
              }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
                  style={{ background: hasCause ? "var(--err)" : "var(--t3)" }}
                >
                  !
                </span>
                <span className="text-[13px] font-medium text-[var(--t1)]">诊断结论</span>
                <CauseBadge missType={gap.miss_type} />
              </div>
              <p className="mt-2 text-[12px] leading-5 text-[var(--t2)]">
                {gapCauseConclusion(gap.miss_type)}
              </p>
            </section>

            <section>
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-medium text-[var(--t1)]">典型问题示例</h3>
                {typical.length > typicalPreview.length && (
                  <button
                    type="button"
                    data-panel-typical-all
                    onClick={() => setTab("典型问题")}
                    className="text-[12px] text-[var(--acc)] hover:underline"
                  >
                    查看全部 ({typical.length})
                  </button>
                )}
              </div>
              <ul data-panel-typical className="mt-1 space-y-1">
                {typicalPreview.length > 0 ? (
                  typicalPreview.map((q, i) => (
                    <li
                      key={i}
                      className="list-disc pl-4 text-[13px] text-[var(--t2)]"
                    >
                      {q}
                    </li>
                  ))
                ) : (
                  <li className="text-[12px] text-[var(--t3)]">无样例问句证据</li>
                )}
              </ul>
            </section>

            <section>
              <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">推荐操作</h3>
              <Link
                to={`/conversations?q=${encodeURIComponent(gap.representative_question)}`}
                data-action="inspect-gap"
                className="block rounded-md border p-3 hover:bg-black/5"
                style={{ borderColor: "var(--bd)" }}
              >
                <div className="text-[13px] font-medium text-[var(--acc)]">
                  查看相关对话 →
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--t3)]">
                  在对话审查中按该主题检索原始对话证据
                </div>
              </Link>
            </section>
          </>
        )}

        {tab === "典型问题" && (
          <section>
            <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">
              典型问题({typical.length})
            </h3>
            <ul className="space-y-1">
              {typical.length > 0 ? (
                typical.map((q, i) => (
                  <li key={i} className="list-disc pl-4 text-[13px] text-[var(--t2)]">
                    {q}
                  </li>
                ))
              ) : (
                <li className="text-[12px] text-[var(--t3)]">无样例问句证据</li>
              )}
            </ul>
          </section>
        )}

        {tab === "相关对话" && (
          <section data-panel-conversations>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[13px] font-medium text-[var(--t1)]">
                归属对话({convQuery.data?.total ?? "…"})
              </h3>
              <Link
                to={`/conversations?q=${encodeURIComponent(gap.representative_question)}`}
                data-action="inspect-gap"
                className="text-[12px] text-[var(--acc)] hover:underline"
              >
                在对话审查中查看 →
              </Link>
            </div>
            {convQuery.isLoading ? (
              <div className="text-[12px] text-[var(--t3)]">加载中...</div>
            ) : convQuery.isError ? (
              <div className="text-[12px] text-[var(--err)]">
                会话证据读取失败,可经上方入口在对话审查中检索
              </div>
            ) : (convQuery.data?.items.length ?? 0) === 0 ? (
              <div className="text-[12px] text-[var(--t3)]">无归属会话证据</div>
            ) : (
              <div className="space-y-2">
                {convQuery.data!.items.map((c) => (
                  <Link
                    key={c.id}
                    data-panel-conv-row
                    to={`/conversations?q=${encodeURIComponent(c.question)}`}
                    className="block rounded-md border p-2 hover:bg-black/5"
                    style={{ borderColor: "var(--bd)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] text-[var(--t1)]">
                        {c.question}
                      </span>
                      <span
                        className="shrink-0 rounded px-1.5 py-0.5 text-[11px]"
                        style={{
                          background: c.is_answered
                            ? "color-mix(in srgb, var(--ok) 14%, transparent)"
                            : "color-mix(in srgb, var(--err) 12%, transparent)",
                          color: c.is_answered ? "var(--ok)" : "var(--err)",
                        }}
                      >
                        {c.is_answered ? "已回答" : "未回答"}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-[var(--t3)]">
                      {relTime(c.created_at)}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "诊断详情" && (
          <section data-panel-diagnosis>
            <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">
              原因分类分布(权威)
            </h3>
            {Object.keys(gap.miss_type_breakdown).length > 0 ? (
              <ul className="space-y-1">
                {Object.entries(gap.miss_type_breakdown).map(([k, v]) => (
                  <li key={k} className="flex items-center gap-2 text-[13px] text-[var(--t2)]">
                    <span className="flex-1">{gapCauseLabel(k)}</span>
                    <span className="tabular-nums">{v}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-[12px] text-[var(--t3)]">无会话证据,分类不可用</div>
            )}
            <dl className="mt-3 space-y-1 text-[12px] text-[var(--t2)]">
              <div className="flex justify-between">
                <dt className="text-[var(--t3)]">聚类创建时间</dt>
                <dd className="tabular-nums">
                  {gap.created_at ? new Date(gap.created_at).toLocaleString() : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[var(--t3)]">统计周期</dt>
                <dd>
                  {gap.period_start
                    ? `${new Date(gap.period_start).toLocaleDateString()} ~ ${
                        gap.period_end
                          ? new Date(gap.period_end).toLocaleDateString()
                          : "至今"
                      }`
                    : "证据不可用"}
                </dd>
              </div>
            </dl>
          </section>
        )}

        {tab === "历史记录" && (
          <section data-panel-history>
            <div className="text-[12px] leading-5 text-[var(--t3)]">
              证据不可用:v1.6.3 暂无该缺口的权威历史记录(观察/流转)数据,
              系统不做推断。
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
