import { describe, expect, it } from "vitest";
import {
  deriveSourceHealth,
  deviceLabel,
  extractConsistencyFacts,
  fallbackLabel,
  formatDuration,
  progressPercent,
  shortCircuitSummary,
  stageLabel,
  stateLabel,
} from "@/lib/dataSourceObservability";
import type { SyncRun, SyncStatusItem } from "@/types/api";

describe("data source observability view models", () => {
  it("为每个 canonical state 和 stage 提供中文标签", () => {
    expect(["QUEUED", "WAITING", "RUNNING", "RECOVERING", "COMPLETED", "FAILED", "INTERRUPTED", "IDLE"]
      .every((value) => stateLabel(value).length > 0)).toBe(true);
    expect(["DISCOVER", "SAFETY_FILTER", "FETCH", "PARSE", "CHUNK", "EMBED", "INDEX", "CONSISTENCY", "DONE"]
      .every((value) => stageLabel(value).length > 0)).toBe(true);
  });

  it("does not show a percentage when the stage denominator is unknown", () => {
    expect(progressPercent(3, null)).toBeNull();
    expect(progressPercent(3, 12)).toBe(25);
  });

  it("only identifies an evidenced no-change short circuit", () => {
    expect(shortCircuitSummary({ docs_total: 0, items_unchanged: 12 })).toBe("无上游变更 · 已检查 · 跳过灌入");
    expect(shortCircuitSummary({ docs_total: 0, items_unchanged: 0 })).toBeNull();
  });

  it("keeps chunk output as chunks and separates missing from orphan facts", () => {
    const run: SyncRun = {
      id: 8,
      source_id: "source/technical-id",
      status: "completed",
      stage: "DONE",
      stage_current: 10,
      stage_total: 10,
      counters: { chunks_written: 42 },
      consistency: { missing: 2, orphan_count: 3 },
      started_at: "2026-09-03T01:00:00Z",
      finished_at: "2026-09-03T01:02:03Z",
    };
    expect(extractConsistencyFacts(run)).toEqual({ missing: 2, orphan: 3 });
    expect(formatDuration(run.started_at, run.finished_at)).toBe("2分3秒");
    expect(deviceLabel("cuda:0")).toBe("GPU");
    expect(fallbackLabel("cuda unavailable")).toBe("降级原因：cuda unavailable");
    expect(run.counters?.chunks_written).toBe(42);
  });

  it("returns unknown health dimensions when a source has no evidence", () => {
    const source: SyncStatusItem = { source_id: "empty-source", state: "IDLE", stage: null };
    const health = deriveSourceHealth(source, undefined, undefined);
    expect(Object.keys(health)).toEqual(["connectivity", "sync", "coverage", "freshness", "consistency"]);
    expect(Object.values(health).every((dimension) =>
      dimension.state === "UNKNOWN" || dimension.state === "INSUFFICIENT_DATA")).toBe(true);
  });
});
