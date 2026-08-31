import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { useReloadProviders, useFetchModels, useUpdateProvider } from "@/hooks/useLLMProviders";
import type { ReactNode } from "react";

const mockFetch = vi.fn();
vi.mock("@/lib/api", () => ({
  apiFetch: (path: string, opts?: RequestInit) => mockFetch(path, opts),
  ApiError: class extends Error {},
}));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => mockFetch.mockReset());

describe("useUpdateProvider", () => {
  it("PATCH /llm-providers/{id} 带 config", async () => {
    mockFetch.mockResolvedValueOnce({ id: "x", type: "t", enabled: true, config: {} });
    const { result } = renderHook(() => useUpdateProvider(), { wrapper });
    result.current.mutate({ id: "x", config: { model: "m" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith(
      "/llm-providers/x",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});

describe("useReloadProviders", () => {
  it("POST /llm-providers/reload", async () => {
    mockFetch.mockResolvedValueOnce({ status: "ok", providers_count: 1, routing: {}, skipped: [] });
    const { result } = renderHook(() => useReloadProviders(), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith(
      "/llm-providers/reload",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("useFetchModels", () => {
  it("POST /llm-providers/{id}/fetch-models(无表单值时不带 body)", async () => {
    mockFetch.mockResolvedValueOnce({ provider_id: "x", models: ["m1"], error: null });
    const { result } = renderHook(() => useFetchModels(), { wrapper });
    result.current.mutate({ id: "x" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith(
      "/llm-providers/x/fetch-models",
      expect.objectContaining({ method: "POST" }),
    );
    const opts = mockFetch.mock.calls[0][1] as RequestInit;
    expect(opts.body).toBeUndefined();
  });

  it("T27:表单 api_base/api_key 非空时随 body 传递", async () => {
    mockFetch.mockResolvedValueOnce({ provider_id: "x", models: [], error: null });
    const { result } = renderHook(() => useFetchModels(), { wrapper });
    result.current.mutate({ id: "x", apiBase: "https://new.example.com/v1", apiKey: "sk-form" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const opts = mockFetch.mock.calls[0][1] as RequestInit;
    expect(opts.body).toBe(JSON.stringify({ api_base: "https://new.example.com/v1", api_key: "sk-form" }));
  });
});
