import { apiFetch } from "@/lib/api";

export type LeadStatus =
  | "potential"
  | "qualified"
  | "contact_captured"
  | "handed_off";

export interface SalesLead {
  id: string;
  session_id: string | null;
  status: LeadStatus;
  contact_type: string | null;
  contact_masked: string | null;
  has_contact: boolean;
  contact_captured_at: string | null;
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
  contact?: "with" | "without" | "";
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
