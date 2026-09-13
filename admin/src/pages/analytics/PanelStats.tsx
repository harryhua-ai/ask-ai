/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track F**(证据聚合)
 * Wave 1 专属 —— 侧板 meta 计数区(data-panel-stats)。
 * Wave 1(track-f-contract「meta 行三项计数并排:相关提问·受影响回答·
 * 涉及用户」U-17)在本文件内扩展用户聚合计数与源卡(meta/源卡面板文件),
 * 不编辑 GapPanel/AnswerGapsTab(Integration 壳仅消费稳定 props=gap;
 * 聚合数据可循 GapPanel convQuery 的 useQuery 模式自取,聚合窗=IF-7)。
 * v1.6.3 既有两项计数+最近发生逐字保留;「涉及用户」为零实现
 * (无权威用户聚合证据,诚实缺席)。
 */

import type { AnswerGapItem } from "@/lib/api/techInsight";
import { relTime } from "./relTime";

export function PanelStats({ gap }: { gap: AnswerGapItem }) {
  return (
    <div data-panel-stats className="mt-2 text-[12px] text-[var(--t2)]">
      {gap.question_count} 次相关提问 · {gap.impacted_answer_count} 次受影响回答
      <div className="mt-0.5 text-[var(--t3)]">
        最近发生:{relTime(gap.last_seen_at)}
      </div>
    </div>
  );
}
