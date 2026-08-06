import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { useTriggerSync } from "@/hooks/useDataSources";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

function createWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useTriggerSync", () => {
  beforeEach(() => vi.clearAllMocks());

  it("#44 成功触发同步:toast.success 反馈 + invalidate data-sources 列表", async () => {
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    vi.mocked(apiFetch).mockResolvedValueOnce({ status: "syncing", source_id: "ne301" });

    const { result } = renderHook(() => useTriggerSync(), { wrapper: createWrapper(qc) });
    result.current.mutate("ne301");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("ne301"));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["data-sources"] });
  });

  it("#44 同步请求失败:toast.error 反馈", async () => {
    const qc = new QueryClient();
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error("数据源已禁用"));

    const { result } = renderHook(() => useTriggerSync(), { wrapper: createWrapper(qc) });
    result.current.mutate("ne301");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalled();
  });
});
