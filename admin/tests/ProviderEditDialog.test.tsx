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
