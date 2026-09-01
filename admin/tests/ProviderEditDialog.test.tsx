import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProviderEditDialog } from "@/components/ProviderEditDialog";
import type { ReactNode } from "react";

afterEach(cleanup);

const mockFetch = vi.fn();
vi.mock("@/lib/api", () => ({
  apiFetch: (p: string, o?: RequestInit) => mockFetch(p, o),
  ApiError: class extends Error {},
}));

function renderDialog(props: Partial<Parameters<typeof ProviderEditDialog>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProviderEditDialog
        provider={{
          id: "deepseek",
          type: "openai_compatible",
          enabled: true,
          config: {
            api_base: "https://api.deepseek.com/v1",
            api_key: "********",
            model: "v4-pro",
            available_models: ["v4-pro", "v4-flash"],
          },
        }}
        onSave={() => {}}
        onClose={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe("ProviderEditDialog", () => {
  it("api_key 不回显真实值，留空保存时不覆盖已有密钥", () => {
    const onSave = vi.fn();
    renderDialog({ onSave });
    expect(screen.queryByDisplayValue("********")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("留空则不修改")).toBeInTheDocument();
    fireEvent.click(screen.getByText("保存"));
    const saved = onSave.mock.calls[0][0];
    expect(saved.config).not.toHaveProperty("api_key");
  });

  it("填入新 api_key 才提交新值", () => {
    const onSave = vi.fn();
    renderDialog({ onSave });
    const keyInput = screen.getByPlaceholderText("留空则不修改");
    fireEvent.change(keyInput, { target: { value: "sk-newkey" } });
    fireEvent.click(screen.getByText("保存"));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ api_key: "sk-newkey" }),
      }),
    );
  });

  it("available_models 可添加新模型", () => {
    renderDialog();
    fireEvent.click(screen.getByText(/手动添加/));
    const input = screen.getByPlaceholderText(/模型名/);
    fireEvent.change(input, { target: { value: "new-model" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("new-model")).toBeInTheDocument();
  });

  it("从 API 拉取调 fetch-models 端点", async () => {
    mockFetch.mockResolvedValueOnce({
      provider_id: "deepseek",
      models: ["v4-pro", "v4-flash", "v4-reasoner"],
      error: null,
    });
    renderDialog();
    fireEvent.click(screen.getByText(/从 API 拉取/));
    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/llm-providers/deepseek/fetch-models",
        expect.any(Object),
      ),
    );
  });
});

// ====================  T27:换供应商三缺陷修复  ====================


describe("ProviderEditDialog T27", () => {
  it("从 API 拉取携带表单当前 api_base/api_key(未保存也生效)", async () => {
    mockFetch.mockResolvedValueOnce({ provider_id: "deepseek", models: ["m1"], error: null });
    renderDialog();
    const baseInput = screen.getByLabelText("API Base");
    fireEvent.change(baseInput, { target: { value: "https://new.example.com/v1" } });
    const keyInput = screen.getByPlaceholderText("留空则不修改");
    fireEvent.change(keyInput, { target: { value: "sk-formkey" } });
    fireEvent.click(screen.getByText(/从 API 拉取/));
    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/llm-providers/deepseek/fetch-models",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ api_base: "https://new.example.com/v1", api_key: "sk-formkey" }),
        }),
      ),
    );
  });

  it("拉取失败显示可读错误文本", async () => {
    mockFetch.mockResolvedValueOnce({
      provider_id: "deepseek",
      models: [],
      error: "api_base 校验失败",
    });
    renderDialog();
    fireEvent.click(screen.getByText(/从 API 拉取/));
    await waitFor(() => expect(screen.getByText("api_base 校验失败")).toBeInTheDocument());
  });

  it("api_base 下有端点授权工作流指引(P1:不再提 .env/LLM_ALLOWED_HOSTS)", () => {
    renderDialog();
    expect(screen.getByText(/端点授权/)).toBeInTheDocument();
    expect(screen.queryByText(/LLM_ALLOWED_HOSTS/)).toBeNull();
  });

  it("设为默认:置顶且保存 payload.model = 所设默认项", () => {
    const onSave = vi.fn();
    renderDialog({ onSave });
    // 初始 ["v4-pro","v4-flash"],把 v4-flash 设为默认
    fireEvent.click(screen.getByText("设为默认"));
    fireEvent.click(screen.getByText("保存"));
    const saved = onSave.mock.calls[0][0];
    expect(saved.config.model).toBe("v4-flash");
    expect(saved.config.available_models).toEqual(["v4-flash", "v4-pro"]);
    // v4-flash 行现在显示「默认」徽标,不再有设为默认按钮
    expect(screen.getAllByText("默认").length).toBe(1);
  });
});

describe("ProviderEditDialog · P1 端点授权指引", () => {
  it("不暴露 .env / LLM_ALLOWED_HOSTS 实现层指引,改为指明「端点授权」产品工作流", () => {
    renderDialog();
    // Radix Dialog 渲染在 portal(document.body)下,查 body 而非 container
    const text = document.body.textContent ?? "";
    expect(text).not.toContain(".env");
    expect(text).not.toContain("LLM_ALLOWED_HOSTS");
    expect(text).toContain("端点授权");
  });
});
