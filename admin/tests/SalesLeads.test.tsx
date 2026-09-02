import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "admin@test.com",
      name: null,
      role: "admin",
      is_active: true,
    },
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock("@/lib/api/salesLeads", () => {
  const mockLeads = [
    {
      id: "lead-1", session_id: "sess-1", status: "contact_captured",
      contact_type: "email", contact_masked: "j***@example.com", has_contact: true,
      contact_captured_at: "2026-09-02T10:00:00+00:00", name: null, company: "Acme",
      region: null, product_interest: "NE503", quantity: "500 台", use_case: null,
      purchase_intent: null, timeline: null,
      ai_summary: "Acme 计划采购 500 台 NE503,要求正式报价",
      prompt_count: 1, last_prompted_at: "2026-09-02T09:00:00+00:00",
      source_conversation_id: "c1", last_conversation_id: "c2",
      channel: "widget", language: "zh", country: null,
      handoff_at: null, handoff_by: null,
      created_at: "2026-09-02T08:00:00+00:00", updated_at: "2026-09-02T10:00:00+00:00",
    },
    {
      id: "lead-2", session_id: "sess-2", status: "potential",
      contact_type: null, contact_masked: null, has_contact: false,
      contact_captured_at: null, name: null, company: null, region: null,
      product_interest: null, quantity: null, use_case: null,
      purchase_intent: null, timeline: null, ai_summary: null,
      prompt_count: 0, last_prompted_at: null,
      source_conversation_id: "c3", last_conversation_id: "c3",
      channel: "widget", language: "en", country: "US",
      handoff_at: null, handoff_by: null,
      created_at: "2026-09-02T07:00:00+00:00", updated_at: "2026-09-02T07:00:00+00:00",
    },
  ];
  const mockDetail = { ...mockLeads[0], contact_value: "john@example.com" };
  const mockThread = {
    session_id: "sess-1",
    messages: [
      {
        conversation_id: "c1", role: "user",
        question: "我们需要500台NE503,请给正式报价",
        answer: "NE503 批量采购可提供正式报价…",
        intent_tag: "commercial", channel: "widget",
        created_at: "2026-09-02T08:00:00+00:00",
      },
    ],
  };
  return {
    fetchSalesLeads: vi.fn().mockResolvedValue({ leads: mockLeads, total: 2 }),
    fetchSalesLead: vi.fn().mockResolvedValue(mockDetail),
    fetchSalesLeadThread: vi.fn().mockResolvedValue(mockThread),
    handoffSalesLead: vi
      .fn()
      .mockResolvedValue({ ...mockDetail, status: "handed_off" }),
  };
});

import SalesLeads, { LEAD_STATUS_META } from "@/pages/SalesLeads";
import { handoffSalesLead } from "@/lib/api/salesLeads";

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <BrowserRouter>
      <QueryClientProvider client={qc}>
        <SalesLeads />
      </QueryClientProvider>
    </BrowserRouter>,
  );
}

beforeEach(() => {
  localStorage.setItem("ask-ai-admin-token", "fake-token");
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("SalesLeads page", () => {
  it("renders lead list rows with status labels", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getAllByTestId("lead-row").length).toBe(2);
    });
    expect(screen.getAllByText("已留联系方式").length).toBeGreaterThan(0);
    expect(screen.getAllByText("潜在线索").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Acme").length).toBeGreaterThan(0);
    expect(screen.getByText("j***@example.com")).toBeInTheDocument();
    // 未留联系方式的线索显示占位,不显示原文
    expect(screen.getByText("未提供")).toBeInTheDocument();
    expect(screen.queryByText("john@example.com")).not.toBeInTheDocument();
  });

  it("opens detail panel with full contact and thread view (LEAD-G009)", async () => {
    renderPage();
    await waitFor(() => screen.getAllByTestId("lead-row"));
    fireEvent.click(screen.getAllByTestId("lead-row")[0]);

    await waitFor(() => {
      expect(screen.getByTestId("lead-detail")).toBeInTheDocument();
    });
    // 详情含联系方式原文(销售跟进需要)
    await waitFor(() => {
      expect(screen.getByText(/john@example.com/)).toBeInTheDocument();
    });
    // 查看完整对话
    fireEvent.click(screen.getByTestId("toggle-thread"));
    await waitFor(() => {
      expect(screen.getByTestId("lead-thread")).toBeInTheDocument();
    });
    expect(screen.getByText("我们需要500台NE503,请给正式报价")).toBeInTheDocument();
  });

  it("handoff action calls api and shows handed off state", async () => {
    renderPage();
    await waitFor(() => screen.getAllByTestId("lead-row"));
    fireEvent.click(screen.getAllByTestId("lead-row")[0]);
    await waitFor(() => screen.getByTestId("handoff-btn"));
    fireEvent.click(screen.getByTestId("handoff-btn"));
    await waitFor(() => {
      expect(handoffSalesLead).toHaveBeenCalledWith("lead-1");
    });
  });

  it("status tabs filter the list", async () => {
    const { fetchSalesLeads } = await import("@/lib/api/salesLeads");
    renderPage();
    await waitFor(() => screen.getAllByTestId("lead-row"));
    fireEvent.click(screen.getByRole("button", { name: "已留联系方式" }));
    await waitFor(() => {
      expect(fetchSalesLeads).toHaveBeenCalledWith(
        expect.objectContaining({ status: "contact_captured" }),
      );
    });
  });

  it("status meta covers full lifecycle", () => {
    expect(Object.keys(LEAD_STATUS_META).sort()).toEqual(
      ["contact_captured", "handed_off", "potential", "qualified"].sort(),
    );
  });
});
