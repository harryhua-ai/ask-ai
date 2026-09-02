import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/businessOverview", () => ({
  fetchBusinessOverview: vi.fn().mockResolvedValue({
    service: {
      total: 120,
      intent_dist: { commercial: 30, product: 50, support: 35, off_topic: 5 },
      unknown_intent_count: 2,
      north_star: 18,
      satisfaction: 85,
      up_count: 80,
      down_count: 15,
      prev_total: 100,
      delta_pct: 20.0,
    },
    leads: {
      commercial_conversations: 30,
      potential: 12,
      qualified: 8,
      contactable: 5,
      handed_off: 2,
      hot_products: [
        { name: "NE503", count: 10 },
        { name: "NE301", count: 6 },
      ],
    },
    scenes: [
      { label: "工业视觉", count: 15, pct: 50 },
      { label: "安防", count: 8, pct: 27 },
    ],
    requirements: [
      { label: "4K 录制", count: 9, pct: 30 },
      { label: "开放 API", count: 6, pct: 20 },
    ],
    top_questions: [
      { question: "NE503 价格", count: 8 },
      { question: "SDK 怎么接入", count: 5 },
    ],
    geo: [
      { name: "中国", count: 60, pct: 50 },
      { name: "美国", count: 30, pct: 25 },
    ],
    geo_note: "地域分布",
    timeseries: Array.from({ length: 7 }, (_, i) => ({
      date: `08-0${i + 1}`,
      total: 10 + i,
      commercial: 3,
      product: 4,
      support: 2,
      off_topic: 1,
    })),
  }),
  fetchBusinessOverviewRange: vi.fn(),
  refreshBusinessSignals: vi.fn().mockResolvedValue({
    scene_count: 0,
    requirement_count: 0,
  }),
  fetchHotQuestions: vi.fn().mockResolvedValue({
    items: [{ question: "NE503 价格", count: 5 }],
    intent: "commercial",
  }),
}));

import BusinessOverview from "@/pages/BusinessOverview";

afterEach(cleanup);

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("BusinessOverview", () => {
  it("渲染服务总览 + 意图堆叠条 + 三列意图卡", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      expect(screen.getByText(/总服务客户/)).toBeInTheDocument();
      // 销售咨询现多处出现(KPI 行的 intent_dist 已移除,但 StackedBar 图例 + IntentColumn)
      expect(screen.getAllByText(/销售咨询/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/产品方案/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/技术支持/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/销售线索/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/合格线索/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/可联系线索/).length).toBeGreaterThan(0);
    });
  });

  it("地域分布渲染 ProgressBar 含 [data-fill]", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      expect(screen.getByText(/中国/)).toBeInTheDocument();
      const fill = document.querySelector("[data-fill]");
      expect(fill).toBeTruthy();
    });
  });

  it("三列意图卡含 mini-trend 柱", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      const cols = document.querySelectorAll("[data-intent-column]");
      expect(cols.length).toBe(3);
      // 每列 7 根 mini-trend 柱
      expect(document.querySelectorAll("[data-bar]").length).toBeGreaterThanOrEqual(7);
    });
  });

  it("线索下钻链接到独立 /leads 页(LEAD-G008/G010)", async () => {
    renderWithProviders(<BusinessOverview />);
    const link = await screen.findByText(/查看线索列表/);
    expect(link.closest("a")).toHaveAttribute(
      "href",
      expect.stringContaining("/leads"),
    );
  });

  it("总服务客户显示环比 delta", async () => {
    renderWithProviders(<BusinessOverview />);
    // KpiCard 渲染 +20%(delta_pct=20,dir=up)
    const delta = await screen.findByText("+20%");
    expect(delta).toBeInTheDocument();
  });

  it("三列意图卡含热门问题 Top3", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      const cols = document.querySelectorAll("[data-intent-column]");
      expect(cols.length).toBe(3);
      // fetchHotQuestions mock 返回 "NE503 价格",三列 IntentColumn 内的 topQuestions 区域应渲染
      const topBlocks = document.querySelectorAll("[data-top-questions]");
      expect(topBlocks.length).toBe(3);
      expect(topBlocks[0].textContent).toContain("NE503 价格");
    });
  });
});
