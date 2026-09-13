/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track D**(原因分类学)
 * Wave 1 专属 —— 诊断结论卡(data-panel-conclusion)呈现与结论语义。
 * Wave 1 扩展随 IF-2 词表(track-d-contract「原因分类是诊断结论的唯一真相」),
 * 经 @/lib/gapCause 与 backend/services/gap_taxonomy.py 同源挂载;扩展时只改
 * 本文件,不编辑 GapPanel/AnswerGapsTab(Integration 壳仅消费稳定 props=gap)。
 * v1.6.3 既有边界逐字保留:仅当权威原因分类存在时呈权威结论,否则明确
 * 「证据不可用」;零新词表值、零新语义(§3.0.1 四零约束)。
 */

import type { AnswerGapItem } from "@/lib/api/techInsight";
import { gapCauseAvailable, gapCauseConclusion } from "@/lib/gapCause";
import { CauseBadge } from "./CauseBadge";

export function DiagnosisConclusion({ gap }: { gap: AnswerGapItem }) {
  const hasCause = gapCauseAvailable(gap.miss_type);

  return (
    <section
      data-panel-conclusion
      data-conclusion-kind={hasCause ? "authoritative" : "unavailable"}
      className="rounded-md p-3"
      style={{
        background: hasCause
          ? "color-mix(in srgb, var(--err) 8%, transparent)"
          : "color-mix(in srgb, var(--t3) 10%, transparent)",
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
          style={{ background: hasCause ? "var(--err)" : "var(--t3)" }}
        >
          !
        </span>
        <span className="text-[13px] font-medium text-[var(--t1)]">诊断结论</span>
        <CauseBadge missType={gap.miss_type} />
      </div>
      <p className="mt-2 text-[12px] leading-5 text-[var(--t2)]">
        {gapCauseConclusion(gap.miss_type)}
      </p>
    </section>
  );
}
