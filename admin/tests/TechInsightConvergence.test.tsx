import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ===========================================================================
// v1.6.3 B2 — Technical Insights Convergence 行为测试(KB-OPS-V163-002 / #57 #58 #59)
//
// 冻结契约(v163-b2-technical-insights-contract.md):
// - 技术性能 + 回答缺口 = 同一 技术洞察 域的 sibling tabs(强共享壳 + 选中态);
// - 回答缺口 = 只读操作者投影:question/topic、counts/impact/cause/status/recency
//   仅在权威时呈现;无权威分类 → 未分类/证据不可用,不发明 cause;
// - 观察中/导出/开始观察/涉及用户数 在 v1.6.3 NOT authorized → 不得出现;
// - 事件行运营可读优先,raw HTTP/内部 stage/code 为可展开证据;
//   critical/abnormal 盖过 routine;
// - 既有 event→source 与 gap→conversation 下钻保持。
// ===========================================================================

const {
  mockTechPerf,
  mockCoverageGaps,
  mockSourceHealth,
  mockGapTrends,
  mockSyncIncidents,
  mockGenerationEvents,
  mockAnswerGaps,
  mockGapConversations,
} = vi.hoisted(() => ({
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

mockGapTrends.mockResolvedValue({ trends: [] });
mockCoverageGaps.mockResolvedValue({
  items: [],
  total: 0,
  page: 1,
  size: 20,
});
mockSourceHealth.mockResolvedValue({ items: [], days: 30 });
mockSyncIncidents.mockResolvedValue({
  failed: { items: [], total: 0, page: 1, size: 10 },
  interrupted: { items: [], total: 0, page: 1, size: 10 },
});
mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });

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
    trends: [],
    anomalies: [],
    degradations: [],
    health: {
      status: "healthy",
      reasons: ["未检测到真实失败,诊断异常与延迟均处正常范围"],
      sample_size: 12,
    },
    trace_coverage_from: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

/** 权威答案缺口投影 mock(GET /tech/answer-gaps 形状)。 */
function answerGapsPayload(overrides: Record<string, unknown> = {}) {
  return {
    items: [
      {
        id: "aaaaaaaa-0000-4000-8000-000000000001",
        cluster_type: "gap",
        representative_question: "NE101 PoE 支持信息缺失",
        sample_questions: [
          "NE101 PoE 支持信息缺失",
          "NE101 是否支持 PoE，PoE 标准是什么?",
          "Does NE101 support PoE input?",
          "NE101 支持哪些 PoE 标准?",
          "Can NE101 be powered by Ethernet?",
          "NE101 PoE 最大功率是多少?",
        ],
        question_count: 23,
        impacted_answer_count: 18,
        status: "open",
        miss_type: "召回空",
        miss_type_breakdown: { "召回空": 18 },
        last_seen_at: "2026-09-12T02:00:00+00:00",
        period_start: null,
        period_end: null,
        created_at: "2026-09-12T10:00:00+00:00",
      },
      {
        id: "aaaaaaaa-0000-4000-8000-000000000002",
        cluster_type: "gap",
        representative_question: "退货政策回答不准确",
        sample_questions: ["退货政策回答不准确", "30 天退货还是 14 天?"],
        question_count: 4,
        impacted_answer_count: 3,
        status: "resolved",
        miss_type: "low",
        miss_type_breakdown: { low: 3 },
        last_seen_at: "2026-09-10T08:00:00+00:00",
        period_start: null,
        period_end: null,
        created_at: "2026-09-09T10:00:00+00:00",
      },
      {
        id: "aaaaaaaa-0000-4000-8000-000000000003",
        cluster_type: "gap",
        representative_question: "配件兼容性信息缺失",
        sample_questions: ["配件兼容性信息缺失"],
        question_count: 3,
        impacted_answer_count: 0,
        status: "open",
        miss_type: "未分类",
        miss_type_breakdown: {},
        last_seen_at: null,
        period_start: null,
        period_end: null,
        created_at: "2026-09-08T10:00:00+00:00",
      },
    ],
    total: 3,
    page: 1,
    size: 10,
    miss_type_summary: { "召回空": 1, low: 1, "未分类": 1 },
    ...overrides,
  };
}

mockTechPerf.mockResolvedValue(techPayload());
mockAnswerGaps.mockResolvedValue(answerGapsPayload());
mockGapConversations.mockResolvedValue({ items: [], total: 0 });

import Analytics from "@/pages/Analytics";

afterEach(() => {
  cleanup();
  mockTechPerf.mockReset();
  mockTechPerf.mockResolvedValue(techPayload());
  mockAnswerGaps.mockReset();
  mockAnswerGaps.mockResolvedValue(answerGapsPayload());
  mockGapConversations.mockReset();
  mockGapConversations.mockResolvedValue({ items: [], total: 0 });
  mockSyncIncidents.mockReset();
  mockSyncIncidents.mockResolvedValue({
    failed: { items: [], total: 0, page: 1, size: 10 },
    interrupted: { items: [], total: 0, page: 1, size: 10 },
  });
  mockGenerationEvents.mockReset();
  mockGenerationEvents.mockResolvedValue({ items: [], total: 0 });
});

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

async function openGapsTab() {
  renderWithProviders(<Analytics />);
  const tab = await screen.findByRole("tab", { name: "回答缺口" });
  fireEvent.click(tab);
  await waitFor(() => {
    expect(document.querySelector("[data-gap-row]")).toBeTruthy();
  });
}

// ====================  #57 共享壳 + 双 Tab  ====================

describe("B2 共享壳:技术洞察域 + 强选中 Tab 状态(#57 / KB-OPS-V163-002 §5.1)", () => {
  it("页标题 技术洞察 + 恢复的副标题;双 Tab 技术性能/回答缺口同域", async () => {
    renderWithProviders(<Analytics />);
    expect(screen.getByRole("heading", { name: "技术洞察" })).toBeInTheDocument();
    expect(
      screen.getByText(/从真实用户对话中发现回答问题，定位原因，并形成知识补充和优化闭环/),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "技术性能" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "回答缺口" })).toBeInTheDocument();
    // 旧标签「知识缺口」被恢复设计取代
    expect(screen.queryByRole("tab", { name: "知识缺口" })).not.toBeInTheDocument();
  });

  it("默认选中 技术性能;点击 回答缺口 后选中态迁移(aria-selected + 强选中态)", async () => {
    renderWithProviders(<Analytics />);
    const techTab = screen.getByRole("tab", { name: "技术性能" });
    const gapsTab = screen.getByRole("tab", { name: "回答缺口" });
    expect(techTab.getAttribute("aria-selected")).toBe("true");
    expect(techTab.getAttribute("data-active")).toBe("true");
    expect(gapsTab.getAttribute("aria-selected")).toBe("false");
    fireEvent.click(gapsTab);
    await waitFor(() => {
      expect(gapsTab.getAttribute("aria-selected")).toBe("true");
      expect(gapsTab.getAttribute("data-active")).toBe("true");
      expect(techTab.getAttribute("aria-selected")).toBe("false");
    });
  });
});

// ====================  #59 回答缺口队列(只读操作者投影)  ====================

describe("B2 回答缺口队列:question/topic + counts + cause + status + recency(#59)", () => {
  it("队列工具行:搜索框(占位符含 搜索问题/主题)+ 全部状态/全部原因/时间窗筛选", async () => {
    await openGapsTab();
    const search = document.querySelector("[data-gap-search]") as HTMLInputElement;
    expect(search).toBeTruthy();
    expect(search.placeholder).toContain("搜索问题/主题");
    expect(document.querySelector("[data-filter-status]")).toBeTruthy();
    expect(
      (document.querySelector("[data-filter-status]") as HTMLSelectElement).textContent,
    ).toContain("全部状态");
    expect(
      (document.querySelector("[data-filter-cause]") as HTMLSelectElement).textContent,
    ).toContain("全部原因");
    expect(document.querySelector("[data-filter-window]")).toBeTruthy();
  });

  it("表列 = 问题/主题、相关提问、影响回答、原因、状态、最近发生", async () => {
    await openGapsTab();
    for (const col of [
      "问题 / 主题",
      /相关提问/,
      /影响回答/,
      "原因",
      "状态",
      /最近发生/,
    ]) {
      expect(screen.getByText(col)).toBeInTheDocument();
    }
  });

  it("行渲染操作者可读值:主问题+代表问句副行、双计数、原因徽章(权威分类运营词)、状态徽章、最近发生", async () => {
    await openGapsTab();
    const row = document.querySelector(
      '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
    );
    expect(row).toBeTruthy();
    // 主标题 + 代表问句副行
    expect(row?.querySelector("[data-gap-question]")?.textContent).toBe(
      "NE101 PoE 支持信息缺失",
    );
    expect(row?.querySelector("[data-gap-sample]")?.textContent).toBe(
      "NE101 是否支持 PoE，PoE 标准是什么?",
    );
    // 相关提问 = question_count(权威);影响回答 = impacted_answer_count(权威)
    expect(row?.querySelector("[data-gap-questions]")?.textContent).toBe("23");
    expect(row?.querySelector("[data-gap-impacted]")?.textContent).toBe("18");
    // 原因徽章:权威 miss_type 原始值经 data 属性保留,运营词为忠实映射
    const badge = row?.querySelector("[data-gap-cause-badge]");
    expect(badge?.getAttribute("data-gap-type")).toBe("召回空");
    expect(badge?.textContent).toBe("知识缺失");
    // 状态徽章:open → 需要处理
    const status = row?.querySelector("[data-gap-status]");
    expect(status?.getAttribute("data-status")).toBe("open");
    expect(status?.textContent).toBe("需要处理");
    // 最近发生:相对时间(权威 last_seen_at)
    expect(row?.querySelector("[data-gap-recency]")?.textContent).toContain("前");
  });

  it("无权威原因分类 → 未分类(不发明 taxonomy);无会话证据 → 最近发生=证据不可用", async () => {
    await openGapsTab();
    const row = document.querySelector(
      '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000003"]',
    );
    expect(row?.querySelector("[data-gap-cause-badge]")?.textContent).toBe("未分类");
    expect(row?.querySelector("[data-gap-recency]")?.textContent).toBe("证据不可用");
  });

  it("resolved → 已解决(绿);v1.6.3 无 观察中 状态(NOT authorized,不伪造)", async () => {
    await openGapsTab();
    const status = document.querySelector(
      '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000002"] [data-gap-status]',
    );
    expect(status?.getAttribute("data-status")).toBe("resolved");
    expect(status?.textContent).toBe("已解决");
    await waitFor(() => {
      expect(screen.queryByText("观察中")).not.toBeInTheDocument();
    });
  });

  it("v1.6.3 未授权能力不出现:无 导出相关对话 / 开始观察 / 内容已补充 / 涉及用户数", async () => {
    await openGapsTab();
    // 点击首行使侧板展开后再断言(侧板是这些元素唯一可能出现的位置)
    fireEvent.click(document.querySelector("[data-gap-row]") as HTMLElement);
    await waitFor(() => {
      expect(document.querySelector("[data-gap-panel]")).toBeTruthy();
    });
    expect(screen.queryByText(/导出相关对话/)).not.toBeInTheDocument();
    expect(screen.queryByText(/开始观察/)).not.toBeInTheDocument();
    expect(screen.queryByText(/内容已补充/)).not.toBeInTheDocument();
    expect(screen.queryByText(/个用户/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CSV/)).not.toBeInTheDocument();
  });

  it("行点击选中(蓝选中态 data-selected)+ 底部 已选择 N 项 + 分页 + 条/页", async () => {
    await openGapsTab();
    const row = document.querySelector(
      '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
    ) as HTMLElement;
    fireEvent.click(row);
    await waitFor(() => {
      expect(row.getAttribute("data-selected")).toBe("true");
      const sel = document.querySelector("[data-selection-count]");
      expect(sel?.textContent).toContain("已选择");
      expect(sel?.textContent).toContain("1");
      expect(document.querySelector("[data-gap-pagination]")).toBeTruthy();
      expect(document.querySelector("[data-gap-page-size]")?.textContent).toContain(
        "条/页",
      );
    });
  });

  it("缺口行保留 gap→conversation 下钻:侧板含 /conversations?q={代表问题} 深链", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
      ) as HTMLElement,
    );
    await waitFor(() => {
      const link = document.querySelector('[data-gap-panel] [data-action="inspect-gap"]');
      expect(link).toBeTruthy();
      expect(link?.getAttribute("href")).toBe(
        `/conversations?q=${encodeURIComponent("NE101 PoE 支持信息缺失")}`,
      );
    });
  });
});

// ====================  #59 诊断侧板(contextual diagnosis)  ====================

describe("B2 诊断侧板:结论仅当权威、典型问题、面板 Tab(#59 / §5.5)", () => {
  it("侧板标题=代表问题 + 状态徽章;统计行=相关提问/受影响回答 + 最近发生(无用户数)", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
      ) as HTMLElement,
    );
    await waitFor(() => {
      expect(document.querySelector("[data-panel-title]")?.textContent).toBe(
        "NE101 PoE 支持信息缺失",
      );
      const stats = document.querySelector("[data-panel-stats]")?.textContent ?? "";
      expect(stats).toContain("23 次相关提问");
      expect(stats).toContain("18 次受影响回答");
      expect(stats).toContain("最近发生");
      expect(stats).not.toContain("个用户");
    });
  });

  it("权威原因 → 诊断结论面板:红色结论 + 原因徽章 + 忠实转述后端分类语义", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
      ) as HTMLElement,
    );
    await waitFor(() => {
      const conclusion = document.querySelector("[data-panel-conclusion]");
      expect(conclusion).toBeTruthy();
      expect(conclusion?.getAttribute("data-conclusion-kind")).toBe("authoritative");
      const badge = conclusion?.querySelector("[data-gap-cause-badge]");
      expect(badge?.getAttribute("data-gap-type")).toBe("召回空");
      // 召回空 = 已回答但未检索到任何知识来源(后端分类语义的忠实转述)
      expect(conclusion?.textContent).toContain("未检索到");
    });
  });

  it("无权威分类 → 诊断结论呈现 证据不可用,不虚构原因", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000003"]',
      ) as HTMLElement,
    );
    await waitFor(() => {
      const conclusion = document.querySelector("[data-panel-conclusion]");
      expect(conclusion?.getAttribute("data-conclusion-kind")).toBe("unavailable");
      expect(conclusion?.textContent).toContain("证据不可用");
    });
  });

  it("典型问题示例列出 sample_questions(权威)+ 查看全部入口;面板 Tab 五项", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
      ) as HTMLElement,
    );
    await waitFor(() => {
      // 样例问句同时出现在队列副行与侧板典型问题(同一权威来源)
      expect(
        screen.getAllByText("NE101 是否支持 PoE，PoE 标准是什么?").length,
      ).toBeGreaterThanOrEqual(1);
      expect(document.querySelector("[data-panel-typical-all]")).toBeTruthy();
      const tabs = document.querySelectorAll("[data-gap-panel] [data-panel-tab]");
      const names = Array.from(tabs).map((t) => t.textContent);
      expect(names).toEqual(["概览", "典型问题", "相关对话", "诊断详情", "历史记录"]);
    });
  });

  it("相关对话 Tab:权威会话证据行 + 每行深链 /conversations?q={问题}", async () => {
    mockGapConversations.mockResolvedValue({
      items: [
        {
          id: "ccccccc1-0000-4000-8000-000000000002",
          question: "NE101 是否支持 PoE?",
          is_answered: false,
          created_at: "2026-09-13T01:00:00+00:00",
        },
      ],
      total: 1,
    });
    await openGapsTab();
    fireEvent.click(
      document.querySelector(
        '[data-gap-row][data-gap-id="aaaaaaaa-0000-4000-8000-000000000001"]',
      ) as HTMLElement,
    );
    const convTab = await screen.findByText("相关对话");
    fireEvent.click(convTab);
    await waitFor(() => {
      const item = document.querySelector("[data-panel-conv-row]");
      expect(item).toBeTruthy();
      expect(item?.getAttribute("href")).toBe(
        `/conversations?q=${encodeURIComponent("NE101 是否支持 PoE?")}`,
      );
    });
  });
});

// ==================== v1.6.3 Design Remediation A 类呈现锁定(audit v163-design-20260913 §4) ====================

describe("v1.6.3 Design Remediation A 类呈现(技术洞察)", () => {
  it("A-B2-01:技术洞察 标题深蓝 rgb(4,3,108),不再近黑", async () => {
    renderWithProviders(<Analytics />);
    const h1 = await screen.findByRole("heading", { name: "技术洞察" });
    expect(h1.getAttribute("style")).toContain("rgb(4, 3, 108)");
  });

  it("A-B2-02:状态徽章 = 圈形图标(ⓘ 需要处理 / ✓ 已解决),不再裸圆点", async () => {
    await openGapsTab();
    const badges = document.querySelectorAll("[data-gap-status]");
    expect(badges.length).toBeGreaterThan(0);
    for (const b of badges) {
      // 圈形图标:svg 内含 circle 基元
      expect(b.querySelector("svg circle")).toBeTruthy();
    }
    // resolved 徽章含 ✓ 对勾 path;open 徽章含 ⓘ 竖点
    const resolved = document.querySelector(
      '[data-gap-status][data-status="resolved"] svg path',
    );
    expect(resolved).toBeTruthy();
  });

  it("A-B2-03:多页时页码按钮组 + 当前页高亮(aria-current)", async () => {
    mockAnswerGaps.mockResolvedValue(answerGapsPayload({ total: 12 }));
    await openGapsTab();
    const numbers = document.querySelectorAll("[data-gap-page-number]");
    expect(numbers.length).toBe(2);
    expect(numbers[0].getAttribute("aria-current")).toBe("page");
    expect(numbers[1].getAttribute("aria-current")).toBeNull();
    // 条/页选择器保留
    expect(document.querySelector("[data-gap-page-size]")).toBeTruthy();
  });

  it("A-B2-03b:单页保持诚实简洁(不造页码按钮组)", async () => {
    await openGapsTab(); // total=3 → 单页
    expect(document.querySelectorAll("[data-gap-page-number]").length).toBe(0);
    expect(document.querySelector("[data-gap-page-size]")).toBeTruthy();
  });

  it("A-B2-04:诊断侧板宽 ~460px;典型问题 bullets 标记强化", async () => {
    await openGapsTab();
    fireEvent.click(
      document.querySelector("[data-gap-row]") as HTMLElement,
    );
    await waitFor(() => {
      const panel = document.querySelector("[data-gap-panel]") as HTMLElement | null;
      expect(panel?.className).toContain("w-[460px]");
      const bullet = panel?.querySelector("[data-panel-typical] li") as HTMLElement | null;
      expect(bullet?.className).toContain("marker:text-[var(--t1)]");
    });
  });
});

// ====================  #58 技术性能:事件层级 + 可展开证据  ====================

describe("B2 技术性能:运营可读事件行优先,raw 证据可展开,critical 盖过 routine(#58)", () => {
  function syncPayloadNewerInfo() {
    return {
      failed: {
        items: [
          {
            id: 201,
            source_id: "wiki-documents-local",
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
      interrupted: { items: [], total: 0, page: 1, size: 10 },
    };
  }

  function genPayloadNewerRetired() {
    return {
      items: [
        {
          generation_id: "33333333-3333-4333-8333-333333333333",
          ordinal: 9,
          source_id: "legacy",
          status: "retired",
          severity: "info",
          doc_count: 5,
          chunk_count: 50,
          failure: null,
          reason_summary: "知识已从在服集撤出(被新一代接替)",
          created_at: "2026-09-12T10:00:00Z",
          activated_at: "2026-09-01T10:01:00Z",
          retired_at: "2026-09-12T10:00:00Z",
          event_at: "2026-09-12T10:00:00Z",
        },
      ],
      total: 1,
    };
  }

  it("critical(error)行排在 routine(info)行之前,即使 info 更新(severity 优先于时间)", async () => {
    mockSyncIncidents.mockResolvedValue(syncPayloadNewerInfo());
    mockGenerationEvents.mockResolvedValue(genPayloadNewerRetired());
    renderWithProviders(<Analytics />);
    await screen.findByText("同步 / 索引 / 生成事件");
    await waitFor(() => {
      const rows = document.querySelectorAll("[data-incident-row]");
      expect(rows.length).toBe(2);
      expect(rows[0].getAttribute("data-severity")).toBe("error");
      expect(rows[1].getAttribute("data-severity")).toBe("info");
    });
  });

  it("事件行运营可读优先;raw 内部证据(尝试次数/stage/failure JSON)收进可展开 <details>,默认折叠", async () => {
    mockSyncIncidents.mockResolvedValue(syncPayloadNewerInfo());
    mockGenerationEvents.mockResolvedValue(genPayloadNewerRetired());
    renderWithProviders(<Analytics />);
    await screen.findByText("同步 / 索引 / 生成事件");
    await waitFor(() => {
      const errRow = document.querySelector(
        '[data-incident-row][data-incident-type="sync_failed"]',
      ) as HTMLDetailsElement;
      // 运营可读主行:类型 + 源归属
      expect(errRow?.textContent).toContain("同步失败");
      expect(errRow?.getAttribute("data-source-id")).toBe("wiki-documents-local");
      // raw 证据在 details 内且默认折叠(details 无 open 属性)
      const details = errRow?.querySelector("[data-incident-evidence]") as HTMLDetailsElement;
      expect(details).toBeTruthy();
      expect(details.open).toBe(false);
      // raw 内部证据(attempt/stage/error)在折叠区内
      expect(details.textContent).toContain("attempt: 2");
      expect(details.textContent).toContain("stage: fetch");
      expect(details.textContent).toContain("clone 失败:auth required");
      // 下钻 href 保留(#50 FROZEN INTERFACE)
      expect(errRow?.getAttribute("href")).toBe(
        `/data-sources/${encodeURIComponent("wiki-documents-local")}`,
      );
    });
    // 生成级 failed 行的 failure JSON 证据同样折叠
    const genRow = document.querySelector(
      '[data-incident-row][data-incident-type="generation_retired"]',
    );
    const genDetails = genRow?.querySelector("[data-incident-evidence]") as HTMLDetailsElement;
    expect(genDetails).toBeTruthy();
    expect(genDetails.open).toBe(false);
  });
});
