import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SystemInfo from "@/pages/SystemInfo";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "admin@test.com" } }),
}));
vi.mock("@/hooks/useReleaseInfo", () => ({
  useReleaseInfo: () => ({ data: undefined, isLoading: false, isError: false }),
}));
vi.mock("@/hooks/useSystemRuntime", () => ({
  useSystemRuntime: () => ({ data: undefined, isLoading: false, isError: false }),
}));
vi.mock("@/hooks/useConversationIdPolicy", () => ({
  useConversationIdPolicy: vi.fn(() => ({
    data: {
      strategy: "uuid4",
      label: "随机 UUID(v4)",
      description: "使用随机 UUID 生成新对话 ID。",
      example: "00000000-0000-4000-8000-000000000000",
      affects_new_conversations_only: true,
      updated_at: null,
    },
    isLoading: false,
    isError: false,
  })),
  useConversationIdPolicySave: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));

afterEach(cleanup);

it("系统信息显示 Conversation ID 生成规则与新建对话边界", () => {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <SystemInfo />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Conversation ID 生成规则")).toBeInTheDocument();
  expect(screen.getAllByText("随机 UUID(v4)").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/仅影响新建对话/)).toBeInTheDocument();
  expect(screen.getByText(/00000000-0000-4000/)).toBeInTheDocument();
});
