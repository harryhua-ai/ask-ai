import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ReleaseInfo } from "@/types/api";

/**
 * #10:当前运行镜像的发布身份(后端权威直呈,前端零版本常量)。
 * 值与 /health 同源(镜像内 RELEASE.json,进程启动时加载,不可变)。
 */
export function useReleaseInfo() {
  return useQuery({
    queryKey: ["system-release"],
    queryFn: () => apiFetch<ReleaseInfo>("/system/release"),
    // 发布身份在进程生命周期内不可变:一次拉取即可(错误重试走 refetch)
    staleTime: Infinity,
  });
}
