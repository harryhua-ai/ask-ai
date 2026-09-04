// 模型运行 Tab(Hardware-Aware Runtime 的业务配置面)。
//
// 只呈现「模型执行决策」所需事实:可用执行设备、三个 workload 的
// Configured/Effective/Status(共享嵌入运行时显式指示)、GPU 运行容量策略
// (自动/手动上限)与容量建议。不做系统监控仪表盘(温度/风扇/进程表等
// 属未来 System Information 页,本页明确排除)。
// 真相契约:Configured ≠ Effective —— 保存仅持久化,重启生效以「待重启」
// 状态如实呈现;Effective 只反映运行时已落地的事实。

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export interface RuntimeDevice {
  kind: "gpu" | "cpu";
  uuid: string | null;
  index: number | null;
  label: string;
  name: string;
  total_memory_mb?: number;
  logical_cores?: number;
}

export interface RuntimePolicyState {
  workload: string;
  model_name: string;
  configured: { kind: string; gpu_uuid: string | null; label: string };
  effective: { kind: string; gpu_uuid: string | null; label: string };
  status: string;
  shared: boolean;
  residency?: string;
  fallback_reason: string | null;
  fallback_detail: string | null;
  restart_required?: boolean;
}

export interface ModelRuntimeState {
  devices: RuntimeDevice[];
  policies: RuntimePolicyState[];
  shared_embedding_runtime: boolean;
  runtime_plan?: {
    mode: string | null;
    budget_mb: number | null;
    reason?: string;
    action_required?: boolean;
    pending_mode?: string | null;
    restart_required?: boolean;
  };
  capacity: {
    state: string;
    budget_mode: string;
    budget_mb: number | null;
    gpu_uuid: string | null;
    gpu_total_mb: number | null;
    gpu_used_mb: number | null;
    gpu_free_mb: number | null;
    askai_resident_mb: number | null;
    peak_reserve_mb: number;
  };
}

const WORKLOAD_META: Record<string, { title: string; role: string }> = {
  query_embedding: { title: "查询嵌入", role: "在线问答的向量召回" },
  sync_embedding: { title: "同步嵌入", role: "后台知识同步的向量化" },
  query_reranker: { title: "查询重排", role: "检索结果精排" },
};

// REV1 B3/B4 + REV2 R2-1:驻留计划真相(预算驱动的装配模式,非展示性字段)
const PLAN_META: Record<string, string> = {
  dual_resident: "双模型常驻 GPU",
  reranker_transient: "重排瞬态驻留(预算驱动,重排步骤按需上卡)",
  embedder_only: "仅嵌入常驻 GPU",
  gpu_insufficient: "GPU 容量不足:查询侧已拒绝执行(UNSAFE),需管理员调整设备策略或运行预算",
  undecided: "维持当前驻留(预算不可读)",
  cpu_only: "无 GPU 工作负载",
};

const CAPACITY_META: Record<string, { label: string; tone: string; advice: string }> = {
  HEALTHY: {
    label: "容量充足",
    tone: "text-emerald-700 dark:text-emerald-400",
    advice: "当前容量可支撑全部 GPU 工作负载。",
  },
  CAPACITY_LIMITED: {
    label: "GPU 容量紧张",
    tone: "text-amber-700 dark:text-amber-400",
    advice:
      "容量接近运行预算:若出现嵌入/重排失败,可将「同步嵌入」移到 CPU,或降低同步批量。",
  },
  UNSAFE: {
    label: "容量不足",
    tone: "text-red-700 dark:text-red-400",
    advice:
      "空闲显存低于单次查询峰值,在线查询可能失败。建议将部分工作负载移到 CPU,或释放 GPU 占用后重试。",
  },
  unknown: {
    label: "容量未知",
    tone: "text-muted-foreground",
    advice: "暂时无法读取 GPU 容量(观测通道不可用),运行时将按配置继续执行。",
  },
};

function gb(mb: number | null | undefined): string {
  return mb == null ? "—" : `${(mb / 1024).toFixed(1)} GB`;
}

export default function ModelRuntimeTab({ canWrite }: { canWrite: boolean }) {
  const [state, setState] = useState<ModelRuntimeState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // 草稿:workload → 设备选择值("cpu" | gpu uuid)
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingWorkload, setSavingWorkload] = useState<string | null>(null);
  const [budgetMode, setBudgetMode] = useState<"auto" | "manual">("auto");
  const [budgetGb, setBudgetGb] = useState<string>("");
  const [savingBudget, setSavingBudget] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const s = await apiFetch<ModelRuntimeState>("/model-runtime");
      setState(s);
      setBudgetMode(s.capacity.budget_mode === "manual" ? "manual" : "auto");
      setBudgetGb(
        s.capacity.budget_mode === "manual" && s.capacity.budget_mb
          ? (s.capacity.budget_mb / 1024).toFixed(1)
          : "",
      );
      setDrafts((prev) => {
        const next: Record<string, string> = {};
        for (const p of s.policies) {
          next[p.workload] =
            prev[p.workload] ??
            (p.configured.kind === "cpu" ? "cpu" : (p.configured.gpu_uuid ?? "cpu"));
        }
        return next;
      });
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const capacity = state?.capacity;
  const capacityMeta = CAPACITY_META[capacity?.state ?? "unknown"] ?? CAPACITY_META.unknown;

  const dirtyWorkloads = useMemo(() => {
    if (!state) return new Set<string>();
    const dirty = new Set<string>();
    for (const p of state.policies) {
      const draft = drafts[p.workload];
      const current = p.configured.kind === "cpu" ? "cpu" : (p.configured.gpu_uuid ?? "cpu");
      if (draft && draft !== current) dirty.add(p.workload);
    }
    return dirty;
  }, [state, drafts]);

  const savePolicy = async (workload: string) => {
    const value = drafts[workload];
    if (!value) return;
    setSavingWorkload(workload);
    try {
      const body =
        value === "cpu"
          ? { device_kind: "cpu", gpu_uuid: null }
          : { device_kind: "gpu", gpu_uuid: value };
      const updated = await apiFetch<RuntimePolicyState>(
        `/model-runtime/policies/${workload}`,
        { method: "PUT", body: JSON.stringify(body) },
      );
      toast.success(
        `已保存「${WORKLOAD_META[workload]?.title ?? workload}」配置:重启后生效`,
      );
      setState((prev) =>
        prev
          ? {
              ...prev,
              policies: prev.policies.map((p) =>
                p.workload === workload ? updated : p,
              ),
            }
          : prev,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingWorkload(null);
    }
  };

  const saveBudget = async () => {
    setSavingBudget(true);
    try {
      const body =
        budgetMode === "manual"
          ? {
              mode: "manual",
              manual_budget_mb: Math.round(Number(budgetGb || "0") * 1024),
            }
          : { mode: "auto", manual_budget_mb: null };
      const cap = await apiFetch<ModelRuntimeState["capacity"]>(
        "/model-runtime/gpu-budget",
        { method: "PUT", body: JSON.stringify(body) },
      );
      setState((prev) => (prev ? { ...prev, capacity: cap } : prev));
      toast.success("GPU 运行容量策略已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSavingBudget(false);
    }
  };

  if (loading) return <p className="text-sm text-muted-foreground">加载中…</p>;
  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!state) return null;

  const gpuDevices = state.devices.filter((d) => d.kind === "gpu");
  const cpuDevices = state.devices.filter((d) => d.kind === "cpu");
  const externalUsedMb =
    capacity?.gpu_used_mb != null && capacity?.askai_resident_mb != null
      ? Math.max(0, capacity.gpu_used_mb - capacity.askai_resident_mb)
      : null;

  return (
    <div className="space-y-4" data-testid="model-runtime-tab">
      {/* A. 可用执行设备 */}
      <Card aria-label="可用执行设备">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">可用执行设备</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 p-4 pt-0 md:grid-cols-2">
          {gpuDevices.map((d) => {
            const limited =
              capacity?.gpu_uuid === d.uuid && capacity.state !== "HEALTHY";
            return (
              <div
                key={d.uuid}
                className="rounded-md border p-3"
                data-testid={`device-gpu-${d.index}`}
              >
                <div className="text-sm font-medium">{d.label}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  总显存 {gb(d.total_memory_mb)} ·{" "}
                  {limited ? "当前容量有限" : "当前容量可观测"}
                  {capacity?.gpu_free_mb != null ? ` · 空闲 ${gb(capacity.gpu_free_mb)}` : ""}
                </div>
              </div>
            );
          })}
          {cpuDevices.map((d) => (
            <div key="cpu" className="rounded-md border p-3" data-testid="device-cpu">
              <div className="text-sm font-medium">{d.label}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                可用于模型运行
                {d.logical_cores ? ` · ${d.logical_cores} 逻辑核` : ""}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* B. 模型运行策略 */}
      <Card aria-label="模型运行策略">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">模型运行策略</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          {state.policies.map((p) => {
            const meta = WORKLOAD_META[p.workload] ?? { title: p.workload, role: "" };
            const isEmbedding =
              p.workload === "query_embedding" || p.workload === "sync_embedding";
            const sharedVisible =
              isEmbedding && state.shared_embedding_runtime;
            return (
              <div
                key={p.workload}
                className="rounded-md border p-3"
                data-testid={`policy-${p.workload}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{meta.title}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {p.model_name}
                  </span>
                  {sharedVisible && (
                    <Badge variant="secondary" data-testid="shared-runtime-badge">
                      共享模型运行实例
                    </Badge>
                  )}
                  {p.residency === "transient" && (
                    <Badge variant="secondary" data-testid="transient-residency-badge">
                      瞬态驻留
                    </Badge>
                  )}
                  {p.status === "fallback_gpu_to_cpu" && (
                    <Badge variant="warning">已回退 CPU</Badge>
                  )}
                  {p.status === "cpu_by_capacity_plan" && (
                    <Badge variant="warning">按容量计划以 CPU 运行</Badge>
                  )}
                  {p.status === "unsafe_no_safe_plan" && (
                    <Badge variant="destructive" data-testid="unsafe-plan-badge">
                      UNSAFE · 无安全运行计划
                    </Badge>
                  )}
                  {p.restart_required && (
                    <Badge variant="outline" className="text-amber-700">
                      待重启生效
                    </Badge>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{meta.role}</div>
                <div className="mt-2 grid gap-1 text-xs">
                  <div>
                    配置设备:
                    <span className="ml-1 font-medium" data-testid={`configured-${p.workload}`}>
                      {p.configured.label}
                    </span>
                  </div>
                  <div>
                    生效设备:
                    <span className="ml-1 font-medium" data-testid={`effective-${p.workload}`}>
                      {p.effective.label}
                    </span>
                  </div>
                  <div>
                    状态:
                    <span className="ml-1" data-testid={`status-${p.workload}`}>
                      {p.status === "fallback_gpu_to_cpu"
                        ? "GPU 故障后已回退 CPU"
                        : p.status === "cpu_by_capacity_plan"
                          ? "按容量计划以 CPU 运行"
                          : p.status === "unsafe_no_safe_plan"
                            ? "无安全运行计划,已拒绝执行(未自动降级 CPU)"
                            : p.restart_required
                              ? "已保存,待重启生效"
                              : "运行中"}
                    </span>
                  </div>
                </div>
                {canWrite && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <select
                      aria-label={`${meta.title}设备`}
                      className="h-8 rounded-md border bg-background px-2 text-xs"
                      value={drafts[p.workload] ?? "cpu"}
                      onChange={(e) =>
                        setDrafts((prev) => ({ ...prev, [p.workload]: e.target.value }))
                      }
                    >
                      <option value="cpu">CPU</option>
                      {gpuDevices.map((d) => (
                        <option key={d.uuid} value={d.uuid ?? ""}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!dirtyWorkloads.has(p.workload) || savingWorkload === p.workload}
                      onClick={() => savePolicy(p.workload)}
                    >
                      {savingWorkload === p.workload ? "保存中…" : "保存设备"}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
          <p className="text-xs text-muted-foreground">
            同一模型 + 同一 GPU 的查询/同步嵌入共享同一运行实例(见「共享模型运行实例」标记);
            保存的设备配置在服务重启后生效,生效前以「生效设备」为准。
          </p>
        </CardContent>
      </Card>

      {/* C. GPU 运行容量 */}
      <Card aria-label="GPU 运行容量">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">GPU 运行容量</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          {canWrite ? (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="gpu-budget-mode"
                  checked={budgetMode === "auto"}
                  onChange={() => setBudgetMode("auto")}
                />
                自动管理(推荐)——按硬件实况推导运行预算
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="gpu-budget-mode"
                  checked={budgetMode === "manual"}
                  onChange={() => setBudgetMode("manual")}
                />
                手动上限
              </label>
              {budgetMode === "manual" && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-muted-foreground">GPU 运行容量上限</span>
                  <Input
                    className="h-8 w-28"
                    inputMode="decimal"
                    value={budgetGb}
                    onChange={(e) => setBudgetGb(e.target.value)}
                    aria-label="手动最大运行预算(GB)"
                  />
                  <span className="text-xs text-muted-foreground">GB</span>
                </div>
              )}
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={savingBudget}
                onClick={saveBudget}
              >
                {savingBudget ? "保存中…" : "保存容量策略"}
              </Button>
              <p className="text-xs text-muted-foreground">
                手动上限是运行规划预算,不能超过硬件当前实际可用容量。
              </p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              当前策略:{capacity?.budget_mode === "manual" ? "手动上限" : "自动管理"}
            </p>
          )}
        </CardContent>
      </Card>

      {/* D. 容量与建议 */}
      <Card aria-label="容量与建议">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">容量与建议</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 p-4 pt-0">
          <div className={cn("text-sm font-semibold", capacityMeta.tone)}>
            <span data-testid="capacity-state">{capacityMeta.label}</span>
            {capacity?.budget_mb != null && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                运行预算 {gb(capacity.budget_mb)}
              </span>
            )}
          </div>
          <div className="grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
            <span>GPU 总显存:{gb(capacity?.gpu_total_mb ?? null)}</span>
            <span>当前空闲:{gb(capacity?.gpu_free_mb ?? null)}</span>
            <span>
              外部占用(非 ASK-AI):
              {externalUsedMb != null ? gb(externalUsedMb) : "—"}
            </span>
            <span>ASK-AI 驻留:{gb(capacity?.askai_resident_mb ?? null)}</span>
          </div>
          {state.runtime_plan?.mode && (
            <div className="text-xs text-muted-foreground" data-testid="runtime-plan">
              运行计划:{PLAN_META[state.runtime_plan.mode] ?? state.runtime_plan.mode}
              {state.runtime_plan.restart_required && state.runtime_plan.pending_mode && (
                <span className="ml-1 text-amber-700 dark:text-amber-400">
                  (预算变化,重启后将变为:
                  {PLAN_META[state.runtime_plan.pending_mode] ??
                    state.runtime_plan.pending_mode}
                  )
                </span>
              )}
              {state.runtime_plan.action_required && (
                <span className="ml-1 font-medium text-red-700 dark:text-red-400">
                  需要操作:在上方调整设备策略或提高运行预算,或释放 GPU 显存后重启。
                </span>
              )}
            </div>
          )}
          <p className="text-xs text-muted-foreground">{capacityMeta.advice}</p>
        </CardContent>
      </Card>
    </div>
  );
}
