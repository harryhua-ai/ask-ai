/**
 * #50 B1 单一权威映射模块(L 轴 / P 轴生成状态 → 运营标签与 badge 语义)。
 *
 * 合同(docs/engineering/tasks/v162-i50-data-source-workspace-v2-contract.md):
 * - 语义级冻结:一处定义、详情工作面消费、#51 可按需复用;禁止第二份映射表;
 * - 运营三桶逐态映射,每一态可解释(见 bucketOfDocument / bucketCountsOf);
 * - 每个非 Current / 有风险条目的原因措辞唯一出处(notServingReason);
 *   后端无记录的成分显式表达「后端无此记录」,绝不编造
 *   (无 content-role / discovered / last-seen 等虚构字段——后端不存在即不呈现);
 * - 词表权威 = backend/services/document_lifecycle.py(DocLifecycle /
 *   GenerationStatus);本模块只做**呈现层本地化与桶归类**,不重判后端状态。
 */

export type DocLifecycleValue =
  | "discovered"
  | "active"
  | "superseded"
  | "missing_candidate"
  | "deleted";

export type GenerationStatusValue =
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "retired";

export type BucketKey = "current" | "attention" | "retired";

export type BadgeVariant =
  | "success"
  | "warning"
  | "destructive"
  | "secondary"
  | "outline";

// --------------------------------------------------------------------------- //
// L 轴(document lifecycle)标签 / badge
// --------------------------------------------------------------------------- //

const LIFECYCLE_LABELS: Record<string, string> = {
  discovered: "已发现未灌入",
  active: "在服",
  superseded: "已被接替",
  missing_candidate: "源中缺失(宽限中)",
  deleted: "已删除(墓碑)",
};

const LIFECYCLE_VARIANTS: Record<string, BadgeVariant> = {
  active: "success",
  missing_candidate: "warning",
  superseded: "outline",
  deleted: "outline",
  discovered: "secondary",
};

export function lifecycleLabel(lifecycle: string | null | undefined): string {
  if (!lifecycle) return "未知状态";
  return LIFECYCLE_LABELS[lifecycle] ?? lifecycle;
}

export function lifecycleVariant(lifecycle: string | null | undefined): BadgeVariant {
  return (lifecycle && LIFECYCLE_VARIANTS[lifecycle]) || "secondary";
}

// --------------------------------------------------------------------------- //
// P 轴生成处理状态(无 ACTIVE;激活 = 关系不是状态,FC-3)
// --------------------------------------------------------------------------- //

const GENERATION_LABELS: Record<string, string> = {
  pending: "等待构建",
  processing: "构建中",
  ready: "构建完成",
  failed: "构建失败",
  retired: "已退役",
};

const GENERATION_VARIANTS: Record<string, BadgeVariant> = {
  pending: "secondary",
  processing: "warning",
  ready: "success",
  failed: "destructive",
  retired: "outline",
};

export function generationStatusLabel(status: string | null | undefined): string {
  if (!status) return "未知状态";
  return GENERATION_LABELS[status] ?? status;
}

export function generationStatusVariant(status: string | null | undefined): BadgeVariant {
  return (status && GENERATION_VARIANTS[status]) || "secondary";
}

// --------------------------------------------------------------------------- //
// 运营三桶(Current / Needs Attention / Retired)—— 逐态映射设计(冻结)
// --------------------------------------------------------------------------- //
//
// 桶判定只消费权威账本字段(后端 /documents 端点行):
//   current   : lifecycle=active 且现行版本可解析(serving)——「current_version_id
//               ⋈ SERVING」中无风险标记的严格子集;
//   attention : missing_candidate(缺席宽限标记,风险证据;其仍由上一代服务的
//               事实经「在服」徽章与原因文案表达)+ discovered(仅发现未灌入)
//               + active 而现行版本悬挂(不可证在服,现行版本缺席显式呈现);
//   retired   : superseded(已接替)+ deleted(墓碑)。
// 三桶并集覆盖 L 轴全部词表;未知未来状态归 attention(原文透传,不静默)。

/** 清单行/真相行中桶判定所需的权威字段子集。 */
export interface BucketInput {
  lifecycle: string;
  serving: boolean;
}

export function bucketOfDocument(doc: BucketInput): BucketKey {
  switch (doc.lifecycle) {
    case "active":
      return doc.serving ? "current" : "attention";
    case "missing_candidate":
    case "discovered":
      return "attention";
    case "superseded":
    case "deleted":
      return "retired";
    default:
      // 未知未来状态:呈现原文并归入需要关注(不静默、不编造语义)
      return "attention";
  }
}

export const BUCKET_LABELS: Record<BucketKey, string> = {
  current: "当前在服",
  attention: "需要关注",
  retired: "已退役",
};

export const BUCKET_VARIANTS: Record<BucketKey, BadgeVariant> = {
  current: "success",
  attention: "warning",
  retired: "outline",
};

export function bucketLabel(bucket: BucketKey): string {
  return BUCKET_LABELS[bucket];
}

export function bucketVariant(bucket: BucketKey): BadgeVariant {
  return BUCKET_VARIANTS[bucket];
}

/** 源级桶计数输入(后端 /documents 响应的权威聚合字段)。 */
export interface BucketCountsInput {
  lifecycle_counts: Record<string, number>;
  current_count: number;
  serving_count: number;
  ledger_total: number;
}

/**
 * 源级三桶计数(与 bucketOfDocument 同一映射的聚合投影):
 * - current = 后端 current_count(active ∧ 现行版本可解析,权威 SQL 计数);
 * - retired = superseded + deleted(账本逐态计数);
 * - attention = 账本总数 − current − retired(missing_candidate + discovered
 *   + active 悬挂;三桶并集 = 全部账本行,数学上封闭)。
 */
export function bucketCountsOf(input: BucketCountsInput): Record<BucketKey, number> {
  const retired =
    (input.lifecycle_counts.superseded ?? 0) + (input.lifecycle_counts.deleted ?? 0);
  const attention = Math.max(0, input.ledger_total - input.current_count - retired);
  return { current: input.current_count, attention, retired };
}

// --------------------------------------------------------------------------- //
// 原因措辞(非在服 / 风险条目;唯一出处)
// --------------------------------------------------------------------------- //

/** 桶/原因合成所需的完整权威字段子集(清单行超集)。 */
export interface ReasonInput extends BucketInput {
  current_version_seq: number | null;
  superseded_by?: string | null;
  superseded_at?: string | null;
  deleted_at?: string | null;
}

/** 非在服/风险原因;在服且无风险标记 → null。只引用权威字段,缺席成分显式「后端无此记录」。 */
export function notServingReason(doc: ReasonInput): string | null {
  switch (doc.lifecycle) {
    case "missing_candidate":
      return "源同步报告该文档缺失,处于缺席宽限期(仍由上一代继续服务)";
    case "superseded":
      return doc.superseded_by
        ? `已被 ${doc.superseded_by} 接替${doc.superseded_at ? `(接替于 ${servingTimestamp(doc.superseded_at)})` : ""},不再服务`
        : `已被接替(接替者:后端无此记录),不再服务`;
    case "deleted":
      return `已删除(墓碑${doc.deleted_at ? `,墓碑于 ${servingTimestamp(doc.deleted_at)}` : ""}),不再服务`;
    case "discovered":
      return "账本仅有发现记录,尚未灌入(无现行版本)";
    case "active":
      return doc.serving
        ? null
        : "现行版本:后端无此记录(账本行存在但现行版本缺失,无法证明在服)";
    default:
      return `未知生命周期状态:${doc.lifecycle}(后端无此状态的解释记录)`;
  }
}

/** 权威时间戳格式化(原样 ISO 便于与 psql 抽查比对;缺席 → null,不虚构)。 */
export function servingTimestamp(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  return value;
}
