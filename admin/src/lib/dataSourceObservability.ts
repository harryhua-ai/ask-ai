import type { SyncRun, SyncState, SyncStatusItem } from "@/types/api";

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

// --------------------------------------------------------------------------- //
// #11 Health Authority:W2 /sync-health 是五维健康唯一权威。前端对 state 只做
// 「本地化」,不重判、不改写、不派生第二健康态;未知词表原文透传。
// 维度级(小写)与 overall(大写)词表以 W2 后端实现为准。
// --------------------------------------------------------------------------- //

const HEALTH_STATE_LABELS: Record<string, string> = {
  // 维度级(W2 _dim 词表)
  ok: "正常",
  healthy: "健康",
  degraded: "降级",
  critical: "严重",
  failed: "失败",
  stale: "过期",
  fresh: "新鲜",
  partial: "部分覆盖",
  unknown: "未知",
  insufficient_data: "证据不足",
  // overall(W2 _overall_health 词表)
  HEALTHY: "健康",
  RECOVERING: "恢复中",
  STALE: "过期",
  ACTION_REQUIRED: "需处理",
  PARTIAL: "部分",
  DEGRADED: "降级",
  INSUFFICIENT_DATA: "证据不足",
  EXCLUDED: "已排除",
  EMPTY_UNEXPECTED: "意外为空",
  EMPTY_EXPECTED: "预期为空",
};

export function healthStateLabel(state: string | null | undefined): string {
  if (!state) return "未知状态";
  return HEALTH_STATE_LABELS[state] ?? state;
}

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
