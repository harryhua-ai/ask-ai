import { apiFetch } from "@/lib/api";

export type LeadStatus =
  | "potential"
  | "qualified"
  | "contact_captured"
  | "handed_off"
  | "unknown_provenance";

export interface SalesLead {
  id: string;
  session_id: string | null;
  /** 不可变历史状态(只升不降,不改写) */
  status: LeadStatus;
  /** 生效状态(#124):作废后的来源不明资格单独标记,不猜成 potential 或 qualified。 */
  effective_status: LeadStatus;
  qualification_provenance: "qualified_signal" | "no_qualified_signal" | null;
  contact_type: string | null;
  contact_masked: string | null;
  /** 有效联系方式在档(#124:已作废的联系方式不计入) */
  has_contact: boolean;
  contact_captured_at: string | null;
  /** #124 错误联系方式作废审计(理由自由文本只在详情,见 SalesLeadDetail) */
  contact_voided: boolean;
  contact_voided_at: string | null;
  contact_voided_by: string | null;
  name: string | null;
  company: string | null;
  region: string | null;
  product_interest: string | null;
  quantity: string | null;
  use_case: string | null;
  purchase_intent: string | null;
  timeline: string | null;
  ai_summary: string | null;
  prompt_count: number;
  last_prompted_at: string | null;
  source_conversation_id: string;
  last_conversation_id: string;
  channel: string | null;
  language: string | null;
  country: string | null;
  handoff_at: string | null;
  handoff_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SalesLeadDetail extends SalesLead {
  /** 仅详情返回联系方式原文(销售跟进必需;列表只有 masked) */
  contact_value: string | null;
  /** 仅详情返回完整作废理由(#124 R2 PII:自由文本可能含敏感字面,
   *  列表投影最小化不含此字段;授权详情视图保留完整审计) */
  contact_voided_reason: string | null;
}

export interface SalesLeadListData {
  leads: SalesLead[];
  total: number;
}

export interface LeadThreadMessage {
  conversation_id: string;
  role: string;
  question: string;
  answer: string | null;
  intent_tag: string | null;
  channel: string | null;
  created_at: string | null;
}

export interface LeadThreadData {
  session_id: string | null;
  messages: LeadThreadMessage[];
}

export interface LeadListParams {
  status?: LeadStatus | "";
  contact?: "with" | "without" | "voided" | "";
  q?: string;
  limit?: number;
  offset?: number;
}

export function fetchSalesLeads(
  params: LeadListParams = {},
): Promise<SalesLeadListData> {
  const sp = new URLSearchParams();
  if (params.status) sp.set("status", params.status);
  if (params.contact) sp.set("contact", params.contact);
  if (params.q) sp.set("q", params.q);
  sp.set("limit", String(params.limit ?? 50));
  sp.set("offset", String(params.offset ?? 0));
  return apiFetch<SalesLeadListData>(`/leads?${sp.toString()}`);
}

export function fetchSalesLead(id: string): Promise<SalesLeadDetail> {
  return apiFetch<SalesLeadDetail>(`/leads/${id}`);
}

export function fetchSalesLeadThread(id: string): Promise<LeadThreadData> {
  return apiFetch<LeadThreadData>(`/leads/${id}/thread`);
}

export function handoffSalesLead(id: string): Promise<SalesLeadDetail> {
  return apiFetch<SalesLeadDetail>(`/leads/${id}/handoff`, { method: "POST" });
}

/**
 * #124:错误联系方式作废(仅 admin;后端要求显式 confirm + 必填理由)。
 * 幂等:后端首写审计,重复提交返回现状。原文保留,仅运营口径失效。
 */
export function voidSalesLeadContact(
  id: string,
  reason: string,
): Promise<SalesLeadDetail> {
  return apiFetch<SalesLeadDetail>(`/leads/${id}/void-contact`, {
    method: "POST",
    body: JSON.stringify({ confirm: true, reason }),
  });
}
