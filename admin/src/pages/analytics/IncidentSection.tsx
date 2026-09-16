/**
 * Ownership: Integration(Wave 0B 落位)— 同步/索引/生成事件信号区。
 * S3(同步级 GET /sync-runs)/ S4(生成级 GET /tech/generation-events)
 * = §3.5 能力矩阵例外面(冻结:latest-N 终态信号流,非时间窗聚合;
 * Wave 1 任何轨不得借例外引入窗口参数/假联动)。行下钻 = /data-sources/{id}。
 *
 * #58 r5 GAP_ONLY(矩阵 A1 PARTIAL + A4 MISSING 最小边界):
 * - B1:失败行主行携带已取回权威字段的事实性 impact 短语
 *   (生成:影响 N 篇文档 / M 块构建产物;同步:第 k 次尝试 / 耗时 t 秒),
 *   纯呈现投影:零新端点/零重算,raw 错误串/failure JSON 仍只进折叠证据;
 * - B2:渲染层按 (sourceId, typeKey) 分组 —— 组头=最高严重度+最新时间+×N
 *   +组级下钻,组可展开,成员逐事件保留各自 evidence details 与独立 href;
 *   仅在已取回 latest-N 上聚合,不合并/丢弃事件;头部诚实计数
 *   「共 N 起 · 显示前 M 起」(数据源:payload total)。
 */

import { useState } from "react";
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

/** #58 B2:(sourceId, typeKey) 呈现分组(仅聚合已取回 latest-N,零事件丢弃)。 */
interface IncidentGroup {
  key: string;
  sourceId: string;
  typeKey: string;
  /** 成员最高严重度(组头视觉优先级)。 */
  severity: IncidentSeverity;
  /** 成员最新 eventAt(组头时间)。 */
  latestAt: string | null;
  items: IncidentRow[];
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
 *  #58 B2:同源同类重复事件分组为一行(×N),组展开后逐事件可审计;
 *  每行 react-router Link 下钻 /data-sources/{source_id}(encodeURIComponent)。 */
export function IncidentSection() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
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
  // #58 B2:分组后按「组最高严重度 + 组内最新时间」排序,组只占一个可见位,
  // 重复事件不再挤占其他源的可见位;截断诚实计数(共 N 起 · 显示前 M 起)
  const groups = groupIncidentRows(rows);
  const visibleGroups = groups.slice(0, 10);
  const visibleEvents = visibleGroups.reduce(
    (n, g) => n + g.items.length,
    0,
  );
  const totalKnown =
    (sync?.failed.total ?? 0) + (sync?.interrupted.total ?? 0) + (gen?.total ?? 0);

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

  const renderRow = (row: IncidentRow, member = false) => (
    <Link
      key={row.key}
      to={`/data-sources/${encodeURIComponent(row.sourceId)}`}
      data-incident-row
      data-incident-type={row.typeKey}
      data-severity={row.severity}
      data-source-id={row.sourceId}
      data-incident-member={member || undefined}
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
        <span
          data-incident-note
          className="flex-1 truncate text-[var(--t2)]"
        >
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
  );

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
        <div className="flex items-baseline gap-3">
          {/* #58 B2:诚实计数(权威 payload total;防 slice 截断静默挤占) */}
          {totalKnown > 0 && (
            <span
              data-incident-total
              className="text-[11px] text-[var(--t3)] tabular-nums"
            >
              {totalKnown > visibleEvents
                ? `共 ${totalKnown} 起 · 显示前 ${visibleEvents} 起`
                : `共 ${totalKnown} 起`}
            </span>
          )}
          <span className="text-[11px] text-[var(--t3)]">
            异常优先 · 点击行查看归属数据源 · 证据可展开
          </span>
        </div>
      </div>
      {visibleGroups.length === 0 ? (
        <div className="text-[12px] text-[var(--t3)]">
          无同步 / 索引 / 生成失败事件
        </div>
      ) : (
        <div className="space-y-1" data-incident-list>
          {visibleGroups.map((g) =>
            g.items.length === 1 ? (
              renderRow(g.items[0])
            ) : (
              <div
                key={g.key}
                data-incident-group
                data-incident-type={g.typeKey}
                data-severity={g.severity}
                data-source-id={g.sourceId}
                className="rounded border px-1 py-0.5"
                style={{ borderColor: "var(--bd)" }}
              >
                <Link
                  to={`/data-sources/${encodeURIComponent(g.sourceId)}`}
                  data-incident-row
                  data-incident-type={g.typeKey}
                  data-severity={g.severity}
                  data-source-id={g.sourceId}
                  data-group-size={g.items.length}
                  title="查看归属数据源详情"
                  className="flex items-center gap-2 rounded px-2 py-1.5 text-[13px] hover:bg-black/5"
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full shrink-0"
                    style={{ background: SEVERITY_COLOR[g.severity] }}
                  />
                  <span className="shrink-0">{g.items[0].typeLabel}</span>
                  <span className="shrink-0 text-[var(--t1)]">{g.sourceId}</span>
                  {/* ×N 徽章:重复事件的诚实聚合(不重复铺行) */}
                  <span
                    data-incident-group-count
                    className="shrink-0 rounded-full border px-1.5 text-[11px] text-[var(--t2)]"
                    style={{ borderColor: "var(--bd)" }}
                  >
                    ×{g.items.length}
                  </span>
                  <span className="flex-1" />
                  {g.latestAt && (
                    <span className="shrink-0 text-[11px] text-[var(--t3)] tabular-nums">
                      {new Date(g.latestAt).toLocaleString()}
                    </span>
                  )}
                  <button
                    type="button"
                    data-incident-group-toggle
                    className="shrink-0 rounded border px-1.5 py-0.5 text-[11px] text-[var(--acc)] hover:bg-black/5"
                    style={{ borderColor: "var(--bd)" }}
                    onClick={(e) => {
                      // 阻止 <a> 导航;组展开 = 成员逐事件证据与下钻(可审计性)
                      e.preventDefault();
                      e.stopPropagation();
                      setExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(g.key)) {
                          next.delete(g.key);
                        } else {
                          next.add(g.key);
                        }
                        return next;
                      });
                    }}
                  >
                    {expanded.has(g.key) ? "收起" : `展开 ${g.items.length} 起`}
                  </button>
                </Link>
                {expanded.has(g.key) && (
                  <div
                    data-incident-group-members
                    className="mt-1 space-y-1 border-l-2 pl-2 pb-1"
                    style={{ borderColor: "var(--bd)" }}
                  >
                    {g.items.map((row) => renderRow(row, true))}
                  </div>
                )}
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** #58 B2:(sourceId, typeKey) 分组。rows 已按严重度+时间排序,组代表 =
 *  成员最高严重度 + 最新时间;分组是呈现聚合,不产生新事件实体、
 *  不合并/丢弃任何事件(成员级证据完整保留)。 */
function groupIncidentRows(rows: IncidentRow[]): IncidentGroup[] {
  const byKey = new Map<string, IncidentGroup>();
  for (const r of rows) {
    const key = `${r.sourceId}::${r.typeKey}`;
    const g = byKey.get(key);
    if (g) {
      g.items.push(r);
      if (SEVERITY_RANK[r.severity] < SEVERITY_RANK[g.severity]) {
        g.severity = r.severity;
      }
      if (
        new Date(r.eventAt ?? 0).getTime() > new Date(g.latestAt ?? 0).getTime()
      ) {
        g.latestAt = r.eventAt;
      }
    } else {
      byKey.set(key, {
        key,
        sourceId: r.sourceId,
        typeKey: r.typeKey,
        severity: r.severity,
        latestAt: r.eventAt,
        items: [r],
      });
    }
  }
  const groups = Array.from(byKey.values());
  groups.sort((a, b) => {
    const rank = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
    if (rank !== 0) return rank;
    return (
      new Date(b.latestAt ?? 0).getTime() - new Date(a.latestAt ?? 0).getTime()
    );
  });
  return groups;
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
  // #58 B1:主行事实性 impact 短语(仅已取回权威字段;raw 错误串不入主行)
  const impactParts = [`第 ${r.attempt ?? 1} 次尝试`];
  if (r.duration_seconds != null) {
    impactParts.push(`耗时 ${r.duration_seconds}s`);
  }
  return {
    key: `sync-${r.id}`,
    sourceId: r.source_id,
    typeKey,
    typeLabel: syncIncidentTypeLabel(r.status),
    severity: syncIncidentSeverity(r.status),
    eventAt: r.started_at,
    operatorNote: impactParts.join(" · "),
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
  // #58 B1:failed 主行事实性 impact 短语(计数>0 才呈现,诚实缺省);
  // retired 仍用 reason_summary(常规生命周期撤出,非失败,行为不变)
  let operatorNote: string | null;
  if (isFailed) {
    const impactParts: string[] = [];
    if (e.doc_count > 0) impactParts.push(`影响 ${e.doc_count} 篇文档`);
    if (e.chunk_count > 0) impactParts.push(`${e.chunk_count} 块构建产物`);
    operatorNote = impactParts.length > 0 ? impactParts.join(" / ") : null;
  } else {
    operatorNote = e.reason_summary;
  }
  return {
    key: `generation-${e.generation_id}`,
    sourceId: e.source_id,
    typeKey: `generation_${e.status}`,
    typeLabel: generationEventTypeLabel(e.status),
    severity: generationEventSeverity(e.status),
    eventAt: e.event_at,
    // retired 的运营摘要是事实性描述可直接上主行;failed 的摘要可能含 raw
    // 错误串,只进证据区(#58 raw 不主导默认层级)
    operatorNote,
    evidenceLines: evidence,
  };
}
