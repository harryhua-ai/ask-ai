/**
 * v1.6.3 B2 — Answer Gaps 权威原因/状态 → 运营词映射(KB-OPS-V163-002 §5.3/§5.4)。
 *
 * 纪律(合同 Forbidden:frontend 自造 cause 分类 / 发明状态):
 * - 权威分类只有 GET /analytics/coverage-gaps(及 /tech/answer-gaps 同源投影)
 *   产出的 miss_type 词表:reject / low / 召回空 / 召回不足(语义见
 *   backend/api/admin/analytics.py:`reject`=未回答拒答;`low`=已回答但最新
 *   置信度<0.6;`召回空`=已回答但检索零来源;`召回不足`=已回答且有来源);
 * - 恢复设计的运营词(知识缺失/服务知识不完整等)只映射到语义一致的权威
 *   分类上,属忠实转述;无权威分类 → 未分类,绝不发明新 taxonomy;
 * - 状态词表 = 权威 open|resolved;OBSERVING/观察中 是 v1.6.3 NOT authorized
 *   的新状态语义,不实现、不伪造(未知状态原样透传)。
 */

export type GapCauseTone = "critical" | "warning" | "accent" | "neutral";

/** 权威 miss_type → 运营标签(data 属性始终保留机器原始值)。 */
const GAP_CAUSE_LABELS: Record<string, string> = {
  // 已回答但未检索到任何知识来源 → 现有知识中没有可支撑内容
  "召回空": "知识缺失",
  // 已回答且有来源但未解决需求 → 在服知识覆盖不完整
  "召回不足": "服务知识不完整",
  reject: "拒答",
  low: "低相关",
  "未分类": "未分类",
};

/** 权威 miss_type → 语义色(critical 红 / warning 琥珀 / accent 蓝 / neutral 灰)。 */
const GAP_CAUSE_TONES: Record<string, GapCauseTone> = {
  "召回空": "critical",
  "召回不足": "accent",
  reject: "neutral",
  low: "warning",
  "未分类": "neutral",
};

/**
 * 诊断结论:权威分类语义的忠实转述(不猜测根因,只复述后端分类依据)。
 * 不可用时明确 证据不可用。
 */
const GAP_CAUSE_CONCLUSIONS: Record<string, string> = {
  "召回空": "已生成回答,但未检索到任何知识来源——现有知识中没有可支撑该主题的内容(知识缺失)。",
  "召回不足": "已检索到部分来源并生成回答,但服务知识覆盖不完整,回答仍无法满足用户需求。",
  reject: "该主题的提问未被回答(拒答),用户未获得有效回答。",
  low: "已生成回答,但最新置信度低于 0.6,回答与问题的相关性较低。",
};

const UNAVAILABLE_CONCLUSION = "证据不可用:该缺口暂无权威原因分类,系统不做推断。";

export function gapCauseLabel(missType?: string | null): string {
  if (missType == null || missType === "" || missType === "未分类") return "未分类";
  return GAP_CAUSE_LABELS[missType] ?? missType;
}

export function gapCauseTone(missType?: string | null): GapCauseTone {
  if (missType == null || missType === "" || missType === "未分类") return "neutral";
  return GAP_CAUSE_TONES[missType] ?? "neutral";
}

/** 是否存在权威原因分类(决定诊断结论面板的 authoritative/unavailable 形态)。 */
export function gapCauseAvailable(missType?: string | null): boolean {
  return (
    missType != null && missType !== "" && missType !== "未分类" && missType in GAP_CAUSE_LABELS
  );
}

export function gapCauseConclusion(missType?: string | null): string {
  if (!gapCauseAvailable(missType)) return UNAVAILABLE_CONCLUSION;
  return GAP_CAUSE_CONCLUSIONS[missType as string] ?? UNAVAILABLE_CONCLUSION;
}

/**
 * 筛选选项 = 权威分类全集 + 未分类。
 * 恢复设计中无权威支撑的词(内容过期/引用异常/生成异常/内容冲突/检索异常)
 * 不得进入选项——后端无该分类真相。
 */
export const GAP_CAUSE_OPTIONS: { value: string; label: string }[] = [
  { value: "召回空", label: "知识缺失" },
  { value: "召回不足", label: "服务知识不完整" },
  { value: "reject", label: "拒答" },
  { value: "low", label: "低相关" },
  { value: "未分类", label: "未分类" },
];

/** 权威状态(open|resolved)→ 运营状态词。观察中 NOT authorized,未知透传。 */
export function gapStatusLabel(status: string): string {
  if (status === "open") return "需要处理";
  if (status === "resolved") return "已解决";
  return status;
}
