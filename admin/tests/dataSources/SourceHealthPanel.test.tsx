import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SourceHealthPanel } from "@/components/dataSources/SourceHealthPanel";
import type { SyncHealthItem } from "@/types/api";

afterEach(cleanup);

// W2 /sync-health 权威条目形态(词表/evidence 均按后端原文)
const dim = (state: string, evidence: string | null = "evidence text", as_of: string | null = null) => ({
  state,
  evidence,
  as_of,
});

const health = (overrides: Partial<SyncHealthItem> = {}): SyncHealthItem => ({
  source_id: "website-camthink",
  source_type: "web_crawl",
  enabled: true,
  expected_state: "REQUIRED",
  overall: "HEALTHY",
  recovering: false,
  document_count: 12,
  connectivity: dim("ok", "latest run #8 completed@DONE"),
  sync: dim("healthy", "24/25 syncs succeeded in 30d"),
  coverage: dim("ok", "extracted=50/50 accepted"),
  freshness: dim("fresh", "last success 3600s ago (threshold=7200s)"),
  consistency: dim("ok", "missing=0, extra_orphan=0 (expected=42, actual=42)"),
  ...overrides,
});

describe("SourceHealthPanel(#11 Health Authority:W2 /sync-health 直呈)", () => {
  it("renders the five dimensions and overall exactly as the backend states them", () => {
    render(<SourceHealthPanel health={health()} />);
    for (const label of ["连接", "同步", "覆盖", "新鲜度", "一致性"]) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }
    // 后端状态词表 → 本地化徽章(不得改判)
    expect(screen.getAllByText("正常").length).toBe(3);        // connectivity/coverage/consistency ok
    expect(screen.getAllByText("健康").length).toBe(2);        // sync healthy + overall HEALTHY
    // 后端 evidence 原文逐字呈现
    expect(screen.getByText("last success 3600s ago (threshold=7200s)")).toBeInTheDocument();
    expect(screen.getByText("24/25 syncs succeeded in 30d")).toBeInTheDocument();
  });

  it("does not override backend UNKNOWN states into another health state", () => {
    render(
      <SourceHealthPanel
        health={health({
          overall: "INSUFFICIENT_DATA",
          connectivity: dim("unknown", null),
          coverage: dim("unknown", "no sync_runs evidence"),
          freshness: dim("unknown", null),
        })}
      />,
    );
    // UNKNOWN 徽章保持「未知」,不被前端改判为「证据不足」状态
    expect(screen.getAllByText("未知").length).toBe(3);
    // overall INSUFFICIENT_DATA 徽章 + 2 个 evidence 空占位,均为「证据不足」
    expect(screen.getAllByText("证据不足").length).toBe(3);
  });

  it("presents backend RECOVERING without frontend synthesis", () => {
    render(
      <SourceHealthPanel
        health={health({ overall: "RECOVERING", recovering: true, sync: dim("degraded", "12/25 syncs succeeded in 30d") })}
      />,
    );
    // 恢复中只能来自后端 overall/state,面板原样呈现
    expect(screen.getByText("恢复中")).toBeInTheDocument();
    expect(screen.getByText("降级")).toBeInTheDocument();
  });

  it("localizes backend STALE freshness without recomputing thresholds", () => {
    render(
      <SourceHealthPanel
        health={health({ overall: "STALE", freshness: dim("stale", "no successful sync on record") })}
      />,
    );
    expect(screen.getAllByText("过期").length).toBe(2); // overall STALE + freshness stale
    expect(screen.getByText("no successful sync on record")).toBeInTheDocument();
  });

  it("passes unknown backend vocabulary through verbatim (no reinterpretation)", () => {
    render(
      <SourceHealthPanel
        health={health({ connectivity: dim("vendor_future_state", "mystery evidence") })}
      />,
    );
    expect(screen.getByText("vendor_future_state")).toBeInTheDocument();
    expect(screen.getByText("mystery evidence")).toBeInTheDocument();
  });

  it("shows an honest empty state when the backend provides no health item", () => {
    render(<SourceHealthPanel />);
    expect(screen.getByText("暂无健康数据(等待后端 /sync-health 提供)")).toBeInTheDocument();
    expect(screen.queryByText("连接")).not.toBeInTheDocument();
  });
});
