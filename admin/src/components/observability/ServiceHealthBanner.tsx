import type { ReactNode } from "react";
import type { TechHealth } from "@/lib/api/techInsight";

/** 服务健康横幅(PRIMARY 层,合同 OBS-01/§11)。

  状态由后端确定性推导(healthy/degraded/critical/insufficient_data/no_data),
  reasons 为证据文字;本组件只做呈现,不做二次推断。
  颜色仅表达状态语义:绿=健康,琥珀=降级,红=需介入,灰=证据不足/无数据。
 */
const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; hint: string }
> = {
  healthy: {
    label: "服务健康",
    color: "var(--ok)",
    bg: "color-mix(in srgb, var(--ok) 8%, transparent)",
    hint: "未检测到需要关注的运行问题",
  },
  degraded: {
    label: "服务降级",
    color: "var(--warn)",
    bg: "color-mix(in srgb, var(--warn) 10%, transparent)",
    hint: "服务可用,但存在需要关注的信号",
  },
  critical: {
    label: "需要介入",
    color: "var(--err)",
    bg: "color-mix(in srgb, var(--err) 10%, transparent)",
    hint: "存在真实失败或严重退化,建议立即排查",
  },
  insufficient_data: {
    label: "证据不足",
    color: "var(--t2)",
    bg: "transparent",
    hint: "样本过少,无法给出自信的健康判定",
  },
  no_data: {
    label: "暂无数据",
    color: "var(--t2)",
    bg: "transparent",
    hint: "所选时间窗内没有 trace 数据",
  },
};

export default function ServiceHealthBanner({
  health,
  windowLabel,
  children,
}: {
  health: TechHealth;
  windowLabel: string;
  /** 操作区(如「查看失败对话」深链)。 */
  children?: ReactNode;
}) {
  const cfg = STATUS_CONFIG[health.status] ?? STATUS_CONFIG.no_data;
  return (
    <div
      data-health-banner
      data-health-status={health.status}
      className="rounded-lg border p-4"
      style={{ borderColor: cfg.color, background: cfg.bg }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              data-health-dot
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: cfg.color }}
            />
            <span
              data-health-label
              className="text-[16px] font-semibold"
              style={{ color: cfg.color }}
            >
              {cfg.label}
            </span>
            <span className="text-[12px] text-[var(--t3)]">{cfg.hint}</span>
          </div>
          {health.reasons.length > 0 && (
            <ul data-health-reasons className="mt-2 space-y-1">
              {health.reasons.map((r, i) => (
                <li key={i} className="text-[13px] text-[var(--t2)] flex gap-1.5">
                  <span className="text-[var(--t3)]">·</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2 text-[12px] text-[var(--t3)]">
            统计窗口:{windowLabel} · 样本 {health.sample_size} 条 trace
          </div>
        </div>
        {children && <div className="shrink-0 flex flex-col gap-2">{children}</div>}
      </div>
    </div>
  );
}
