/**
 * v1.6.3 B1(KB-OPS-V163-002):数据源列表收敛行为测试(硬参考 panel 1)。
 *
 * 冻结要点:
 * - 扫描优先密集表:名称/类型/状态/知识数量/需处理(一等列)/最后同步/操作;
 * - 需处理计数与操作者状态均来自后端权威投影(attention-summary/last_sync/
 *   /sync-health),前端零健康重判;
 * - 异常优先排序;搜索/状态/类型过滤为呈现层;页脚 共 N 个数据源;
 * - 既有操作(同步/编辑/删除/可观测性)保留,操作收敛为 context-preserving
 *   抽屉语法(编辑数据源 Drawer,KB-OPS-V163-002 §4.5)。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";
import {
  useDataSources,
  useTriggerSync,
  useTriggerSyncAll,
  useSourceHealth,
  useSyncHealth,
  useSyncStatus,
  useSyncRuns,
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
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useRetryDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false, variables: null })),
  useTriggerSyncAll: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useSourceHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useSyncHealth: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSyncStatus: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSyncRuns: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
  useAttentionSummary: vi.fn(() => ({ data: undefined, isLoading: false })),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
  fetchRepoDiscovery: vi.fn(),
  fetchWebsiteDiscovery: vi.fn(),
  usePreviewDirs: vi.fn(() => ({ data: { dirs: [] }, isLoading: false, error: null })),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const H2 = 2 * 3600 * 1000;
const H4 = 4 * 3600 * 1000;

const wooSource = {
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

const wikiSource = {
  id: "wiki",
  type: "github",
  product: "Product Wiki",
  enabled: true,
  config: { repo_url: "https://github.com/camthink-ai/wiki.git" },
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: new Date(Date.now() - H4).toISOString(),
  last_sync_status: "success",
  last_sync_error: null,
  lifecycle_state: null,
  lifecycle_since: null,
  lifecycle_error: null,
};

const summary = {
  items: [
    {
      source_id: "woo-store",
      ledger_total: 202,
      current_count: 199,
      serving_count: 200,
      retired_count: 0,
      attention_count: 3,
      lifecycle_counts: { active: 200, missing_candidate: 2 },
    },
    {
      source_id: "wiki",
      ledger_total: 486,
      current_count: 486,
      serving_count: 486,
      retired_count: 0,
      attention_count: 0,
      lifecycle_counts: { active: 486 },
    },
  ],
};

function withRouter(ui: React.ReactElement) {
  return (
    <MemoryRouter initialEntries={["/data-sources"]}>
      <Routes>
        <Route path="/data-sources" element={ui} />
      </Routes>
    </MemoryRouter>
  );
}

function renderList(sources: unknown[], summaryData: unknown = summary) {
  vi.mocked(useDataSources).mockReturnValue({
    data: sources as never,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useAttentionSummary).mockReturnValue({
    data: summaryData as never,
    isLoading: false,
  } as never);
  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}>{withRouter(<DataSources />)}</QueryClientProvider>);
}

describe("v1.6.3 B1 数据源列表收敛(hard ref panel 1)", () => {
  it("页头:面包屑 配置/数据源 + 标题 数据源 + 副标题 + 主按钮 添加数据源", () => {
    renderList([wooSource, wikiSource]);
    expect(screen.getByRole("heading", { name: "数据源" })).toBeInTheDocument();
    expect(screen.getByText(/管理.*知识来源/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /添加数据源/ })).toBeInTheDocument();
  });

  it("密集扫描表:一等 需处理 列 + 知识数量 列(权威聚合投影)", () => {
    renderList([wooSource, wikiSource]);
    for (const h of ["名称", "类型", "状态", "知识数量", "需处理", "最后同步"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    // WooCommerce 行:知识数量 202 / 需处理 3
    expect(screen.getByText("202")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // wiki 行:486 条知识
    expect(screen.getByText("486")).toBeInTheDocument();
  });

  it("操作者状态徽章:需处理(红)与 正常(绿)来自权威值", () => {
    renderList([wooSource, wikiSource]);
    expect(screen.getByText("3")).toBeInTheDocument(); // 需处理列:WooCommerce = 3(红)
    expect(screen.getAllByText("正常").length).toBeGreaterThan(0); // wiki 操作者状态徽章
  });

  it("异常优先排序:需处理源排在正常源之前", () => {
    renderList([wikiSource, wooSource]); // 传入时正常源在前
    const rows = screen.getAllByRole("row");
    const wooIdx = rows.findIndex((r) => (r.textContent ?? "").includes("WooCommerce"));
    const wikiIdx = rows.findIndex((r) => (r.textContent ?? "").includes("Product Wiki"));
    expect(wooIdx).toBeGreaterThan(-1);
    expect(wikiIdx).toBeGreaterThan(-1);
    expect(wooIdx).toBeLessThan(wikiIdx); // 异常优先:需处理源在前
  });

  it("相对时间:最后同步列人性化(2小时前),精确时间由 title 保留", () => {
    renderList([wooSource, wikiSource]);
    expect(screen.getAllByText(/小时前/).length).toBeGreaterThan(0);
  });

  it("页脚:共 N 个数据源", () => {
    renderList([wooSource, wikiSource]);
    expect(screen.getByText(/共 2 个数据源/)).toBeInTheDocument();
  });

  it("搜索框按名称过滤(呈现层)", () => {
    renderList([wooSource, wikiSource]);
    fireEvent.change(screen.getByPlaceholderText(/搜索数据源/), {
      target: { value: "Wiki" },
    });
    expect(screen.getByText("Product Wiki")).toBeInTheDocument();
    expect(screen.queryByText("WooCommerce")).not.toBeInTheDocument();
  });

  it("状态过滤下拉(呈现层,选项来自操作者状态词表)", () => {
    renderList([wooSource, wikiSource]);
    const filter = screen.getByLabelText("按状态过滤");
    fireEvent.change(filter, { target: { value: "attention" } });
    expect(screen.getByText("WooCommerce")).toBeInTheDocument();
    expect(screen.queryByText("Product Wiki")).not.toBeInTheDocument();
  });

  it("编辑打开右侧抽屉(context-preserving drawer 语法,§4.5),抽屉含标题 编辑数据源", () => {
    renderList([wooSource, wikiSource]);
    fireEvent.click(screen.getAllByRole("button", { name: "编辑" })[0]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("编辑数据源")).toBeInTheDocument();
  });

  it("既有破坏性操作(删除)保留但收敛进 ⋯ 次要菜单(hard ref §4.1 compact actions)", async () => {
    renderList([wooSource, wikiSource]);
    // 删除不再以大红按钮平铺;收进紧凑操作菜单
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
    const trigger = screen.getAllByRole("button", { name: "更多操作" })[0];
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);
    expect(await screen.findByRole("menuitem", { name: "查看可观测性" })).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem", { name: "删除" }).length).toBe(1);
  });

  it("零数据源:空态与页脚 共 0 个数据源", () => {
    renderList([], { items: [] });
    expect(screen.getByText(/暂无数据源/)).toBeInTheDocument();
    expect(screen.getByText(/共 0 个数据源/)).toBeInTheDocument();
  });
});
