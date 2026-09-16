/**
 * Issue #53 GAP_ONLY(matrix row A1,Implementation Contract r5-UX orchestrator):
 * 有需处理项的数据源行,attention reason(后端权威 lifecycle_counts 的
 * attentionReasonClasses 投影)必须在列表行扫描可见 —— 无需进入详情页。
 *
 * 基线事实(矩阵 A1,PARTIAL):该权威投影此前仅在详情 banner 渲染
 * (DataSourceDetail.tsx);列表「需处理」单元格只有计数 + 泛化 tooltip
 * (「N 项知识需要处理」),不回答"为什么需要处理"。
 * 冻结纪律:投影输入 = 已取回的 attention-summary lifecycle_counts,前端零健康重判。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";
import { attentionReasonClasses } from "@/lib/dataSourceOps";
import {
  useDataSources,
  useTriggerSync,
  useTriggerSyncAll,
  useSourceHealth,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
  useAttentionSummary,
} from "@/hooks/useDataSources";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRetryDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useTriggerSyncAll: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSourceHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useSyncHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useSyncStatus: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSyncRuns: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useAttentionSummary: vi.fn(() => ({ data: undefined, isLoading: false })),
  usePreviewDirs: vi.fn(() => ({ data: { dirs: [] }, isLoading: false, error: null })),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
  fetchRepoDiscovery: vi.fn(),
  fetchWebsiteDiscovery: vi.fn(),
}));

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useDataSources).mockReturnValue({ data: [], isLoading: false });
  vi.mocked(useTriggerSync).mockReturnValue({ mutate: vi.fn(), isPending: false });
  vi.mocked(useSourceHealth).mockReturnValue({ data: undefined, isLoading: false });
  vi.mocked(useSyncHealth).mockReturnValue({ data: undefined, isLoading: false });
  vi.mocked(useSyncStatus).mockReturnValue({ data: { items: [] }, isLoading: false });
  vi.mocked(useSyncRuns).mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  vi.mocked(useAttentionSummary).mockReturnValue({ data: undefined, isLoading: false });
});

const attentionSource = {
  id: "woo-store",
  type: "web_crawl",
  product: "WooCommerce",
  enabled: true,
  config: { base_url: "https://woo.example" },
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
  last_sync: "2026-09-15T08:00:00Z",
  last_sync_status: "success",
  last_sync_error: null,
};

const healthySource = {
  ...attentionSource,
  id: "wiki",
  product: "Product Wiki",
};

const attentionSummaryItem = {
  source_id: "woo-store",
  ledger_total: 202,
  current_count: 199,
  serving_count: 200,
  retired_count: 0,
  attention_count: 3,
  lifecycle_counts: { active: 199, missing_candidate: 2, discovered: 1 },
};

const healthySummaryItem = {
  source_id: "wiki",
  ledger_total: 486,
  current_count: 486,
  serving_count: 486,
  retired_count: 0,
  attention_count: 0,
  lifecycle_counts: { active: 486 },
};

function renderList(sources: unknown[], summaryItems: unknown[]) {
  vi.mocked(useDataSources).mockReturnValue({ data: sources as never, isLoading: false });
  vi.mocked(useAttentionSummary).mockReturnValue({
    data: { items: summaryItems } as never,
    isLoading: false,
  });
  const qc = new QueryClient();
  render(
    <MemoryRouter initialEntries={["/data-sources"]}>
      <Routes>
        <Route path="/data-sources" element={<DataSources />} />
        <Route path="/data-sources/:sourceId" element={<div data-testid="detail-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Issue #53 A1:列表行 attention reason 扫描可见", () => {
  it("有需处理项的行:attentionReasonClasses 权威原因以单元格文本扫描可见 + 完整分解在 title;零需处理行不渲染", () => {
    renderList([attentionSource, healthySource], [attentionSummaryItem, healthySummaryItem]);

    // 权威原因文本与详情 banner 同一出处(attentionReasonClasses 投影)
    const expectedReasons = attentionReasonClasses(
      attentionSummaryItem.lifecycle_counts,
      attentionSummaryItem.attention_count,
    );
    expect(expectedReasons.length).toBeGreaterThan(0);

    // 需处理计数仍是一等红数(既有视觉语法不动)
    expect(screen.getByText("3")).toBeInTheDocument();

    // 原因文本扫描可见:作为单元格文本直接在行内(非 hover-only)
    const reasonSpan = screen.getByText(/项源内容缺失/);
    expect(reasonSpan.textContent ?? "").toContain(expectedReasons[0]);
    expect(reasonSpan.textContent ?? "").toContain(expectedReasons[1]);

    // 完整分解保留在 title(取代旧泛化 tooltip「N 项知识需要处理」)
    const titled = screen.getByTitle(/项源内容缺失/);
    expect(titled.getAttribute("title") ?? "").toContain(expectedReasons[0]);
    expect(titled.getAttribute("title") ?? "").toContain(expectedReasons[1]);
    expect(screen.queryByTitle("3 项知识需要处理")).not.toBeInTheDocument();

    // 零需处理行:不渲染原因(—)
    const wikiRow = screen.getByText("Product Wiki").closest("tr");
    expect(wikiRow?.textContent ?? "").not.toContain("缺席宽限期");
  });
});
