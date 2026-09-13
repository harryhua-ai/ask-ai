/**
 * v1.6.3 B1(KB-OPS-V163-002):数据源详情收敛行为测试(硬参考 panel 2/3/4)。
 *
 * 冻结层级:身份 → 操作者状态 → 最新同步摘要 → 知识总量+需处理 →
 * prominent attention banner → 知识内容工作区 → 本地诊断/历史。
 * Forbidden 断言:无 重新处理(无既有权威操作支撑)、无 知识设置、
 * 无 高风险变更影响预览。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSourceDetail from "@/pages/DataSourceDetail";
import {
  useDataSources,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
  useSourceHealth,
} from "@/hooks/useDataSources";
import {
  useSourceDocuments,
  useSourceDocumentTruth,
  useSourceGenerations,
} from "@/hooks/useDataSourceWorkspace";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false, variables: null })),
  useSyncHealth: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSyncRuns: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
  useSyncStatus: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSourceHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useAttentionSummary: vi.fn(() => ({ data: undefined, isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useDataSourceWorkspace", () => ({
  useSourceDocuments: vi.fn(() => ({
    data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn(),
  })),
  useSourceDocumentTruth: vi.fn(() => ({
    data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn(),
  })),
  useSourceGenerations: vi.fn(() => ({
    data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn(),
  })),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const H2 = 2 * 3600 * 1000;
const D3 = 3 * 86400 * 1000;

const source = {
  id: "woo-store",
  type: "woocommerce",
  product: "WooCommerce",
  enabled: true,
  config: { store_url: "https://woocommerce.com" },
  sync_interval: "6h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: new Date(Date.now() - H2).toISOString(),
  last_sync_status: "partial",
  last_sync_error: null,
  lifecycle_state: null,
  lifecycle_since: null,
  lifecycle_error: null,
};

// 权威聚合(与 /documents 端点同字段):attention = 6 − 3 − 1 = 2
const documents = {
  source_id: "woo-store",
  total: 6,
  ledger_total: 6,
  page: 1,
  size: 20,
  lifecycle_counts: { active: 3, missing_candidate: 2, superseded: 1 },
  serving_count: 5,
  current_count: 3,
  items: [
    {
      source_id: "woo-store/main/p1",
      title: "Product One",
      url: "https://woo.test/p1",
      branch: "main",
      source_type: "woocommerce",
      product: "WooCommerce",
      lifecycle: "active",
      serving: true,
      chunk_count: 4,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: new Date(Date.now() - H2).toISOString(),
      current_version_seq: 17,
      generation_ordinal: 7,
    },
    {
      source_id: "woo-store/main/gone",
      title: "Vanishing Page",
      url: "https://woo.test/gone",
      branch: "main",
      source_type: "woocommerce",
      product: "WooCommerce",
      lifecycle: "missing_candidate",
      serving: true,
      chunk_count: 2,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: new Date(Date.now() - D3).toISOString(),
      current_version_seq: 4,
      generation_ordinal: 7,
    },
  ],
};

const truth = {
  source_id: "woo-store",
  doc_source_id: "woo-store/main/gone",
  title: "Vanishing Page",
  url: "https://woo.test/gone",
  branch: "main",
  source_type: "woocommerce",
  product: "WooCommerce",
  lifecycle: "missing_candidate",
  serving: true,
  chunk_count: 2,
  created_at: "2026-08-01T00:00:00+00:00",
  updated_at: "2026-09-10T00:00:00+00:00",
  superseded_by: null,
  superseded_at: null,
  deleted_at: null,
  current_version: {
    id: "v-uuid",
    version_seq: 4,
    status: "active",
    title: "Vanishing Page",
    url: "https://woo.test/gone",
    chunk_count: 2,
    chunks_total: 12,
    source_version: null,
    valid_from: "2026-08-01T00:00:00+00:00",
    valid_to: null,
    superseded_by_version_id: null,
    generation_id: "g-uuid",
    generation_ordinal: 7,
  },
  generation: {
    id: "g-uuid",
    ordinal: 7,
    status: "ready",
    doc_count: 6,
    chunk_count: 40,
    failure: null,
    created_at: "2026-08-01T00:00:00+00:00",
    ready_at: "2026-08-01T00:01:00+00:00",
    activated_at: "2026-08-01T00:02:00+00:00",
    withdrawn_at: null,
    retired_at: null,
    gc_eligible_at: null,
    purged_at: null,
  },
};

const generations = {
  source_id: "woo-store",
  total: 1,
  serving_ordinals: [7],
  items: [truth.generation],
};

// 一次 failed 运行 + 两次常规无变更成功
const runs = {
  items: [
    {
      id: 31,
      source_id: "woo-store",
      triggered_by: "manual",
      status: "failed",
      started_at: new Date(Date.now() - 3600 * 1000).toISOString(),
      finished_at: new Date(Date.now() - 3500 * 1000).toISOString(),
      duration_seconds: 100,
      error_summary: "sitemap 请求超时",
      counters: {},
      sync_log: null,
    },
    {
      id: 30,
      source_id: "woo-store",
      triggered_by: "cron",
      status: "completed",
      started_at: new Date(Date.now() - 7200 * 1000).toISOString(),
      counters: {},
      sync_log: { status: "success", items_new: 0, chunks_written: 0, items_deleted: 0, items_unchanged: 200, error_detail: null },
    },
    {
      id: 29,
      source_id: "woo-store",
      triggered_by: "cron",
      status: "completed",
      started_at: new Date(Date.now() - 10800 * 1000).toISOString(),
      counters: {},
      sync_log: { status: "success", items_new: 0, chunks_written: 0, items_deleted: 0, items_unchanged: 200, error_detail: null },
    },
  ],
  total: 3,
  page: 1,
  size: 20,
};

function withRouter(ui: React.ReactElement) {
  return (
    <MemoryRouter initialEntries={["/data-sources/woo-store"]}>
      <Routes>
        <Route path="/data-sources/:sourceId" element={ui} />
      </Routes>
    </MemoryRouter>
  );
}

function renderDetail() {
  vi.mocked(useDataSources).mockReturnValue({
    data: [source] as never,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useSyncRuns).mockReturnValue({ data: runs as never, isLoading: false, error: null, refetch: vi.fn() } as never);
  vi.mocked(useSourceHealth).mockReturnValue({
    data: {
      items: [
        {
          source_id: "woo-store",
          health: "healthy",
          sync_success_rate: 0.987,
          window_days: 30,
          total_syncs: 80,
          success_syncs: 79,
          partial_syncs: 1,
          failed_syncs: 0,
          doc_count: 202,
          chunk_count: 900,
        },
      ],
    },
    isLoading: false,
  } as never);
  vi.mocked(useSourceDocuments).mockReturnValue({
    data: documents as never, isLoading: false, isError: false, error: null, refetch: vi.fn(),
  } as never);
  vi.mocked(useSourceGenerations).mockReturnValue({
    data: generations as never, isLoading: false, isError: false, error: null, refetch: vi.fn(),
  } as never);

  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}>{withRouter(<DataSourceDetail />)}</QueryClientProvider>);
}

describe("v1.6.3 B1 数据源详情收敛(hard ref panel 2/3/4)", () => {
  it("层级 1-2 身份与操作者状态:名称 + 需处理徽章 + 类型|来源地址;右侧 最后同步/知识/需处理", () => {
    renderDetail();
    expect(screen.getByTestId("detail-title")).toHaveTextContent("WooCommerce");
    expect(screen.getAllByText("商城").length).toBeGreaterThan(0);
    expect(screen.getByText("https://woocommerce.com")).toBeInTheDocument();
    // 右侧摘要:202 条知识 · 2 项需处理(数字与单位分属相邻节点)
    expect(screen.getByText(/条知识/)).toBeInTheDocument();
    expect(screen.getByText(/项需处理/)).toBeInTheDocument();
    expect(screen.getByText(/条知识/).textContent).toContain("6");
    expect(screen.getAllByText(/小时前/).length).toBeGreaterThan(0);
  });

  it("层级 5 prominent attention banner:权威原因摘要 + 查看需处理", () => {
    renderDetail();
    expect(screen.getByText(/有 2 项知识需要处理/)).toBeInTheDocument();
    // 原因摘要 = 权威生命周期计数投影(missing_candidate=2)
    expect(screen.getByText(/2 项源内容缺失/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看需处理" }));
    // 桶过滤到达后端读面(authoritative projection,非前端行过滤)
    expect(useSourceDocuments).toHaveBeenCalledWith(
      "woo-store",
      expect.objectContaining({ bucket: "attention" }),
    );
  });

  it("层级 6 知识内容工作区:表列 名称/类型/状态/当前版本/服务/更新时间 + 共 N 条", () => {
    renderDetail();
    for (const h of ["名称", "类型", "状态", "当前版本", "服务", "更新时间"]) {
      expect(screen.getAllByRole("columnheader", { name: h }).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByText(/共 6 条/).length).toBeGreaterThan(0);
    expect(screen.getByText("v17")).toBeInTheDocument();
    // A-P2-02(audit):serving 真相的参考词+色映射 = 正常(绿);不在服 → 不完整(蓝)
    expect(screen.getAllByText("正常").length).toBeGreaterThan(0);
  });

  it("展开行本地诊断(panel 3 只读部分):问题说明 + 当前有效版本 + 服务真相 + 生成真相", async () => {
    // 真相在渲染前就绪(点击行展开即呈现,只读诊断)
    vi.mocked(useSourceDocumentTruth).mockReturnValue({
      data: truth as never, isLoading: false, isError: false, error: null, refetch: vi.fn(),
    } as never);
    renderDetail();
    // 第二行(Vanishing Page / missing_candidate)的真相展开(A-P3-01:行头 chevron 触发,原地展开)
    fireEvent.click(screen.getAllByTestId("doc-row-toggle")[1]);
    expect(await screen.findByText(/当前有效版本/)).toBeInTheDocument();
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(screen.getAllByText(/缺席宽限/).length).toBeGreaterThan(0);
    // A-P3-02(audit):「生效自」人类化,不再裸 ISO
    expect(screen.queryByText(/生效自 2026-08-01T00:00:00/)).not.toBeInTheDocument();
  });

  it("Forbidden:页面不出现 重新处理 / 知识设置 / 高风险影响预览(无权威支撑不得伪造)", () => {
    renderDetail();
    expect(screen.queryByText("重新处理")).not.toBeInTheDocument();
    expect(screen.queryByText("知识设置")).not.toBeInTheDocument();
    expect(screen.queryByText(/预计影响/)).not.toBeInTheDocument();
  });

  it("panel 4 同步状态卡:最近成功 / 最近结果(部分成功)/ 同步可靠性 / 同步周期", () => {
    renderDetail();
    expect(screen.getByText(/最近成功/)).toBeInTheDocument();
    expect(screen.getByText(/最近结果/)).toBeInTheDocument();
    expect(screen.getAllByText("部分成功").length).toBeGreaterThan(0);
    expect(screen.getByText(/同步可靠性/)).toBeInTheDocument();
    // A-P4-01(audit):参考「98.7%」一位小数(0.987 → 98.7%);样本注记收进 title
    expect(screen.getByText("98.7%")).toBeInTheDocument();
    expect(screen.getByText(/同步周期/)).toBeInTheDocument();
    expect(screen.getByText("每 6 小时")).toBeInTheDocument();
  });

  it("panel 4 活动时间线:异常优先(同步失败红色),常规无变更压缩成组", () => {
    renderDetail();
    expect(screen.getByText("同步失败")).toBeInTheDocument();
    expect(screen.getByText(/sitemap 请求超时/)).toBeInTheDocument();
    // 2 次常规无变更运行 → 单个压缩组节点,不逐条成卡
    expect(screen.getByText(/2 次常规同步/)).toBeInTheDocument();
  });

  it("Forbidden 断言之二:时态角色/新鲜度策略词表不出现(NOT authorized)", () => {
    renderDetail();
    expect(screen.queryByText(/时态角色/)).not.toBeInTheDocument();
    expect(screen.queryByText(/新鲜度要求/)).not.toBeInTheDocument();
  });
});

// ==================== v1.6.3 Design Remediation A 类呈现锁定(audit v163-design-20260913 §4) ====================

describe("v1.6.3 Design Remediation A 类呈现(数据源详情)", () => {
  it("A-P2-01:部分成功 = 链接态(蓝 + chevron svg),指向同步活动锚点", () => {
    renderDetail();
    const link = screen.getByTestId("partial-result-link");
    expect(link.className).toContain("text-[var(--acc)]");
    expect(link.querySelector("svg")).toBeTruthy();
    expect(document.getElementById("sync-activity")).toBeTruthy();
    // A-P2-03:相对时间单格式(精确时间收进 title),不再「N小时前 + 绝对时间」双格式并排
    const relSpans = Array.from(document.querySelectorAll("span")).filter((s) =>
      /小时前/.test(s.textContent ?? ""),
    );
    expect(relSpans.length).toBeGreaterThan(0);
    for (const s of relSpans) {
      expect(s.querySelector("span")).toBeNull();
    }
  });

  it("A-P2-02:服务列呈现映射 = 正常(绿)/不完整(蓝)/—(灰,无现行版本)", () => {
    // renderDetail 内部固定 mock documents;此处临时替换其 items 注入 serving 变体
    const originalItems = documents.items;
    documents.items = [
      { ...originalItems[0], serving: false },
      { ...originalItems[1], current_version_seq: null },
    ];
    try {
      renderDetail();
    } finally {
      documents.items = originalItems;
    }
    const incomplete = screen.getByText("不完整");
    expect(incomplete.className).toContain("bg-blue-50");
    // 无现行版本 → 「—」(灰),不再红「不在服」
    expect(screen.queryByText("不在服")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("A-P2-04:banner 图标 = 红圈 ⚠ 图标", () => {
    renderDetail();
    const icon = document.querySelector("span.rounded-full.bg-red-600");
    expect(icon?.textContent).toContain("⚠");
  });

  it("A-P2-05:页头动作 = 单「⋯」;编辑/返回列表在菜单内", async () => {
    renderDetail();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "返回列表" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "更多页操作" });
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "编辑" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "返回列表" })).toBeInTheDocument();
  });

  it("A-P1-07:面包屑「配置 › 数据源 › {源}」,返回列表由面包屑承担", () => {
    renderDetail();
    const nav = screen.getByRole("navigation", { name: "面包屑" });
    expect(nav.textContent).toContain("›");
    const backLinks = nav.querySelectorAll('a[href="/data-sources"]');
    expect(backLinks.length).toBe(2);
  });

  it("A-P3-01:真相 = 行下原地展开(行头 chevron 触发,aria-expanded)", async () => {
    vi.mocked(useSourceDocumentTruth).mockReturnValue({
      data: truth as never, isLoading: false, isError: false, error: null, refetch: vi.fn(),
    } as never);
    renderDetail();
    const toggles = screen.getAllByTestId("doc-row-toggle");
    fireEvent.click(toggles[1]);
    expect(await screen.findByText(/当前有效版本/)).toBeInTheDocument();
    expect(screen.getAllByTestId("doc-row-toggle")[1]).toHaveAttribute("aria-expanded", "true");
  });

  it("A-P1-03 同口径:知识表名称单行,doc_source_id 收进 title", () => {
    renderDetail();
    expect(screen.queryByText("woo-store/main/p1")).not.toBeInTheDocument();
    expect(screen.getByTitle(/woo-store\/main\/p1/)).toBeInTheDocument();
  });
});
