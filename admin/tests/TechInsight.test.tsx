import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { mockTechPerf, mockCoverageGaps, mockSourceHealth, mockGapTrends } = vi.hoisted(() => ({
  mockTechPerf: vi.fn(),
  mockCoverageGaps: vi.fn(),
  mockSourceHealth: vi.fn(),
  mockGapTrends: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchCoverageGaps: mockCoverageGaps,
  fetchSourceHealth: mockSourceHealth,
  fetchGapTrends: mockGapTrends,
}));

// 缺口趋势默认空(KnowledgeGapsTab 用)
mockGapTrends.mockResolvedValue({ trends: [] });

// 覆盖缺口默认一条(KnowledgeGapsTab 用)
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

describe("TechInsight 知识缺口 tab", () => {
  it("切换到知识缺口 tab 显示覆盖缺口 + 类型 badge", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("知识缺口"));
    await waitFor(() => {
      expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
      expect(document.querySelector("[data-gap-type='召回空']")).toBeTruthy();
    });
  });

  it("澄清漏斗显示暂无数据", async () => {
    renderWithProviders(<Analytics />);
    fireEvent.click(await screen.findByText("知识缺口"));
    await waitFor(() => {
      expect(screen.getByText(/澄清漏斗/)).toBeInTheDocument();
      expect(screen.getByText(/暂无数据|待接入/)).toBeInTheDocument();
    });
  });
});

// ====================  DSH-02:数据源健康主位迁移至数据源管理  ====================

describe("DSH 技术洞察的数据源健康摘要(OBS-G008 边界)", () => {
  it("呈现一行健康摘要(按 health 计数)+ 跳转数据源管理", async () => {
    renderWithProviders(<Analytics />);
    const summary = await screen.findByText("数据源健康(近 30 天)");
    expect(summary).toBeInTheDocument();
    expect(screen.getByText(/正常 1/)).toBeInTheDocument();
    expect(screen.getByText(/严重 1/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /明细与操作 → 数据源管理/ }),
    ).toHaveAttribute("href", "/data-sources");
  });

  it("不再呈现与数据源页竞争的完整健康表格(无成功率列/逐源行)", async () => {
    renderWithProviders(<Analytics />);
    await screen.findByText("数据源健康(近 30 天)");
    expect(screen.queryByText("website-camthink")).not.toBeInTheDocument();
    expect(screen.queryByText("同步成功率")).not.toBeInTheDocument();
    expect(screen.queryByText("文档数")).not.toBeInTheDocument();
  });
});
