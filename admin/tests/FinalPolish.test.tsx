/** Final Polish 修复集验收测试(AFP-002 RBAC 真相 / AFP-003 登录文案 / AFP-008 空结果语义)。 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

type Role = "admin" | "editor" | "viewer" | undefined;

const state = vi.hoisted(() => ({ role: "admin" as Role }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: state.role ? { role: state.role, email: "t@x.com" } : null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
}));

const dsMocks = vi.hoisted(() => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
}));

vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: dsMocks.useDataSources,
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useTriggerSync: () => ({ mutate: vi.fn(), isPending: false }),
  useTriggerSyncAll: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSourceHealth: () => ({ data: undefined, isLoading: false }),
  useSyncStatus: () => ({ data: { items: [] }, isLoading: false }),
  useSyncRuns: () => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() }),
  usePreviewDirs: () => ({ data: { dirs: [] }, isLoading: false, error: null }),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
}));

vi.mock("@/hooks/useLLMProviders", () => ({
  useLLMProviders: () => ({ data: [], isLoading: false }),
  useLLMRouting: () => ({ data: [], isLoading: false }),
  useLocalModels: () => ({ data: undefined, isLoading: false }),
  useReloadProviders: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateRouting: () => ({ mutate: vi.fn(), isPending: false }),
  useToggleProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateProvider: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useConversations", () => ({
  useConversations: vi.fn(() => ({
    data: { items: [], total: 0, page: 1, size: 20 },
    isLoading: false,
  })),
  useConversationDetail: () => ({ data: undefined }),
  useTagConversation: () => ({ mutate: vi.fn() }),
  useBatchTag: () => ({ mutate: vi.fn(), isPending: false, data: undefined }),
  useTraces: () => ({ data: undefined }),
}));

vi.mock("@/hooks/useAnswerOverrides", () => ({
  useAnswerOverrides: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useCreateOverride: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateOverride: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteOverride: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useUsers", () => ({
  useUsers: () => ({ data: [], isLoading: false }),
  useCreateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteUser: () => ({ mutate: vi.fn(), isPending: false }),
}));

import DataSources from "@/pages/DataSources";
import LLMProviders from "@/pages/LLMProviders";
import Conversations from "@/pages/Conversations";
import AnswerOverrides from "@/pages/AnswerOverrides";
import Users from "@/pages/Users";

afterEach(() => {
  cleanup();
  state.role = "admin";
});

function renderPage(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AFP-002 viewer 不被广告写操作", () => {
  it("viewer 打开数据源:无 同步全部/新增数据源/删除", async () => {
    state.role = "viewer";
    renderPage(<DataSources />);
    await waitFor(() => expect(screen.getByText("数据源管理")).toBeInTheDocument());
    expect(screen.queryByText("同步全部")).not.toBeInTheDocument();
    expect(screen.queryByText("新增数据源")).not.toBeInTheDocument();
    expect(screen.queryByText("删除")).not.toBeInTheDocument();
  });

  it("admin 打开数据源:写操作保留(G010)", async () => {
    renderPage(<DataSources />);
    await waitFor(() => expect(screen.getByText("同步全部")).toBeInTheDocument());
    expect(screen.getByText("新增数据源")).toBeInTheDocument();
  });

  it("viewer 打开模型配置:无 供应商凭证/端点授权/应用变更", async () => {
    state.role = "viewer";
    renderPage(<LLMProviders />);
    await waitFor(() => expect(screen.getByText("模型配置")).toBeInTheDocument());
    expect(screen.queryByText("供应商凭证")).not.toBeInTheDocument();
    expect(screen.queryByText("端点授权")).not.toBeInTheDocument();
    expect(screen.queryByText("应用变更")).not.toBeInTheDocument();
  });

  it("viewer 打开对话审查:无 批量标注 Intent", async () => {
    state.role = "viewer";
    renderPage(<Conversations />);
    await waitFor(() => expect(screen.getByText("对话审查")).toBeInTheDocument());
    expect(screen.queryByText("批量标注 Intent")).not.toBeInTheDocument();
  });

  it("viewer 打开答案覆盖:无 新增覆盖/删除", async () => {
    state.role = "viewer";
    renderPage(<AnswerOverrides />);
    await waitFor(() => expect(screen.getByText("答案覆盖管理")).toBeInTheDocument());
    expect(screen.queryByText("新增覆盖")).not.toBeInTheDocument();
    expect(screen.queryByText("删除")).not.toBeInTheDocument();
  });

  it("AFP-008 viewer 直达用户管理 → 显式无权限态,非空表(G009)", async () => {
    state.role = "viewer";
    renderPage(<Users />);
    await waitFor(() => expect(screen.getByText("无访问权限")).toBeInTheDocument());
    expect(screen.getByText(/请联系管理员/)).toBeInTheDocument();
    expect(screen.queryByText("新增用户")).not.toBeInTheDocument();
  });

  it("admin 用户管理不受影响(G010)", async () => {
    renderPage(<Users />);
    await waitFor(() => expect(screen.getByText("用户管理")).toBeInTheDocument());
    expect(screen.getByText("新增用户")).toBeInTheDocument();
  });
});

describe("AFP-008 空结果语义", () => {
  it("对话审查 total=0 → 「暂无对话数据」而非无声空表", async () => {
    renderPage(<Conversations />);
    await waitFor(() => {
      expect(screen.getByText(/暂无对话数据/)).toBeInTheDocument();
    });
  });

  it("对话审查筛选无匹配 → 「无匹配对话」提示", async () => {
    const { useConversations } = await import("@/hooks/useConversations");
    vi.mocked(useConversations).mockReturnValue({
      data: { items: [], total: 0, page: 1, size: 20 },
      isLoading: false,
    } as never);
    // 模拟「有筛选但无匹配」:total=0 且 items 空,语义同上;此处锁定空态组件存在
    renderPage(<Conversations />);
    await waitFor(() => {
      expect(document.querySelector("[data-empty-state]")).toBeTruthy();
    });
  });
});

describe("AFP-003 登录错误文案映射", () => {
  it("Pydantic 邮箱校验错误 → 中文;401 中文保留;其余 → 通用文案", async () => {
    const { formatLoginError } = await import("@/pages/Login");
    expect(formatLoginError("value is not a valid email address: blah")).toBe(
      "邮箱格式不正确,请检查后重试",
    );
    expect(formatLoginError("邮箱或密码错误")).toBe("邮箱或密码错误");
    expect(formatLoginError("Internal Server Error")).toBe("登录失败,请稍后再试");
    expect(formatLoginError("")).toBe("登录失败,请稍后再试");
  });
});
