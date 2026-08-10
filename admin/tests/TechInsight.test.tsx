import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { mockTechPerf, mockCoverageGaps } = vi.hoisted(() => ({
  mockTechPerf: vi.fn(),
  mockCoverageGaps: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchCoverageGaps: mockCoverageGaps,
}));

mockTechPerf.mockResolvedValue({
  kpi: { p95_ms: 1200, anomaly_rate: 0.1, retry_rate: 0.05, fail_rate: 0.02 },
  stages: {
    intent: { p50: 50, p95: 80, normal_max: 500 },
    rewrite: { p50: 200, p95: 400, normal_max: 2000 },
    retrieve: { p50: 500, p95: 800, normal_max: 3000 },
    rerank: { p50: 300, p95: 600, normal_max: 2000 },
    generate: { p50: 3000, p95: 5000, normal_max: 2000 },
  },
  trends: Array.from({ length: 7 }, (_, i) => ({
    date: `08-0${i + 1}`,
    p50: 300,
    p95: 1000,
  })),
  anomalies: [{ type: "LLM 超时", count: 3 }],
  degradations: [],
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
      expect(screen.getByText(/异常率/)).toBeInTheDocument();
      expect(screen.getByText(/重试|retry/i)).toBeInTheDocument();
      expect(screen.getByText(/失败率/)).toBeInTheDocument();
    });
  });

  it("P50/P95 趋势图渲染 7 柱且每柱含双段", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const bars = document.querySelectorAll("[data-bar]");
      expect(bars.length).toBe(7);
      bars.forEach((b) => {
        expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
        expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
      });
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

  it("切换到知识缺口 tab 显示覆盖缺口", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("知识缺口"));
    await waitFor(() => {
      expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
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
