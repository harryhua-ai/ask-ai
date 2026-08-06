import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";
import { useDataSources, useTriggerSync } from "@/hooks/useDataSources";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { toast } from "sonner";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

// Mock 网络层 hooks,避免真实 fetch
vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  fetchPreviewBranches: vi.fn(),
}));

afterEach(() => {
  vi.mocked(useDataSources).mockReturnValue({ data: [], isLoading: false });
  vi.mocked(useTriggerSync).mockReset();
});

function renderWithSources(sources: unknown[]) {
  vi.mocked(useDataSources).mockReturnValue({ data: sources, isLoading: false });
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <DataSources />
    </QueryClientProvider>,
  );
}

describe("DataSources", () => {
  it("renders title", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    expect(screen.getByText("数据源管理")).toBeInTheDocument();
  });

  it("shows empty state when no data sources", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    expect(screen.getByText("暂无数据源")).toBeInTheDocument();
  });

  it("opens create form when clicking new button", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByText("新增数据源"));
    expect(screen.getByText("创建")).toBeInTheDocument();
  });

  it("#1 编辑 local_git 源:类型归一为 github 且 repo_path 转换为 repo_url+clone_path", () => {
    const localGitDs = {
      id: "ne301-docs-local",
      type: "local_git",
      product: "ne301",
      enabled: true,
      config: {
        repo_path: "~/ask-ai-corpus/ne301",
        branches: ["main", "hw-v1.2"],
        file_types: [".md", ".py"],
      },
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    renderWithSources([localGitDs]);
    fireEvent.click(screen.getByText("编辑"));
    // 类型下拉归一为 github
    expect(screen.getByDisplayValue("github")).toBeInTheDocument();
    // repo_path → repo_url(与迁移脚本 build_github_config 一致的 camthink-ai org 规则)
    expect(
      screen.getByDisplayValue("https://github.com/camthink-ai/ne301.git"),
    ).toBeInTheDocument();
    // repo_path 保留为 clone_path(复用现有 clone 副本)
    expect(screen.getByDisplayValue("~/ask-ai-corpus/ne301")).toBeInTheDocument();
    // branches / file_types 逗号拼接回填
    expect(screen.getByDisplayValue("main, hw-v1.2")).toBeInTheDocument();
    expect(screen.getByDisplayValue(".md, .py")).toBeInTheDocument();
  });

  it("#2 表格对 local_git 源显示中文类型标签(代码仓库),不裸显英文", () => {
    const localGitDs = {
      id: "ne301-docs-local",
      type: "local_git",
      product: "ne301",
      enabled: true,
      config: {},
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    renderWithSources([localGitDs]);
    expect(screen.getByText("代码仓库")).toBeInTheDocument();
    expect(screen.queryByText("local_git")).not.toBeInTheDocument();
  });

  it("#3 同名产品线多源:每行显示源 ID 副标题用于区分", () => {
    const dsA = {
      id: "neomind-docs",
      type: "github",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: "2026-08-01T10:30:00Z",
    };
    const dsB = {
      id: "neomind-sdk",
      type: "filesystem",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: null,
    };
    renderWithSources([dsA, dsB]);
    // 两行同名产品线下,ID 作为副标题区分
    expect(screen.getAllByText("NeoMind 平台").length).toBe(2);
    expect(screen.getByText("neomind-docs")).toBeInTheDocument();
    expect(screen.getByText("neomind-sdk")).toBeInTheDocument();
  });

  it("最新同步列:显示最近一次同步时间,无记录显示占位符", () => {
    const withSync = {
      id: "neomind-docs",
      type: "github",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: "2026-08-01T10:30:00Z",
    };
    const noSync = {
      id: "neomind-sdk",
      type: "filesystem",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: null,
    };
    renderWithSources([withSync, noSync]);
    expect(screen.getByText("08-01 18:30")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("#44 点击某行「同步」:仅触发该源,仅该行进入同步中状态", () => {
    const dsA = {
      id: "neomind-docs",
      type: "github",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const dsB = {
      id: "neomind-sdk",
      type: "filesystem",
      product: "neomind",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const mutate = vi.fn();
    vi.mocked(useTriggerSync).mockReturnValue({ mutate, isPending: false });
    renderWithSources([dsA, dsB]);

    const syncButtons = screen.getAllByText("同步");
    expect(syncButtons).toHaveLength(2);
    fireEvent.click(syncButtons[0]);

    expect(mutate).toHaveBeenCalledWith("neomind-docs");
    // 仅该行进入"同步中...", 另一行保持"同步"可独立操作
    expect(screen.getByText("同步中...")).toBeInTheDocument();
    expect(screen.getAllByText("同步")).toHaveLength(1);
  });

  it("#44 禁用源:同步按钮不可点击", () => {
    const ds = {
      id: "ne301-docs",
      type: "github",
      product: "ne301",
      enabled: false,
      config: {},
      sync_interval: "24h",
      last_sync: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const mutate = vi.fn();
    vi.mocked(useTriggerSync).mockReturnValue({ mutate, isPending: false });
    renderWithSources([ds]);

    const syncBtn = screen.getByText("同步") as HTMLButtonElement;
    expect(syncBtn).toBeDisabled();
    fireEvent.click(syncBtn);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("#44 后台同步完成(last_sync 推进):提示完成且按钮恢复为「同步」", () => {
    const ds = {
      id: "ne301-docs",
      type: "github",
      product: "ne301",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const mutate = vi.fn();
    vi.mocked(useTriggerSync).mockReturnValue({ mutate, isPending: false });
    vi.mocked(useDataSources).mockReturnValue({ data: [ds], isLoading: false });
    const qc = new QueryClient();
    const view = render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByText("同步"));
    expect(screen.getByText("同步中...")).toBeInTheDocument();

    // 模拟 5s 轮询返回:后台 _sync_one 写入 SyncLog → list 聚合 last_sync 推进到触发时刻之后
    const updated = {
      ...ds,
      last_sync: new Date(Date.now() + 60000).toISOString(),
    };
    vi.mocked(useDataSources).mockReturnValue({ data: [updated], isLoading: false });
    view.rerender(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );

    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("同步完成"));
    expect(screen.getByText("同步")).toBeInTheDocument();
    expect(screen.queryByText("同步中...")).not.toBeInTheDocument();
  });
});
