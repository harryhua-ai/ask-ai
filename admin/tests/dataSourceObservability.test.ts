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
  syncRunDisplayState,
} from "@/lib/dataSourceObservability";
import type { DataSource, SyncRun } from "@/types/api";
import type { SourceHealthItem } from "@/lib/api/techInsight";

const legacyHealth = (health: string): SourceHealthItem => ({
  source_id: "source-a",
  source_type: "github",
  product: "NE503",
  enabled: true,
  doc_count: 10,
  chunk_count: 20,
  window_days: 30,
  total_syncs: 4,
  success_syncs: 3,
  partial_syncs: 0,
  failed_syncs: 1,
  sync_success_rate: 0.75,
  health,
  last_sync: "2026-09-03T01:02:03Z",
  last_sync_status: "success",
  last_sync_error: null,
});

const source = (overrides: Partial<DataSource> = {}): DataSource => ({
  id: "source-a",
  type: "github",
  product: "NE503",
  enabled: true,
  config: {},
  sync_interval: "1h",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: null,
  last_sync_status: null,
  last_sync_error: null,
  ...overrides,
});

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

  it("returns unknown health dimensions when a source has no evidence", () => {
    const health = deriveSourceHealth(
      source({ id: "empty-source" }),
      undefined,
      undefined,
      undefined,
      new Date("2026-09-03T04:00:00Z"),
    );
    expect(Object.keys(health)).toEqual(["connectivity", "sync", "coverage", "freshness", "consistency"]);
    expect(Object.values(health).every((dimension) =>
      dimension.state === "UNKNOWN" || dimension.state === "INSUFFICIENT_DATA")).toBe(true);
  });

  it("derives each health dimension only from its frozen evidence", () => {
    const latestRun: SyncRun = {
      id: 8,
      source_id: "source-a",
      triggered_by: "manual",
      request_id: 42,
      attempt: 1,
      recovery: false,
      status: "failed",
      started_at: "2026-09-03T03:00:00Z",
      finished_at: "2026-09-03T03:01:00Z",
      duration_seconds: 60,
      stage: "FETCH",
      counters: { failed: 1 },
      consistency: { missing: 2, orphan_count: 3 },
      execution_device: "cpu",
      fallback_reason: "CUDA unavailable",
      fallback_detail: "CUDAOutOfMemoryError",
      error_summary: "connector timeout",
      sync_log: {
        status: "failed",
        items_new: 0,
        chunks_written: 0,
        items_deleted: 0,
        items_unchanged: 0,
        error_detail: "connector timeout",
      },
    };
    const health = deriveSourceHealth(
      source({ last_sync: "2026-09-03T01:02:03Z", last_sync_status: "success" }),
      legacyHealth("degraded"),
      latestRun,
      undefined,
      new Date("2026-09-03T04:00:00Z"),
    );

    expect(health.connectivity.state).toBe("CRITICAL");
    expect(health.connectivity.evidence).toContain("connector timeout");
    expect(health.sync.state).toBe("DEGRADED");
    expect(health.coverage).toEqual({
      state: "HEALTHY",
      evidence: "文档 10，分块 20",
      as_of: "2026-09-03T01:02:03Z",
    });
    expect(health.freshness.state).toBe("DEGRADED");
    expect(health.freshness.evidence).toContain("阈值 2小时");
    expect(health.consistency.state).toBe("DEGRADED");
    expect(health.consistency.evidence).toBe("缺失 2，孤儿 3");
  });

  it("uses a recent run error as connectivity evidence even after a later phase", () => {
    const health = deriveSourceHealth(
      source(),
      undefined,
      {
        id: 9,
        source_id: "source-a",
        triggered_by: "cron",
        request_id: null,
        attempt: 1,
        recovery: false,
        status: "failed",
        started_at: "2026-09-03T03:00:00Z",
        finished_at: "2026-09-03T03:01:00Z",
        duration_seconds: 60,
        stage: "PARSE",
        counters: null,
        consistency: null,
        execution_device: null,
        fallback_reason: null,
        fallback_detail: null,
        error_summary: "network timeout",
        sync_log: null,
      },
    );
    expect(health.connectivity.state).toBe("CRITICAL");
    expect(health.connectivity.evidence).toContain("network timeout");
  });

  it("uses twice the source interval for freshness without inventing a timestamp", () => {
    const health = deriveSourceHealth(
      source({ sync_interval: "30m", last_sync: "2026-09-03T03:15:00Z", last_sync_status: "success" }),
      undefined,
      undefined,
      undefined,
      new Date("2026-09-03T04:00:00Z"),
    );
    expect(health.freshness.state).toBe("HEALTHY");
    expect(health.freshness.evidence).toContain("阈值 1小时");
  });

  it("keeps recovery explicit over every prior health state and preserves evidence", () => {
    for (const priorState of ["healthy", "degraded", "critical", "disabled", "insufficient_data"]) {
      const health = deriveSourceHealth(
        source(),
        legacyHealth(priorState),
        undefined,
        {
          source_id: "source-a",
          state: "RECOVERING",
          request_id: 42,
          attempt: 2,
          recovering: true,
          stage: "FETCH",
          stage_current: null,
          stage_total: null,
          counters: null,
          execution_device: null,
          started_at: "2026-09-03T01:00:00Z",
          updated_at: "2026-09-03T01:00:01Z",
        },
      );
      expect(health.sync).toEqual({
        state: "RECOVERING",
        evidence: `窗口内同步 3/4 次成功`,
        as_of: "2026-09-03T01:02:03Z",
      });
    }
  });

  it("maps an unknown legacy health state to UNKNOWN", () => {
    expect(deriveSourceHealth(
      source(),
      legacyHealth("vendor_future_state"),
    ).sync).toEqual({
      state: "UNKNOWN",
      evidence: "窗口内同步 3/4 次成功",
      as_of: "2026-09-03T01:02:03Z",
    });
  });
});
