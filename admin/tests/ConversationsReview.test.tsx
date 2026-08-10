import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
          trace_summary: {
            stages: {
              intent: { ms: 50 },
              rewrite: { ms: 80 },
              retrieve: { ms: 200 },
              rerank: { ms: 120 },
              generate: { ms: 550 },
            },
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
      intent: { ms: 50 },
      rewrite: { ms: 80 },
      retrieve: { ms: 200 },
      rerank: { ms: 120 },
      generate: { ms: 550 },
      output: { ms: 5 },
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
  it("列表显示问题、意图标签、迷你阶段条、总耗时", async () => {
    renderWithProviders(<Conversations />);
    await waitFor(() => {
      expect(screen.getByText("NE503 价格")).toBeInTheDocument();
      expect(screen.getAllByText(/commercial|商务/).length).toBeGreaterThan(0);
      expect(screen.getByText(/1,?000/)).toBeInTheDocument();
      expect(document.querySelectorAll("[data-bar-seg]").length).toBeGreaterThan(0);
    });
  });

  it("点击行展开 trace 5 泳道", async () => {
    renderWithProviders(<Conversations />);
    const row = await screen.findByText("NE503 价格");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText("前置")).toBeInTheDocument();
      expect(screen.getByText("输出")).toBeInTheDocument();
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
});
