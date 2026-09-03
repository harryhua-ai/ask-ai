import { describe, expect, it, vi, beforeEach } from "vitest";
import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { fetchSyncRuns, fetchSyncStatus, useSyncRuns, useSyncStatus } from "@/hooks/useDataSources";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const wrapper = ({ children }: { children: React.ReactNode }) =>
  React.createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );

describe("data source observability API hooks", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset());

  it("uses the frozen sync status path", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [] });
    await fetchSyncStatus();
    expect(apiFetch).toHaveBeenCalledWith("/sync-status");
  });

  it("URL-encodes source and optional run filters", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [], total: 0, page: 2, size: 25 });
    await fetchSyncRuns("产品/来源", { status: "FAILED", page: 2, size: 25 });
    expect(apiFetch).toHaveBeenCalledWith("/sync-runs?source_id=%E4%BA%A7%E5%93%81%2F%E6%9D%A5%E6%BA%90&status=FAILED&page=2&size=25");
  });

  it("scopes query keys by source and only polls when configured", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [], total: 0, page: 1, size: 20 });
    const status = renderHook(() => useSyncStatus({ refetchInterval: 5000 }), { wrapper });
    const runs = renderHook(() => useSyncRuns("source-a", { enabled: true }), { wrapper });
    await waitFor(() => expect(status.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(runs.result.current.isSuccess).toBe(true));
    expect(status.result.current.data?.items).toEqual([]);
    expect(runs.result.current.data).toEqual({ items: [], total: 0, page: 1, size: 20 });
  });
});
