import { describe, expect, it } from "vitest";
import {
  deviceLabel,
  extractConsistencyFacts,
  fallbackLabel,
  formatDuration,
  healthStateLabel,
  humanizeHealthEvidence,
  overallRollupExplanation,
  progressPercent,
  shortCircuitSummary,
  stageLabel,
  stateLabel,
  syncRunDisplayState,
} from "@/lib/dataSourceObservability";
import type { SyncHealthDimension, SyncHealthItem, SyncRun } from "@/types/api";

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

// -------------------------------------------------------------------------- //
// Issue #54 R3+R4:overall rollup 解释 = 复述后端 _overall_health 文档化优先级,
// 仅由 overall+维度权威 state 组合映射,零重判、不派生第二健康态。
// -------------------------------------------------------------------------- //

const dim = (state: string, evidence: string | null = "evidence"): SyncHealthDimension => ({
  state,
  evidence,
  as_of: null,
});

const healthItem = (overrides: Partial<SyncHealthItem> = {}): SyncHealthItem => ({
  source_id: "s",
  source_type: "web_crawl",
  enabled: true,
  expected_state: "REQUIRED",
  overall: "HEALTHY",
  recovering: false,
  document_count: 12,
  connectivity: dim("ok"),
  sync: dim("healthy"),
  coverage: dim("ok"),
  freshness: dim("fresh"),
  consistency: dim("ok"),
  currency: dim("ok"),
  ...overrides,
});

describe("overallRollupExplanation(#54 R3+R4:复述后端 rollup 优先级,零重判)", () => {
  it("HEALTHY + sync degraded + coverage unknown:解释历史参考与未知不拖低,消除表面矛盾", () => {
    const lines = overallRollupExplanation(
      healthItem({
        sync: dim("degraded", "12/25 syncs succeeded in 30d"),
        coverage: dim("unknown", "no structured coverage counters for this source type"),
      }),
    );
    const text = lines.join("\n");
    expect(text).toContain("整体=健康");
    // #21 口径:sync 维为近30天历史参考,不驱动 overall
    expect(text).toContain("近30天");
    expect(text).toContain("不驱动整体");
    // unknown 维度不参与 worst-of,单维如实呈现
    expect(text).toContain("未知");
    expect(text).toContain("不拖低整体");
  });

  it("ACTION_REQUIRED:列出后端既定的同级驱动(connectivity failed / currency degraded)", () => {
    const lines = overallRollupExplanation(
      healthItem({
        overall: "ACTION_REQUIRED",
        connectivity: dim("failed", "latest run #9 failed@FETCH"),
        currency: dim("degraded", "member drift unresolved"),
      }),
    );
    const text = lines.join("\n");
    expect(text).toContain("需处理");
    expect(text).toContain("连接失败");
    expect(text).toContain("上游成员对账降级");
  });

  it("maps every documented overall precedence value to an explanation line", () => {
    for (const overall of [
      "EXCLUDED",
      "RECOVERING",
      "EMPTY_UNEXPECTED",
      "EMPTY_EXPECTED",
      "STALE",
      "PARTIAL",
      "INSUFFICIENT_DATA",
    ] as const) {
      const lines = overallRollupExplanation(healthItem({ overall }));
      expect(lines.length).toBeGreaterThan(0);
      expect(lines.join("")).toContain(healthStateLabel(overall));
    }
  });

  it("passes unknown overall vocabulary through without deriving a second health state", () => {
    const lines = overallRollupExplanation(healthItem({ overall: "vendor_future_overall" }));
    expect(lines.length).toBe(1);
    expect(lines[0]).toContain("按当前证据");
    expect(lines[0]).toContain("vendor_future_overall");
  });
});

// -------------------------------------------------------------------------- //
// Issue #54 R6:freshness 阈值证据本地化 = 仅命中已知权威格式(last success Ns ago
// (threshold=Ns)/no successful sync on record/source disabled),未知逐字透传。
// -------------------------------------------------------------------------- //

describe("humanizeHealthEvidence(#54 R6:freshness 已知权威格式本地化,未知透传)", () => {
  it("humanizes the documented last-success/threshold format with understandable units", () => {
    expect(
      humanizeHealthEvidence({ state: "fresh", evidence: "last success 3600s ago (threshold=7200s)" }),
    ).toEqual({ text: "最近成功 1小时前；要求 2小时内有成功同步", humanized: true });
    expect(
      humanizeHealthEvidence({ state: "stale", evidence: "last success 172800s ago (threshold=172800s)" }),
    ).toEqual({ text: "最近成功 2天前；要求 48小时内有成功同步", humanized: true });
  });

  it("humanizes the other two documented freshness formats", () => {
    expect(humanizeHealthEvidence({ state: "stale", evidence: "no successful sync on record" })).toEqual({
      text: "暂无成功同步记录",
      humanized: true,
    });
    expect(humanizeHealthEvidence({ state: "unknown", evidence: "source disabled" })).toEqual({
      text: "数据源已禁用，新鲜度不作要求",
      humanized: true,
    });
  });

  it("passes unknown evidence formats and other dimensions through verbatim", () => {
    expect(humanizeHealthEvidence({ state: "stale", evidence: "vendor_future evidence" })).toEqual({
      text: "vendor_future evidence",
      humanized: false,
    });
    expect(
      humanizeHealthEvidence({ state: "ok", evidence: "missing=0, extra_orphan=0 (expected=42, actual=42)" }),
    ).toEqual({ text: "missing=0, extra_orphan=0 (expected=42, actual=42)", humanized: false });
    expect(humanizeHealthEvidence({ state: "ok", evidence: null })).toEqual({ text: "", humanized: false });
  });
});
