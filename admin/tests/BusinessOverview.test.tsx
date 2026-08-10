import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/businessOverview", () => ({
  fetchBusinessOverview: vi.fn().mockResolvedValue({
    service: {
      total: 120,
      intent_dist: { commercial: 30, product: 50, support: 35, off_topic: 5 },
      north_star: 18,
      satisfaction: 85,
    },
    leads: {
      valid: 12,
      potential: 8,
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
    geo: [],
    geo_note: "地域字段待接入",
    timeseries: [],
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
  it("渲染服务总览及意图分布", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      expect(screen.getByText(/总服务客户/)).toBeInTheDocument();
      expect(screen.getByText(/销售咨询/)).toBeInTheDocument();
      expect(screen.getAllByText(/有效线索/).length).toBeGreaterThan(0);
    });
  });

  it("下钻链接到 /conversations?intent=commercial", async () => {
    renderWithProviders(<BusinessOverview />);
    const link = await screen.findByText(/查看销售对话/);
    expect(link.closest("a")).toHaveAttribute(
      "href",
      expect.stringContaining("/conversations?intent=commercial"),
    );
  });
});
