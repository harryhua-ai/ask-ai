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
  it("POST /llm-providers/{id}/fetch-models", async () => {
    mockFetch.mockResolvedValueOnce({ provider_id: "x", models: ["m1"], error: null });
    const { result } = renderHook(() => useFetchModels(), { wrapper });
    result.current.mutate("x");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith(
      "/llm-providers/x/fetch-models",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
