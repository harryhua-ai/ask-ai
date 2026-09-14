/** V1.6.3 Wave 1 Track A — IF-7 单一共享分析窗状态(词表/解析/三控制面绑定)。
 *
 * 冻结词表(IF-7,remediation plan §3.5):{今日 today, 近7天 7d, 近30天 30d,
 * 全部 all, 显式起止 from/to};默认 近 7 天。SH-09 顶栏控件、TI-10 缺口工具栏
 * 窗选择(data-filter-window)、tech tab TimeFilter 为同一窗状态的三个呈现面;
 * 改动任一 → 各窗口面(S1 performance / S2 source-health / S5 answer-gaps 队列)
 * 真实联动。S2 硬编码 days=30 → 绑定共享窗(以解析后的 from/to 请求)。
 * (S1 fetch 参数构建单元断言见 AnalysisWindowApi.test.ts —— 该文件 mock 本模块。)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const {
  mockTechPerf,
  mockSourceHealth,
  mockSyncIncidents,
  mockGenerationEvents,
  mockAnswerGaps,
  mockGapConversations,
} = vi.hoisted(() => ({
  mockTechPerf: vi.fn(),
  mockSourceHealth: vi.fn(),
  mockSyncIncidents: vi.fn(),
  mockGenerationEvents: vi.fn(),
  mockAnswerGaps: vi.fn(),
  mockGapConversations: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchSourceHealth: mockSourceHealth,
  fetchSyncIncidents: mockSyncIncidents,
  fetchGenerationEvents: mockGenerationEvents,
  fetchAnswerGaps: mockAnswerGaps,
  fetchGapConversations: mockGapConversations,
}));

import Analytics from "@/pages/Analytics";
import { AnalyticsWindowControl } from "@/pages/analytics/AnalyticsWindowControl";
import {
  AnalysisWindowProvider,
  useAnalysisWindow,
  resolveAnalysisWindow,
  windowLabel,
  ANALYSIS_WINDOW_DEFAULT,
} from "@/lib/analysisWindow";

beforeEach(() => {
  mockTechPerf.mockReset();
  mockSourceHealth.mockReset();
  mockSyncIncidents.mockReset();
  mockGenerationEvents.mockReset();
  mockAnswerGaps.mockReset();
  mockGapConversations.mockReset();
  mockSourceHealth.mockResolvedValue({ items: [], days: 30 });
  mockSyncIncidents.mockResolvedValue({
    failed: { items: [], total: 0, page: 1, size: 10 },
    interrupted: { items: [], total: 0, page: 1, size: 10 },
  });
  mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });
  mockAnswerGaps.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    size: 10,
    miss_type_summary: {},
  });
  mockGapConversations.mockResolvedValue({ items: [], total: 0 });
  mockTechPerf.mockResolvedValue(techPayload());
});

afterEach(cleanup);

function techPayload() {
  return {
    kpi: {
      p95_ms: 1200,
      anomaly_rate: 0,
      fail_rate: 0,
      recovered_rate: 0,
      anomaly_count: 0,
      fail_count: 0,
      recovered_count: 0,
      anomaly_delta: null,
      fail_delta: null,
      recovered_delta: null,
      failure_kinds: {},
      trace_total: 12,
      window: { from: "2026-09-06T00:00:00", to: "2026-09-13T00:00:00" },
      baseline: 3000,
      baseline_source: "previous_window",
      comparison: 0,
    },
    stages: {
      intent: { p50: 50, p95: 80, normal_max: 3000, over_count: 0, p50_pct: 1, p95_pct: 2 },
      rewrite: { p50: 200, p95: 400, normal_max: 4000, over_count: 0, p50_pct: 4, p95_pct: 8 },
      retrieve: { p50: 500, p95: 800, normal_max: 3000, over_count: 0, p50_pct: 10, p95_pct: 16 },
      rerank: { p50: 300, p95: 600, normal_max: 3000, over_count: 0, p50_pct: 6, p95_pct: 12 },
      generate: { p50: 3000, p95: 5000, normal_max: 30000, over_count: 0, p50_pct: 60, p95_pct: 100 },
      output: { p50: 0, p95: 0, normal_max: 100, over_count: 0, p50_pct: 0, p95_pct: 0 },
    },
    trends: [],
    anomalies: [],
    degradations: [],
    health: { status: "healthy", reasons: [], sample_size: 12 },
    trace_coverage_from: "2026-08-01T00:00:00Z",
  };
}

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function Probe({ to = "30d" }: { to?: string }) {
  const { value, setValue } = useAnalysisWindow();
  return (
    <button data-probe onClick={() => setValue(to as never)}>
      probe:{value}
    </button>
  );
}

// ----------------------------------------------------------------------- //

describe("IF-7 分析窗词表解析(resolveAnalysisWindow)", () => {
  it("默认值 = 7d(近 7 天)", () => {
    expect(ANALYSIS_WINDOW_DEFAULT).toBe("7d");
  });

  it("today = UTC 日历日起点 → now;7d/30d = now-Nd → now", () => {
    const before = Date.now();
    const t = resolveAnalysisWindow("today");
    const after = Date.now();
    // fromISO 为无时区后缀的 UTC ISO(传输约定)→ 测试端解析需补 Z
    expect(new Date(`${t.fromISO}Z`).getTime()).toBe(
      new Date(new Date(before).toISOString().slice(0, 10) + "T00:00:00.000Z").getTime(),
    );
    expect(new Date(`${t.toISO}Z`).getTime()).toBeGreaterThanOrEqual(before);
    expect(new Date(`${t.toISO}Z`).getTime()).toBeLessThanOrEqual(after);

    const w7 = resolveAnalysisWindow("7d");
    expect(new Date(`${w7.toISO}Z`).getTime()).toBeGreaterThanOrEqual(before);
    expect(
      Math.round(
        (new Date(`${w7.toISO}Z`).getTime() - new Date(`${w7.fromISO}Z`).getTime()) / 86400000,
      ),
    ).toBe(7);

    const w30 = resolveAnalysisWindow("30d");
    expect(
      Math.round(
        (new Date(`${w30.toISO}Z`).getTime() - new Date(`${w30.fromISO}Z`).getTime()) / 86400000,
      ),
    ).toBe(30);
  });

  it("all = 显式起止表达(远早锚点 2000-01-01 → now);显式起止 = 起日 00:00Z → 结束日全天含", () => {
    const before = Date.now();
    const all = resolveAnalysisWindow("all");
    expect(all.fromISO.startsWith("2000-01-01")).toBe(true);
    expect(new Date(`${all.toISO}Z`).getTime()).toBeGreaterThanOrEqual(before);

    const ex = resolveAnalysisWindow("range:2026-09-01/2026-09-09");
    expect(ex.fromISO.startsWith("2026-09-01T00:00:00")).toBe(true);
    expect(ex.toISO.startsWith("2026-09-09T23:59:59")).toBe(true);
  });

  it("词表标签:今日/过去 7 天/过去 30 天/全部时间/显式起止 span", () => {
    expect(windowLabel("today")).toBe("今日");
    expect(windowLabel("7d")).toBe("过去 7 天");
    expect(windowLabel("30d")).toBe("过去 30 天");
    expect(windowLabel("all")).toBe("全部时间");
    expect(windowLabel("range:2026-09-01/2026-09-09")).toBe("2026-09-01 → 2026-09-09");
  });
});

describe("S2 绑定:source-health 随共享窗请求(替换硬编码 days=30)", () => {
  it("TechPerfTab 以共享窗解析的 from/to 请求 source-health(非 days=30)", async () => {
    renderWithProviders(
      <AnalysisWindowProvider>
        <Analytics />
      </AnalysisWindowProvider>,
    );
    await waitFor(() => expect(mockSourceHealth).toHaveBeenCalled());
    const arg = mockSourceHealth.mock.calls.at(-1)![0];
    expect(arg).toEqual(
      expect.objectContaining({ from: expect.any(String), to: expect.any(String) }),
    );
    expect(arg.from).toBeTruthy();
    expect(arg.to).toBeTruthy();
  });
});

describe("三控制面绑定(单一共享窗状态)", () => {
  it("tech tab TimeFilter 改窗 → TechPerfTab 以所选窗请求(30d)", async () => {
    renderWithProviders(
      <AnalysisWindowProvider>
        <Analytics />
      </AnalysisWindowProvider>,
    );
    await waitFor(() => expect(mockTechPerf).toHaveBeenCalledWith("7d"));
    fireEvent.click(screen.getByRole("button", { name: "30 天" }));
    await waitFor(() => expect(mockTechPerf).toHaveBeenCalledWith("30d"));
  });

  it("共享状态外部变更(probe 模拟顶栏)→ tech 窗面真实联动", async () => {
    renderWithProviders(
      <AnalysisWindowProvider>
        <Probe />
        <Analytics />
      </AnalysisWindowProvider>,
    );
    await waitFor(() => expect(mockTechPerf).toHaveBeenCalledWith("7d"));
    fireEvent.click(screen.getByRole("button", { name: "probe:7d" }));
    await waitFor(() => expect(mockTechPerf).toHaveBeenCalledWith("30d"));
  });

  it("缺口队列窗选择(data-filter-window)与共享状态双向绑定;改窗 → S5 请求参数可见变化", async () => {
    renderWithProviders(
      <AnalysisWindowProvider>
        <Probe to="all" />
        <Analytics />
      </AnalysisWindowProvider>,
    );
    // 切到 回答缺口 tab
    fireEvent.click(screen.getByRole("tab", { name: "回答缺口" }));
    await waitFor(() => expect(mockAnswerGaps).toHaveBeenCalled());
    const select = document.querySelector<HTMLSelectElement>("[data-filter-window]")!;
    expect(select).toBeTruthy();
    // 缺口工具栏控制面改窗 → S5 请求 window 参数变化
    fireEvent.change(select, { target: { value: "30d" } });
    await waitFor(() =>
      expect(mockAnswerGaps).toHaveBeenCalledWith(expect.objectContaining({ window: "30d" })),
    );
    // 共享状态外部变更 → 队列控制面同步(无窗口面停留异窗)
    fireEvent.click(screen.getByRole("button", { name: "probe:30d" }));
    await waitFor(() =>
      expect(mockAnswerGaps).toHaveBeenCalledWith(expect.objectContaining({ window: "all" })),
    );
    expect((document.querySelector("[data-filter-window]") as HTMLSelectElement).value).toBe("all");
  });

  it("AnalyticsWindowControl 呈现 IF-7 全词表(今日/过去 7 天/过去 30 天/全部时间/明确起止)", () => {
    renderWithProviders(
      <AnalysisWindowProvider>
        <AnalyticsWindowControl value="7d" onChange={() => {}} />
      </AnalysisWindowProvider>,
    );
    const select = document.querySelector<HTMLSelectElement>("[data-filter-window]")!;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("today");
    expect(options).toContain("7d");
    expect(options).toContain("30d");
    expect(options).toContain("all");
    expect(options).toContain("__explicit__");
  });

  it("明确起止:选择后出现开始/结束日历输入;两者齐备才可应用;应用 → onChange(range:from/to)", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <AnalysisWindowProvider>
        <AnalyticsWindowControl value="7d" onChange={onChange} />
      </AnalysisWindowProvider>,
    );
    const select = document.querySelector<HTMLSelectElement>("[data-filter-window]")!;
    fireEvent.change(select, { target: { value: "__explicit__" } });
    const fromInput = screen.getByLabelText("开始日期") as HTMLInputElement;
    const toInput = screen.getByLabelText("结束日期") as HTMLInputElement;
    const apply = screen.getByRole("button", { name: /应用/ }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true); // 起止不完整 → 不可应用(禁半开窗)
    fireEvent.change(fromInput, { target: { value: "2026-09-01" } });
    fireEvent.change(toInput, { target: { value: "2026-09-09" } });
    expect(apply.disabled).toBe(false);
    fireEvent.click(apply);
    expect(onChange).toHaveBeenCalledWith("range:2026-09-01/2026-09-09");
  });
});
