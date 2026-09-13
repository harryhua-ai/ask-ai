/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track F**(证据聚合)
 * Wave 1 专属 —— 队列「问题 / 主题」列单元格。
 * Wave 1(track-f-contract「主题列渲染+回退代表问句」U-19)在本文件内实现
 * 主题短语渲染(现内容=回退代表问句,逐字保留为回退路径),不编辑
 * AnswerGapsTab(Integration 壳仅消费稳定 props=gap)。
 * 队列行用户/源卡 meta(track-f U-17 源卡)同为 Track F 将来区域,
 * 于 F 自有文件落地;本文件零新列/零新语义(§3.0.1 四零约束)。
 */

import type { AnswerGapItem } from "@/lib/api/techInsight";
import { TableCell } from "@/components/ui/table";

export function GapTopicCell({ gap }: { gap: AnswerGapItem }) {
  return (
    <TableCell>
      <div
        data-gap-question
        className="truncate text-[13px] font-semibold text-[var(--t1)]"
      >
        {gap.representative_question}
      </div>
      {gap.sample_questions.filter(
        (s) => s !== gap.representative_question,
      ).length > 0 && (
        <div
          data-gap-sample
          className="mt-0.5 truncate text-[12px] text-[var(--t3)]"
        >
          {
            gap.sample_questions.filter(
              (s) => s !== gap.representative_question,
            )[0]
          }
        </div>
      )}
    </TableCell>
  );
}
