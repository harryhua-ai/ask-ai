import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EndpointAuthDialog } from "@/components/EndpointAuthDialog";

afterEach(cleanup);

const mockFetch = vi.fn();
vi.mock("@/lib/api", () => ({
  apiFetch: (p: string, o?: RequestInit) => mockFetch(p, o),
  ApiError: class extends Error {},
}));

let mockRole: "admin" | "editor" | "viewer" = "admin";
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: "u1", email: "a@b.c", name: "A", role: mockRole, is_active: true } }),
}));

const HOSTS = [
  {
    host: "api.together.xyz",
    allow_private: false,
    note: "第三方公网供应商",
    created_by: "admin@camthink.ai",
    created_at: "2026-09-01T00:00:00+00:00",
  },
  {
    host: "10.201.3.7",
    allow_private: true,
    note: null,
    created_by: "admin@camthink.ai",
    created_at: "2026-09-01T00:00:00+00:00",
  },
];

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EndpointAuthDialog onClose={() => {}} />
    </QueryClientProvider>,
  );
}

describe("EndpointAuthDialog", () => {
  it("列出已授权主机并区分公网/内网信任级别", async () => {
    mockFetch.mockResolvedValue(HOSTS);
    renderDialog();
    await waitFor(() => expect(screen.getByText("api.together.xyz")).toBeTruthy());
    expect(screen.getByText("10.201.3.7")).toBeTruthy();
    expect(screen.getByText("内网")).toBeTruthy();
    expect(screen.getByText("公网")).toBeTruthy();
  });

  it("admin 可添加授权:提交 host 调 POST /llm-allowed-hosts", async () => {
    mockFetch.mockResolvedValue([]);
    renderDialog();
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const input = screen.getByPlaceholderText("如 api.together.xyz 或 10.0.0.5");
    fireEvent.change(input, { target: { value: "https://Api.Together.XYZ/v1" } });
    fireEvent.click(screen.getByText("授权"));
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const [, opts] = mockFetch.mock.calls.find(
      (c: unknown[]) => String(c[0]).includes("/llm-allowed-hosts") && c[1]?.method === "POST",
    )!;
    // 前端发原始输入,归一化由服务端负责(POST /llm-allowed-hosts 响应已含归一化 host)
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({
      host: "https://Api.Together.XYZ/v1",
      note: "",
    });
  });

  it("admin 可撤销授权:点击撤销调 DELETE", async () => {
    mockFetch.mockResolvedValue(HOSTS);
    renderDialog();
    await waitFor(() => expect(screen.getByText("api.together.xyz")).toBeTruthy());
    const buttons = screen.getAllByTitle("撤销授权");
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const [path, opts] = mockFetch.mock.calls.find(
      (c: unknown[]) => String(c[0]).includes("/llm-allowed-hosts/") && c[1]?.method === "DELETE",
    )!;
    expect(String(path)).toContain("/llm-allowed-hosts/api.together.xyz");
    expect((opts as RequestInit).method).toBe("DELETE");
  });

  it("非 admin 只读:无添加/撤销控件,显示需管理员提示", async () => {
    mockRole = "editor";
    mockFetch.mockResolvedValue(HOSTS);
    renderDialog();
    await waitFor(() => expect(screen.getByText("api.together.xyz")).toBeTruthy());
    expect(screen.queryByText("授权")).toBeNull();
    expect(screen.queryAllByTitle("撤销授权").length).toBe(0);
    expect(screen.getByText(/需管理员/)).toBeTruthy();
    mockRole = "admin";
  });
});
