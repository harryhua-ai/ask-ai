import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import LoadError from "@/components/LoadError";
import { useReleaseInfo } from "@/hooks/useReleaseInfo";
import { useSystemRuntime } from "@/hooks/useSystemRuntime";
import type {
  AcceleratorGpuInfo,
  RuntimeObservation,
  SystemRuntimeInfo,
} from "@/types/api";

/**
 * #10 系统信息页:发布身份直呈(值全部来自后端 /api/admin/system/release,
 * 前端零版本常量)。运行时权威 = 镜像内 RELEASE.json(进程启动加载,不可变)。
 *
 * #7 系统运行时:本页预留的硬件/系统 section(只读快照,数据来自
 * GET /api/admin/system/runtime)。分区网格:主机 → 资源(CPU/内存/磁盘)
 * → 加速器 → 服务状态;每项 = available 直呈 / 不可得显式「不可用+原因」
 * (后端绝不虚构,前端如实直呈);按需采集 + 手动刷新,零自动轮询。
 * 安全边界:纯只读观测,本页不提供任何重启/进程控制等操作按钮。
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function formatObsValue(value: RuntimeObservation["value"]): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

/** 观测项直呈:available → 值;不可得 → 显式「不可用(原因)」。 */
function ObsField({ label, obs }: { label: string; obs: RuntimeObservation }) {
  return (
    <Field label={label}>
      {obs.available ? (
        <span className="break-all font-mono text-xs" data-obs-available>
          {formatObsValue(obs.value)}
        </span>
      ) : (
        <span className="text-xs text-muted-foreground" data-obs-unavailable title={obs.reason ?? undefined}>
          不可用{obs.reason ? `(${obs.reason})` : ""}
        </span>
      )}
    </Field>
  );
}

function RuntimeGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border p-3" data-runtime-group={title}>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </div>
  );
}

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d > 0 ? `${d} 天 ${h} 小时 ${m} 分` : `${h} 小时 ${m} 分`;
}

function capacityBadge(state: string | null): { label: string; variant: "success" | "warning" | "destructive" | "secondary" } {
  switch (state) {
    case "HEALTHY":
      return { label: "容量正常", variant: "success" };
    case "CAPACITY_LIMITED":
      return { label: "容量受限", variant: "warning" };
    case "UNSAFE":
      return { label: "容量不安全", variant: "destructive" };
    default:
      return { label: "容量未知", variant: "secondary" };
  }
}

function GpuRow({ gpu }: { gpu: AcceleratorGpuInfo }) {
  const na = <span className="text-xs text-muted-foreground">不可得</span>;
  return (
    <div className="rounded-md border p-2 text-xs" data-gpu-row>
      <div className="mb-1 font-medium">
        {gpu.name ?? "未知 GPU"}
        {gpu.index !== null ? ` · GPU ${gpu.index}` : ""}
      </div>
      <div className="grid gap-1 text-muted-foreground sm:grid-cols-2">
        <div>
          利用率:{gpu.utilization_percent !== null ? `${gpu.utilization_percent}%` : na}
        </div>
        <div>
          温度:{gpu.temperature_c !== null ? `${gpu.temperature_c}°C` : na}
        </div>
        <div>
          显存:
          {gpu.memory_used_mb !== null && gpu.memory_total_mb !== null
            ? `${gpu.memory_used_mb} / ${gpu.memory_total_mb} MiB`
            : na}
        </div>
        <div className="break-all">UUID:{gpu.uuid ?? na}</div>
      </div>
    </div>
  );
}

function RuntimeSectionBody({ data }: { data: SystemRuntimeInfo }) {
  const capacityState =
    data.service.model_runtime.available && data.service.model_runtime.value
      ? ((data.service.model_runtime.value.capacity?.state as string | undefined) ?? null)
      : null;
  const cap = capacityBadge(capacityState);
  const policies =
    data.service.model_runtime.available && data.service.model_runtime.value
      ? data.service.model_runtime.value.policies
      : [];

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground" data-runtime-as-of>
          采集时间 {data.as_of}
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <RuntimeGroup title="主机">
          <ObsField label="主机名" obs={data.host.hostname} />
          <ObsField label="操作系统" obs={data.host.os} />
          <ObsField label="内核版本" obs={data.host.kernel} />
          <Field label="运行时长(uptime)">
            {data.host.uptime_seconds.available ? (
              <span className="font-mono text-xs" data-obs-available>
                {formatUptime(Number(data.host.uptime_seconds.value))}(
                {String(data.host.uptime_seconds.value)} 秒)
              </span>
            ) : (
              <span className="text-xs text-muted-foreground" data-obs-unavailable title={data.host.uptime_seconds.reason ?? undefined}>
                不可用({data.host.uptime_seconds.reason})
              </span>
            )}
          </Field>
        </RuntimeGroup>

        <RuntimeGroup title="资源(CPU · 内存 · 磁盘)">
          <ObsField label="CPU 型号" obs={data.resources.cpu_model} />
          <ObsField label="CPU 逻辑核数" obs={data.resources.cpu_logical_cores} />
          <ObsField label="CPU 利用率" obs={data.resources.cpu_utilization_percent} />
          <ObsField label="负载(loadavg 1m)" obs={data.resources.loadavg_1m} />
          <ObsField label="负载(loadavg 5m)" obs={data.resources.loadavg_5m} />
          <ObsField label="负载(loadavg 15m)" obs={data.resources.loadavg_15m} />
          <ObsField label="内存总量" obs={data.resources.memory_total_mb} />
          <ObsField label="内存已用" obs={data.resources.memory_used_mb} />
          <ObsField label="Swap 总量" obs={data.resources.swap_total_mb} />
          <ObsField label="Swap 已用" obs={data.resources.swap_used_mb} />
          <ObsField label="磁盘(部署卷)总量" obs={data.resources.disk_total_gb} />
          <ObsField label="磁盘(部署卷)已用" obs={data.resources.disk_used_gb} />
          <ObsField label="磁盘(部署卷)可用" obs={data.resources.disk_free_gb} />
          <ObsField label="磁盘(部署卷)用量" obs={data.resources.disk_used_percent} />
        </RuntimeGroup>

        <RuntimeGroup title="加速器">
          <div className="sm:col-span-2 space-y-2">
            <div className="flex items-center gap-2">
              {data.accelerator.available ? (
                <Badge variant="success">GPU 可观测</Badge>
              ) : (
                <Badge variant="secondary">不可用</Badge>
              )}
              {!data.accelerator.available && data.accelerator.reason && (
                <span className="text-xs text-muted-foreground" data-accelerator-reason>
                  {data.accelerator.reason}
                </span>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <ObsField label="驱动版本" obs={data.accelerator.driver_version} />
              <ObsField label="CUDA 版本" obs={data.accelerator.cuda_version} />
            </div>
            {data.accelerator.gpus.map((gpu, i) => (
              <GpuRow key={gpu.uuid ?? `gpu-${i}`} gpu={gpu} />
            ))}
          </div>
        </RuntimeGroup>

        <RuntimeGroup title="服务状态">
          <ObsField label="健康检查(/health)" obs={data.service.health} />
          <Field label="ASK-AI 版本">
            {data.service.release.available && data.service.release.value ? (
              <span className="font-mono text-xs" data-obs-available>
                {data.service.release.value.version}({data.service.release.value.app_mode})
              </span>
            ) : (
              <span className="text-xs text-muted-foreground" data-obs-unavailable title={data.service.release.reason ?? undefined}>
                不可用({data.service.release.reason})
              </span>
            )}
          </Field>
          <Field label="模型运行时">
            {data.service.model_runtime.available ? (
              <span className="flex items-center gap-2" data-model-runtime-ok>
                <Badge variant={cap.variant}>{cap.label}</Badge>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground" data-obs-unavailable title={data.service.model_runtime.reason ?? undefined}>
                不可用({data.service.model_runtime.reason})
              </span>
            )}
          </Field>
          <Field label="推理负载状态">
            {data.service.model_runtime.available && data.service.model_runtime.value ? (
              <div className="space-y-1" data-policy-list>
                {policies.map((p, i) => (
                  <div key={i} className="font-mono text-xs text-muted-foreground">
                    {String(p.workload ?? "?")}: {String(p.status ?? "?")}
                    {typeof p.effective === "object" && p.effective !== null
                      ? ` · ${String((p.effective as Record<string, unknown>).label ?? "")}`
                      : ""}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted-foreground">不可用</span>
            )}
          </Field>
        </RuntimeGroup>
      </div>
    </>
  );
}

export default function SystemInfo() {
  const { data: release, isLoading, isError, error, refetch } = useReleaseInfo();
  const runtime = useSystemRuntime();

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">系统信息</h1>

      <Card aria-label="版本与发布">
        <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
          <CardTitle className="text-base">版本 / 发布</CardTitle>
          {release && (
            <Badge variant={release.source === "manifest" ? "success" : "secondary"}>
              {release.source === "manifest" ? "正式发布" : "开发态"}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              正在加载发布信息…
            </p>
          )}
          {isError && <LoadError error={error} onRetry={() => refetch()} />}
          {release && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="ASK-AI 版本">
                <span className="font-mono text-base font-semibold">{release.version}</span>
              </Field>
              <Field label="运行环境">
                <span>{release.app_mode}</span>
              </Field>
              <Field label="Git SHA(完整)">
                <span className="break-all font-mono text-xs">{release.git_sha}</span>
              </Field>
              <Field label="构建时间">
                <span className="font-mono text-xs">{release.built_at ?? "—"}</span>
              </Field>
              <Field label="镜像 / Tag">
                <span className="break-all font-mono text-xs">{release.image ?? "—"}</span>
              </Field>
              <Field label="CI 构建">
                {release.ci_run_id ? (
                  <a
                    className="break-all font-mono text-xs underline underline-offset-2"
                    href={`https://github.com/harryhua-ai/ask-ai/actions/runs/${release.ci_run_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    run {release.ci_run_id}
                  </a>
                ) : (
                  <span className="text-muted-foreground">不可用</span>
                )}
              </Field>
            </div>
          )}
        </CardContent>
      </Card>

      <Card aria-label="系统运行时">
        <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
          <CardTitle className="text-base">系统运行时</CardTitle>
          <button
            type="button"
            data-runtime-refresh
            onClick={() => runtime.refetch()}
            disabled={runtime.isFetching}
            className="rounded-md border px-2.5 py-1 text-xs text-[var(--t1)] hover:bg-accent disabled:opacity-50"
          >
            {runtime.isFetching ? "刷新中…" : "刷新"}
          </button>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {runtime.isLoading && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              正在加载系统运行时…
            </p>
          )}
          {runtime.isError && <LoadError error={runtime.error} onRetry={() => runtime.refetch()} />}
          {runtime.data && <RuntimeSectionBody data={runtime.data} />}
        </CardContent>
      </Card>
    </div>
  );
}
