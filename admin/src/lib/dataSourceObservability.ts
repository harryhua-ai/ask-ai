import type {
  SourceHealthDimension,
  SyncRun,
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

function legacyDimension(sourceHealth: SourceHealthItem | undefined): SourceHealthDimension {
  if (!sourceHealth) return { ...UNKNOWN };
  const state: SourceHealthDimension["state"] = {
    healthy: "HEALTHY",
    degraded: "DEGRADED",
    critical: "CRITICAL",
    disabled: "DISABLED",
    insufficient_data: "INSUFFICIENT_DATA",
  }[sourceHealth.health] ?? "UNKNOWN";
  return {
    state,
    evidence: `窗口内同步 ${sourceHealth.success_syncs}/${sourceHealth.total_syncs} 次成功`,
    as_of: sourceHealth.last_sync,
  };
}

export function deriveSourceHealth(
  source: SyncStatusItem,
  sourceHealth?: SourceHealthItem,
  latestRun?: SyncRun,
): Record<"connectivity" | "sync" | "coverage" | "freshness" | "consistency", SourceHealthDimension> {
  const sync = legacyDimension(sourceHealth);
  const facts = extractConsistencyFacts(latestRun);
  const activeSync = source.state === "RECOVERING"
    ? { ...sync, state: "RECOVERING" as const }
    : sync;
  return {
    connectivity: sourceHealth ? { ...sync, evidence: sourceHealth.enabled ? "数据源已启用" : "数据源已禁用" } : { ...UNKNOWN },
    sync: activeSync,
    coverage: sourceHealth && Number.isFinite(sourceHealth.doc_count) ? { state: "HEALTHY", evidence: `文档 ${sourceHealth.doc_count}，分块 ${sourceHealth.chunk_count}`, as_of: sourceHealth.last_sync } : { ...UNKNOWN },
    freshness: sourceHealth?.last_sync ? { state: "HEALTHY", evidence: `最近同步 ${sourceHealth.last_sync}`, as_of: sourceHealth.last_sync } : { ...UNKNOWN },
    consistency: facts.missing !== null || facts.orphan !== null ? { state: facts.missing || facts.orphan ? "DEGRADED" : "HEALTHY", evidence: `缺失 ${facts.missing ?? "未知"}，孤儿 ${facts.orphan ?? "未知"}`, as_of: latestRun?.finished_at ?? latestRun?.updated_at ?? null } : { ...UNKNOWN },
  };
}
