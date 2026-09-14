/**
 * #65 administrator-facing synchronization delta boundary.
 *
 * `items_*` and `chunks_written` are historical fields with mixed semantics.
 * They are intentionally not used to derive document-level changes here.
 */

export const LEGACY_DELTA_UNAVAILABLE = "变更单位不可用（历史记录）";

export interface AdminDocumentDelta {
  schema_version?: number;
  unit?: string;
  new_count: number;
  new_unit?: string;
  updated_count: number;
  updated_unit?: string;
  retired_count: number;
  retired_unit?: string;
  unchanged_count: number;
  unchanged_unit?: string;
}

export type SyncLogDeltaBoundary = {
  delta_counts?: Partial<AdminDocumentDelta> | null;
};

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

export function documentDelta(log: unknown): AdminDocumentDelta | null {
  const delta =
    log && typeof log === "object"
      ? (log as SyncLogDeltaBoundary).delta_counts
      : undefined;
  if (!delta || delta.unit !== "document") return null;
  if (
    !isCount(delta.new_count) ||
    !isCount(delta.updated_count) ||
    !isCount(delta.retired_count) ||
    !isCount(delta.unchanged_count)
  ) {
    return null;
  }
  const units = [delta.new_unit, delta.updated_unit, delta.retired_unit, delta.unchanged_unit];
  if (units.some((unit) => unit != null && unit !== "document")) return null;
  return delta as AdminDocumentDelta;
}

export function hasAuthoritativeDocumentDelta(
  log: unknown,
): boolean {
  return documentDelta(log) !== null;
}

export function documentDeltaSummary(log: unknown): string[] {
  const delta = documentDelta(log);
  if (!delta) return [LEGACY_DELTA_UNAVAILABLE];
  return [
    `新增知识 ${delta.new_count}`,
    `更新知识 ${delta.updated_count}`,
    `淘汰知识 ${delta.retired_count}`,
    `未变更知识 ${delta.unchanged_count}`,
  ];
}

export function documentDeltaChangeSummary(log: unknown): string[] {
  const delta = documentDelta(log);
  if (!delta) return [LEGACY_DELTA_UNAVAILABLE];
  const lines: string[] = [];
  if (delta.new_count > 0) lines.push(`新增 ${delta.new_count} 篇知识`);
  if (delta.updated_count > 0) lines.push(`更新 ${delta.updated_count} 篇知识`);
  if (delta.retired_count > 0) lines.push(`淘汰 ${delta.retired_count} 篇知识`);
  return lines;
}
