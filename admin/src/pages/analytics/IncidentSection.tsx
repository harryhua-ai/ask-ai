/**
 * Ownership: Integration(Wave 0B 落位)— 同步/索引/生成事件信号区。
 * S3(同步级 GET /sync-runs)/ S4(生成级 GET /tech/generation-events)
 * = §3.5 能力矩阵例外面(冻结:latest-N 终态信号流,非时间窗聚合;
 * Wave 1 任何轨不得借例外引入窗口参数/假联动)。行下钻 = /data-sources/{id}。
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import LoadError from "@/components/LoadError";
import {
  fetchSyncIncidents,
  fetchGenerationEvents,
  type GenerationEventItem,
} from "@/lib/api/techInsight";
import {
  syncIncidentSeverity,
  syncIncidentTypeLabel,
  generationEventSeverity,
  generationEventTypeLabel,
  type IncidentSeverity,
} from "@/lib/generationStatus";

/** #58 事件行模型:运营可读主行 + raw 证据行内折叠;症状 → 源详情下钻。
 *  洞察页零源清单:行内只呈现事件事实(源归属/类型/时间/严重度),
 *  源的全部事实经链接进入 /data-sources/{source_id}(#50 FROZEN INTERFACE)。
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
export function IncidentSection() {
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
