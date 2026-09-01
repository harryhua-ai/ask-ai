import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { mockTechPerf, mockCoverageGaps, mockSourceHealth, mockGapTrends } = vi.hoisted(() => ({
  mockTechPerf: vi.fn(),
  mockCoverageGaps: vi.fn(),
  mockSourceHealth: vi.fn(),
  mockGapTrends: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchCoverageGaps: mockCoverageGaps,
  fetchSourceHealth: mockSourceHealth,
  fetchGapTrends: mockGapTrends,
}));

// 缺口趋势默认空(KnowledgeGapsTab 用)
mockGapTrends.mockResolvedValue({ trends: [] });

// 数据源健康默认两条(技术洞察只应有摘要条,不再有完整表格)
mockSourceHealth.mockResolvedValue({
  items: [
    {
      source_id: "website-camthink",
      source_type: "web_crawl",
      product: "website",
      enabled: true,
      doc_count: 75,
      chunk_count: 1200,
      window_days: 30,
      total_syncs: 25,
      success_syncs: 24,
      partial_syncs: 0,
      failed_syncs: 1,
      sync_success_rate: 0.96,
      health: "healthy",
      last_sync: "2026-09-01T02:00:00Z",
      last_sync_status: "success",
      last_sync_error: null,
    },
    {
      source_id: "ne301-docs",
      source_type: "github",
      product: "ne301",
      enabled: true,
      doc_count: 10,
      chunk_count: 100,
      window_days: 30,
      total_syncs: 3,
      success_syncs: 1,
      partial_syncs: 1,
      failed_syncs: 1,
      sync_success_rate: 0.3333,
      health: "critical",
      last_sync: "2026-09-01T01:00:00Z",
      last_sync_status: "failed",
      last_sync_error: "clone 失败",
    },
  ],
  days: 30,
});

mockTechPerf.mockResolvedValue({
  kpi: {
    p95_ms: 1200,
    anomaly_rate: 0.1,
    retry_rate: 0.05,
    fail_rate: 0.02,
    anomaly_count: 12,
    retry_count: 6,
    fail_count: 2,
    anomaly_delta: 0.03,
    retry_delta: -0.01,
    fail_delta: 0.0,
    baseline: 3000,
    comparison: 0.0,
  },
  stages: {
    intent: { p50: 50, p95: 80, normal_max: 500, p50_pct: 1, p95_pct: 2 },
    rewrite: { p50: 200, p95: 400, normal_max: 2000, p50_pct: 4, p95_pct: 8 },
    retrieve: { p50: 500, p95: 800, normal_max: 3000, p50_pct: 10, p95_pct: 16 },
    rerank: { p50: 300, p95: 600, normal_max: 2000, p50_pct: 6, p95_pct: 12 },
    generate: { p50: 3000, p95: 5000, normal_max: 2000, p50_pct: 60, p95_pct: 100 },
  },
  trends: Array.from({ length: 7 }, (_, i) => ({
    date: `08-0${i + 1}`,
    p50: 300,
    p95: 1000,
  })),
  anomalies: [{ type: "LLM 超时", count: 3, pct: 60.0 }],
  degradations: [{ from: "正常 RAG", to: "单路检索", reason: "向量库降级 2 次" }],
});

mockCoverageGaps.mockResolvedValue({
  items: [
    {
      id: "g1",
      cluster_type: "gap",
      representative_question: "如何接入 SDK",
      sample_questions: ["如何接入 SDK"],
      question_count: 5,
      status: "open",
      miss_type: "召回空",
      period_start: null,
      period_end: null,
      created_at: "2026-08-10T10:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  size: 20,
});

import Analytics from "@/pages/Analytics";

afterEach(cleanup);

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TechInsight 技术洞察页", () => {
  it("KPI 卡片显示 P95、异常率、重试率、失败率", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("P95 耗时")).toBeInTheDocument();
      expect(screen.getByText(/1,200/)).toBeInTheDocument();
      expect(screen.getByText("异常率")).toBeInTheDocument();
      expect(screen.getByText("重试率")).toBeInTheDocument();
      expect(screen.getByText("失败率")).toBeInTheDocument();
    });
  });

  it("P50/P95 趋势图渲染 7 柱且每柱含双段 + 基线虚线", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const bars = document.querySelectorAll("[data-bar]");
      expect(bars.length).toBe(7);
      bars.forEach((b) => {
        expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
        expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
      });
      // DualTrendBar 基线虚线
      expect(document.querySelector("[data-baseline]")).toBeTruthy();
    });
  });

  it("阶段表超标阶段 data-over=true", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute(
        "data-over",
        "true",
      );
      expect(screen.getByText("intent").closest("[data-over]")).toHaveAttribute(
        "data-over",
        "false",
      );
    });
  });

  it("切换到知识缺口 tab 显示覆盖缺口 + 类型 badge", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("知识缺口"));
    await waitFor(() => {
      expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
      // GapTypeBadge 渲染(mock miss_type="召回空")
      expect(document.querySelector("[data-gap-type='召回空']")).toBeTruthy();
    });
  });

  it("澄清漏斗显示暂无数据", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("知识缺口"));
    await waitFor(() => {
      expect(screen.getByText(/澄清漏斗/)).toBeInTheDocument();
      expect(screen.getByText(/暂无数据|待接入/)).toBeInTheDocument();
    });
  });
});

// ====================  DSH-02:数据源健康主位迁移至数据源管理  ====================


describe("DSH 技术洞察的数据源健康摘要", () => {
  it("呈现一行健康摘要(按 health 计数)+ 跳转数据源管理", async () => {
    renderWithProviders(<Analytics />);
    const summary = await screen.findByText("数据源健康(近 30 天)");
    expect(summary).toBeInTheDocument();
    // 计数摘要:正常 1 · 严重 1(不再逐源展开)
    expect(screen.getByText(/正常 1/)).toBeInTheDocument();
    expect(screen.getByText(/严重 1/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /明细与操作 → 数据源管理/ }),
    ).toHaveAttribute("href", "/data-sources");
  });

  it("不再呈现与数据源页竞争的完整健康表格(无成功率列/逐源行)", async () => {
    renderWithProviders(<Analytics />);
    await screen.findByText("数据源健康(近 30 天)");
    // 旧表格特征:逐源 source_id 行 + 裸百分比列头,均不应存在
    expect(screen.queryByText("website-camthink")).not.toBeInTheDocument();
    expect(screen.queryByText("同步成功率")).not.toBeInTheDocument();
    expect(screen.queryByText("文档数")).not.toBeInTheDocument();
  });
});
