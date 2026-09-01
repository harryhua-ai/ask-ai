import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LLMProviders from "@/pages/LLMProviders";
import { ApiError } from "@/lib/api";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { toast } from "sonner";

const provider = {
  id: "deepseek",
  type: "openai_compatible",
  enabled: true,
  config: {
    api_base: "https://api.deepseek.com/v1",
    api_key: "********",
    model: "deepseek-chat",
    available_models: ["deepseek-chat", "deepseek-reasoner"],
  },
};

const mockFetch = vi.fn();
vi.mock("@/lib/api", () => ({
  apiFetch: (path: string, opts?: RequestInit) => mockFetch(path, opts),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LLMProviders />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string) => {
    if (path === "/llm-providers") return Promise.resolve([provider]);
    if (path === "/llm-routing") return Promise.resolve([]);
    if (path === "/local-models") return Promise.resolve([]);
    return Promise.resolve({});
  });
});

afterEach(cleanup);

describe("LLMProviders T27 保存链路", () => {
  it("保存失败(422):红色 toast 显示可读原因,弹窗不关、表单态保留", async () => {
    renderPage();
    fireEvent.click(screen.getByText("供应商凭证"));
    fireEvent.click(await screen.findByText("编辑"));
    // 编辑弹窗打开
    expect(screen.getByText("编辑供应商 · deepseek")).toBeInTheDocument();
    // 改个 api_base,验证失败后表单态保留
    const baseInput = screen.getByLabelText("API Base");
    fireEvent.change(baseInput, {
      target: { value: "https://evil.example.net/v1" },
    });
    // apiFetch(PATCH)按真实 api.ts 同样语义抛出已扁平化的 ApiError
    mockFetch.mockImplementationOnce(() => {
      throw new ApiError(
        422,
        "Value error, api_base 主机 evil.example.net 不在 allowlist（通过 LLM_ALLOWED_HOSTS 配置）",
      );
    });
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("保存失败"),
      ),
    );
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("allowlist"),
    );
    // 弹窗保持打开
    expect(screen.getByText("编辑供应商 · deepseek")).toBeInTheDocument();
    // 表单态保留(输入值未被重置)
    expect((screen.getByLabelText("API Base") as HTMLInputElement).value).toBe(
      "https://evil.example.net/v1",
    );
  });

  it("保存成功:弹窗关闭且提示保存成功", async () => {
    renderPage();
    fireEvent.click(screen.getByText("供应商凭证"));
    fireEvent.click(await screen.findByText("编辑"));
    expect(screen.getByText("编辑供应商 · deepseek")).toBeInTheDocument();
    mockFetch.mockImplementationOnce(() =>
      Promise.resolve({ id: "deepseek", type: "openai_compatible", enabled: true, config: {} }),
    );
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringContaining("供应商已保存"),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByText("编辑供应商 · deepseek")).not.toBeInTheDocument(),
    );
  });
});
