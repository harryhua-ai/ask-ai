/**
 * #51 B2 自有:生成状态(P 轴)→ 运营标签 / 事件严重度映射。
 *
 * P 轴词表(index_generations.status,后端冻结):
 *   pending → processing → ready(验证通过;被激活=documents.current_version_id
 *   关系翻转,非 P 轴状态) / failed(构建/验证失败,证据入 failure)/
 *   retired(服务撤出完成,常规生命周期)。
 *
 * 注意:本模块与 #50 数据源工作区的 L 轴(生命周期 L0-L4)映射词汇不同,
 * 属 #51 技术洞察所有;不得复制源清单语义(洞察页零源清单/零源配置)。
 */

export const GENERATION_STATUS_LABELS: Record<string, string> = {
  pending: "待构建",
  processing: "构建中",
  ready: "已就绪",
  failed: "生成失败",
  retired: "已退役",
};

export function generationStatusLabel(status: string): string {
  return GENERATION_STATUS_LABELS[status] ?? status;
}

export type IncidentSeverity = "error" | "warning" | "info";

/** 同步级事件(权威源 GET /sync-runs 的 status)严重度:
 *  failed=同步失败(error)/ interrupted=同步中断(warning,可恢复)。 */
export function syncIncidentSeverity(status: string): IncidentSeverity {
  return status === "failed" ? "error" : "warning";
}

export function syncIncidentTypeLabel(status: string): string {
  return status === "interrupted" ? "同步中断" : "同步失败";
}

/** 生成级事件(权威源 GET /tech/generation-events 的 status/severity)严重度:
 *  failed=error / retired=info(常规生命周期撤出,非失败)。 */
export function generationEventSeverity(status: string): IncidentSeverity {
  return status === "failed" ? "error" : "info";
}

export function generationEventTypeLabel(status: string): string {
  return generationStatusLabel(status);
}
