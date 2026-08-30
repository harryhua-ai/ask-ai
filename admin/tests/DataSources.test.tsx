import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";
import {
  useDataSources,
  useTriggerSync,
  fetchPreviewBranches,
  fetchPreviewFileTypes,
  useTriggerSyncAll,
} from "@/hooks/useDataSources";

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
  useTriggerSyncAll: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
}));

afterEach(() => {
  vi.mocked(useDataSources).mockReturnValue({ data: [], isLoading: false });
  vi.mocked(useTriggerSync).mockReset();
  vi.mocked(useTriggerSyncAll).mockReset();
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

  it("github 拉取分支后:复选框供选择,已配置分支预选,勾选/取消更新值", async () => {
    vi.mocked(fetchPreviewBranches).mockResolvedValue({
      branches: ["main", "hw-v1.2", "dev"],
      defaultBranch: "main",
    });
    const ds = {
      id: "ne301-docs",
      type: "github",
      product: "ne301",
      enabled: true,
      config: { repo_url: "https://github.com/camthink-ai/ne301.git", branches: ["main"] },
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: null,
    };
    renderWithSources([ds]);
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("拉取分支"));
    // 拉取后渲染复选框(远端 3 个分支)
    const mainChk = await screen.findByRole("checkbox", { name: "main" });
    const hwChk = screen.getByRole("checkbox", { name: "hw-v1.2" });
    const devChk = screen.getByRole("checkbox", { name: "dev" });
    // 已配置的 main 预选,其余未选
    expect(mainChk).toBeChecked();
    expect(hwChk).not.toBeChecked();
    expect(devChk).not.toBeChecked();
    // 勾选 dev → 选中
    fireEvent.click(devChk);
    expect(devChk).toBeChecked();
    // 取消 main → 不再选中
    fireEvent.click(mainChk);
    expect(mainChk).not.toBeChecked();
  });

  it("同步间隔:预设下拉(1h/12h/1天) + 自定义显示文本输入", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    const select = screen.getByLabelText("同步间隔");
    // 默认 24h = "1 天" 预设
    expect(select).toHaveValue("24h");
    // 切 1h
    fireEvent.change(select, { target: { value: "1h" } });
    expect(select).toHaveValue("1h");
    // 切自定义 → 文本输入出现,初始为空
    fireEvent.change(select, { target: { value: "__custom" } });
    const input = screen.getByPlaceholderText("30m / 48h");
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue("");
    fireEvent.change(input, { target: { value: "30m" } });
    expect(input).toHaveValue("30m");
    // 切回预设 → 文本输入消失
    fireEvent.change(select, { target: { value: "12h" } });
    expect(screen.queryByPlaceholderText("30m / 48h")).not.toBeInTheDocument();
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

  it("#3 同名产品线多源:产品线列副标题按类型显示 repo_url/root_path 用于区分", () => {
    const dsA = {
      id: "neomind-docs",
      type: "github",
      product: "neomind",
      enabled: true,
      config: { repo_url: "https://github.com/camthink-ai/neomind-docs.git" },
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
      config: { root_path: "/data/neomind-sdk" },
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: null,
    };
    renderWithSources([dsA, dsB]);
    // 两行同名产品线下,产品线统一显示裸 product key(与编辑框一致,不再查中文标签)
    expect(screen.getAllByText("neomind").length).toBe(2);
    expect(screen.getByText("https://github.com/camthink-ai/neomind-docs.git")).toBeInTheDocument();
    expect(screen.getByText("/data/neomind-sdk")).toBeInTheDocument();
    // 源 ID 不裸显在产品线列
    expect(screen.queryByText("neomind-docs")).not.toBeInTheDocument();
    expect(screen.queryByText("neomind-sdk")).not.toBeInTheDocument();
  });

  it("代码仓库源缺 repo_url 时:副标题由 repo_path 重建 github 链接,不裸显本地路径", () => {
    // 历史 local_git 源 DB 里只有 repo_path(本地 clone 路径),没有 repo_url
    const ds = {
      id: "ne301-docs-local",
      type: "local_git",
      product: "ne301",
      enabled: true,
      config: { repo_path: "~/ask-ai-corpus/ne301" },
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      last_sync: null,
    };
    renderWithSources([ds]);
    // 由 repo_path 末段按 camthink-ai 约定重建 github 链接(与编辑表单 dsToForm 同规则)
    expect(screen.getByText("https://github.com/camthink-ai/ne301.git")).toBeInTheDocument();
    // 不再把本地 clone 路径当副标题裸显
    expect(screen.queryByText("~/ask-ai-corpus/ne301")).not.toBeInTheDocument();
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

  it("#B 后台同步失败(last_sync 推进但 status=failed):提示同步失败,不误报完成", () => {
    const ds = {
      id: "ne301-local",
      type: "github",
      product: "ne301",
      enabled: true,
      config: { repo_url: "https://github.com/camthink-ai/ne301.git" },
      sync_interval: "24h",
      last_sync: null,
      last_sync_status: null,
      last_sync_error: null,
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

    // 模拟轮询返回:后台同步失败,sync_log 仍写了一行(started_at 推进,status=failed,error_detail='local_git')
    const updated = {
      ...ds,
      last_sync: new Date(Date.now() + 60000).toISOString(),
      last_sync_status: "failed",
      last_sync_error: "local_git",
    };
    vi.mocked(useDataSources).mockReturnValue({ data: [updated], isLoading: false });
    view.rerender(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("同步失败"));
    expect(toast.success).not.toHaveBeenCalledWith(expect.stringContaining("同步完成"));
    expect(screen.getByText("同步")).toBeInTheDocument();
  });

  it("同步全部:触发后端顺序同步,把返回 source_ids 批量入 syncingIds", async () => {
    const dsA = {
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
    const dsB = {
      id: "ne503-docs",
      type: "github",
      product: "ne503",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const mutateAllAsync = vi.fn().mockResolvedValue({
      status: "syncing",
      source_ids: ["ne301-docs", "ne503-docs"],
      count: 2,
    });
    vi.mocked(useTriggerSyncAll).mockReturnValue({
      mutateAsync: mutateAllAsync,
      isPending: false,
    });
    renderWithSources([dsA, dsB]);

    fireEvent.click(screen.getByText("同步全部"));
    await waitFor(() => expect(mutateAllAsync).toHaveBeenCalled());
    // 两行均进入"同步中..."
    expect(await screen.findAllByText("同步中...")).toHaveLength(2);
    // syncingIds>0 时「同步全部」按钮禁用,避免并发触发
    expect(screen.getByText("同步全部")).toBeDisabled();
  });
});

// ====================  C10:branches 默认值跟随仓库 default_branch  ====================


describe("C10 branches 默认分支", () => {
  it("新建表单 branches 初始为空,不再硬编码 main", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    const el = document.querySelector('input[name="branches"]') as HTMLInputElement;
    expect(el?.value).toBe("");
  });

  it("拉取分支后 default_branch 自动选中(替代 main 硬编码)", async () => {
    vi.mocked(fetchPreviewBranches).mockResolvedValue({
      branches: ["master", "hw-v1.2"],
      defaultBranch: "hw-v1.2",
    });
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    fireEvent.change(
      screen.getByPlaceholderText("https://github.com/camthink-ai/ne301.git"),
      { target: { value: "https://github.com/camthink-ai/demo.git" } },
    );
    fireEvent.click(screen.getByText("拉取分支"));
    await waitFor(() => expect(screen.getByText("hw-v1.2")).toBeInTheDocument());
    // default_branch 自动勾选,master 未勾选
    const hw = screen
      .getByText("hw-v1.2")
      .closest("label")
      ?.querySelector("input") as HTMLInputElement;
    expect(hw.checked).toBe(true);
    const master = screen
      .getByText("master")
      .closest("label")
      ?.querySelector("input") as HTMLInputElement;
    expect(master.checked).toBe(false);
  });

  it("编辑无 branches 配置的源回填空串,不再兜底 main", () => {
    renderWithSources([
      {
        id: "c10-src",
        type: "github",
        product: "demo",
        enabled: true,
        sync_interval: "24h",
        config: { repo_url: "https://github.com/camthink-ai/demo.git" },
      },
    ]);
    fireEvent.click(screen.getByText("编辑"));
    const el = document.querySelector('input[name="branches"]') as HTMLInputElement;
    expect(el?.value).toBe("");
  });
});

// ====================  C9:filesystem 内容来源双模式  ====================


describe("C9 filesystem 内容来源", () => {
  it("新建 filesystem 源:默认服务器路径模式,root_path 可见", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    fireEvent.change(screen.getByDisplayValue("github"), {
      target: { value: "filesystem" },
    });
    expect(screen.getByPlaceholderText("/data/docs")).toBeInTheDocument();
    expect(screen.queryByLabelText("选择文件夹")).not.toBeInTheDocument();
  });

  it("切到上传文件夹模式:root_path 隐藏,出现文件夹选择器", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    fireEvent.change(screen.getByDisplayValue("github"), {
      target: { value: "filesystem" },
    });
    fireEvent.click(screen.getByText("上传文件夹"));
    expect(screen.queryByPlaceholderText("/data/docs")).not.toBeInTheDocument();
    expect(screen.getByLabelText("选择文件夹")).toBeInTheDocument();
  });
});

// ====================  C10 增补:拉取时自动列全仓库文件后缀  ====================


it("拉取分支后 file_types 自动预填仓库全部后缀,用户按需删", async () => {
  vi.mocked(fetchPreviewBranches).mockResolvedValue({
    branches: ["master"],
    defaultBranch: "master",
  });
  vi.mocked(fetchPreviewFileTypes).mockResolvedValue({
    extensions: [".c", ".h", ".md"],
  });
  renderWithSources([]);
  fireEvent.click(screen.getByText("新增数据源"));
  fireEvent.change(
    screen.getByPlaceholderText("https://github.com/camthink-ai/ne301.git"),
    { target: { value: "https://github.com/camthink-ai/demo.git" } },
  );
  fireEvent.click(screen.getByText("拉取分支"));
  await waitFor(() => {
    expect(
      (screen.getByDisplayValue(".c, .h, .md") as HTMLInputElement).value,
    ).toBe(".c, .h, .md");
  });
});
