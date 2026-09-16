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
  /** U-7 逐文档内容类型(结构化后端真值;null = 存量行不可用,禁推断)。 */
  content_type: string | null;
}

/** U-9 chunk 级 serving 投影真值(UI 比例必须等于 serving/total)。 */
export interface ChunkServingTruth {
  serving_chunks: number;
  total_chunks: number;
  missing_indices: number[];
  stale_indices: number[];
  consistent: boolean;
}

/** U-8 修复任务(进度/结果/审计;验证卡数据源 = result 真值)。 */
export interface DocumentRepairTask {
  id: string;
  source_id: string;
  doc_source_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  stage: string | null;
  requested_by: string | null;
  idempotency_key: string | null;
  result: {
    version_seq?: number;
    chunks_serving?: number;
    chunks_total?: number;
    consistency?: "passed" | "failed";
    repaired_indices?: number[];
    repair_mode?: string;
  } | null;
  error: string | null;
  events: Array<Record<string, unknown>>;
  created_at: string | null;
  finished_at: string | null;
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
  /** U-7 逐文档内容类型账本聚合(类型过滤词表真实来源;NULL 不入)。 */
  content_type_counts: Record<string, number>;
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
  /** U-7 逐文档内容类型(null = 不可用)。 */
  content_type: string | null;
  /** U-9 chunk 级 serving 投影(null = 向量库不可用,诚实降级)。 */
  chunk_serving: ChunkServingTruth | null;
  /** U-10 自动恢复尝试未成功次数(持久化权威事件计数)。 */
  recovery_attempts_failed: number;
  /** U-10 自动恢复尝试成功次数。 */
  recovery_attempts_succeeded: number;
  /** U-8 最近一次修复任务(验证卡数据源)。 */
  latest_repair_task: DocumentRepairTask | null;
  /** Issue #55 版本历史(document_versions 权威行降序;空 = 后端无此记录)。 */
  versions: DocumentVersionHistoryEntry[];
  /** Issue #55 True = 超出上限仅最近 N 条(诚实标注,不静默截断)。 */
  versions_truncated: boolean;
  /** Issue #55 引用与链接有效性(#48 权威派生;null = 不可用,绝不伪造)。 */
  citation: DocumentCitationTruth | null;
}

/** Issue #55:版本历史行(document_versions 权威行的 Inspector 投影)。 */
export interface DocumentVersionHistoryEntry {
  version_seq: number;
  status: string;
  chunk_count: number;
  source_version: Record<string, unknown> | null;
  valid_from: string | null;
  valid_to: string | null;
  superseded_by_version_id: string | null;
  generation_ordinal: number | null;
}

/** Issue #55:引用真值(#48 link_state 词表 external/none/private/stale)。 */
export interface DocumentCitationTruth {
  /** 账本存储 canonical 目标(identity 保全,绝不改写)。 */
  url: string;
  /** 权威引用目标(wiki slug 权威映射路由;与 url 相同 = 无映射;空白 URL = null)。 */
  citation_url: string | null;
  link_state: string;
  /** 连接器 clone 时探测真值;null = 未记录(显式缺席,不推断)。 */
  visitor_reachability: string | null;
}

/** 逐源索引生成列表响应。 */
export interface SourceGenerationsResponse {
  source_id: string;
  total: number;
  /** 权威在服代序集合(active_generation 口径的源内投影)。 */
  serving_ordinals: number[];
  items: GenerationTruth[];
}
