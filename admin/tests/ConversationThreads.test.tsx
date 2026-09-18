import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Conversations from "@/pages/Conversations";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));

const mockThreads = vi.fn();
const mockThreadDetail = vi.fn();
vi.mock("@/hooks/useConversationThreads", () => ({
  useConversationThreads: (filters: unknown, enabled: boolean) =>
    mockThreads(filters, enabled),
  useConversationThread: (id: string | null) => mockThreadDetail(id),
}));

const { mockFetchTraces } = vi.hoisted(() => ({ mockFetchTraces: vi.fn() }));
vi.mock("@/lib/api/traces", () => ({
  fetchTraces: (...a: unknown[]) => mockFetchTraces(...a),
}));

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: { items: [], total: 0, page: 1, size: 20 },
    isLoading: false,
  }),
  useConversationDetail: () => ({ data: undefined }),
  useTagConversation: () => ({ mutate: vi.fn(), isPending: false }),
  useBatchTag: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useEntryOptions: () => ({ data: [] }),
  useCountryOptions: () => ({ data: { countries: [] } }),
}));

const THREAD = {
  thread_id: "thread_abc1234567",
  first_question: "如何配置 NeoMind webhook",
  turn_count: 3,
  started_at: "2026-09-18T10:00:00Z",
  last_activity_at: "2026-09-18T10:20:00Z",
  intent_tag: "support",
  channel: "widget",
  site_id: "site-a",
  entry: { site_id: "site-a", display_name: "官网" },
  country: "DE",
  country_source: "ingress",
  has_abnormal: false,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Conversations />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Conversation Review 会话模式(#87)", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    mockThreadDetail.mockReturnValue({ data: undefined });
    mockThreads.mockReturnValue({
      data: { items: [THREAD], total: 1, page: 1, size: 20 },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  it("默认单轮模式:线程查询不启用(enabled=false),不渲染线程卡片", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "单轮" })).toBeTruthy();
    expect(document.querySelector("[data-thread-card]")).toBeNull();
    expect(mockThreads.mock.calls[0][1]).toBe(false);
  });

  it("切换到会话模式:紧凑线程卡片呈现真实派生字段(首问/轮数/入口/国家)", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "会话" }));
    await waitFor(() => expect(document.querySelector("[data-thread-card]")).toBeTruthy());
    expect(screen.getByText("如何配置 NeoMind webhook")).toBeTruthy();
    expect(screen.getByText("3 轮")).toBeTruthy();
    expect(screen.getByText("DE · 官网")).toBeTruthy();
    expect(screen.getByText(/thread_abc1234567/)).toBeTruthy();
    // 单轮专属控件在会话模式隐藏(轮级 toggle)
    expect(document.querySelector("[data-toggle-bar]")).toBeNull();
  });

  it("点击线程打开 transcript-first 详情;查看 Trace 复用既有诊断数据面", async () => {
    mockThreadDetail.mockReturnValue({
      data: {
        thread_id: "thread_abc1234567",
        turn_count: 2,
        started_at: "2026-09-18T10:00:00Z",
        last_activity_at: "2026-09-18T10:20:00Z",
        session_id: "s1",
        channel: "widget",
        entry: { site_id: "site-a", display_name: "官网" },
        country: "DE",
        country_source: "ingress",
        turns: [
          {
            id: "conv-1",
            question: "如何配置 NeoMind webhook",
            answer: "在站点设置中填写回调地址。",
            is_answered: true,
            intent_tag: "support",
            channel: "widget",
            created_at: "2026-09-18T10:00:00Z",
            response_time_ms: 1200,
          },
          {
            id: "conv-2",
            question: "签名怎么验证?",
            answer: "使用 HMAC-SHA256。",
            is_answered: true,
            intent_tag: "support",
            channel: "widget",
            created_at: "2026-09-18T10:20:00Z",
            response_time_ms: 900,
          },
        ],
      },
    });
    mockFetchTraces.mockResolvedValue([
      {
        id: "tr1",
        conversation_id: "conv-1",
        turn_index: 0,
        type: "rag",
        stages: {},
        total_ms: 800,
        confidence: 0.9,
      },
    ]);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "会话" }));
    await waitFor(() => expect(document.querySelector("[data-thread-card]")).toBeTruthy());
    fireEvent.click(screen.getByText("如何配置 NeoMind webhook"));
    await waitFor(() => expect(document.querySelector("[data-thread-detail]")).toBeTruthy());
    const turns = document.querySelectorAll("[data-transcript-turn]");
    expect(turns.length).toBe(2);
    expect(screen.getByText("签名怎么验证?")).toBeTruthy();
    // 展开第一轮 Trace(复用既有 fetchTraces + 阶段面板)
    fireEvent.click(screen.getAllByText("查看 Trace")[0]);
    await waitFor(() => expect(document.querySelectorAll("[data-trace-meta]").length).toBeGreaterThan(0));
    expect(mockFetchTraces).toHaveBeenCalledWith("conv-1");
  });
});
