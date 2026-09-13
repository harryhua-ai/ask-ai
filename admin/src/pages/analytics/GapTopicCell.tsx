/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track F**(证据聚合)
 * Wave 1 专属 —— 队列「问题 / 主题」列单元格。
 *
 * Wave 1 实现(track-f-contract U-19;matrix-TI TI-12):
 * - 主题式标题:确定性主题真值存在(后端权威派生投影
 *   GET /tech/answer-gaps/{id}/topic,跨问句公共因子,零 LLM 零词表)→
 *   主行渲染主题短语(data-gap-topic)+ 副行回显代表问句;
 * - 无主题(不可派生)→ 回退代表问句为主行(合同:无主题回退代表问句),
 *   副行保持既有样例问句呈现,既有行为逐字保留为回退路径。
 * 零前端猜测/零 hard-coded topic:主题值仅来自后端权威派生。
 * 数据经 useQuery 自取(Integration 壳零编辑;加载/失败态保持回退渲染,
 * 不闪不造)。
 */

import { useQuery } from "@tanstack/react-query";
import type { AnswerGapItem } from "@/lib/api/techInsight";
import { fetchGapTopic } from "@/lib/api/techEvidence";
import { TableCell } from "@/components/ui/table";

export function GapTopicCell({ gap }: { gap: AnswerGapItem }) {
  const topicQuery = useQuery({
    queryKey: ["gap-topic", gap.id],
    queryFn: () => fetchGapTopic(gap.id),
    retry: false,
    staleTime: 30_000,
  });

  const topic = topicQuery.data?.topic ?? null;
  const samples = gap.sample_questions.filter(
    (s) => s !== gap.representative_question,
  );

  return (
    <TableCell>
      {topic ? (
        <>
          <div
            data-gap-topic
            className="truncate text-[13px] font-semibold text-[var(--t1)]"
          >
            {topic}
          </div>
          <div
            data-gap-question
            className="mt-0.5 truncate text-[12px] text-[var(--t3)]"
          >
            {gap.representative_question}
          </div>
        </>
      ) : (
        <>
          <div
            data-gap-question
            className="truncate text-[13px] font-semibold text-[var(--t1)]"
          >
            {gap.representative_question}
          </div>
          {samples.length > 0 && (
            <div
              data-gap-sample
              className="mt-0.5 truncate text-[12px] text-[var(--t3)]"
            >
              {samples[0]}
            </div>
          )}
        </>
      )}
    </TableCell>
  );
}
