/**
 * Issue #86(RCA_VERDICT = ROW_ACTION_DISCOVERABILITY_DRIFT / PROVEN)
 * Frozen Product Direction 回归测试:
 * - 常态行不再有「⋯/更多操作」overflow 入口(AC1);
 * - 同步记录 直显,点击行为与既有完全一致 = 展开/收起记录面板(AC2);
 * - 删除 直显,权限/disabled/window.confirm 删除语义完全保持(AC3);
 * - 详情/编辑/同步 不回归(AC4);
 * - read-only 用户不得获得任何写操作(AC5);
 * - delete_failed / deletion-in-flight lifecycle guard 保持;
 *   重试删除 仍为 delete_failed 条件动作,正常行不出现(AC6)。
 * 纯前端呈现层:不改 backend API、删除语义、同步语义、数据模型。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";
import { useDataSources, useSyncRuns } from "@/hooks/useDataSources";

const authState = vi.hoisted(() => ({ role: "admin" as string }));
const mocks = vi.hoisted(() => ({
  deleteMutateAsync: vi.fn(),
  retryDeleteMutateAsync: vi.fn(),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: authState.role, email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: mocks.deleteMutateAsync, isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useRetryDeleteDataSource: () => ({
    mutateAsync: mocks.retryDeleteMutateAsync,
    isPending: false,
  }),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false, variables: null })),
  useTriggerSyncAll: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
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
  authState.role = "admin";
  vi.clearAllMocks();
});

const H2 = 2 * 3600 * 1000;

const baseSource = (overrides: Record<string, unknown> = {}) => ({
  id: "wiki",
  type: "github",
  product: "Product Wiki",
  enabled: true,
  config: { repo_url: "https://github.com/camthink-ai/wiki.git" },
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: new Date(Date.now() - H2).toISOString(),
  last_sync_status: "success",
  last_sync_error: null,
  lifecycle_state: null,
  lifecycle_since: null,
  lifecycle_error: null,
  ...overrides,
});

function withRouter(ui: React.ReactElement) {
  return (
    <MemoryRouter initialEntries={["/data-sources"]}>
      <Routes>
        <Route path="/data-sources" element={ui} />
        <Route path="/data-sources/:sourceId" element={<div data-testid="detail-probe" />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderList(sources: unknown[], role = "admin") {
  authState.role = role;
  vi.mocked(useDataSources).mockReturnValue({
    data: sources as never,
    isLoading: false,
  } as never);
  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}>{withRouter(<DataSources />)}</QueryClientProvider>);
}

describe("#86 行级操作直显(ROW_ACTION_DISCOVERABILITY_DRIFT,Frozen Direction)", () => {
  it("AC1:正常行不再渲染 ⋯/更多操作 overflow 入口", () => {
    renderList([baseSource()]);
    expect(screen.queryByRole("button", { name: "更多操作" })).not.toBeInTheDocument();
  });

  it("AC2:同步记录 直显为行级按钮;点击展开记录面板,再点收起(行为与既有菜单一致)", async () => {
    vi.mocked(useSyncRuns).mockImplementation((_sourceId, options) => ({
      data: options?.enabled
        ? {
            items: [
              {
                id: 11,
                source_id: "wiki",
                status: "completed",
                started_at: "2026-09-14T01:00:00Z",
                sync_log: {
                  status: "success",
                  delta_counts: {
                    unit: "document",
                    new_count: 1,
                    updated_count: 2,
                    retired_count: 0,
                    unchanged_count: 3,
                  },
                },
              },
            ],
            total: 1,
            page: 1,
            size: 20,
          }
        : undefined,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }) as never);
    renderList([baseSource()]);
    // 懒加载契约保持:未展开时 enabled:false
    expect(useSyncRuns).toHaveBeenCalledWith("wiki", { enabled: false });
    fireEvent.click(screen.getByRole("button", { name: "同步记录" }));
    expect(useSyncRuns).toHaveBeenCalledWith("wiki", { enabled: true });
    expect(await screen.findByText(/新增知识 1/)).toBeInTheDocument();
    // 再点收起:面板消失,按钮回到 同步记录
    fireEvent.click(screen.getByRole("button", { name: "收起同步记录" }));
    await waitFor(() =>
      expect(screen.queryByText(/新增知识 1/)).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "同步记录" })).toBeInTheDocument();
  });

  it("AC3:删除 直显;点击走 window.confirm 删除确认后受理删除(语义不变)", async () => {
    mocks.deleteMutateAsync.mockResolvedValue({
      status: "deleting",
      source_id: "wiki",
      accepted: true,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderList([baseSource()]);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain("确定删除数据源 wiki");
    await waitFor(() => expect(mocks.deleteMutateAsync).toHaveBeenCalledWith("wiki"));
    confirmSpy.mockRestore();
  });

  it("AC3/AC6:deletion-in-flight(delete_requested)时 删除/编辑 禁用且不可触发(guard 保持)", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderList([baseSource({ lifecycle_state: "delete_requested" })]);
    const del = screen.getByRole("button", { name: "删除中…" });
    expect(del).toBeDisabled();
    fireEvent.click(del);
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(mocks.deleteMutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "编辑" })).toBeDisabled();
    confirmSpy.mockRestore();
  });

  it("AC4:详情/编辑/同步 仍直显(权限语义保持)", () => {
    renderList([baseSource()]);
    expect(screen.getByRole("button", { name: "详情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "同步" })).toBeEnabled();
  });

  it("AC5:read-only 用户仅 详情/同步记录 可见,不获得任何写操作", () => {
    renderList([baseSource()], "viewer");
    expect(screen.getByRole("button", { name: "详情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "同步记录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "同步" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试删除" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "更多操作" })).not.toBeInTheDocument();
  });

  it("AC6:delete_failed 行直显 重试删除 并受理重试;同步 guard 保持(deny-by-default)", async () => {
    mocks.retryDeleteMutateAsync.mockResolvedValue({
      status: "deleting",
      source_id: "wiki-failed",
      accepted: true,
    });
    renderList([
      baseSource({
        id: "wiki-failed",
        lifecycle_state: "delete_failed",
        lifecycle_error: "orphan cleanup failed",
      }),
    ]);
    const retry = screen.getByRole("button", { name: "重试删除" });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    await waitFor(() =>
      expect(mocks.retryDeleteMutateAsync).toHaveBeenCalledWith("wiki-failed"),
    );
    // delete_failed 非正常态:同步被 lifecycle guard 禁用(既有语义)
    expect(screen.getByRole("button", { name: "同步" })).toBeDisabled();
  });

  it("AC6:正常行不出现 重试删除(delete_failed 条件动作,非常态菜单项)", () => {
    renderList([baseSource()]);
    expect(screen.queryByRole("button", { name: "重试删除" })).not.toBeInTheDocument();
  });
});
