// 全局 QueryClient 工厂(AFP-CLOSURE-01:mutation 失败可见反馈的统一架构)。
//
// 设计(任务书 §12:按真实仓库选择最小一致实现,避免重复 toast):
// - MutationCache.onError 统一兜底:任何**没有自带 onError** 的 mutation 失败
//   → toast 可见反馈;自带 onError 的(如 useTriggerSync 的定制文案、
//   SalesLeads handoff、LLMProviders reload)由其自身处理,全局跳过防重复;
// - 401 不 toast:apiFetch 已有跳登录流程(既有行为,即反馈),弹 toast 是噪音;
// - 403 呈现权限语义(apiFetch 已映射为「无权限执行此操作」)。
// 查询(queries)不在此兜底:读取失败由各页的 LoadError 显式态呈现
// (避免后台 refetchInterval 轮询失败产生噪音 toast)。

import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "./api";

export function formatMutationError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "无权限执行此操作";
    if (error.message) return `操作失败:${error.message}`;
  }
  if (error instanceof Error && error.message) return `操作失败:${error.message}`;
  return "操作失败,请稍后再试";
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        // mutation 自带 onError → 由其定制处理(跳过防重复 toast)
        if (mutation.options.onError) return;
        // 401:apiFetch 已清 token 并跳登录页,跳转本身就是反馈
        if (error instanceof ApiError && error.status === 401) return;
        toast.error(formatMutationError(error));
      },
    }),
  });
}
