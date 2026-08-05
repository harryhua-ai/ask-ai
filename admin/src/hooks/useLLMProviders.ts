import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { LLMChainItem, LLMProvider, LLMRouting } from "@/types/api";

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
    mutationFn: ({ task, chain }: { task: string; chain: LLMChainItem[] }) =>
      apiFetch<{ status: string }>(`/llm-routing/${task}`, { method: "PUT", body: JSON.stringify({ chain }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-routing"] }),
  });
}

export interface LocalModel {
  role: string;
  model_name: string;
  device: string;
  dimension?: number;
}

export function useLocalModels() {
  return useQuery({
    queryKey: ["local-models"],
    queryFn: () => apiFetch<LocalModel[]>("/local-models"),
  });
}

export function useUpdateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      type?: string;
      enabled?: boolean;
      config?: Record<string, unknown>;
    }) =>
      apiFetch<LLMProvider>(`/llm-providers/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-providers"] }),
  });
}

export interface ReloadResult {
  status: string;
  providers_count: number;
  routing: Record<string, unknown>;
  skipped: string[];
}

export function useReloadProviders() {
  return useMutation({
    mutationFn: () =>
      apiFetch<ReloadResult>("/llm-providers/reload", { method: "POST" }),
  });
}

export interface FetchModelsResult {
  provider_id: string;
  models: string[];
  error: string | null;
}

export function useFetchModels() {
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<FetchModelsResult>(`/llm-providers/${id}/fetch-models`, {
        method: "POST",
      }),
  });
}
