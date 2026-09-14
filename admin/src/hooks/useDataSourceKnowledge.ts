/**
 * v1.6.3 Track C(U-8/U-11/U-12/U-13)— 行级修复/调度真值/知识设置/预览 hooks。
 *
 * 与既有 useDataSourceWorkspace.ts 分文件(零改动既有 hooks,降低集成冲突面)。
 * 全部真值来自后端权威端点:计数/倒计时/预览影响/修复结果一律不在前端计算。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { DocumentRepairTask } from "@/types/dataSourceWorkspace";

/** U-11 调度真值(后端权威 next_run_at + 状态词表)。 */
export interface SourceScheduleTruth {
  source_id: string;
  next_run_at: string | null;
  state: "scheduled" | "syncing" | "paused" | "waiting_first" | "deleting";
  sync_interval: string;
  enabled: boolean;
}

/** U-12 知识设置读面(生效值 + 新鲜度真值)。 */
export interface KnowledgeSettings {
  source_id: string;
  role: "current" | "historical";
  explicit_role: string | null;
  freshness_hours: number;
  explicit_freshness_hours: number | null;
  freshness: {
    freshness_hours: number;
    last_success_at: string | null;
    overdue: boolean;
    overdue_hours_ago?: number;
    basis: string;
  };
  updated_at: string | null;
}

/** U-13 预览响应(影响计数 = 服务端权威)。 */
export interface KnowledgePreview {
  preview_token: string;
  source_id: string;
  current_policy: { role: string; freshness_hours: number };
  pending_policy: { role: string; freshness_hours?: number };
  impact: {
    affected_documents: number;
    current_eligibility_change: number;
    historical_eligibility_change: number;
  };
  expires_at: string | null;
}

export function useSourceSchedule(sourceId: string) {
  return useQuery({
    queryKey: ["data-source-schedule", sourceId],
    queryFn: () =>
      apiFetch<SourceScheduleTruth>(
        `/data-sources/${encodeURIComponent(sourceId)}/schedule`,
      ),
    enabled: !!sourceId,
  });
}

export function useKnowledgeSettings(sourceId: string, enabled = true) {
  return useQuery({
    queryKey: ["knowledge-settings", sourceId],
    queryFn: () =>
      apiFetch<KnowledgeSettings>(
        `/data-sources/${encodeURIComponent(sourceId)}/knowledge-settings`,
      ),
    enabled: !!sourceId && enabled,
  });
}

export function useKnowledgePreview(sourceId: string) {
  return useMutation({
    mutationFn: (req: { role: string; freshness_hours?: number | null }) =>
      apiFetch<KnowledgePreview>(
        `/data-sources/${encodeURIComponent(sourceId)}/knowledge-settings/preview`,
        { method: "POST", body: JSON.stringify(req) },
      ),
  });
}

export function useKnowledgeSettingsSave(sourceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: {
      role: string;
      freshness_hours?: number | null;
      preview_token?: string | null;
    }) =>
      apiFetch<KnowledgeSettings>(
        `/data-sources/${encodeURIComponent(sourceId)}/knowledge-settings`,
        { method: "PUT", body: JSON.stringify(req) },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["knowledge-settings", sourceId] });
      void qc.invalidateQueries({ queryKey: ["data-sources"] });
      void qc.invalidateQueries({ queryKey: ["data-source-schedule", sourceId] });
    },
  });
}

/** U-8 行级修复命令(POST;后端同步执行 plan→repair→verify 并返回任务真值)。 */
export function useDocumentRepair(sourceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: { doc_source_id: string; idempotency_key?: string }) =>
      apiFetch<DocumentRepairTask>(
        `/data-sources/${encodeURIComponent(sourceId)}/documents/repair`,
        { method: "POST", body: JSON.stringify(req) },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["data-source-documents", sourceId] });
      // 与 useDataSourceWorkspace.useSourceDocumentTruth 的 queryKey 对齐:
      // 修复后展开行真相(serving/chunk 投影/验证卡)自动重取
      void qc.invalidateQueries({ queryKey: ["data-source-document-truth"] });
    },
  });
}
