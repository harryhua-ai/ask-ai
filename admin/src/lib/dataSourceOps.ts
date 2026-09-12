/**
 * v1.6.3 B1(KB-OPS-V163-002)数据源运营呈现映射模块 — 唯一出处。
 *
 * 冻结纪律(合同 v163-b1-data-source-operations-contract):
 * - 操作者状态/原因/时间/周期全部是**后端权威值的呈现层投影**,不重判、
 *   不派生第二健康态、不伪造 cause/health/reason;
 * - 权威输入:documents 聚合投影(attention-summary)/ last_sync_*(/data-sources)
 *   / overall(/sync-health)/ sync_runs+sync_log / index_generations;
 * - 无证据 → 显式「待分类 / — / 后端无此记录」,绝不默认健康。
 */

import type { SyncRun } from "@/types/api";
import type { GenerationTruth } from "@/types/dataSourceWorkspace";

// --------------------------------------------------------------------------- //
// 后端权威投影类型(与 GET /data-sources/attention-summary 契约一致)
// --------------------------------------------------------------------------- //

export interface AttentionSummaryItem {
  source_id: string;
  ledger_total: number;
  current_count: number;
  serving_count: number;
  retired_count: number;
  attention_count: number;
  lifecycle_counts: Record<string, number>;
}

export interface AttentionSummaryResponse {
  items: AttentionSummaryItem[];
}

// --------------------------------------------------------------------------- //
// 人性化相对时间(#54:主时间人性化,精确时间由调用方以 title 次级保留)
// --------------------------------------------------------------------------- //

export function relativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const diffSeconds = Math.round((now.getTime() - t) / 1000);
  if (diffSeconds < 0) return "刚刚";
  if (diffSeconds < 60) return "刚刚";
  const minutes = Math.floor(diffSeconds / 60);
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}天前`;
  const months = Math.round(days / 30);
  if (months <= 2) return `${months}个月前`;
  // 超过两个月退回精确日期,避免失真
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// --------------------------------------------------------------------------- //
// 操作者状态(列表/详情 状态徽章;后端权威值 → 展示词表的呈现映射)
// --------------------------------------------------------------------------- //

export type OperatorTone =
  | "ok"
  | "attention"
  | "intermediate"
  | "unclassified"
  | "failed"
  | "disabled";

export interface OperatorState {
  key: string;
  label: string;
  tone: OperatorTone;
}

const OVERALL_INTERMEDIATE_LABELS: Record<string, string> = {
  RECOVERING: "恢复中",
  STALE: "过期",
  PARTIAL: "部分覆盖",
  DEGRADED: "降级",
};

export function operatorStateOf(input: {
  enabled: boolean;
  lastSyncStatus: string | null | undefined;
  attentionCount: number | null | undefined;
  syncHealthOverall: string | null | undefined;
  lifecycleState?: string | null;
}): OperatorState {
  const {
    enabled,
    lastSyncStatus,
    attentionCount,
    syncHealthOverall,
    lifecycleState,
  } = input;
  // 优先级:删除失败 > 禁用 > 同步失败 > 需处理 > 中间态 > 待分类 > 正常
  if (lifecycleState === "delete_failed") {
    return { key: "delete_failed", label: "删除失败", tone: "failed" };
  }
  if (!enabled) return { key: "disabled", label: "已禁用", tone: "disabled" };
  if (lastSyncStatus === "failed") {
    return { key: "sync_failed", label: "同步失败", tone: "failed" };
  }
  if ((attentionCount ?? 0) > 0 || syncHealthOverall === "ACTION_REQUIRED") {
    return { key: "attention", label: "需处理", tone: "attention" };
  }
  if (syncHealthOverall && OVERALL_INTERMEDIATE_LABELS[syncHealthOverall]) {
    return {
      key: syncHealthOverall,
      label: OVERALL_INTERMEDIATE_LABELS[syncHealthOverall],
      tone: "intermediate",
    };
  }
  if (
    syncHealthOverall === "EMPTY_UNEXPECTED" ||
    syncHealthOverall === "EMPTY_EXPECTED" ||
    syncHealthOverall === "INSUFFICIENT_DATA"
  ) {
    // 证据不足 → 待分类(KB-OPS-V163-002 §5.3:证据缺席不得推断)
    return { key: "unclassified", label: "待分类", tone: "unclassified" };
  }
  if (syncHealthOverall === "EXCLUDED") {
    return { key: "excluded", label: "已排除", tone: "disabled" };
  }
  // 至此:任一权威输入存在(最近同步结果 / 桶聚合 / 健康 rollup),
  // 且未落入上述任一异常分支 → 正常;
  // 完全无任何权威证据 → 待分类(绝不默认健康)。
  const hasAnyEvidence =
    lastSyncStatus != null || attentionCount != null || syncHealthOverall != null;
  if (!hasAnyEvidence) {
    return { key: "unclassified", label: "待分类", tone: "unclassified" };
  }
  return { key: "ok", label: "正常", tone: "ok" };
}

export function toneVariant(tone: OperatorTone): "success" | "warning" | "destructive" | "secondary" | "outline" {
  switch (tone) {
    case "ok":
      return "success";
    case "attention":
    case "failed":
      return "destructive";
    case "intermediate":
      return "warning";
    case "disabled":
      return "outline";
    default:
      return "secondary";
  }
}

// --------------------------------------------------------------------------- //
// 需处理原因摘要(banner/list;权威生命周期计数的逐类投影)
// --------------------------------------------------------------------------- //

export function attentionReasonClasses(
  lifecycleCounts: Record<string, number> | null | undefined,
  attentionCount: number,
): string[] {
  if (!attentionCount || attentionCount <= 0) return [];
  const counts = lifecycleCounts ?? {};
  const lines: string[] = [];
  const missing = counts.missing_candidate ?? 0;
  const discovered = counts.discovered ?? 0;
  if (missing > 0) {
    lines.push(`${missing} 项源内容缺失,处于缺席宽限期(仍由上一代继续服务)`);
  }
  if (discovered > 0) {
    lines.push(`${discovered} 项已发现但尚未灌入(无现行版本)`);
  }
  const suspended = attentionCount - missing - discovered;
  if (suspended > 0) {
    lines.push(`${suspended} 项现行版本缺失,无法证明在服`);
  }
  if (lines.length === 0) {
    lines.push(`${attentionCount} 项知识处于需要关注状态`);
  }
  return lines;
}

// --------------------------------------------------------------------------- //
// 同步周期人性化(sync_interval 原文兜底,不编造)
// --------------------------------------------------------------------------- //

export function humanizeInterval(value: string | null | undefined): string {
  if (!value) return "—";
  const m = value.match(/^(\d+)([hm])$/);
  if (!m) return value;
  const n = m[1];
  return m[2] === "h" ? `每 ${n} 小时` : `每 ${n} 分钟`;
}

// --------------------------------------------------------------------------- //
// 同步状态与活动时间线(panel 4;异常优先,常规无变更压缩;#56)
// --------------------------------------------------------------------------- //

export type ActivityTone = "red" | "amber" | "green" | "gray" | "info";

export interface ActivityEvent {
  kind: "run" | "generation" | "routine-group";
  tone: ActivityTone;
  title: string;
  timeIso: string | null;
  meta?: string[];
  run?: SyncRun;
  count?: number;
}

export interface SyncActivity {
  events: ActivityEvent[];
  routineGroup: { count: number; latestTimeIso: string | null } | null;
}

function runMeta(run: SyncRun): string[] {
  const meta: string[] = [];
  if (run.error_summary) meta.push(run.error_summary);
  if (run.sync_log?.error_detail) meta.push(run.sync_log.error_detail);
  if (run.triggered_by) meta.push(`触发方式:${run.triggered_by === "manual" ? "管理员" : run.triggered_by}`);
  return meta;
}

export function buildSyncActivity(
  runs: SyncRun[] | null | undefined,
  generations: GenerationTruth[] | null | undefined,
  now: Date = new Date(),
): SyncActivity {
  const events: ActivityEvent[] = [];
  const routineRuns: SyncRun[] = [];

  for (const run of runs ?? []) {
    const status = run.status?.toLowerCase();
    const logStatus = run.sync_log?.status;
    if (status === "failed") {
      events.push({
        kind: "run",
        tone: "red",
        title: "同步失败",
        timeIso: run.started_at ?? null,
        meta: runMeta(run),
        run,
      });
      continue;
    }
    if (status === "interrupted") {
      events.push({
        kind: "run",
        tone: "red",
        title: "同步中断",
        timeIso: run.started_at ?? null,
        meta: runMeta(run),
        run,
      });
      continue;
    }
    if (status === "running" || status === "recovering" || status === "queued" || status === "waiting" || status === "pending") {
      events.push({
        kind: "run",
        tone: "info",
        title: status === "recovering" ? "同步恢复中" : "同步进行中",
        timeIso: run.started_at ?? null,
        meta: runMeta(run),
        run,
      });
      continue;
    }
    if (status === "completed" || status === "success") {
      if (logStatus === "partial") {
        events.push({
          kind: "run",
          tone: "amber",
          title: "同步完成(部分成功)",
          timeIso: run.started_at ?? null,
          meta: runMeta(run),
          run,
        });
        continue;
      }
      const changed = (run.sync_log?.items_new ?? 0) > 0 || (run.sync_log?.items_deleted ?? 0) > 0;
      if (changed) {
        const meta: string[] = [];
        if ((run.sync_log?.items_new ?? 0) > 0) meta.push(`新增 ${run.sync_log?.items_new}`);
        if ((run.sync_log?.items_deleted ?? 0) > 0) meta.push(`删除 ${run.sync_log?.items_deleted}`);
        events.push({
          kind: "run",
          tone: "green",
          title: "同步完成",
          timeIso: run.started_at ?? null,
          meta: [...meta, ...runMeta(run)],
          run,
        });
        continue;
      }
      routineRuns.push(run);
    }
  }

  for (const gen of generations ?? []) {
    if (gen.status === "failed") {
      events.push({
        kind: "generation",
        tone: "red",
        title: `索引生成 #${gen.ordinal} 失败`,
        timeIso: gen.created_at,
        meta: gen.failure ? Object.entries(gen.failure).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`) : [],
      });
    } else if (gen.status === "ready" && gen.activated_at) {
      events.push({
        kind: "generation",
        tone: "gray",
        title: `索引生成 #${gen.ordinal} 已激活`,
        timeIso: gen.activated_at,
      });
    } else if (gen.status === "retired" && gen.retired_at) {
      events.push({
        kind: "generation",
        tone: "gray",
        title: `索引生成 #${gen.ordinal} 已退役`,
        timeIso: gen.retired_at,
      });
    }
  }

  let routineGroup: SyncActivity["routineGroup"] = null;
  if (routineRuns.length > 0) {
    const latest = routineRuns.reduce(
      (acc, r) => (r.started_at && (!acc || r.started_at > acc) ? r.started_at : acc),
      null as string | null,
    );
    routineGroup = { count: routineRuns.length, latestTimeIso: latest };
    events.push({
      kind: "routine-group",
      tone: "gray",
      title: `${routineRuns.length} 次常规同步(无变更)`,
      timeIso: latest,
      count: routineRuns.length,
      run: routineRuns[0],
    });
  }

  events.sort((a, b) => {
    const ta = a.timeIso ? new Date(a.timeIso).getTime() : now.getTime();
    const tb = b.timeIso ? new Date(b.timeIso).getTime() : now.getTime();
    return tb - ta;
  });

  return { events, routineGroup };
}

/** 最近一次成功同步(sync_log.status=success 的最近 run;无 → null)。 */
export function lastSuccessIso(runs: SyncRun[] | null | undefined): string | null {
  for (const run of runs ?? []) {
    if (run.sync_log?.status === "success" && run.started_at) return run.started_at;
  }
  return null;
}
