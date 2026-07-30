import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { AnswerOverride, AnswerOverrideList } from "@/types/api";

export function useAnswerOverrides() {
  return useQuery({
    queryKey: ["answer-overrides"],
    queryFn: () => apiFetch<AnswerOverrideList>("/answer-overrides"),
  });
}

export function useCreateOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      match_pattern: string;
      match_type: string;
      override_answer: string;
      override_sources?: unknown[];
    }) =>
      apiFetch<AnswerOverride>("/answer-overrides", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}

export function useUpdateOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<AnswerOverride>) =>
      apiFetch<AnswerOverride>(`/answer-overrides/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}

export function useDeleteOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/answer-overrides/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}
