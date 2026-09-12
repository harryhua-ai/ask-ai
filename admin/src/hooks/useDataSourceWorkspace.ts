/**
 * #50 B1 Data Source Workspace V2 — 详情工作面查询 hooks。
 *
 * 全部只读 GET(apiFetch 走 /api/admin 前缀 + Bearer;401/403 语义同全局);
 * 与既有 useDataSources.ts 分文件,零改动既有 hooks(降低集成冲突面)。
 */

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type {
  SourceDocumentTruth,
  SourceDocumentsResponse,
  SourceGenerationsResponse,
} from "@/types/dataSourceWorkspace";

export interface SourceDocumentsParams {
  /** L 轴生命周期过滤(词表见 backend document_lifecycle.DocLifecycle)。 */
  lifecycle?: string;
  /** v1.6.3 B1:运营桶投影(current/attention/retired;后端权威公式)。 */
  bucket?: string;
  /** v1.6.3 B1:排序(-updated_at 默认 | title)。 */
  order?: string;
  /** v1.6.3 B1:documents.source_type 精确匹配。 */
  sourceType?: string;
  /** title/url 子串搜索(不区分大小写)。 */
  search?: string;
  page?: number;
  size?: number;
}

export function fetchSourceDocuments(
  sourceId: string,
  params: SourceDocumentsParams = {},
): Promise<SourceDocumentsResponse> {
  const q = new URLSearchParams();
  if (params.lifecycle) q.set("lifecycle", params.lifecycle);
  if (params.bucket) q.set("bucket", params.bucket);
  if (params.order) q.set("order", params.order);
  if (params.sourceType) q.set("source_type", params.sourceType);
  if (params.search) q.set("search", params.search);
  q.set("page", String(params.page ?? 1));
  q.set("size", String(params.size ?? 20));
  return apiFetch<SourceDocumentsResponse>(
    `/data-sources/${encodeURIComponent(sourceId)}/documents?${q.toString()}`,
  );
}

export function useSourceDocuments(sourceId: string, params: SourceDocumentsParams = {}) {
  const { lifecycle, bucket, order, sourceType, search, page = 1, size = 20 } = params;
  return useQuery({
    queryKey: [
      "data-source-documents",
      sourceId,
      { lifecycle, bucket, order, sourceType, search, page, size },
    ],
    queryFn: () =>
      fetchSourceDocuments(sourceId, { lifecycle, bucket, order, sourceType, search, page, size }),
    enabled: !!sourceId,
  });
}

/**
 * 单文档真相。复合文档身份(含斜杠)经 query 参数传递,规避 path 段斜杠
 * 编码歧义(与后端契约一致)。
 */
export function fetchSourceDocumentTruth(
  sourceId: string,
  docSourceId: string,
): Promise<SourceDocumentTruth> {
  return apiFetch<SourceDocumentTruth>(
    `/data-sources/${encodeURIComponent(sourceId)}/documents/detail?doc_source_id=${encodeURIComponent(docSourceId)}`,
  );
}

export function useSourceDocumentTruth(sourceId: string, docSourceId: string | null) {
  return useQuery({
    queryKey: ["data-source-document-truth", sourceId, docSourceId],
    queryFn: () => fetchSourceDocumentTruth(sourceId, docSourceId as string),
    enabled: !!sourceId && !!docSourceId,
  });
}

export function fetchSourceGenerations(sourceId: string): Promise<SourceGenerationsResponse> {
  return apiFetch<SourceGenerationsResponse>(
    `/data-sources/${encodeURIComponent(sourceId)}/generations`,
  );
}

export function useSourceGenerations(sourceId: string) {
  return useQuery({
    queryKey: ["data-source-generations", sourceId],
    queryFn: () => fetchSourceGenerations(sourceId),
    enabled: !!sourceId,
  });
}
