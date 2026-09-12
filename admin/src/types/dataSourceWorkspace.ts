/**
 * #50 B1 Data Source Workspace V2 — 只读内容/生成真相读模型类型。
 *
 * 权威 = 后端账本(documents / document_versions / document_version_chunks /
 * index_generations);后端无记录的成分一律 null(前端呈现「后端无此记录」,
 * 绝不编造 content-role / discovered / last-seen 等不存在的字段)。
 */

/** 逐源文档清单行(复合身份 <source_id>/<branch>/<rel_path> 即 canonical path)。 */
export interface SourceDocumentItem {
  /** 复合文档身份(canonical path;含斜杠)。 */
  source_id: string;
  title: string;
  /** canonical URL(账本 url 列)。 */
  url: string;
  branch: string;
  source_type: string;
  product: string;
  /** L 轴生命周期(词表:discovered/active/superseded/missing_candidate/deleted)。 */
  lifecycle: string;
  /** 在服判定 = lifecycle ∈ SERVING 且现行版本可解析(权威关系,后端计算)。 */
  serving: boolean;
  chunk_count: number;
  /** 权威时间戳(后端不存在 discovered/last-seen,禁止虚构)。 */
  created_at: string | null;
  updated_at: string | null;
  /** 现行版本号(null = 后端无此记录)。 */
  current_version_seq: number | null;
  /** 现行版本所属生成序数(null = 后端无此记录)。 */
  generation_ordinal: number | null;
}

/** 逐源文档清单响应(total 为过滤后分页总数;聚合计数不受过滤影响)。 */
export interface SourceDocumentsResponse {
  source_id: string;
  total: number;
  /** 账本总数(不受过滤影响;LIKE 前缀口径,与 /sync-health document_count 同源)。 */
  ledger_total: number;
  page: number;
  size: number;
  /** 全源逐 L 轴账本计数(不受过滤影响)。 */
  lifecycle_counts: Record<string, number>;
  /** 在服集合计数(SERVING ∧ 现行版本可解析;active_generation 权威口径)。 */
  serving_count: number;
  /** Current 桶计数(active ∧ 现行版本可解析;严格在服且无风险标记)。 */
  current_count: number;
  items: SourceDocumentItem[];
}

/** 现行版本真相(归属版本链与生成)。 */
export interface DocumentCurrentVersionTruth {
  id: string;
  version_seq: number;
  /** 版本状态(active/superseded)。 */
  status: string;
  title: string;
  url: string;
  chunk_count: number;
  /** document_version_chunks 持久账本计数。 */
  chunks_total: number;
  /** 源原生版本元数据(git sha/lastmod 等;渐进填充,可 null)。 */
  source_version: Record<string, unknown> | null;
  valid_from: string | null;
  valid_to: string | null;
  superseded_by_version_id: string | null;
  generation_id: string;
  generation_ordinal: number;
}

/** 索引生成行真相(P 轴;失败证据 failure JSONB 原样)。 */
export interface GenerationTruth {
  id: string;
  ordinal: number;
  status: string;
  doc_count: number;
  chunk_count: number;
  failure: Record<string, unknown> | null;
  created_at: string | null;
  ready_at: string | null;
  activated_at: string | null;
  withdrawn_at: string | null;
  retired_at: string | null;
  gc_eligible_at: string | null;
  purged_at: string | null;
}

/** 单文档真相(状态 + 权威原因字段 + 版本/生成归属 + canonical 身份)。 */
export interface SourceDocumentTruth {
  /** 数据源配置 id(路径前缀)。 */
  source_id: string;
  /** 复合文档身份(canonical path)。 */
  doc_source_id: string;
  title: string;
  url: string;
  branch: string;
  source_type: string;
  product: string;
  lifecycle: string;
  serving: boolean;
  chunk_count: number;
  created_at: string | null;
  updated_at: string | null;
  superseded_by: string | null;
  superseded_at: string | null;
  deleted_at: string | null;
  /** 现行版本(null = 后端无此记录,显式缺席)。 */
  current_version: DocumentCurrentVersionTruth | null;
  /** 现行版本所属生成行(null = 后端无此记录,显式缺席)。 */
  generation: GenerationTruth | null;
}

/** 逐源索引生成列表响应。 */
export interface SourceGenerationsResponse {
  source_id: string;
  total: number;
  /** 权威在服代序集合(active_generation 口径的源内投影)。 */
  serving_ordinals: number[];
  items: GenerationTruth[];
}
