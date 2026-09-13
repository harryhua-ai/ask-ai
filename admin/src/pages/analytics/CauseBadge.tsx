/**
 * Ownership: Track D (taxonomy) — Wave 1。
 * 原因徽章 = 队列行 cause chip 与诊断结论的共享呈现面(IF-6:theme chips=D);
 * 词表/运营词/语调映射单一来源 = @/lib/gapCause(前端权威常量模块,
 * 与 backend/services/gap_taxonomy.py 同源语义);Wave 1 Track D 扩展
 * 新原因类时只改词表模块与本徽章消费,不改队列/侧板结构。
 */

import { gapCauseLabel, gapCauseTone, type GapCauseTone as CauseTone } from "@/lib/gapCause";

const CAUSE_TONE_STYLE: Record<CauseTone, { bg: string; fg: string }> = {
  critical: { bg: "color-mix(in srgb, var(--err) 12%, transparent)", fg: "var(--err)" },
  warning: { bg: "color-mix(in srgb, var(--warn) 15%, transparent)", fg: "var(--warn)" },
  accent: { bg: "color-mix(in srgb, var(--acc) 12%, transparent)", fg: "var(--acc)" },
  // U-14 六新类语调:参考 PNG 权威中 检索异常/生成异常/引用异常=淡彩紫;
  // 主题 token 无紫色,唯一字面量(#7c3aed=violet-600)即参考词表语义色。
  violet: { bg: "color-mix(in srgb, #7c3aed 12%, transparent)", fg: "#7c3aed" },
  neutral: { bg: "color-mix(in srgb, var(--t3) 15%, transparent)", fg: "var(--t2)" },
};

/** 原因徽章:data-gap-type 恒为权威机器值;运营词为忠实映射(lib/gapCause)。 */
export function CauseBadge({ missType }: { missType?: string | null }) {
  const tone = gapCauseTone(missType);
  const style = CAUSE_TONE_STYLE[tone];
  return (
    <span
      data-gap-cause-badge
      data-gap-type={missType ?? "未分类"}
      className="inline-flex items-center whitespace-nowrap rounded px-2 py-0.5 text-[12px] font-medium"
      style={{ background: style.bg, color: style.fg }}
    >
      {gapCauseLabel(missType)}
    </span>
  );
}
