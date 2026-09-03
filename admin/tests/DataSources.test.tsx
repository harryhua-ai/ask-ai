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
  useSourceHealth,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
} from "@/hooks/useDataSources";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { toast } from "sonner";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

// Mock 网络层 hooks,避免真实 fetch;create/update mutateAsync 提升为共享 mock 供 payload 断言
const mocks = vi.hoisted(() => ({
  createMutateAsync: vi.fn(),
  updateMutateAsync: vi.fn(),
}));

vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: mocks.createMutateAsync, isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: mocks.updateMutateAsync, isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
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
  usePreviewDirs: vi.fn(() => ({ data: { dirs: [] }, isLoading: false, error: null })),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(useDataSources).mockReturnValue({ data: [], isLoading: false });
  vi.mocked(useTriggerSync).mockReturnValue({ mutate: vi.fn(), isPending: false });
  vi.mocked(useTriggerSyncAll).mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  vi.mocked(useSourceHealth).mockReturnValue({ data: undefined, isLoading: false });
  vi.mocked(useSyncHealth).mockReturnValue({ data: undefined, isLoading: false });
  vi.mocked(useSyncStatus).mockReturnValue({ data: { items: [] }, isLoading: false });
  vi.mocked(useSyncRuns).mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
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
    // 类型下拉归一为 github(选项显示中文可读名,选中值仍为 github)
    expect(screen.getByDisplayValue("代码仓库")).toHaveValue("github");
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

  it("点击某行同步只提交该源，后端没有 active 证据时不伪造同步中", () => {
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
    expect(screen.queryByText("同步中...")).not.toBeInTheDocument();
    expect(screen.getAllByText("同步")).toHaveLength(2);
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

  it("挂载即恢复后端 active 状态，并按源隔离动作与阶段进度", () => {
    const dsA = {
      id: "ne301-docs",
      type: "github",
      product: "ne301",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: "2026-09-03T01:00:00Z",
      last_sync_status: "success",
      last_sync_error: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    const dsB = { ...dsA, id: "ne503-docs", product: "ne503" };
    vi.mocked(useSyncStatus).mockReturnValue({
      data: {
        items: [{
          source_id: "ne301-docs",
          state: "RUNNING",
          request_id: 42,
          attempt: 1,
          recovering: false,
          stage: "EMBED",
          stage_current: 3,
          stage_total: 12,
          counters: { docs_total: 12, chunks_written: 8 },
          execution_device: "cuda:0",
          started_at: "2026-09-03T02:00:00Z",
          updated_at: "2026-09-03T02:00:05Z",
        }],
      },
      isLoading: false,
    });

    renderWithSources([dsA, dsB]);

    expect(useSyncStatus).toHaveBeenCalledWith({ refetchInterval: 5000 });
    expect(screen.getByText("同步中...")).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "同步" })).toHaveLength(1);
    expect(screen.getByText("当前同步")).toBeInTheDocument();
    expect(screen.getByText("生成向量")).toBeInTheDocument();
    expect(screen.getByText("3/12 · 25%")).toBeInTheDocument();
    expect(screen.getByText("执行设备：GPU")).toBeInTheDocument();
  });

  it("成功的 last_sync 不能在 /sync-status 无 active 证据时保持同步中", () => {
    renderWithSources([{
      id: "ne301-docs",
      type: "github",
      product: "ne301",
      enabled: true,
      config: {},
      sync_interval: "24h",
      last_sync: new Date(Date.now() + 60000).toISOString(),
      last_sync_status: "success",
      last_sync_error: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    }]);

    expect(screen.queryByText("同步中...")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "同步" })).toBeEnabled();
    expect(toast.success).not.toHaveBeenCalledWith(expect.stringContaining("同步完成"));
  });

  it("同步全部只提交请求，行状态随后仅由后端 active items 恢复", async () => {
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
    vi.mocked(useDataSources).mockReturnValue({ data: [dsA, dsB], isLoading: false });
    const qc = new QueryClient();
    const view = render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByText("同步全部"));
    await waitFor(() => expect(mutateAllAsync).toHaveBeenCalled());
    expect(screen.queryByText("同步中...")).not.toBeInTheDocument();

    vi.mocked(useSyncStatus).mockReturnValue({
      data: {
        items: ["ne301-docs", "ne503-docs"].map((source_id) => ({
          source_id,
          state: "WAITING" as const,
          request_id: 77,
          attempt: 1,
          recovering: false,
          stage: "DISCOVER" as const,
          stage_current: null,
          stage_total: null,
          counters: null,
          execution_device: null,
          started_at: null,
          updated_at: "2026-09-03T02:00:05Z",
        })),
      },
      isLoading: false,
    });
    view.rerender(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );

    expect(screen.getAllByText("同步中...")).toHaveLength(2);
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
    fireEvent.change(screen.getByDisplayValue("代码仓库"), {
      target: { value: "filesystem" },
    });
    expect(screen.getByPlaceholderText("/data/docs")).toBeInTheDocument();
    expect(screen.queryByLabelText("选择文件夹")).not.toBeInTheDocument();
  });

  it("切到上传文件夹模式:root_path 隐藏,出现文件夹选择器", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    fireEvent.change(screen.getByDisplayValue("代码仓库"), {
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

// ====================  C8B:web_crawl 表单一等公民  ====================


const c8bWebCrawlDs = (config: Record<string, unknown>) => ({
  id: "web-crawl-test",
  type: "web_crawl",
  product: "camthink",
  enabled: true,
  config,
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
  last_sync: null,
});

describe("C8B web_crawl 表单一等公民", () => {
  it("类型下拉包含网站爬取选项(web_crawl)", () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    const select = screen.getByDisplayValue("代码仓库") as HTMLSelectElement;
    const webOpt = Array.from(select.options).find((o) => o.value === "web_crawl");
    expect(webOpt?.textContent).toBe("网站爬取");
  });

  it("新建 web_crawl:四字段表单出现,base_url 留空提交被拦截", async () => {
    renderWithSources([]);
    fireEvent.click(screen.getByText("新增数据源"));
    fireEvent.change(screen.getByDisplayValue("代码仓库"), {
      target: { value: "web_crawl" },
    });
    expect(screen.getByPlaceholderText("https://www.camthink.ai")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("500")).toBeInTheDocument();
    // base_url 留空提交被 zod 拦截
    fireEvent.click(screen.getByText("创建"));
    await waitFor(() =>
      expect(screen.getByText("站点地址必填")).toBeInTheDocument(),
    );
    expect(mocks.createMutateAsync).not.toHaveBeenCalled();
  });

  it("编辑 web_crawl 源:类型显示 web_crawl 不被归一 github,四字段按本类型预填", () => {
    renderWithSources([
      c8bWebCrawlDs({
        base_url: "https://www.camthink.ai",
        sitemap_url: "https://www.camthink.ai/sitemap_index.xml",
        exclude_patterns: ["/store/"],
        crawl_delay_ms: 800,
      }),
    ]);
    fireEvent.click(screen.getByText("编辑"));
    // 陷阱关闭的直接证据:类型选项显示「网站爬取」且选中值为 web_crawl,不再归一 github
    expect(screen.getByDisplayValue("网站爬取")).toHaveValue("web_crawl");
    expect(
      screen.getByDisplayValue("https://www.camthink.ai"),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("https://www.camthink.ai/sitemap_index.xml"),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("/store/")).toBeInTheDocument();
    expect(screen.getByDisplayValue("800")).toBeInTheDocument();
  });

  it("编辑往返不改点保存:payload type=web_crawl 且 config 四键原样(AC2 形态)", async () => {
    const config = {
      base_url: "https://www.camthink.ai",
      sitemap_url: "https://www.camthink.ai/sitemap_index.xml",
      exclude_patterns: ["/store/"],
      crawl_delay_ms: 800,
    };
    mocks.updateMutateAsync.mockResolvedValue({});
    renderWithSources([c8bWebCrawlDs(config)]);
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(mocks.updateMutateAsync).toHaveBeenCalled());
    expect(mocks.updateMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ id: "web-crawl-test", type: "web_crawl", config }),
    );
  });

  it("最简 config(仅 base_url)round-trip:保存后不引入空键,config 仍仅 base_url", async () => {
    mocks.updateMutateAsync.mockResolvedValue({});
    renderWithSources([c8bWebCrawlDs({ base_url: "https://www.camthink.ai" })]);
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(mocks.updateMutateAsync).toHaveBeenCalled());
    expect(mocks.updateMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "web_crawl",
        config: { base_url: "https://www.camthink.ai" },
      }),
    );
  });

  it("列表徽标:web_crawl 显示中文「网站爬取」,产品线副标题为 base_url", () => {
    renderWithSources([c8bWebCrawlDs({ base_url: "https://www.camthink.ai" })]);
    expect(screen.getByText("网站爬取")).toBeInTheDocument();
    expect(screen.getByText("https://www.camthink.ai")).toBeInTheDocument();
  });
});

// ====================  C8B:三旧类型 round-trip 回归(零波及)  ====================


describe("C8B 三旧类型回归", () => {
  const legacyCases = [
    {
      type: "github",
      product: "ne301",
      config: { repo_url: "https://github.com/camthink-ai/ne301.git", branches: ["main"] },
    },
    {
      type: "filesystem",
      product: "docs",
      config: { root_path: "/data/docs", include_dirs: ["docs"] },
    },
    {
      type: "woocommerce",
      product: "store",
      config: { store_url: "https://camthink.ai", consumer_key: "ck_x", consumer_secret: "cs_x" },
    },
  ];
  it.each(legacyCases)("编辑 $type 源不改点保存:type 保持且 config 关键键不丢", async ({ type, product, config }) => {
    mocks.updateMutateAsync.mockResolvedValue({});
    renderWithSources([
      {
        id: `rt-${type}`,
        type,
        product,
        enabled: true,
        config,
        sync_interval: "24h",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
      },
    ]);
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(mocks.updateMutateAsync).toHaveBeenCalled());
    expect(mocks.updateMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        type,
        config: expect.objectContaining(config),
      }),
    );
  });

  it("local_git 历史归一用例仍在(#1):编辑归一 github 且 repo_path 转换", () => {
    const localGitDs = {
      id: "ne301-docs-local",
      type: "local_git",
      product: "ne301",
      enabled: true,
      config: { repo_path: "~/ask-ai-corpus/ne301", branches: ["main"] },
      sync_interval: "24h",
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    renderWithSources([localGitDs]);
    fireEvent.click(screen.getByText("编辑"));
    expect(screen.getByDisplayValue("代码仓库")).toHaveValue("github");
    expect(
      screen.getByDisplayValue("https://github.com/camthink-ai/ne301.git"),
    ).toBeInTheDocument();
  });
});

// ====================  DSH-01/02:数据源健康语义(当前态 vs 历史可靠性)  ====================


const dshSource = (overrides: Record<string, unknown> = {}) => ({
  id: "website-camthink",
  type: "web_crawl",
  product: "website",
  enabled: true,
  config: { base_url: "https://www.camthink.ai" },
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
  last_sync: null,
  last_sync_status: null,
  last_sync_error: null,
  ...overrides,
});

const dshHealth = (overrides: Record<string, unknown> = {}) => ({
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
  ...overrides,
});

function renderWithHealth(sources: unknown[], items: unknown[] | undefined, syncHealthItems?: unknown[]) {
  vi.mocked(useDataSources).mockReturnValue({ data: sources as never, isLoading: false });
  vi.mocked(useSourceHealth).mockReturnValue({
    data: items ? { items: items as never, days: 30 } : undefined,
    isLoading: false,
  });
  vi.mocked(useSyncHealth).mockReturnValue({
    data: syncHealthItems ? { items: syncHealthItems as never } : undefined,
    isLoading: false,
  });
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <DataSources />
    </QueryClientProvider>,
  );
}

describe("DSH 数据源健康语义", () => {
  it("按源懒加载 exact sync-runs 契约，并展开历史与五维健康", () => {
    vi.mocked(useSyncRuns).mockImplementation((_sourceId, options) => ({
      data: options?.enabled ? {
        items: [{
          id: 8,
          source_id: "website-camthink",
          triggered_by: "manual",
          request_id: 42,
          attempt: 2,
          recovery: true,
          status: "completed",
          started_at: "2026-09-03T01:00:00Z",
          finished_at: "2026-09-03T01:02:03Z",
          duration_seconds: 123,
          stage: "DONE",
          counters: { docs_total: 12, chunks_deleted: 2 },
          consistency: { missing: 2, orphan_count: 3 },
          execution_device: "cpu",
          fallback_reason: "CUDA unavailable",
          fallback_detail: "CUDAOutOfMemoryError",
          error_summary: null,
          sync_log: {
            status: "success",
            items_new: 2,
            chunks_written: 42,
            items_deleted: 1,
            items_unchanged: 9,
            error_detail: null,
          },
        }],
        total: 1,
        page: 1,
        size: 20,
      } : undefined,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }));

    const syncHealthItem = {
      source_id: "website-camthink",
      source_type: "web_crawl",
      enabled: true,
      expected_state: "REQUIRED",
      overall: "HEALTHY",
      recovering: false,
      document_count: 12,
      connectivity: { state: "ok", evidence: "latest run #8 completed@DONE", as_of: null },
      sync: { state: "healthy", evidence: "24/25 syncs succeeded in 30d", as_of: null },
      coverage: { state: "ok", evidence: "extracted=50/50 accepted", as_of: null },
      freshness: { state: "fresh", evidence: "last success 3600s ago", as_of: null },
      consistency: { state: "ok", evidence: "missing=0, extra_orphan=0", as_of: null },
    };
    renderWithHealth(
      [dshSource({ last_sync: "2026-09-03T01:02:03Z", last_sync_status: "success" })],
      [dshHealth({ last_sync: "2026-09-03T01:02:03Z" })],
      [syncHealthItem],
    );

    expect(useSyncRuns).toHaveBeenCalledWith("website-camthink", { enabled: false });
    fireEvent.click(screen.getByRole("button", { name: "查看可观测性" }));

    expect(useSyncRuns).toHaveBeenCalledWith("website-camthink", { enabled: true });
    expect(screen.getByText("最近同步")).toBeInTheDocument();
    expect(screen.getByText("新增文档 2")).toBeInTheDocument();
    expect(screen.getByText("删除文档 1")).toBeInTheDocument();
    expect(screen.getByText("未变更文档 9")).toBeInTheDocument();
    expect(screen.getByText("分块 42")).toBeInTheDocument();
    expect(screen.getByText("已删除分块 2")).toBeInTheDocument();
    expect(screen.getByText("CPU")).toBeInTheDocument();
    expect(screen.getByText("降级原因：CUDA unavailable")).toBeInTheDocument();
    expect(screen.getByText("数据源健康")).toBeInTheDocument();
    for (const label of ["连接", "同步", "覆盖", "新鲜度", "一致性"]) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }
    expect(screen.getAllByText("缺失 2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("孤儿 3").length).toBeGreaterThan(0);
  });

  it("#11 Health Authority:五维面板由 /sync-health 驱动,前端不重判状态", () => {
    const syncHealthItem = {
      source_id: "website-camthink",
      source_type: "web_crawl",
      enabled: true,
      expected_state: "REQUIRED",
      overall: "STALE",
      recovering: false,
      document_count: 12,
      connectivity: { state: "ok", evidence: "latest run #8 completed@DONE", as_of: "2026-09-03T01:00:00Z" },
      sync: { state: "insufficient_data", evidence: "1/1 syncs in 30d (<3)", as_of: null },
      coverage: { state: "unknown", evidence: "no sync_runs evidence", as_of: null },
      freshness: { state: "stale", evidence: "no successful sync on record", as_of: null },
      consistency: { state: "ok", evidence: "missing=0, extra_orphan=0", as_of: null },
    };
    renderWithHealth(
      [dshSource({ last_sync: "2026-09-03T01:02:03Z", last_sync_status: "success" })],
      [dshHealth({ last_sync: "2026-09-03T01:02:03Z" })],
      [syncHealthItem],
    );

    fireEvent.click(screen.getByRole("button", { name: "查看可观测性" }));

    // overall 由后端给:STALE → 过期(前端只本地化)
    expect(screen.getByText("数据源健康")).toBeInTheDocument();
    expect(screen.getAllByText("过期").length).toBe(2); // overall + freshness
    // 后端词表逐维本地化,UNKNOWN 不被改判
    expect(screen.getByText("未知")).toBeInTheDocument();          // coverage unknown
    expect(screen.getByText("证据不足")).toBeInTheDocument();      // sync insufficient_data
    // evidence 原文直呈
    expect(screen.getByText("no successful sync on record")).toBeInTheDocument();
    expect(screen.getByText("no sync_runs evidence")).toBeInTheDocument();
    // 前端不再派生:旧的本地推导文案不得出现
    expect(screen.queryByText("阈值 2小时")).not.toBeInTheDocument();
    expect(screen.queryByText("文档 75，分块 1200")).not.toBeInTheDocument();
  });

  it("G001 健康:当前成功 + 历史 96%(窗口/分母可见)+ 内容数", () => {
    renderWithHealth(
      [dshSource({ last_sync: "2026-09-01T02:00:00Z", last_sync_status: "success" })],
      [dshHealth()],
    );
    // 健康列:正常 badge + 带窗口与分母的历史行
    expect(screen.getByText("正常")).toBeInTheDocument();
    expect(screen.getByText("96% 成功 · 近30天 25 次")).toBeInTheDocument();
    // 内容数可见
    expect(screen.getByText("75 篇")).toBeInTheDocument();
    // 最新同步列:成功 badge
    expect(screen.getByText("成功")).toBeInTheDocument();
  });

  it("G002 最新成功 + 历史差:两个事实同屏且措辞不冲突", () => {
    renderWithHealth(
      [dshSource({ last_sync_status: "success" })],
      [
        dshHealth({
          sync_success_rate: 0.5,
          success_syncs: 12,
          failed_syncs: 10,
          partial_syncs: 3,
          total_syncs: 25,
          health: "degraded",
        }),
      ],
    );
    expect(screen.getByText("成功")).toBeInTheDocument(); // 当前态
    expect(screen.getByText("不稳定")).toBeInTheDocument(); // 历史态
    expect(screen.getByText("50% 成功 · 近30天 25 次")).toBeInTheDocument();
  });

  it("G003 最新失败:失败 badge + 错误明细可见(可操作)", () => {
    renderWithHealth(
      [dshSource({ last_sync_status: "failed", last_sync_error: "sitemap 请求超时" })],
      [
        dshHealth({
          last_sync_status: "failed",
          last_sync_error: "sitemap 请求超时",
          health: "degraded",
        }),
      ],
    );
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("sitemap 请求超时")).toBeInTheDocument();
  });

  it("G004 样本不足:不伪造百分比与可靠性结论", () => {
    renderWithHealth(
      [dshSource()],
      [
        dshHealth({
          total_syncs: 2,
          success_syncs: 1,
          failed_syncs: 1,
          sync_success_rate: 0.5,
          health: "insufficient_data",
        }),
      ],
    );
    expect(screen.getByText("样本不足")).toBeInTheDocument();
    // 不出现裸百分比(分母过小不给成功率结论)
    expect(screen.queryByText(/成功 · 近30天/)).not.toBeInTheDocument();
    expect(screen.getByText(/仅 2 次同步/)).toBeInTheDocument();
  });

  it("G005 禁用:已禁用状态与不健康可区分", () => {
    renderWithHealth(
      [dshSource({ enabled: false })],
      [dshHealth({ enabled: false, health: "disabled" })],
    );
    // 健康列显示"已禁用"而非不稳定/严重
    expect(screen.getByText("已禁用")).toBeInTheDocument();
    expect(screen.queryByText("不稳定")).not.toBeInTheDocument();
  });

  it("健康数据缺失时优雅降级为 —,不阻塞表格", () => {
    renderWithHealth([dshSource()], undefined);
    expect(screen.getByText("数据源管理")).toBeInTheDocument();
  });

  it("悬停健康徽标可见分子/分母明细(含 partial)", () => {
    renderWithHealth(
      [dshSource()],
      [
        dshHealth({
          success_syncs: 12,
          partial_syncs: 3,
          failed_syncs: 10,
          sync_success_rate: 0.48,
          health: "critical",
        }),
      ],
    );
    const badge = screen.getByText("严重");
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("title")).toContain("12 次成功");
    expect(badge.getAttribute("title")).toContain("3 次补齐");
    expect(badge.getAttribute("title")).toContain("10 次失败");
  });
});
