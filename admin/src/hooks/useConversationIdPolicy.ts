import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

export interface ConversationIdPolicy {
  strategy: "uuid4" | "uuid7";
  label: string;
  description: string;
  example: string;
  affects_new_conversations_only: boolean;
  updated_at: string | null;
}

export function useConversationIdPolicy() {
  return useQuery({
    queryKey: ["conversation-id-policy"],
    queryFn: () => apiFetch<ConversationIdPolicy>("/system/conversation-id-policy"),
  });
}

export function useConversationIdPolicySave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (strategy: ConversationIdPolicy["strategy"]) =>
      apiFetch<ConversationIdPolicy>("/system/conversation-id-policy", {
        method: "PUT",
        body: JSON.stringify({ strategy }),
      }),
    onSuccess: (policy) => {
      qc.setQueryData(["conversation-id-policy"], policy);
      void qc.invalidateQueries({ queryKey: ["conversation-id-policy"] });
    },
  });
}
