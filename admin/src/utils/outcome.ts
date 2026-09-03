/**
 * 阶段⑯:Admin 对话 outcome 呈现分类(纯函数,可单测)。
 *
 * Canonical semantic model(产品契约冻结):
 * - SUCCESS(answered / social_reply)→「已回答」
 * - REFUSAL(no_evidence / off_topic,reject_short)→「拒答」
 * - FAILURE(empty_generation / provider_error / stream_interrupted,
 *   trace type=generation_error)→「生成失败」
 * - DECLINED(budget_declined)→「服务繁忙」
 *
 * Refusal != Failure:二者 is_answered 都是 False,但 trace 血统不同
 * (reject_short vs generation_error),Admin 不得再把失败统一显示成拒答。
 */

export interface OutcomeBadge {
  label: string;
  /** 对应 Badge variant(success / destructive / warning) */
  tone: "success" | "warning" | "destructive";
}

export function deriveOutcome(
  isAnswered: boolean,
  traceType?: string | null,
): OutcomeBadge {
  if (isAnswered) return { label: "已回答", tone: "success" };
  switch (traceType) {
    case "generation_error":
      return { label: "生成失败", tone: "destructive" };
    case "budget_declined":
      return { label: "服务繁忙", tone: "warning" };
    case "reject_short":
      return { label: "拒答", tone: "warning" };
    default:
      // 旧数据无 trace / 未知类型:保持基线「拒答」兜底,不虚构 outcome
      return { label: "拒答", tone: "warning" };
  }
}
