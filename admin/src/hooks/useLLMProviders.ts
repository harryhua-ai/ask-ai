import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { LLMProvider, LLMRouting } from "@/types/api";

/** 连通性测试端点返回结构(与后端 ConnectivityTestResult 对齐)。 */
export interface ConnectivityTestResult {
  provider_id: string;
  success: boolean;
  latency_ms: number | null;
  error: string | null;
}

export function useLLMProviders() {
  return useQuery({
    queryKey: ["llm-providers"],
    queryFn: () => apiFetch<LLMProvider[]>("/llm-providers"),
  });
}

export function useLLMRouting() {
  return useQuery({
    queryKey: ["llm-routing"],
    queryFn: () => apiFetch<LLMRouting[]>("/llm-routing"),
  });
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; type: string; config: Record<string, unknown> }) =>
      apiFetch<LLMProvider>("/llm-providers", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-providers"] }),
  });
}

export function useToggleProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiFetch<LLMProvider>(`/llm-providers/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-providers"] }),
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<ConnectivityTestResult>(`/llm-providers/${id}/test`, { method: "POST" }),
  });
}

export function useUpdateRouting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ task, chain }: { task: string; chain: string[] }) =>
      apiFetch<{ status: string }>(`/llm-routing/${task}`, { method: "PUT", body: JSON.stringify({ chain }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-routing"] }),
  });
}
