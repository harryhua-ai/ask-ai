/**
 * Ownership(IF-6 附录):本文件 = **Track F**(证据聚合)Wave 1 专属 ——
 * 证据聚合 API 客户端(U-17 用户聚合 / U-18 gap→源归因 / U-19 主题短语)。
 * 端点实现在 backend/api/admin/tech_evidence.py(Track F 专属子模块,
 * 已由 tech.py 挂载);本文件仅封装类型与 fetch,零推断零兜底编造 ——
 * unavailable 语义以后端 users_available/unavailable_reason 为权威。
 * 注意:类型 AnswerGapItem 仍以 @/lib/api/techInsight 为单一来源(仅
 * type-only import,该文件零改动)。
 */

import { apiFetch } from "@/lib/api";

// --------------------------------------------------------------------------- //
// U-17(TI-27)受影响用户聚合 —— 伪匿名会话去重(隐私保持聚合,零 PII)
// --------------------------------------------------------------------------- //

/** IF-7 冻结分析窗词表(Track F 消费端;显式起止经 from/to 参数表达)。 */
export type EvidenceWindowValue = "today" | "7d" | "30d" | "all";

export interface GapUsersProjection {
  gap_id: string;
  window: { preset: string; from: string | null; to: string | null };
  conversations_in_window: number;
  conversations_with_session_identity: number;
  conversations_without_session_identity: number;
  /** 窗内去重伪匿名会话数(DISTINCT session_id;聚合投影,无原值)。 */
  distinct_sessions: number;
  /** 权威去重计数;身份真值不足 → null(诚实 unavailable,不得编造)。 */
  users: number | null;
  users_available: boolean;
  /** session_identity_insufficient = 窗内存在 session_id 缺失的历史行。 */
  unavailable_reason: string | null;
}

export function fetchGapUsers(
  gapId: string,
  window: EvidenceWindowValue = "all",
  from?: string,
  to?: string,
): Promise<GapUsersProjection> {
  const params = new URLSearchParams();
  params.set("window", window);
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  return apiFetch(`/tech/answer-gaps/${gapId}/users?${params.toString()}`);
}

// --------------------------------------------------------------------------- //
// U-18(TI-33)gap→源归因 —— 会话引用真值 × 数据源身份匹配(零前端猜测)
// --------------------------------------------------------------------------- //

export interface GapSourceAttributionItem {
  source_id: string;
  source_type: string;
  product: string;
  /** 引用了该源身份的 gap 归属会话数(按会话去重)。 */
  citing_conversations: number;
  /** 冻结证据规则 ID = conversation_citation_identity_match。 */
  evidence_rule: string;
}

export interface GapSourceAttribution {
  gap_id: string;
  conversations_total: number;
  citing_conversations_total: number;
  items: GapSourceAttributionItem[];
  /** 有引用真值但无对应数据源行(知识案例/已删源)→ 透明列出,不归因。 */
  unmatched_citations: {
    source_type: string;
    product: string | null;
    citing_conversations: number;
  }[];
}

export function fetchGapSources(gapId: string): Promise<GapSourceAttribution> {
  return apiFetch(`/tech/answer-gaps/${gapId}/sources`);
}

// --------------------------------------------------------------------------- //
// U-19(TI-12)主题短语 —— 确定性派生(跨问句公共因子;零 LLM 零词表)
// --------------------------------------------------------------------------- //

export interface GapTopicProjection {
  gap_id: string;
  /** 确定性主题;不可派生 → null(UI 回退 fallback 代表问句)。 */
  topic: string | null;
  /** cross_question_common_factor(冻结规则 ID);无主题 → null。 */
  derivation: string | null;
  corpus_size: number;
  fallback: string;
}

export function fetchGapTopic(gapId: string): Promise<GapTopicProjection> {
  return apiFetch(`/tech/answer-gaps/${gapId}/topic`);
}
