import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Customization } from "@/types/api";

/**
 * 渠道绑定 —— 与后端 BindingOut 对齐。
 * channel ∈ {widget, discord, whatsapp, mcp}。
 */
export interface Binding {
  channel: string;
  customization_id: string;
}

export function useCustomizations() {
  return useQuery({
    queryKey: ["customizations"],
    queryFn: () => apiFetch<Customization[]>("/customizations"),
  });
}

export function useBindings() {
  return useQuery({
    queryKey: ["bindings"],
    queryFn: () => apiFetch<Binding[]>("/customization-bindings"),
  });
}

export function useCreateCustomization() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      id: string;
      name: string;
      system_prompt: string;
      style_tone?: string;
      guardrails?: string;
    }) =>
      apiFetch<Customization>("/customizations", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customizations"] }),
  });
}

export function useUpdateCustomization() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Customization>) =>
      apiFetch<Customization>(`/customizations/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customizations"] }),
  });
}

export function useUpdateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channel,
      customization_id,
    }: {
      channel: string;
      customization_id: string;
    }) =>
      apiFetch<{ status: string }>(
        `/customization-bindings/${channel}`,
        { method: "PUT", body: JSON.stringify({ customization_id }) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bindings"] }),
  });
}
