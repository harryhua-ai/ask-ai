import type { SyncHealthDimension, SyncHealthItem, SyncRun, SyncState, SyncStatusItem } from "@/types/api";

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
  // #71 权威成员货币维度(connector 无成员枚举能力 = 中性)
  unsupported: "不适用",
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

// --------------------------------------------------------------------------- //
// Issue #54 R3+R4:overall rollup 解释。复述 backend `sync_runs.py:_overall_health`
// 的文档化优先级(EXCLUDED → RECOVERING overlay → EMPTY_* → connectivity failed /
// consistency degraded / currency degraded → STALE → PARTIAL → INSUFFICIENT_DATA →
// HEALTHY;unknown 维度不参与 worst-of;#21 sync=近30天历史参考不驱动 overall;
// #71 currency degraded 与 connectivity/consistency 同级)。仅由 overall + 维度权威
// state 组合映射为操作者语言,零重判、不派生第二健康态;未知词表「按当前证据」透传。
// --------------------------------------------------------------------------- //

const dimState = (d: SyncHealthDimension | null | undefined): string => d?.state ?? "";

export function overallRollupExplanation(item: SyncHealthItem): string[] {
  const lines: string[] = [];
  switch (item.overall) {
    case "EXCLUDED":
      lines.push("整体=已排除：数据源已禁用或被显式排除，整体健康不参与评估，各维度仅作技术核证参考。");
      break;
    case "RECOVERING":
      lines.push("同步正在恢复中：恢复期间整体不显示「健康」，恢复完成后按当前证据重新评估。");
      break;
    case "EMPTY_UNEXPECTED":
      lines.push("该源为必需内容，但当前 0 篇文档且从未成功同步（意外为空）。");
      break;
    case "EMPTY_EXPECTED":
      lines.push("该源为可选/发现类内容，当前 0 篇文档（预期为空），不构成异常。");
      break;
    case "ACTION_REQUIRED": {
      // 后端既定同级驱动:connectivity==failed / consistency==degraded / currency==degraded
      const drivers: string[] = [];
      if (dimState(item.connectivity) === "failed") drivers.push("连接失败");
      if (dimState(item.consistency) === "degraded") drivers.push("一致性校验降级");
      if (dimState(item.currency) === "degraded") drivers.push("上游成员对账降级");
      lines.push(
        drivers.length > 0
          ? `整体=需处理：${drivers.join("、")}（后端既定优先级中最高级驱动，健康面不显示「健康」）。`
          : "整体=需处理：按当前证据存在需处理项，具体主因见各维度卡片。",
      );
      break;
    }
    case "STALE":
      lines.push("整体=过期：数据新鲜度超期（要求阈值内无成功同步），按权威维度如实呈现。");
      break;
    case "PARTIAL":
      lines.push("整体=部分：内容覆盖为部分覆盖（按权威计数），其余维度无更高优先级异常。");
      break;
    case "INSUFFICIENT_DATA":
      lines.push("整体=证据不足：近30天同步窗口证据不足，仅作参考呈现，不推断健康与否。");
      break;
    case "HEALTHY": {
      lines.push("整体=健康：连接、一致性、新鲜度、覆盖当前均无异常证据。");
      if (!["ok", "healthy"].includes(dimState(item.sync))) {
        // #21:sync 维是近30天历史窗口成功率(参考信号),不驱动 overall
        lines.push(
          `同步可靠性显示「${healthStateLabel(dimState(item.sync))}」：该维为近30天历史成功率参考，不驱动整体、不拖低健康。`,
        );
      }
      if (["unknown", "insufficient_data"].includes(dimState(item.coverage))) {
        // unknown 维度不参与 worst-of:缺证据 ≠ 不健康,单维如实呈现
        lines.push(
          `覆盖显示「${healthStateLabel(dimState(item.coverage))}」：缺少可证明的覆盖分母，按单维如实呈现，不拖低整体。`,
        );
      }
      const insufficient = [
        ["连接状态", item.connectivity] as const,
        ["数据新鲜度", item.freshness] as const,
        ["检索/索引一致性", item.consistency] as const,
      ].filter(([, d]) => ["unknown", "insufficient_data"].includes(dimState(d)));
      if (insufficient.length > 0) {
        lines.push(
          `${insufficient.map(([label]) => label).join("、")}当前证据不足，按未知单维如实呈现，不拖低整体。`,
        );
      }
      if (dimState(item.currency) === "unsupported") {
        // #71:connector 无成员枚举能力 = 中性,不参与评估
        lines.push("上游成员对账为「不适用」：连接器无成员枚举能力，不参与评估。");
      }
      break;
    }
    default:
      lines.push(`按当前证据呈现：整体状态「${healthStateLabel(item.overall)}」，各维度详见下方卡片。`);
  }
  return lines;
}

// --------------------------------------------------------------------------- //
// Issue #54 R6:freshness 阈值证据本地化。仅对 backend `sync_runs.py:_freshness_dim`
// 的已知权威证据格式做呈现层单位换算/本地化(不重推 2× 规则、不解析业务值);
// 未知模式逐字透传(与 healthStateLabel 同纪律)。原文整串由调用方收进 title。
// --------------------------------------------------------------------------- //

const LAST_SUCCESS_RE = /^last success (\d+)s ago \(threshold=(\d+)s\)$/;

function humanizeAgeSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时`;
  return `${Math.floor(seconds / 86400)}天`;
}

function humanizeThresholdSeconds(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}小时`;
  if (seconds % 60 === 0) return `${seconds / 60}分钟`;
  return `${seconds}秒`;
}

export interface HumanizedEvidence {
  text: string;
  humanized: boolean;
}

export function humanizeHealthEvidence(dimension: {
  state: string;
  evidence: string | null;
}): HumanizedEvidence {
  const evidence = dimension.evidence;
  if (!evidence) return { text: "", humanized: false };
  const lastSuccess = evidence.match(LAST_SUCCESS_RE);
  if (lastSuccess) {
    const age = Number(lastSuccess[1]);
    const threshold = Number(lastSuccess[2]);
    return {
      text: `最近成功 ${humanizeAgeSeconds(age)}前；要求 ${humanizeThresholdSeconds(threshold)}内有成功同步`,
      humanized: true,
    };
  }
  if (evidence === "no successful sync on record") {
    return { text: "暂无成功同步记录", humanized: true };
  }
  if (evidence === "source disabled") {
    return { text: "数据源已禁用，新鲜度不作要求", humanized: true };
  }
  return { text: evidence, humanized: false };
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
