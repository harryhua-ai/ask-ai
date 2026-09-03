import type {
  DataSource,
  SourceHealthDimension,
  SyncRun,
  SyncState,
  SyncStatusItem,
} from "@/types/api";
import type { SourceHealthItem } from "@/lib/api/techInsight";

const STATE_LABELS: Record<string, string> = {
  QUEUED: "排队中",
  WAITING: "等待执行",
  RUNNING: "同步中",
  RECOVERING: "恢复中",
  COMPLETED: "已完成",
  FAILED: "失败",
  INTERRUPTED: "已中断",
  IDLE: "空闲",
};

const STAGE_LABELS: Record<string, string> = {
  DISCOVER: "发现内容",
  SAFETY_FILTER: "安全过滤",
  FETCH: "抓取内容",
  PARSE: "解析内容",
  CHUNK: "切分文档",
  EMBED: "生成向量",
  INDEX: "写入索引",
  CONSISTENCY: "一致性校验",
  DONE: "完成",
};

export function stateLabel(state: string | null | undefined): string {
  return (state && STATE_LABELS[state]) ?? "未知状态";
}

export function syncRunDisplayState(status: string | null | undefined): SyncState | null {
  switch (status?.toLowerCase()) {
    case "pending":
    case "queued":
      return "QUEUED";
    case "waiting":
      return "WAITING";
    case "running":
      return "RUNNING";
    case "completed":
    case "success":
      return "COMPLETED";
    case "failed":
    case "error":
      return "FAILED";
    case "interrupted":
      return "INTERRUPTED";
    default:
      return null;
  }
}

export function stageLabel(stage: string | null | undefined): string {
  return (stage && STAGE_LABELS[stage]) ?? "未知阶段";
}

export function progressPercent(current: number | null | undefined, total: number | null | undefined): number | null {
  if (!Number.isFinite(current) || !Number.isFinite(total) || (total as number) <= 0) return null;
  return Math.round(((current as number) / (total as number)) * 100);
}

export function shortCircuitSummary(counters: SyncStatusItem["counters"]): string | null {
  if (counters?.docs_total === 0 && (counters.items_unchanged ?? 0) > 0) {
    return "无上游变更 · 已检查 · 跳过灌入";
  }
  return null;
}

export function formatDuration(startOrMilliseconds: string | number | null | undefined, finish?: string | null): string {
  const milliseconds = typeof startOrMilliseconds === "number"
    ? startOrMilliseconds
    : startOrMilliseconds && finish
      ? new Date(finish).getTime() - new Date(startOrMilliseconds).getTime()
      : null;
  if (milliseconds === null || !Number.isFinite(milliseconds) || milliseconds < 0) return "未知";
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`;
}

export function extractConsistencyFacts(run: SyncRun | null | undefined): { missing: number | null; orphan: number | null } {
  const consistency = run?.consistency;
  return {
    missing: consistency?.missing ?? consistency?.missing_count ?? null,
    orphan: consistency?.orphan_count ?? consistency?.orphan ?? null,
  };
}

export function deviceLabel(device: string | null | undefined): string {
  if (!device) return "未知设备";
  return /cuda|gpu|hailo/i.test(device) ? "GPU" : /cpu/i.test(device) ? "CPU" : device;
}

export function fallbackLabel(reason: string | null | undefined): string | null {
  return reason ? `降级原因：${reason}` : null;
}

const UNKNOWN: SourceHealthDimension = { state: "UNKNOWN", evidence: null, as_of: null };
type HealthDimensions = Record<"connectivity" | "sync" | "coverage" | "freshness" | "consistency", SourceHealthDimension>;
const LEGACY_HEALTH_STATES: Record<string, SourceHealthDimension["state"]> = {
  healthy: "HEALTHY",
  degraded: "DEGRADED",
  critical: "CRITICAL",
  disabled: "DISABLED",
  insufficient_data: "INSUFFICIENT_DATA",
};

function legacyDimension(sourceHealth: SourceHealthItem | undefined): SourceHealthDimension {
  if (!sourceHealth) return { ...UNKNOWN };
  const state = LEGACY_HEALTH_STATES[sourceHealth.health] ?? "UNKNOWN";
  return {
    state,
    evidence: `窗口内同步 ${sourceHealth.success_syncs}/${sourceHealth.total_syncs} 次成功`,
    as_of: sourceHealth.last_sync,
  };
}

function latestRunTime(run: SyncRun | undefined): string | null {
  return run?.finished_at ?? run?.started_at ?? null;
}

function connectivityDimension(latestRun: SyncRun | undefined): SourceHealthDimension {
  if (!latestRun) return { ...UNKNOWN };
  const asOf = latestRunTime(latestRun);
  const displayState = syncRunDisplayState(latestRun.status);
  const connectorFailures = latestRun.counters?.failed;
  const error = latestRun.error_summary ?? latestRun.sync_log?.error_detail;
  const phase = stageLabel(latestRun.stage);
  const hasConnectivityError = !!error && /connect|network|timeout|dns|http|fetch|github|sitemap|连接|网络|超时/i.test(error);

  if (displayState === "FAILED" && (latestRun.stage === "DISCOVER" || latestRun.stage === "FETCH" || hasConnectivityError)) {
    return {
      state: "CRITICAL",
      evidence: `连接失败证据：${phase}${error ? ` · ${error}` : ""}`,
      as_of: asOf,
    };
  }
  if (typeof connectorFailures === "number" && connectorFailures > 0) {
    return {
      state: "DEGRADED",
      evidence: `连接器失败 ${connectorFailures} 项${error ? ` · ${error}` : ""}`,
      as_of: asOf,
    };
  }
  if (displayState === "COMPLETED") {
    return { state: "HEALTHY", evidence: "最近运行已完成连接阶段", as_of: asOf };
  }
  if (displayState === "FAILED" && latestRun.stage) {
    return {
      state: "HEALTHY",
      evidence: `失败发生于${phase}，未归因为连接阶段`,
      as_of: asOf,
    };
  }
  return { ...UNKNOWN };
}

function coverageDimension(source: DataSource, sourceHealth: SourceHealthItem | undefined): SourceHealthDimension {
  if (!sourceHealth || !Number.isFinite(sourceHealth.doc_count) || !Number.isFinite(sourceHealth.chunk_count)) {
    return { ...UNKNOWN };
  }
  const evidence = `文档 ${sourceHealth.doc_count}，分块 ${sourceHealth.chunk_count}`;
  if (!source.enabled) return { state: "DISABLED", evidence, as_of: sourceHealth.last_sync };
  return {
    state: sourceHealth.doc_count > 0 && sourceHealth.chunk_count > 0 ? "HEALTHY" : "DEGRADED",
    evidence,
    as_of: sourceHealth.last_sync,
  };
}

function intervalMilliseconds(interval: string): number | null {
  const match = interval.match(/^(\d+)([hm])$/);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  return amount * (match[2] === "h" ? 60 * 60 * 1000 : 60 * 1000);
}

function durationThresholdLabel(milliseconds: number): string {
  const hours = milliseconds / (60 * 60 * 1000);
  return Number.isInteger(hours) ? `${hours}小时` : `${milliseconds / (60 * 1000)}分钟`;
}

function successfulSyncTime(
  source: DataSource,
  sourceHealth: SourceHealthItem | undefined,
  latestRun: SyncRun | undefined,
): string | null {
  if (latestRun?.sync_log?.status === "success" && latestRun.finished_at) return latestRun.finished_at;
  if (sourceHealth?.last_sync_status === "success" && sourceHealth.last_sync) return sourceHealth.last_sync;
  if (source.last_sync_status === "success" && source.last_sync) return source.last_sync;
  return null;
}

function freshnessDimension(
  source: DataSource,
  sourceHealth: SourceHealthItem | undefined,
  latestRun: SyncRun | undefined,
  now: Date,
): SourceHealthDimension {
  const lastSuccess = successfulSyncTime(source, sourceHealth, latestRun);
  if (!lastSuccess) return { ...UNKNOWN };
  const interval = intervalMilliseconds(source.sync_interval);
  const successTime = new Date(lastSuccess).getTime();
  if (interval === null || !Number.isFinite(successTime)) {
    return { state: "UNKNOWN", evidence: `最近成功同步 ${lastSuccess}，同步间隔证据无效`, as_of: now.toISOString() };
  }
  const threshold = interval * 2;
  const fresh = now.getTime() - successTime <= threshold;
  return {
    state: fresh ? "HEALTHY" : "DEGRADED",
    evidence: `最近成功同步 ${lastSuccess}，阈值 ${durationThresholdLabel(threshold)}`,
    as_of: now.toISOString(),
  };
}

function consistencyDimension(latestRun: SyncRun | undefined): SourceHealthDimension {
  if (!latestRun?.consistency) return { ...UNKNOWN };
  const facts = extractConsistencyFacts(latestRun);
  const evidence = facts.missing !== null || facts.orphan !== null
    ? `缺失 ${facts.missing ?? "未知"}，孤儿 ${facts.orphan ?? "未知"}`
    : null;
  if (latestRun.consistency.verification_failed) {
    return {
      state: "UNKNOWN",
      evidence: evidence ? `${evidence}；校验失败` : "一致性校验失败",
      as_of: latestRunTime(latestRun),
    };
  }
  if (!evidence) return { ...UNKNOWN };
  return {
    state: (facts.missing ?? 0) > 0 || (facts.orphan ?? 0) > 0 ? "DEGRADED" : "HEALTHY",
    evidence,
    as_of: latestRunTime(latestRun),
  };
}

export function deriveSourceHealth(
  source: DataSource,
  sourceHealth?: SourceHealthItem,
  latestRun?: SyncRun,
  activeStatus?: SyncStatusItem,
  now = new Date(),
): HealthDimensions {
  const sync = legacyDimension(sourceHealth);
  const isRecovering = activeStatus?.state === "RECOVERING" || activeStatus?.recovering === true;
  const activeSync = isRecovering && sync.evidence
    ? { ...sync, state: "RECOVERING" as const }
    : sync;
  return {
    connectivity: connectivityDimension(latestRun),
    sync: activeSync,
    coverage: coverageDimension(source, sourceHealth),
    freshness: freshnessDimension(source, sourceHealth, latestRun, now),
    consistency: consistencyDimension(latestRun),
  };
}
