import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: {
      items: [
        {
          id: "c1",
          question: "NE503 价格",
          intent_tag: "commercial",
          is_answered: true,
          response_time_ms: 1000,
          channel: "widget",
          created_at: "2026-08-10T10:00:00Z",
          feedback: "up",
          trace_summary: {
            stages: {
              intent: { ms: 50 },
              rewrite: { ms: 80 },
              retrieve: { ms: 200 },
              rerank: { ms: 120 },
              generate: { ms: 550 },
            },
            confidence: 0.45,
            markers: { retry: true, failure: false, clarify: false, reject_short: false, degraded: true },
          },
        },
      ],
      total: 1,
      page: 1,
      size: 20,
    },
    isLoading: false,
  }),
  useConversationDetail: () => ({
    data: {
      id: "c1",
      question: "NE503 价格",
      answer: "NE503 的价格请咨询销售",
      channel: "widget",
      language: "zh",
      sources: [],
      is_answered: true,
      feedback: null,
      response_time_ms: 1000,
      created_at: "2026-08-10T10:00:00Z",
      intent_tag: "commercial",
      clicks: [],
    },
  }),
  useTagConversation: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useBatchTag: () => ({ mutate: vi.fn(), isPending: false, data: null }),
}));

const { mockFetchTraces } = vi.hoisted(() => ({ mockFetchTraces: vi.fn() }));

vi.mock("@/lib/api/traces", () => ({ fetchTraces: mockFetchTraces }));

mockFetchTraces.mockResolvedValue([
  {
    id: "t1",
    conversation_id: "c1",
    prev_trace_id: null,
    turn_index: 0,
    type: "rag",
    stages: {
      intent: { ms: 50, category: "commercial", reason: "价格咨询" },
      rewrite: { ms: 80, rewritten: "NE503 价格多少" },
      retrieve: { ms: 200, hybrid_count: 15, min_results_met: true },
      rerank: { ms: 120, top_score: 0.82, count: 5 },
      generate: { ms: 550, tokens_output: 120, latency_ms: 540 },
      output: { ms: 5, sources_count: 3 },
    },
    total_ms: 1000,
    intent: "commercial",
    config_snapshot: {},
    created_at: "2026-08-10T10:00:00Z",
  },
]);

import Conversations from "@/pages/Conversations";

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

describe("Conversations 审查页", () => {
  it("列表显示问题、意图标签、总耗时", async () => {
    renderWithProviders(<Conversations />);
    await waitFor(() => {
      expect(screen.getByText("NE503 价格")).toBeInTheDocument();
      expect(screen.getAllByText(/commercial|商务/).length).toBeGreaterThan(0);
      expect(screen.getByText(/1,?000/)).toBeInTheDocument();
    });
  });

  it("点击行展开 trace 5 泳道", async () => {
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText("意图分类")).toBeInTheDocument();
      expect(screen.getByText("输出构建")).toBeInTheDocument();
    });
  });

  it("commercial 对话显示联系销售提示", async () => {
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/联系销售/)).toBeInTheDocument();
    });
  });

  it("trace 详情显示诊断 detail(召回/top分/token/来源)", async () => {
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/召回 15 条/)).toBeInTheDocument();
      expect(screen.getByText(/top分 0\.820/)).toBeInTheDocument();
      expect(screen.getByText(/输出 120 token/)).toBeInTheDocument();
      expect(screen.getByText(/来源 3 条/)).toBeInTheDocument();
    });
  });

  it("多轮对话可切换轮次查看 trace", async () => {
    mockFetchTraces.mockResolvedValueOnce([
      {
        id: "t1", conversation_id: "c1", turn_index: 0, type: "rag",
        stages: {
          intent: { ms: 50, category: "product" },
          retrieve: { ms: 200, hybrid_count: 10 },
          rerank: { ms: 120, top_score: 0.9 },
          generate: { ms: 500 },
          output: { ms: 5, sources_count: 2 },
        },
        total_ms: 800, intent: "product", config_snapshot: {}, created_at: "",
      },
      {
        id: "t2", conversation_id: "c1", turn_index: 1, type: "rag",
        stages: {
          intent: { ms: 40, category: "support" },
          retrieve: { ms: 300, hybrid_count: 5 },
          rerank: { ms: 100, top_score: 0.7 },
          generate: { ms: 600 },
          output: { ms: 5, sources_count: 1 },
        },
        total_ms: 1000, intent: "support", config_snapshot: {}, created_at: "",
      },
    ]);
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/召回 10 条/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("轮 2"));
    await waitFor(() => {
      expect(screen.getByText(/召回 5 条/)).toBeInTheDocument();
    });
  });

  it("列表显示搜索框", () => {
    renderWithProviders(<Conversations />);
    expect(screen.getByPlaceholderText(/搜索问题/)).toBeInTheDocument();
  });

  it("列表卡片显示用户反馈图标", async () => {
    renderWithProviders(<Conversations />);
    await waitFor(() => {
      expect(document.querySelector('[data-feedback="up"]')).toBeInTheDocument();
    });
  });

  it("trace 详情显示类型 badge", async () => {
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText("RAG 生成")).toBeInTheDocument();
    });
  });

  it("Phase 2:渲染快速筛选 toggle 栏 + markers 圆点", async () => {
    renderWithProviders(<Conversations />);
    await waitFor(() => {
      // 5 个 toggle 按钮(置信/失败/重试/反馈/澄清)
      const bar = document.querySelector("[data-toggle-bar]");
      expect(bar).toBeTruthy();
      const toggles = bar?.querySelectorAll("button[data-toggle]");
      expect(toggles?.length).toBe(5);
      // markers 圆点(retry + degraded 为 true)
      const markersHost = document.querySelector("[data-markers]");
      expect(markersHost).toBeTruthy();
      expect(markersHost?.querySelector('[data-marker="retry"]')).toBeTruthy();
      expect(markersHost?.querySelector('[data-marker="degraded"]')).toBeTruthy();
      // clarify/reject_short 为 false,不渲染
      expect(markersHost?.querySelector('[data-marker="clarify"]')).toBeNull();
    });
  });
});
