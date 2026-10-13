import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
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
      effective_status: "contact_captured",
      contact_type: "email", contact_masked: "j***@example.com", has_contact: true,
      contact_captured_at: "2026-09-02T10:00:00+00:00", name: null, company: "Acme",
      contact_voided: false, contact_voided_at: null, contact_voided_by: null, contact_voided_reason: null,
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
      id: "lead-3", session_id: "sess-3", status: "contact_captured",
      effective_status: "potential",
      contact_type: "phone", contact_masked: "138******78", has_contact: false,
      contact_voided: true,
      contact_voided_at: "2026-10-01T09:00:00+00:00",
      contact_voided_by: "boss@test.com",
      contact_voided_reason: "时间戳被误判为电话",
      contact_captured_at: "2026-09-02T10:00:00+00:00", name: null, company: "VoidCo",
      region: null, product_interest: null, quantity: null, use_case: null,
      purchase_intent: null, timeline: null,
      ai_summary: null,
      prompt_count: 0, last_prompted_at: null,
      source_conversation_id: "c9", last_conversation_id: "c9",
      channel: "widget", language: "zh", country: null,
      handoff_at: null, handoff_by: null,
      created_at: "2026-09-02T06:00:00+00:00", updated_at: "2026-10-01T09:00:00+00:00",
    },
    {
      id: "lead-2", session_id: "sess-2", status: "potential",
      effective_status: "potential",
      contact_type: null, contact_masked: null, has_contact: false,
      contact_captured_at: null, name: null, company: null, region: null,
      contact_voided: false, contact_voided_at: null, contact_voided_by: null, contact_voided_reason: null,
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
  const mockVoidedDetail = {
    ...mockLeads[1],
    contact_value: "13800000000",
  };
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
    fetchSalesLeads: vi.fn().mockResolvedValue({ leads: mockLeads, total: 3 }),
    fetchSalesLead: vi
      .fn()
      .mockImplementation(async (id: string) =>
        id === "lead-3" ? mockVoidedDetail : mockDetail,
      ),
    fetchSalesLeadThread: vi.fn().mockResolvedValue(mockThread),
    handoffSalesLead: vi
      .fn()
      .mockResolvedValue({ ...mockDetail, status: "handed_off" }),
    voidSalesLeadContact: vi
      .fn()
      .mockImplementation(async (_id: string, reason: string) => ({
        ...mockDetail,
        contact_voided: true,
        has_contact: false,
        contact_voided_by: "admin@test.com",
        contact_voided_at: "2026-10-01T09:00:00+00:00",
        contact_voided_reason: reason,
      })),
  };
});

import SalesLeads, { LEAD_STATUS_META } from "@/pages/SalesLeads";
import { handoffSalesLead, voidSalesLeadContact } from "@/lib/api/salesLeads";

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
      expect(screen.getAllByTestId("lead-row").length).toBe(3);
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

  it("voids an invalid contact after explicit confirm with reason (#124)", async () => {
    renderPage();
    await waitFor(() => screen.getAllByTestId("lead-row"));
    fireEvent.click(screen.getAllByTestId("lead-row")[0]);
    await waitFor(() => screen.getByTestId("void-contact-btn"));

    // 打开确认对话框(二次确认流)
    fireEvent.click(screen.getByTestId("void-contact-btn"));
    await waitFor(() => screen.getByTestId("void-contact-dialog"));

    // 明确确认流:无理由时确认按钮禁用
    expect(screen.getByTestId("void-confirm-btn")).toBeDisabled();
    fireEvent.change(screen.getByTestId("void-reason-input"), {
      target: { value: "时间戳被误判为电话" },
    });
    expect(screen.getByTestId("void-confirm-btn")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("void-confirm-btn"));

    await waitFor(() => {
      expect(voidSalesLeadContact).toHaveBeenCalledWith("lead-1", "时间戳被误判为电话");
    });
  });

  it("shows voided badge and audit info, and hides void action for already voided lead", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("lead-row").length).toBe(3));
    // lead-3(VoidCo):已作废联系方式 —— 按内容定位,不依赖列表顺序
    const voidedRow = screen.getByText("VoidCo").closest('[data-testid="lead-row"]')!;
    fireEvent.click(voidedRow);
    await waitFor(() => {
      expect(screen.getByTestId("lead-detail")).toBeInTheDocument();
    });
    // 已作废徽章与审计信息可见
    await waitFor(() => {
      expect(screen.getByTestId("contact-voided-badge")).toBeInTheDocument();
    });
    expect(screen.getByTestId("contact-voided-audit")).toHaveTextContent("boss@test.com");
    expect(screen.getByTestId("contact-voided-audit")).toHaveTextContent("时间戳被误判为电话");
    // 已作废线索不再提供作废操作(幂等入口收缩)
    expect(screen.queryByTestId("void-contact-btn")).not.toBeInTheDocument();
  });

  it("renders effective status so voided contact no longer claims 已留联系方式 (#124 R2)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("lead-row").length).toBe(3));
    // 列表行:作废行按生效口径渲染 potential 徽章 + 作废徽章,不再并存
    // 「已留联系方式」与作废标记的矛盾呈现(AC2 运营视图一致不误导)
    const voidedRow = screen.getByText("VoidCo").closest('[data-testid="lead-row"]')!;
    expect(within(voidedRow).getByText("潜在线索")).toBeInTheDocument();
    expect(within(voidedRow).getByTestId("contact-voided-badge")).toBeInTheDocument();
    expect(within(voidedRow).queryByText("已留联系方式")).not.toBeInTheDocument();
    // 有效行不受影响
    const validRow = screen.getByText("Acme").closest('[data-testid="lead-row"]')!;
    expect(within(validRow).getByText("已留联系方式")).toBeInTheDocument();
    // 详情面板同样按生效口径渲染
    fireEvent.click(voidedRow);
    await waitFor(() => {
      expect(screen.getByTestId("lead-effective-status")).toHaveTextContent("潜在线索");
    });
  });
});
