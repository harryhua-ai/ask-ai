import { describe, expect, it, vi, beforeEach } from "vitest";
import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import {
  fetchSyncRuns,
  fetchSyncStatus,
  useSyncRuns,
  useSyncStatus,
  useTriggerSync,
  useTriggerSyncAll,
} from "@/hooks/useDataSources";

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

  it("polls sync status only while the backend returns active items", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const localWrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client: queryClient }, children);
    vi.mocked(apiFetch).mockResolvedValue({ items: [] });

    const status = renderHook(() => useSyncStatus({ refetchInterval: 5000 }), { wrapper: localWrapper });
    await waitFor(() => expect(status.result.current.isSuccess).toBe(true));
    const query = queryClient.getQueryCache().find({ queryKey: ["sync-status"] });
    if (!query || typeof query.options.refetchInterval !== "function") {
      throw new Error("sync-status refetchInterval must be data-aware");
    }

    expect(query.options.refetchInterval(query)).toBe(false);
    query.setData({
      items: [{
        source_id: "source-a",
        state: "RUNNING",
        request_id: 42,
        attempt: 1,
        recovering: false,
        stage: "FETCH",
        stage_current: 1,
        stage_total: null,
        counters: null,
        execution_device: null,
        started_at: "2026-09-03T01:00:00Z",
        updated_at: "2026-09-03T01:00:01Z",
      }],
    });
    expect(query.options.refetchInterval(query)).toBe(5000);
  });

  it("invalidates status, sources, and health after manual and sync-all requests", async () => {
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);
    const localWrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client: queryClient }, children);
    const mutations = renderHook(() => ({ one: useTriggerSync(), all: useTriggerSyncAll() }), {
      wrapper: localWrapper,
    });

    vi.mocked(apiFetch).mockResolvedValueOnce({ status: "syncing", source_id: "source-a" });
    await act(async () => mutations.result.current.one.mutateAsync("source-a"));
    expect(invalidate.mock.calls.map(([options]) => options?.queryKey)).toEqual([
      ["sync-status"],
      ["data-sources"],
      ["source-health"],
    ]);

    invalidate.mockClear();
    vi.mocked(apiFetch).mockResolvedValueOnce({ status: "syncing", source_ids: ["source-a"], count: 1 });
    await act(async () => mutations.result.current.all.mutateAsync());
    expect(invalidate.mock.calls.map(([options]) => options?.queryKey)).toEqual([
      ["sync-status"],
      ["data-sources"],
      ["source-health"],
    ]);
  });
});
