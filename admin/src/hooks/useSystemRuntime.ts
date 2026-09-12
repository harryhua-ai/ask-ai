import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { SystemRuntimeInfo } from "@/types/api";

/**
 * #7:系统运行时只读快照(GET /api/admin/system/runtime)。
 * v1 采样语义 = 按需采集 + 手动刷新(轻量无实时要求;不自动轮询)。
 * 每项 available/value/reason/as_of;不可得项由后端显式标注,前端如实直呈。
 */
export function useSystemRuntime() {
  return useQuery({
    queryKey: ["system-runtime"],
    queryFn: () => apiFetch<SystemRuntimeInfo>("/system/runtime"),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
}
