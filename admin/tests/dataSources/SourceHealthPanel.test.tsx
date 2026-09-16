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
    // #67:健康维度使用管理员语义,历史窗口与检索/索引边界明确
    for (const label of ["连接状态", "同步可靠性（历史30天）", "知识可用性", "数据新鲜度", "检索/索引一致性"]) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }
    // 后端状态词表 → 本地化徽章(不得改判)
    expect(screen.getAllByText("正常").length).toBe(3);        // connectivity/coverage/consistency ok
    expect(screen.getAllByText("健康").length).toBe(2);        // sync healthy + overall HEALTHY
    // #54 R6:freshness 证据人类化呈现(原文整串收进 title,技术核证仍可得);
    // 非 freshness 维 evidence 仍逐字直呈
    expect(screen.getByText("最近成功 1小时前；要求 2小时内有成功同步")).toBeInTheDocument();
    expect(screen.getByTitle("last success 3600s ago (threshold=7200s)")).toBeInTheDocument();
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
    expect(screen.getByText("暂不可评估")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
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
    // #54 R6:已知权威格式本地化,原文收进 title
    expect(screen.getByText("暂无成功同步记录")).toBeInTheDocument();
    expect(screen.getByTitle("no successful sync on record")).toBeInTheDocument();
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

// ==================== Issue #54(R3+R4/R5/R6:呈现层差距收敛) ====================

describe("SourceHealthPanel(#54:rollup 解释 + freshness 单位 + 时间人类化)", () => {
  it("R3+R4:overall=健康与同步降级/覆盖未知并置时,必须出现 rollup 解释行(矛盾被显式解释)", () => {
    render(
      <SourceHealthPanel
        health={health({
          sync: dim("degraded", "12/25 syncs succeeded in 30d"),
          coverage: dim("unknown", "no structured coverage counters for this source type"),
        })}
      />,
    );
    // 解释行复述后端文档化优先级,消除「健康 vs 降级/未知」的表面矛盾
    expect(screen.getByText(/整体=健康/)).toBeInTheDocument();
    expect(screen.getByText(/近30天/)).toBeInTheDocument();
    expect(screen.getByText(/不驱动整体/)).toBeInTheDocument();
    expect(screen.getAllByText(/不拖低整体/).length).toBe(1);
  });

  it("R3+R4:ACTION_REQUIRED 解释行列出后端既定的同级驱动因子", () => {
    render(
      <SourceHealthPanel
        health={health({
          overall: "ACTION_REQUIRED",
          connectivity: dim("failed", "latest run #9 failed@FETCH"),
          currency: dim("degraded", "member drift unresolved"),
        })}
      />,
    );
    expect(screen.getByText(/整体=需处理/)).toBeInTheDocument();
    expect(screen.getByText(/连接失败/)).toBeInTheDocument();
    expect(screen.getByText(/上游成员对账降级/)).toBeInTheDocument();
  });

  it("R6:freshness 证据以人类可读单位呈现「最近成功 + 允许阈值」,原文收进 title", () => {
    render(<SourceHealthPanel health={health()} />);
    expect(screen.getByText("最近成功 1小时前；要求 2小时内有成功同步")).toBeInTheDocument();
    expect(screen.getByTitle("last success 3600s ago (threshold=7200s)")).toBeInTheDocument();
  });

  it("R5:维度 as_of 主呈现为人类化相对时间,原样 ISO 收进 title", () => {
    const asOf = new Date().toISOString();
    render(
      <SourceHealthPanel health={health({ freshness: dim("fresh", "last success 60s ago (threshold=7200s)", asOf) })} />,
    );
    expect(screen.getByText(/截至/)).toBeInTheDocument();
    expect(screen.getByTitle(asOf)).toBeInTheDocument();
    // 不再裸呈 ISO 主文本
    expect(screen.queryByText(`截至 ${asOf}`)).not.toBeInTheDocument();
  });
});
