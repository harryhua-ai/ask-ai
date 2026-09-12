import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { mockTechPerf, mockCoverageGaps, mockSourceHealth, mockGapTrends, mockSyncIncidents, mockGenerationEvents, mockAnswerGaps, mockGapConversations } = vi.hoisted(() => ({
  mockTechPerf: vi.fn(),
  mockCoverageGaps: vi.fn(),
  mockSourceHealth: vi.fn(),
  mockGapTrends: vi.fn(),
  mockSyncIncidents: vi.fn(),
  mockGenerationEvents: vi.fn(),
  mockAnswerGaps: vi.fn(),
  mockGapConversations: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchCoverageGaps: mockCoverageGaps,
  fetchSourceHealth: mockSourceHealth,
  fetchGapTrends: mockGapTrends,
  fetchSyncIncidents: mockSyncIncidents,
  fetchGenerationEvents: mockGenerationEvents,
  fetchAnswerGaps: mockAnswerGaps,
  fetchGapConversations: mockGapConversations,
}));

// 缺口趋势默认空(KnowledgeGapsTab 用)
mockGapTrends.mockResolvedValue({ trends: [] });

// #51 B2:事件信号区默认空(显式空态)
mockSyncIncidents.mockResolvedValue({
  failed: { items: [], total: 0, page: 1, size: 10 },
  interrupted: { items: [], total: 0, page: 1, size: 10 },
});
mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });

// 覆盖缺口默认一条(旧读面兼容保留;v1.6.3 B2 回答缺口队列消费 answer-gaps 投影)
mockCoverageGaps.mockResolvedValue({
  items: [
    {
      id: "g1",
      cluster_type: "gap",
      representative_question: "如何接入 SDK",
      sample_questions: ["如何接入 SDK"],
      question_count: 5,
      status: "open",
      miss_type: "召回空",
      period_start: null,
      period_end: null,
      created_at: "2026-08-10T10:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  size: 20,
});

// v1.6.3 B2:回答缺口只读投影默认一条(AnswerGapsTab 用)
mockAnswerGaps.mockResolvedValue({
  items: [
    {
      id: "g1",
      cluster_type: "gap",
      representative_question: "如何接入 SDK",
      sample_questions: ["如何接入 SDK"],
      question_count: 5,
      impacted_answer_count: 3,
      status: "open",
      miss_type: "召回空",
      miss_type_breakdown: { "召回空": 3 },
      last_seen_at: "2026-09-01T10:00:00Z",
      period_start: null,
      period_end: null,
      created_at: "2026-08-10T10:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  size: 10,
  miss_type_summary: { "召回空": 1 },
});
mockGapConversations.mockResolvedValue({ items: [], total: 0 });

// 数据源健康默认两条(技术洞察只应有摘要条,不再有完整表格)— DSH-02 边界
mockSourceHealth.mockResolvedValue({
  items: [
    {
      source_id: "website-camthink",
      source_type: "web_crawl",
      product: "website",
      enabled: true,
      doc_count: 75,
      chunk_count: 1200,
      window_days: 30,
      total_syncs: 25,
      success_syncs: 24,
      partial_syncs: 0,
      failed_syncs: 1,
      sync_success_rate: 0.96,
      health: "healthy",
      last_sync: "2026-09-01T02:00:00Z",
      last_sync_status: "success",
      last_sync_error: null,
    },
    {
      source_id: "ne301-docs",
      source_type: "github",
      product: "ne301",
      enabled: true,
      doc_count: 10,
      chunk_count: 100,
      window_days: 30,
      total_syncs: 3,
      success_syncs: 1,
      partial_syncs: 1,
      failed_syncs: 1,
      sync_success_rate: 0.3333,
      health: "critical",
      last_sync: "2026-09-01T01:00:00Z",
      last_sync_status: "failed",
      last_sync_error: "clone 失败",
    },
  ],
  days: 30,
});

/** OBS-G 场景 mock 工厂:健康基线数据,按场景覆盖字段。 */
function techPayload(overrides: Record<string, unknown> = {}) {
  return {
    kpi: {
      p95_ms: 1200,
      anomaly_rate: 0.0,
      fail_rate: 0.0,
      recovered_rate: 0.0,
      anomaly_count: 0,
      fail_count: 0,
      recovered_count: 0,
      anomaly_delta: null,
      fail_delta: null,
      recovered_delta: null,
      failure_kinds: {},
      trace_total: 12,
      window: { from: "2026-08-25T00:00:00+00:00", to: "2026-09-01T00:00:00+00:00" },
      baseline: 3000,
      baseline_source: "previous_window",
      comparison: 0.0,
    },
    stages: {
      intent: { p50: 50, p95: 80, normal_max: 3000, over_count: 0, p50_pct: 1, p95_pct: 2 },
      rewrite: { p50: 200, p95: 400, normal_max: 4000, over_count: 0, p50_pct: 4, p95_pct: 8 },
      retrieve: { p50: 500, p95: 800, normal_max: 3000, over_count: 0, p50_pct: 10, p95_pct: 16 },
      rerank: { p50: 300, p95: 600, normal_max: 3000, over_count: 0, p50_pct: 6, p95_pct: 12 },
      generate: { p50: 3000, p95: 5000, normal_max: 30000, over_count: 0, p50_pct: 60, p95_pct: 100 },
      output: { p50: 0, p95: 0, normal_max: 100, over_count: 0, p50_pct: 0, p95_pct: 0 },
    },
    trends: Array.from({ length: 7 }, (_, i) => ({
      date: `08-0${i + 1}`,
      p50: 300,
      p95: 1000,
    })),
    anomalies: [],
    degradations: [{ from: "正常 RAG", to: "单路检索", reason: "单路检索 共 2 次" }],
    health: {
      status: "healthy",
      reasons: ["未检测到真实失败,诊断异常与延迟均处正常范围"],
      sample_size: 12,
    },
    trace_coverage_from: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

import Analytics from "@/pages/Analytics";

afterEach(() => {
  cleanup();
  mockTechPerf.mockReset();
  mockTechPerf.mockResolvedValue(techPayload());
  mockSyncIncidents.mockReset();
  mockSyncIncidents.mockResolvedValue({
    failed: { items: [], total: 0, page: 1, size: 10 },
    interrupted: { items: [], total: 0, page: 1, size: 10 },
  });
  mockGenerationEvents.mockReset();
  mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });
  mockAnswerGaps.mockReset();
  mockAnswerGaps.mockResolvedValue({
    items: [
      {
        id: "g1",
        cluster_type: "gap",
        representative_question: "如何接入 SDK",
        sample_questions: ["如何接入 SDK"],
        question_count: 5,
        impacted_answer_count: 3,
        status: "open",
        miss_type: "召回空",
        miss_type_breakdown: { "召回空": 3 },
        last_seen_at: "2026-09-01T10:00:00Z",
        period_start: null,
        period_end: null,
        created_at: "2026-08-10T10:00:00Z",
      },
    ],
    total: 1,
    page: 1,
    size: 10,
    miss_type_summary: { "召回空": 1 },
  });
  mockGapConversations.mockReset();
  mockGapConversations.mockResolvedValue({ items: [], total: 0 });
});

// 未显式设置 mock 的测试用例回退到健康基线
mockTechPerf.mockResolvedValue(techPayload());

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

describe("TechInsight 技术洞察页 — 信息架构(OBS-01/02)", () => {
  it("SECONDARY 三卡:真实失败/诊断异常/降级恢复,含分子分母,无「重试率」裸标签", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("真实失败")).toBeInTheDocument();
      expect(screen.getByText("诊断异常")).toBeInTheDocument();
      expect(screen.getByText("降级恢复")).toBeInTheDocument();
      expect(screen.queryByText("重试率")).not.toBeInTheDocument();
      // 分子/分母 footnote(无裸百分比)
      expect(screen.getByText(/0 \/ 12 条 trace/)).toBeInTheDocument();
    });
  });

  it("P50/P95 趋势图渲染 7 柱且每柱含双段 + 基线虚线", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const bars = document.querySelectorAll("[data-bar]");
      expect(bars.length).toBe(7);
      bars.forEach((b) => {
        expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
        expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
      });
      expect(document.querySelector("[data-baseline]")).toBeTruthy();
    });
  });

  it("阶段表用人类可读标签,机器名经 data-stage 保留;超标行 data-over=true", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("生成")).toBeInTheDocument();
      const rewriteHost = document.querySelector('[data-stage="rewrite"]');
      expect(rewriteHost).toBeTruthy();
      expect(rewriteHost?.querySelector("[data-over]")).toBeTruthy();
    });
  });

  it("OBS-G003:主导瓶颈高亮(over_count 最多的阶段)", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        stages: {
          intent: { p50: 50, p95: 80, normal_max: 3000, over_count: 0, p50_pct: 1, p95_pct: 2 },
          rewrite: { p50: 200, p95: 9000, normal_max: 4000, over_count: 3, p50_pct: 4, p95_pct: 100 },
          retrieve: { p50: 500, p95: 800, normal_max: 3000, over_count: 1, p50_pct: 10, p95_pct: 16 },
          rerank: { p50: 300, p95: 600, normal_max: 3000, over_count: 0, p50_pct: 6, p95_pct: 12 },
          generate: { p50: 3000, p95: 5000, normal_max: 30000, over_count: 0, p50_pct: 60, p95_pct: 50 },
          output: { p50: 0, p95: 0, normal_max: 100, over_count: 0, p50_pct: 0, p95_pct: 0 },
        },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/主导瓶颈:查询改写/)).toBeInTheDocument();
      expect(screen.getByText(/3 条超阈值/)).toBeInTheDocument();
      expect(
        document.querySelector('[data-stage="rewrite"][data-dominant="true"]'),
      ).toBeTruthy();
      expect(
        document.querySelector('[data-stage="generate"][data-dominant="true"]'),
      ).toBeNull();
    });
  });

  it("OBS-03:异常列表按语义严重度着色,人类标签 + 机器类型保留", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        anomalies: [
          {
            type: "generate_slow",
            label: "生成缓慢",
            severity: "slow",
            count: 3,
            pct: 60,
          },
          {
            type: "generation_error:provider_error",
            label: "生成失败·供应商异常",
            severity: "error",
            count: 2,
            pct: 40,
          },
        ],
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const slow = document.querySelector('[data-anomaly-item="generate_slow"]');
      expect(slow?.getAttribute("data-severity")).toBe("slow");
      expect(screen.getByText("生成缓慢")).toBeInTheDocument();
      const err = document.querySelector(
        '[data-anomaly-item="generation_error:provider_error"]',
      );
      expect(err?.getAttribute("data-severity")).toBe("error");
      expect(screen.getByText("生成失败·供应商异常")).toBeInTheDocument();
    });
  });
});

describe("OBS-G 健康状态场景", () => {
  it("OBS-G001:高诊断异常+零失败 → degraded,不把诊断信号说成失败", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: {
          ...techPayload().kpi,
          anomaly_rate: 0.75,
          anomaly_count: 9,
        },
        health: {
          status: "degraded",
          reasons: ["诊断异常率 75% 偏高(超过性能阈值或含错误;属诊断信号,不等同服务失败)"],
          sample_size: 12,
        },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const banner = document.querySelector("[data-health-banner]");
      expect(banner?.getAttribute("data-health-status")).toBe("degraded");
      // 理由不声称真实失败
      const reasons = banner?.querySelector("[data-health-reasons]")?.textContent ?? "";
      expect(reasons).not.toContain("真实失败");
      // 诊断异常卡明确标注 ≠服务失败;失败与恢复均为 0%
      expect(screen.getByText(/≠服务失败/)).toBeInTheDocument();
      expect(screen.getAllByText("0%").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("OBS-G002:真实失败 → critical + 查看失败对话深链(has_failure)", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: {
          ...techPayload().kpi,
          fail_count: 2,
          fail_rate: 2 / 12,
          failure_kinds: { provider_error: 2 },
        },
        health: {
          status: "critical",
          reasons: ["存在 2 条真实失败(占 16.7%),已达严重阈值(失败率≥5% 或失败≥5 条)"],
          sample_size: 12,
        },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(
        document.querySelector('[data-health-status="critical"]'),
      ).toBeTruthy();
      const link = document.querySelector('[data-action="inspect-failures"]');
      expect(link).toBeTruthy();
      expect(link?.getAttribute("href")).toBe("/conversations?failure=true");
    });
  });

  it("OBS-G004:降级恢复独立呈现,不计入失败", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: { ...techPayload().kpi, recovered_count: 5, recovered_rate: 5 / 12 },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/5 \/ 12 条 · 性能降级但已恢复/)).toBeInTheDocument();
      expect(document.querySelector('[data-level="recovered"]')).toBeTruthy();
      // 失败仍为 0
      expect(screen.getByText(/0 \/ 12 条 trace/)).toBeInTheDocument();
    });
  });

  it("OBS-G005:健康周期 → 服务健康,无 alarm 色卡", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(
        document.querySelector('[data-health-status="healthy"]'),
      ).toBeTruthy();
      expect(screen.getByText("服务健康")).toBeInTheDocument();
      // 无失败 → 失败卡无 critical 色
      const failCard = screen.getByText("真实失败").closest("[data-tone]");
      expect(failCard?.getAttribute("data-tone")).toBe("neutral");
    });
  });

  it("OBS-G006:零数据 → 暂无数据;小样本 → 证据不足", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: { ...techPayload().kpi, trace_total: 0 },
        health: {
          status: "no_data",
          reasons: ["所选时间窗内无 trace 数据,无法评估服务状态"],
          sample_size: 0,
        },
      }),
    );
    const { unmount } = renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("暂无数据")).toBeInTheDocument();
      expect(screen.getAllByText(/无 trace 数据/).length).toBeGreaterThan(0);
    });
    unmount();
    cleanup();

    mockTechPerf.mockResolvedValue(
      techPayload({
        health: { status: "insufficient_data", reasons: ["样本过少(仅 3 条 trace)"], sample_size: 3 },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("证据不足")).toBeInTheDocument();
    });
  });

  it("OBS-G007:基线回退时明示「本窗 P50,非历史对比」;有上一窗时显示历史对比", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: {
          ...techPayload().kpi,
          baseline_source: "current_window_p50_fallback",
          anomaly_delta: null,
        },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getAllByText(/本窗 P50/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/非历史对比/).length).toBeGreaterThan(0);
    });
    cleanup();
    mockTechPerf.mockReset();
    mockTechPerf.mockResolvedValue(techPayload()); // previous_window 基线
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getAllByText(/上一周期 P95/).length).toBeGreaterThan(0);
    });
  });

  it("OBS-G009:存在异常/失败时提供「在对话审查中排查」入口 + 如实标注限制", async () => {
    mockTechPerf.mockResolvedValue(
      techPayload({
        kpi: { ...techPayload().kpi, anomaly_count: 9, anomaly_rate: 0.75 },
      }),
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const link = document.querySelector('[data-action="inspect-window"]');
      expect(link?.getAttribute("href")).toBe("/conversations");
      expect(screen.getByText(/异常类型过滤暂不支持/)).toBeInTheDocument();
    });
  });
});

describe("TechInsight 回答缺口 tab(v1.6.3 B2 收敛:知识缺口 → 回答缺口)", () => {
  it("切换到回答缺口 tab 显示缺口队列 + 权威类型 badge", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("回答缺口"));
    await waitFor(() => {
      expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
      expect(document.querySelector("[data-gap-type='召回空']")).toBeTruthy();
    });
  });

  it("AFP-007:不再渲染「澄清漏斗(待接入)」占位面板", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("回答缺口"));
    await waitFor(() => {
      expect(document.querySelector("[data-answer-gaps-queue]")).toBeTruthy();
    });
    expect(screen.queryByText(/澄清漏斗/)).not.toBeInTheDocument();
    expect(screen.queryByText(/待接入/)).not.toBeInTheDocument();
  });
});

// ====================  DSH-02:数据源健康主位迁移至数据源管理  ====================

describe("DSH 技术洞察的数据源健康摘要(OBS-G008 边界)", () => {
  it("呈现一行健康摘要(按 health 计数)+ 跳转数据源管理", async () => {
    renderWithProviders(<Analytics />);
    // #21:摘要标题与 critical 计数显式历史措辞
    const summary = await screen.findByText("数据源历史可靠性(近 30 天)");
    expect(summary).toBeInTheDocument();
    expect(screen.getByText(/正常 1/)).toBeInTheDocument();
    expect(screen.getByText(/历史低成功率 1/)).toBeInTheDocument();
    expect(screen.queryByText(/^严重/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /明细与操作 → 数据源管理/ }),
    ).toHaveAttribute("href", "/data-sources");
  });

  it("不再呈现与数据源页竞争的完整健康表格(无成功率列/逐源行)", async () => {
    renderWithProviders(<Analytics />);
    await screen.findByText("数据源历史可靠性(近 30 天)");
    expect(screen.queryByText("website-camthink")).not.toBeInTheDocument();
    expect(screen.queryByText("同步成功率")).not.toBeInTheDocument();
    expect(screen.queryByText("文档数")).not.toBeInTheDocument();
  });
});

// ====================  #51 B2:事件信号区 + 下钻链路  ====================

/** 复用优先:同步级事件 mock(权威源 GET /sync-runs;前端零新增后端)。 */
function syncIncidentsPayload() {
  return {
    failed: {
      items: [
        {
          id: 101,
          source_id: "ne301-docs",
          triggered_by: "cron",
          request_id: 7,
          attempt: 2,
          recovery: false,
          status: "failed",
          started_at: "2026-09-10T02:00:00Z",
          finished_at: "2026-09-10T02:05:00Z",
          duration_seconds: 300,
          stage: "fetch",
          counters: {},
          consistency: null,
          execution_device: null,
          fallback_reason: null,
          fallback_detail: null,
          error_summary: "clone 失败:auth required",
          ingestion_skipped: false,
          sync_log: null,
        },
      ],
      total: 1,
      page: 1,
      size: 10,
    },
    interrupted: {
      items: [
        {
          id: 102,
          source_id: "website camthink",
          triggered_by: "cron",
          request_id: 8,
          attempt: 1,
          recovery: false,
          status: "interrupted",
          started_at: "2026-09-11T08:00:00Z",
          finished_at: "2026-09-11T08:01:00Z",
          duration_seconds: 60,
          stage: "embed",
          counters: {},
          consistency: null,
          execution_device: null,
          fallback_reason: null,
          fallback_detail: null,
          error_summary: null,
          ingestion_skipped: false,
          sync_log: null,
        },
      ],
      total: 1,
      page: 1,
      size: 10,
    },
  };
}

/** 生成级事件 mock(新增只读读面 GET /tech/generation-events)。 */
function generationEventsPayload() {
  return {
    items: [
      {
        generation_id: "11111111-1111-1111-1111-111111111111",
        ordinal: 1,
        source_id: "ne301-docs",
        status: "failed",
        severity: "error",
        doc_count: 3,
        chunk_count: 0,
        failure: { error: "doc build failures", docs: ["d1"] },
        reason_summary: "doc build failures",
        created_at: "2026-09-09T10:00:00Z",
        activated_at: null,
        retired_at: null,
        event_at: "2026-09-09T10:00:00Z",
      },
      {
        generation_id: "22222222-2222-2222-2222-222222222222",
        ordinal: 2,
        source_id: "handbook-src",
        status: "retired",
        severity: "info",
        doc_count: 5,
        chunk_count: 50,
        failure: null,
        reason_summary: "知识已从在服集撤出(被新一代接替)",
        created_at: "2026-09-01T10:00:00Z",
        activated_at: "2026-09-01T10:01:00Z",
        retired_at: "2026-09-12T10:00:00Z",
        event_at: "2026-09-12T10:00:00Z",
      },
    ],
    total: 2,
  };
}

describe("B2 事件信号区(同步/索引/生成事件)", () => {
  it("聚合展示同步失败/中断与生成级事件,行含源/类型/严重度/时间", async () => {
    mockSyncIncidents.mockResolvedValue(syncIncidentsPayload());
    mockGenerationEvents.mockResolvedValue(generationEventsPayload());
    renderWithProviders(<Analytics />);
    const section = await screen.findByText("同步 / 索引 / 生成事件");
    expect(section).toBeInTheDocument();
    await waitFor(() => {
      const rows = document.querySelectorAll("[data-incident-row]");
      expect(rows.length).toBe(4);
    });
    // 同步失败行:error 严重度 + 源归属
    const syncFailed = document.querySelector(
      '[data-incident-row][data-incident-type="sync_failed"]',
    );
    expect(syncFailed?.getAttribute("data-severity")).toBe("error");
    expect(syncFailed?.getAttribute("data-source-id")).toBe("ne301-docs");
    expect(syncFailed?.textContent).toContain("同步失败");
    expect(syncFailed?.textContent).toContain("clone 失败:auth required");
    // 同步中断行:warning
    const syncInterrupted = document.querySelector(
      '[data-incident-row][data-incident-type="sync_interrupted"]',
    );
    expect(syncInterrupted?.getAttribute("data-severity")).toBe("warning");
    // 生成级失败行:机器证据(ordinal)透传
    const genFailed = document.querySelector(
      '[data-incident-row][data-incident-type="generation_failed"]',
    );
    expect(genFailed?.getAttribute("data-severity")).toBe("error");
    expect(genFailed?.textContent).toContain("生成失败");
    expect(genFailed?.textContent).toContain("doc build failures");
    // retired 是生命周期事件,info 严重度,不冒充失败
    const genRetired = document.querySelector(
      '[data-incident-row][data-incident-type="generation_retired"]',
    );
    expect(genRetired?.getAttribute("data-severity")).toBe("info");
  });

  it("事件行下钻到源详情(#50 FROZEN INTERFACE 路由字符串;source_id 编码)", async () => {
    mockSyncIncidents.mockResolvedValue(syncIncidentsPayload());
    mockGenerationEvents.mockResolvedValue(generationEventsPayload());
    renderWithProviders(<Analytics />);
    await screen.findByText("同步 / 索引 / 生成事件");
    await waitFor(() => {
      expect(document.querySelectorAll("[data-incident-row]").length).toBe(4);
    });
    const syncFailed = document.querySelector(
      '[data-incident-row][data-incident-type="sync_failed"]',
    );
    expect(syncFailed?.getAttribute("href")).toBe("/data-sources/ne301-docs");
    // 空格等非常规字符经 encodeURIComponent 编码
    const interrupted = document.querySelector(
      '[data-incident-row][data-incident-type="sync_interrupted"]',
    );
    expect(interrupted?.getAttribute("href")).toBe(
      `/data-sources/${encodeURIComponent("website camthink")}`,
    );
    const genFailed = document.querySelector(
      '[data-incident-row][data-incident-type="generation_failed"]',
    );
    expect(genFailed?.getAttribute("href")).toBe("/data-sources/ne301-docs");
    const genRetired = document.querySelector(
      '[data-incident-row][data-incident-type="generation_retired"]',
    );
    expect(genRetired?.getAttribute("href")).toBe("/data-sources/handbook-src");
  });

  it("空态显式:无任何事件时给出明确空态文案", async () => {
    mockSyncIncidents.mockResolvedValue({
      failed: { items: [], total: 0, page: 1, size: 10 },
      interrupted: { items: [], total: 0, page: 1, size: 10 },
    });
    mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<Analytics />);
    await screen.findByText("同步 / 索引 / 生成事件");
    await waitFor(() => {
      expect(screen.getByText("无同步 / 索引 / 生成失败事件")).toBeInTheDocument();
      expect(document.querySelectorAll("[data-incident-row]").length).toBe(0);
    });
  });

  it("非重叠:事件区只做源归属与下钻,不渲染源清单/内容列表/配置控件", async () => {
    mockSyncIncidents.mockResolvedValue(syncIncidentsPayload());
    mockGenerationEvents.mockResolvedValue(generationEventsPayload());
    renderWithProviders(<Analytics />);
    await screen.findByText("同步 / 索引 / 生成事件");
    await waitFor(() => {
      expect(document.querySelectorAll("[data-incident-row]").length).toBe(4);
    });
    // 无逐源内容计数列(文档数/chunk 数清单)、无源配置控件
    expect(screen.queryByText("文档数")).not.toBeInTheDocument();
    expect(screen.queryByText(/同步间隔/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /立即同步/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /启用|禁用/ })).not.toBeInTheDocument();
  });
});

describe("B2 覆盖缺口行 → 对话核查面深链(冻结参数语法)", () => {
  it("选中缺口行后,侧板代表问题深链 /conversations?q={代表问题 URL 编码}", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("回答缺口"));
    await waitFor(() => {
      expect(document.querySelector("[data-gap-row]")).toBeTruthy();
    });
    fireEvent.click(document.querySelector("[data-gap-row]") as HTMLElement);
    await waitFor(() => {
      const link = document.querySelector('[data-gap-panel] [data-action="inspect-gap"]');
      expect(link).toBeTruthy();
      expect(link?.getAttribute("href")).toBe(
        `/conversations?q=${encodeURIComponent("如何接入 SDK")}`,
      );
    });
  });
});
