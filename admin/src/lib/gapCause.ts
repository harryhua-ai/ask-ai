/**
 * v1.6.3 B2 — Answer Gaps 权威原因/状态 → 运营词映射(KB-OPS-V163-002 §5.3/§5.4)。
 *
 * 纪律(合同 Forbidden:frontend 自造 cause 分类 / 发明状态):
 * - 权威分类只有 GET /analytics/coverage-gaps(及 /tech/answer-gaps 同源投影)
 *   产出的 miss_type 词表。v1.6.3 Wave 1 U-14(IF-2 冻结)起为参考词表
 *   (TI-09)全集:reject / low / 召回空 / 召回不足 + 六新类(内容过期/
 *   检索异常/生成异常/引用异常/内容冲突/内容缺失);每类均有后端确定性
 *   证据规则(语义见 backend/services/gap_taxonomy.py 与 analytics.py
 *   classify_gap_miss_types),前端只消费后端权威分类,零 keyword 猜测;
 * - 运营词(知识缺失/服务知识不完整/六新类参考词)只映射到语义一致的权威
 *   分类上,属忠实转述;无权威分类 → 未分类,绝不发明新 taxonomy;
 * - 状态词表 = 权威 open|resolved;OBSERVING/观察中 是 v1.6.3 NOT authorized
 *   的新状态语义,不实现、不伪造(未知状态原样透传)。
 *
 * Ownership(IF-6):本文件=前端词表单一真相源;cause 词表面=Track D
 * (本注释以下至 gapStatusLabel 之前),status 呈现面=Track E(不动)。
 */

export type GapCauseTone = "critical" | "warning" | "accent" | "violet" | "neutral";

/** 权威 miss_type → 运营标签(data 属性始终保留机器原始值)。 */
const GAP_CAUSE_LABELS: Record<string, string> = {
  // 已回答但未检索到任何知识来源 → 现有知识中没有可支撑内容
  "召回空": "知识缺失",
  // 已回答且有来源但未解决需求 → 在服知识覆盖不完整
  "召回不足": "服务知识不完整",
  reject: "拒答",
  low: "低相关",
  // ---- U-14 六新类(TI-09 参考词表逐词;机器值=权威字面)----
  // 已回答且所引文档内容更新早于会话超过 180 天(内容时间真相)
  "内容过期": "内容过期",
  // 已回答有来源但检索未达最低有效召回(检索异常证据)
  "检索异常": "检索异常",
  // 回答生成失败:generation_error trace(generation failure 真相)
  "生成异常": "生成异常",
  // 答案引用编号越界(引用一致性违例;引用需要重新验证)
  "引用异常": "引用异常",
  // 同会话同时引用 superseded 文档与其接替者(多源冲突真相)
  "内容冲突": "内容冲突",
  // 未回答 + 零来源 + 检索零候选(知识缺失变体)
  "内容缺失": "内容缺失",
  "未分类": "未分类",
};

/** 权威 miss_type → 语义色(critical 红 / warning 琥珀 / accent 蓝 / neutral 灰)。 */
const GAP_CAUSE_TONES: Record<string, GapCauseTone> = {
  "召回空": "critical",
  "召回不足": "accent",
  reject: "neutral",
  low: "warning",
  // ---- U-14 六新类语义色(参考 PNG 权威:内容过期/内容冲突=琥珀,
  // 检索异常/生成异常/引用异常=紫,内容缺失=红系)----
  "内容过期": "warning",
  "检索异常": "violet",
  "生成异常": "violet",
  "引用异常": "violet",
  "内容冲突": "warning",
  "内容缺失": "critical",
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
  // ---- U-14 六新类:逐条复述后端证据规则(IF-2),不做根因推断 ----
  "内容过期":
    "已生成回答并引用了知识来源,但所引文档的内容最后更新时间早于本次提问超过 180 天——内容已过期,回答可能基于过时信息。",
  "检索异常":
    "已生成回答并引用了来源,但检索阶段未达到最低有效召回标准——检索过程存在异常,结果覆盖不完整。",
  "生成异常": "回答生成失败(供应商错误/空生成/流中断),用户未获得有效回答。",
  "引用异常":
    "已生成回答,但答案中的引用编号超出实际来源数量——引用一致性异常,引用需要重新验证。",
  "内容冲突":
    "已生成回答,但同一次回答同时引用了同一来源的新旧两个版本——多源内容存在冲突,结论可能互相矛盾。",
  "内容缺失":
    "提问未被回答:检索阶段在知识库中零候选,没有可支撑该问题的内容(内容缺失)。",
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
 * 筛选选项 = 权威分类全集 + 未分类(U-14:六新类已有后端证据规则,
 * 经 IF-2 词表进入权威全集;前端不发明,只消费后端分类)。
 */
export const GAP_CAUSE_OPTIONS: { value: string; label: string }[] = [
  { value: "召回空", label: "知识缺失" },
  { value: "召回不足", label: "服务知识不完整" },
  { value: "reject", label: "拒答" },
  { value: "low", label: "低相关" },
  { value: "内容过期", label: "内容过期" },
  { value: "检索异常", label: "检索异常" },
  { value: "生成异常", label: "生成异常" },
  { value: "引用异常", label: "引用异常" },
  { value: "内容冲突", label: "内容冲突" },
  { value: "内容缺失", label: "内容缺失" },
  { value: "未分类", label: "未分类" },
];

/** 权威状态(open|resolved)→ 运营状态词。观察中 NOT authorized,未知透传。 */
export function gapStatusLabel(status: string): string {
  if (status === "open") return "需要处理";
  if (status === "resolved") return "已解决";
  return status;
}
