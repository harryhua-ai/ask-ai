import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Handshake,
  Loader2,
  Mail,
  MessageSquare,
  Phone,
  Search,
  Smartphone,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/useAuth";
import LoadError from "@/components/LoadError";
import {
  fetchSalesLead,
  fetchSalesLeadThread,
  fetchSalesLeads,
  handoffSalesLead,
  voidSalesLeadContact,
  type LeadStatus,
  type LeadThreadData,
  type SalesLead,
  type SalesLeadDetail,
} from "@/lib/api/salesLeads";

export const LEAD_STATUS_META: Record<
  LeadStatus,
  { label: string; variant: "secondary" | "default" | "outline" | "destructive" }
> = {
  potential: { label: "潜在线索", variant: "secondary" },
  qualified: { label: "合格线索", variant: "default" },
  contact_captured: { label: "已留联系方式", variant: "outline" },
  handed_off: { label: "已移交销售", variant: "destructive" },
};

export const LEAD_CONTACT_ICONS: Record<string, typeof Mail> = {
  email: Mail,
  phone: Phone,
  whatsapp: Smartphone,
  wechat: MessageSquare,
  other: MessageSquare,
};

function formatTime(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")} ${String(
    d.getHours(),
  ).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function ContactCell({ lead }: { lead: SalesLead }) {
  if (lead.contact_voided) {
    // #124:已作废联系方式 —— 审计可见但不冒充有效线索
    return (
      <span className="inline-flex items-center gap-1.5" data-testid="contact-voided-cell">
        <Badge variant="destructive" data-testid="contact-voided-badge">
          已作废
        </Badge>
        <span className="text-muted-foreground line-through">{lead.contact_masked}</span>
      </span>
    );
  }
  if (!lead.has_contact) {
    return <span className="text-muted-foreground/60">未提供</span>;
  }
  const Icon = LEAD_CONTACT_ICONS[lead.contact_type ?? "other"] ?? MessageSquare;
  return (
    <span className="inline-flex items-center gap-1.5" data-contact={lead.contact_type}>
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      {lead.contact_masked}
    </span>
  );
}

function FieldRow({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-20 shrink-0 text-muted-foreground">{label}</span>
      <span className="break-all">{value}</span>
    </div>
  );
}

function ThreadView({ leadId }: { leadId: string }) {
  const { data, isLoading } = useQuery<LeadThreadData>({
    queryKey: ["lead-thread", leadId],
    queryFn: () => fetchSalesLeadThread(leadId),
  });
  if (isLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }
  if (!data || data.messages.length === 0) {
    return <p className="text-sm text-muted-foreground">会话记录不存在或已被清理。</p>;
  }
  return (
    <div className="space-y-3" data-testid="lead-thread">
      {data.messages.map((m) => (
        <div key={m.conversation_id} className="space-y-1">
          <div className="ml-auto w-fit max-w-[85%] rounded-lg rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
            {m.question}
          </div>
          {m.answer && (
            <div className="w-fit max-w-[85%] rounded-lg rounded-bl-sm bg-muted px-3 py-2 text-sm">
              {m.answer}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function LeadDetailPanel({
  leadId,
  onClose,
}: {
  leadId: string;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [showThread, setShowThread] = useState(false);
  const [voidDialogOpen, setVoidDialogOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const canHandoff = user?.role === "admin" || user?.role === "editor";
  // #124:作废是改变运营口径的敏感人工处置 → 仅 admin;且只对「有效在档联系方式」开放
  const canVoid = user?.role === "admin";

  const { data: lead, isLoading } = useQuery<SalesLeadDetail>({
    queryKey: ["lead-detail", leadId],
    queryFn: () => fetchSalesLead(leadId),
  });

  const handoff = useMutation({
    mutationFn: () => handoffSalesLead(leadId),
    onSuccess: () => {
      toast.success("已标记移交销售");
      queryClient.invalidateQueries({ queryKey: ["sales-leads"] });
      queryClient.invalidateQueries({ queryKey: ["lead-detail", leadId] });
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "移交失败"),
  });

  const voidContact = useMutation({
    mutationFn: () => voidSalesLeadContact(leadId, voidReason.trim()),
    onSuccess: () => {
      toast.success("已标记联系方式无效(已保留审计记录)");
      setVoidDialogOpen(false);
      setVoidReason("");
      queryClient.invalidateQueries({ queryKey: ["sales-leads"] });
      queryClient.invalidateQueries({ queryKey: ["lead-detail", leadId] });
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "作废失败"),
  });

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-[480px] max-w-full flex-col border-l bg-card shadow-xl" data-testid="lead-detail">
      <div className="flex h-14 items-center justify-between border-b px-4">
        <span className="font-semibold">线索详情</span>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭">
          <X className="h-4 w-4" />
        </Button>
      </div>
      {isLoading || !lead ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {/* #124 R2:生效口径 —— 作废的联系方式不再宣称「已留联系方式」 */}
              <Badge
                variant={LEAD_STATUS_META[lead.effective_status ?? lead.status].variant}
                data-testid="lead-effective-status"
              >
                {LEAD_STATUS_META[lead.effective_status ?? lead.status].label}
              </Badge>
              {lead.contact_voided && (
                <Badge variant="destructive" data-testid="contact-voided-badge">
                  联系方式已作废
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              {canHandoff && lead.status !== "handed_off" && (
                <Button
                  size="sm"
                  onClick={() => handoff.mutate()}
                  disabled={handoff.isPending}
                  data-testid="handoff-btn"
                >
                  {handoff.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Handshake className="h-3.5 w-3.5" />
                  )}
                  移交销售
                </Button>
              )}
              {canVoid && lead.has_contact && !lead.contact_voided && (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/50 text-destructive hover:bg-destructive/10"
                  onClick={() => setVoidDialogOpen(true)}
                  disabled={voidContact.isPending}
                  data-testid="void-contact-btn"
                >
                  标记无效
                </Button>
              )}
            </div>
          </div>

          <div className="rounded-md border p-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">AI 摘要</p>
            <p className="text-sm">{lead.ai_summary || "暂无摘要"}</p>
          </div>

          <div className="space-y-2" data-testid="lead-fields">
            <FieldRow
              label="联系方式"
              value={
                lead.has_contact
                  ? `${lead.contact_type ?? ""} ${lead.contact_value ?? ""}`
                  : null
              }
            />
            <FieldRow label="姓名" value={lead.name} />
            <FieldRow label="公司" value={lead.company} />
            <FieldRow label="地区" value={lead.region || lead.country} />
            <FieldRow label="意向产品" value={lead.product_interest} />
            <FieldRow label="数量" value={lead.quantity} />
            <FieldRow label="用途/需求" value={lead.use_case} />
            <FieldRow label="采购意向" value={lead.purchase_intent} />
            <FieldRow label="时间表" value={lead.timeline} />
            <FieldRow label="创建时间" value={formatTime(lead.created_at)} />
            <FieldRow label="邀请次数" value={String(lead.prompt_count)} />
            {lead.status === "handed_off" && (
              <FieldRow
                label="移交信息"
                value={`${lead.handoff_by ?? ""} · ${formatTime(lead.handoff_at)}`}
              />
            )}
            {lead.contact_voided && (
              <div
                className="rounded-md border border-destructive/40 bg-destructive/5 p-2.5 text-sm"
                data-testid="contact-voided-audit"
              >
                <p className="mb-1 text-xs font-medium text-destructive">
                  联系方式已作废(原文保留以供审计,不再计入有效联系方式)
                </p>
                <p className="text-xs text-muted-foreground">
                  {lead.contact_voided_by ?? "-"} · {formatTime(lead.contact_voided_at)}
                  {lead.contact_voided_reason ? ` · 理由:${lead.contact_voided_reason}` : ""}
                </p>
              </div>
            )}
          </div>

          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowThread((v) => !v)}
              data-testid="toggle-thread"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              {showThread ? "收起完整对话" : "查看完整对话"}
            </Button>
            {showThread && (
              <div className="mt-3 rounded-md border p-3">
                <ThreadView leadId={leadId} />
              </div>
            )}
          </div>

          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            已记录用户联系方式与需求;「移交销售」仅表示人工接管跟进,系统不会自动联系客户。
          </p>
        </div>
      )}

      <Dialog open={voidDialogOpen} onOpenChange={setVoidDialogOpen}>
        <DialogContent className="max-w-md" data-testid="void-contact-dialog">
          <DialogHeader>
            <DialogTitle>标记联系方式无效</DialogTitle>
            <DialogDescription>
              确认将
              {lead?.contact_masked ? `「${lead.contact_masked}」` : "该联系方式"}
              标记为无效?作废后不再计入「已留联系方式」与有效联系数,操作人、时间与理由将留存审计;原文保留、不可删除。
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="必填:作废理由(如:时间戳被误判为电话)"
            value={voidReason}
            onChange={(e) => setVoidReason(e.target.value)}
            maxLength={500}
            rows={3}
            data-testid="void-reason-input"
          />
          <DialogFooter>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setVoidDialogOpen(false)}
              data-testid="void-cancel-btn"
            >
              取消
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => voidContact.mutate()}
              disabled={!voidReason.trim() || voidContact.isPending}
              data-testid="void-confirm-btn"
            >
              {voidContact.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              确认作废
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function SalesLeads() {
  const [status, setStatus] = useState<LeadStatus | "">("");
  const [contactOnly, setContactOnly] = useState(false);
  const [q, setQ] = useState("");
  const [searchText, setSearchText] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-leads", status, contactOnly, searchText],
    queryFn: () =>
      fetchSalesLeads({
        status,
        contact: contactOnly ? "with" : "",
        q: searchText || undefined,
      }),
  });

  const statuses: (LeadStatus | "")[] = [
    "",
    "potential",
    "qualified",
    "contact_captured",
    "handed_off",
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">销售线索</h1>
          <p className="text-sm text-muted-foreground">
            哪些客户值得跟进 —— 与业务概览(生意整体)和对话审查(AI 质量)相互独立
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="w-56 pl-8"
              placeholder="搜索公司 / 摘要 / 联系方式"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setSearchText(q)}
              data-testid="lead-search"
            />
          </div>
          <Button
            variant={contactOnly ? "default" : "outline"}
            size="sm"
            onClick={() => setContactOnly((v) => !v)}
            data-testid="filter-contactable"
          >
            可联系
          </Button>
        </div>
      </div>

      <div className="flex gap-2" data-testid="status-tabs">
        {statuses.map((s) => (
          <Button
            key={s || "all"}
            variant={status === s ? "default" : "outline"}
            size="sm"
            onClick={() => setStatus(s)}
          >
            {s === "" ? "全部" : LEAD_STATUS_META[s].label}
          </Button>
        ))}
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>状态</TableHead>
              <TableHead>联系方式</TableHead>
              <TableHead>公司</TableHead>
              <TableHead>意向产品</TableHead>
              <TableHead>数量</TableHead>
              <TableHead>地区</TableHead>
              <TableHead>需求摘要</TableHead>
              <TableHead>创建时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isError && !data ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center">
                  <LoadError error={error} onRetry={refetch} />
                </TableCell>
              </TableRow>
            ) : isLoading ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : !data || data.leads.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                  暂无销售线索 —— 达到合格资格或用户主动留联系方式的对话会出现在这里
                </TableCell>
              </TableRow>
            ) : (
              data.leads.map((lead) => (
                <TableRow
                  key={lead.id}
                  className="cursor-pointer"
                  onClick={() => setSelectedId(lead.id)}
                  data-testid="lead-row"
                >
                  <TableCell>
                    {/* #124 R2:生效口径 —— 作废的联系方式不再宣称「已留联系方式」 */}
                    <Badge
                      variant={LEAD_STATUS_META[lead.effective_status ?? lead.status].variant}
                    >
                      {LEAD_STATUS_META[lead.effective_status ?? lead.status].label}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <ContactCell lead={lead} />
                  </TableCell>
                  <TableCell>{lead.company || "-"}</TableCell>
                  <TableCell>{lead.product_interest || "-"}</TableCell>
                  <TableCell>{lead.quantity || "-"}</TableCell>
                  <TableCell>{lead.region || lead.country || "-"}</TableCell>
                  <TableCell className="max-w-[220px] truncate">
                    {lead.ai_summary || "-"}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {formatTime(lead.created_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      {data && (
        <p className="text-xs text-muted-foreground">
          共 {data.total} 条线索
        </p>
      )}

      {selectedId && (
        <LeadDetailPanel
          leadId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
