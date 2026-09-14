/**
 * V1.6.3 Wave 1 Track E — U-15 观察状态机 + U-16 导出 前端行为测试。
 *
 * 契约(track-e-contract.md / IF-1 / IF-5;参考 PNG 权威):
 * - status filter 含 观察中 选项(IF-1 词表;GapStatusFilter 唯一挂载点);
 * - 状态徽章 观察中 = 蓝圈形系(StatusBadge;延续圈形图标语法);
 * - 历史记录 tab = 纯流转时间线(INT-E-01 收口;零重复动作);观察工作流
 *   (内容补充完成后 + CTA 副文案逐字「系统将验证数据同步状态，通过后进入
 *   观察中。」)与导出卡(隐私说明逐字)挂载于概览推荐操作区(组件直测);
 * - 开始观察点击 → confirmed=true 真实调用;409 gates 明细诚实呈现;
 * - 观察中态:观察窗元数据 + 中止观察;
 * - 导出点击 → 真实下载行为(blob + download 锚点),非前端造 CSV。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const {
  mockFetchGapObservation,
  mockFetchGapObservationEvents,
  mockStartGapObservation,
  mockAbortGapObservation,
  mockFetchGapExportAudits,
  mockGetToken,
  mockGlobalFetch,
} = vi.hoisted(() => ({
  mockFetchGapObservation: vi.fn(),
  mockFetchGapObservationEvents: vi.fn(),
  mockStartGapObservation: vi.fn(),
  mockAbortGapObservation: vi.fn(),
  mockFetchGapExportAudits: vi.fn(),
  mockGetToken: vi.fn(),
  mockGlobalFetch: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    fetchGapObservation: mockFetchGapObservation,
    fetchGapObservationEvents: mockFetchGapObservationEvents,
    startGapObservation: mockStartGapObservation,
    abortGapObservation: mockAbortGapObservation,
    fetchGapExportAudits: mockFetchGapExportAudits,
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, getToken: mockGetToken };
});

import { GapStatusFilter, type GapStatusFilterValue } from "@/pages/analytics/GapStatusFilter";
import { StatusBadge } from "@/pages/analytics/StatusBadge";
import { PanelHistory } from "@/pages/analytics/PanelHistory";
import { GapObservationSection } from "@/pages/analytics/GapObservationSection";
import { GapExportCard } from "@/pages/analytics/GapExportCard";
import type { AnswerGapItem, GapObservationState } from "@/lib/api/techInsight";

const GAP: AnswerGapItem = {
  id: "ebeb0000-0000-4000-8000-000000000001",
  cluster_type: "gap",
  representative_question: "NE101 PoE 支持信息缺失",
  sample_questions: ["NE101 是否支持 PoE?"],
  question_count: 23,
  impacted_answer_count: 18,
  status: "open",
  miss_type: "召回空",
  miss_type_breakdown: { "召回空": 3 },
  last_seen_at: "2026-09-13T02:00:00+00:00",
  period_start: null,
  period_end: null,
  created_at: "2026-09-10T00:00:00+00:00",
};

function observationState(overrides: Partial<GapObservationState> = {}): GapObservationState {
  return {
    gap_id: GAP.id,
    status: "open",
    observation: null,
    recurrence: null,
    ...overrides,
  };
}

function renderUI(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mockGetToken.mockReturnValue("test-token");
  mockFetchGapObservation.mockResolvedValue(observationState());
  mockFetchGapObservationEvents.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

// --------------------------------------------------------------------------- //
// status filter(IF-1 观察中选项;唯一挂载点)
// --------------------------------------------------------------------------- //

describe("GapStatusFilter:IF-1 observing 选项", () => {
  it("选项 = 全部状态/需要处理/观察中/已解决(观察中在位)", () => {
    const onChange = vi.fn();
    renderUI(<GapStatusFilter value="" onChange={onChange} />);
    const select = document.querySelector("[data-filter-status]") as HTMLSelectElement;
    expect(select).toBeTruthy();
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["", "open", "observing", "resolved"]);
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual(["全部状态", "需要处理", "观察中", "已解决"]);
  });

  it("选择 观察中 → onChange('observing')(过滤值直通队列 status 查询)", () => {
    const onChange = vi.fn();
    renderUI(<GapStatusFilter value={"" as GapStatusFilterValue} onChange={onChange} />);
    const select = document.querySelector("[data-filter-status]") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "observing" } });
    expect(onChange).toHaveBeenCalledWith("observing");
  });
});

// --------------------------------------------------------------------------- //
// 状态徽章:观察中 蓝圈形系
// --------------------------------------------------------------------------- //

describe("StatusBadge:observing 蓝态", () => {
  it("data-status=observing,文案 观察中,圈形图标(外圈+内圈),蓝色系", () => {
    renderUI(<StatusBadge status="observing" />);
    const badge = document.querySelector('[data-gap-status][data-status="observing"]');
    expect(badge).toBeTruthy();
    expect(badge?.textContent).toBe("观察中");
    const circles = badge?.querySelectorAll("svg circle");
    expect(circles?.length).toBe(2);
    expect(badge?.getAttribute("style")).toContain("var(--acc)");
  });

  it("既有两态零回归:open → 需要处理(红);resolved → 已解决(绿)", () => {
    const { container: c1 } = renderUI(<StatusBadge status="open" />);
    expect(
      c1.querySelector('[data-gap-status][data-status="open"]')?.textContent,
    ).toBe("需要处理");
    cleanup();
    const { container: c2 } = renderUI(<StatusBadge status="resolved" />);
    expect(
      c2.querySelector('[data-gap-status][data-status="resolved"]')?.textContent,
    ).toBe("已解决");
  });
});

// --------------------------------------------------------------------------- //
// 概览挂点组件(INT-E-01):GapObservationSection(U-15 三前置门 CTA)+
// GapExportCard(U-16)。挂载面 = GapPanel 概览推荐操作区;PanelHistory =
// 纯流转时间线(零重复动作)。
// --------------------------------------------------------------------------- //

describe("GapObservationSection + GapExportCard(U-15 三前置门 CTA / U-16 导出卡)", () => {
  it("open 态:内容补充完成后 区块 + 开始观察 CTA(副文案逐字)+ 导出卡(隐私说明逐字)", async () => {
    renderUI(
      <>
        <GapObservationSection gap={GAP} />
        <GapExportCard gap={GAP} />
      </>,
    );
    await waitFor(() => {
      expect(screen.getByText("内容补充完成后")).toBeInTheDocument();
    });
    expect(screen.getByText("▷ 内容已补充,开始观察")).toBeInTheDocument();
    expect(
      screen.getByText("系统将验证数据同步状态，通过后进入观察中。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/导出相关对话/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "导出内容包含用户问题、对话上下文、当前回答及引用信息,不包含用户个人身份信息。",
      ),
    ).toBeInTheDocument();
  });

  it("点击 开始观察 → startGapObservation(gap.id, true) 真实调用", async () => {
    mockStartGapObservation.mockResolvedValue(observationState());
    renderUI(<GapObservationSection gap={GAP} />);
    await waitFor(() => {
      expect(screen.getByText("▷ 内容已补充,开始观察")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("▷ 内容已补充,开始观察"));
    await waitFor(() => {
      expect(mockStartGapObservation).toHaveBeenCalledWith(GAP.id, true);
    });
  });

  it("后端 409 三前置门未过 → gates 明细诚实呈现(不伪造成功)", async () => {
    const { ApiError } = await import("@/lib/api");
    mockStartGapObservation.mockRejectedValue(
      new ApiError(
        409,
        "gate failed",
        { code: "gate_failed", gates: { sync: { "we-src": "last_sync_not_completed" } } },
      ),
    );
    renderUI(<GapObservationSection gap={GAP} />);
    fireEvent.click(await screen.findByText("▷ 内容已补充,开始观察"));
    await waitFor(() => {
      expect(document.querySelector("[data-observation-error]")?.textContent).toContain(
        "相关数据源同步未完成或无同步证据",
      );
    });
  });

  it("observing 态:观察窗元数据 + 中止观察 → abort 真实调用", async () => {
    mockAbortGapObservation.mockResolvedValue(observationState());
    mockFetchGapObservation.mockResolvedValue(
      observationState({
        status: "observing",
        observation: {
          started_at: "2026-09-12T00:00:00+00:00",
          window_days: 7,
          window_ends_at: "2026-09-19T00:00:00+00:00",
          is_active: true,
          ended_at: null,
          ended_reason: null,
        },
        recurrence: { recurred: false, new_evidence_count: 0 },
      }),
    );
    renderUI(<GapObservationSection gap={{ ...GAP, status: "observing" }} />);
    await waitFor(() => {
      expect(screen.getByText("中止观察(回到待处理)")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("中止观察(回到待处理)"));
    await waitFor(() => {
      expect(mockAbortGapObservation).toHaveBeenCalledWith(GAP.id);
    });
  });
});

describe("PanelHistory:流转时间线(U-15 History 可见;INT-E-01 后 = 纯历史零重复动作)", () => {
  it("渲染全部持久化流转事件(时间戳/from→to/操作者),最新在前;无观察/导出动作", async () => {
    mockFetchGapObservationEvents.mockResolvedValue({
      items: [
        {
          id: "ev-1",
          event_type: "start",
          from_status: "open",
          to_status: "observing",
          actor: "admin@camthink.ai",
          detail: { window_days: 7 },
          created_at: "2026-09-12T00:00:00+00:00",
        },
        {
          id: "ev-2",
          event_type: "resolve",
          from_status: "observing",
          to_status: "resolved",
          actor: null,
          detail: {},
          created_at: "2026-09-19T00:00:00+00:00",
        },
      ],
      total: 2,
    });
    renderUI(<PanelHistory gap={GAP} />);
    const timeline = await screen.findByText("流转历史");
    expect(timeline).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector('[data-history-event="start"]')).toBeTruthy();
      expect(document.querySelector('[data-history-event="resolve"]')).toBeTruthy();
    });
    // 最新在前(resolve 先渲染)
    const first = document.querySelector("[data-gap-history-timeline] li");
    expect(first?.getAttribute("data-history-event")).toBe("resolve");
    expect(document.querySelector('[data-history-event="start"]')?.textContent).toContain(
      "admin@camthink.ai",
    );
    // INT-E-01:概览与历史零重复动作 —— 历史 tab 无观察 CTA/导出卡
    expect(screen.queryByText("▷ 内容已补充,开始观察")).not.toBeInTheDocument();
    expect(screen.queryByText(/导出相关对话/)).not.toBeInTheDocument();
    expect(document.querySelector("[data-gap-export-card]")).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// 导出卡:真实下载行为(blob 下载,非前端造 CSV)
// --------------------------------------------------------------------------- //

describe("GapExportCard:真实 CSV 下载", () => {
  it("点击导出 → 携带认证头请求权威范围端点 → blob 下载", async () => {
    const blob = new Blob(["conversation_id\nx"], { type: "text/csv" });
    mockGlobalFetch.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => blob,
    });
    vi.stubGlobal("fetch", mockGlobalFetch);
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true, writable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true, writable: true });
    HTMLAnchorElement.prototype.click = vi.fn();

    renderUI(<GapExportCard gap={GAP} />);
    fireEvent.click(await screen.findByText(/导出相关对话/));
    await waitFor(() => {
      expect(mockGlobalFetch).toHaveBeenCalledWith(
        `/api/admin/tech/answer-gaps/${GAP.id}/conversations/export`,
        { headers: { Authorization: "Bearer test-token" } },
      );
      expect(createObjectURL).toHaveBeenCalled();
    });
  });

  it("403(非 admin)→ 权限语义诚实呈现", async () => {
    mockGlobalFetch.mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal("fetch", mockGlobalFetch);
    renderUI(<GapExportCard gap={GAP} />);
    fireEvent.click(await screen.findByText(/导出相关对话/));
    await waitFor(() => {
      expect(document.querySelector("[data-export-error]")?.textContent).toContain("无权限");
    });
  });
});
