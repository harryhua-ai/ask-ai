import { describe, expect, it } from "vitest";
import {
  deviceLabel,
  extractConsistencyFacts,
  fallbackLabel,
  formatDuration,
  healthStateLabel,
  progressPercent,
  shortCircuitSummary,
  stageLabel,
  stateLabel,
  syncRunDisplayState,
} from "@/lib/dataSourceObservability";
import type { SyncRun } from "@/types/api";

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
      triggered_by: "manual",
      request_id: 42,
      attempt: 1,
      recovery: false,
      status: "completed",
      stage: "DONE",
      counters: { chunks_written: 42 },
      consistency: { missing: 2, orphan_count: 3 },
      execution_device: "cuda:0",
      started_at: "2026-09-03T01:00:00Z",
      finished_at: "2026-09-03T01:02:03Z",
      duration_seconds: 123,
      fallback_reason: null,
      fallback_detail: null,
      error_summary: null,
      sync_log: null,
    };
    expect(extractConsistencyFacts(run)).toEqual({ missing: 2, orphan: 3 });
    expect(formatDuration(run.started_at, run.finished_at)).toBe("2分3秒");
    expect(deviceLabel("cuda:0")).toBe("GPU");
    expect(fallbackLabel("cuda unavailable")).toBe("降级原因：cuda unavailable");
    expect(run.counters?.chunks_written).toBe(42);
  });

  it("normalizes history state only from the backend run status", () => {
    expect(syncRunDisplayState("completed")).toBe("COMPLETED");
    expect(syncRunDisplayState("failed")).toBe("FAILED");
    expect(syncRunDisplayState("interrupted")).toBe("INTERRUPTED");
    expect(syncRunDisplayState(null)).toBeNull();
    expect(syncRunDisplayState("vendor_future_status")).toBeNull();
  });

  // ------------------------------------------------------------------ //
  // #11 Health Authority:前端只本地化 W2 /sync-health 的状态词表,
  //     不重判、不改写;未知词表原文透传(绝不映射成另一种健康态)。
  // ------------------------------------------------------------------ //

  it("localizes the W2 dimension-level health states", () => {
    for (const [state, label] of [
      ["ok", "正常"],
      ["healthy", "健康"],
      ["degraded", "降级"],
      ["critical", "严重"],
      ["failed", "失败"],
      ["stale", "过期"],
      ["fresh", "新鲜"],
      ["partial", "部分覆盖"],
      ["unknown", "未知"],
      ["insufficient_data", "证据不足"],
    ] as const) {
      expect(healthStateLabel(state)).toBe(label);
    }
  });

  it("localizes the W2 overall health vocabulary", () => {
    for (const [state, label] of [
      ["HEALTHY", "健康"],
      ["RECOVERING", "恢复中"],
      ["STALE", "过期"],
      ["ACTION_REQUIRED", "需处理"],
      ["PARTIAL", "部分"],
      ["DEGRADED", "降级"],
      ["INSUFFICIENT_DATA", "证据不足"],
      ["EXCLUDED", "已排除"],
      ["EMPTY_UNEXPECTED", "意外为空"],
      ["EMPTY_EXPECTED", "预期为空"],
    ] as const) {
      expect(healthStateLabel(state)).toBe(label);
    }
  });

  it("passes unknown backend health states through verbatim without reinterpretation", () => {
    expect(healthStateLabel("vendor_future_state")).toBe("vendor_future_state");
    expect(healthStateLabel("")).toBe("未知状态");
    expect(healthStateLabel(null)).toBe("未知状态");
  });
});
