/**
 * v1.6.3 Wave 1 Track D — U-14 扩展原因词表前端呈现测试。
 *
 * 冻结契约(track-d-contract + IF-2):
 * - filter 选项 = 权威全集(TI-09 参考词表 8 词 + 拒答/低相关)+ 未分类;
 * - 新类徽章 = 淡彩语法 + data-gap-type 机器值恒存,运营词为忠实映射;
 * - 诊断结论新类 = 权威形态(复述后端证据规则),零 keyword 前端分类;
 * - 前端只消费后端权威分类(gapCause 单一词表源,与 gap_taxonomy 同源)。
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { GapCauseFilter } from "@/pages/analytics/GapCauseFilter";
import { CauseBadge } from "@/pages/analytics/CauseBadge";
import { DiagnosisConclusion } from "@/pages/analytics/DiagnosisConclusion";
import {
  GAP_CAUSE_OPTIONS,
  gapCauseAvailable,
  gapCauseConclusion,
  gapCauseLabel,
  gapCauseTone,
} from "@/lib/gapCause";
import type { AnswerGapItem } from "@/lib/api/techInsight";

/** TI-09 参考词表(权威 PNG 逐词):队列原因列全词表。 */
const REFERENCE_CAUSE_WORDS = [
  "知识缺失",
  "服务知识不完整",
  "内容过期",
  "检索异常",
  "生成异常",
  "引用异常",
  "内容冲突",
  "内容缺失",
];

/** U-14 六新类机器值(= 后端 gap_taxonomy 权威字面)。 */
const NEW_CAUSE_TYPES = [
  "内容过期",
  "检索异常",
  "生成异常",
  "引用异常",
  "内容冲突",
  "内容缺失",
];

function makeGap(missType: string): AnswerGapItem {
  return {
    id: "aaaaaaaa-0000-4000-8000-00000000d001",
    cluster_type: "gap",
    representative_question: "WD-U14 问句",
    sample_questions: [],
    question_count: 1,
    impacted_answer_count: 1,
    status: "open",
    miss_type: missType,
    miss_type_breakdown: { [missType]: 1 },
    last_seen_at: "2026-09-13T10:00:00+00:00",
    period_start: null,
    period_end: null,
    created_at: "2026-09-13T09:00:00+00:00",
  };
}

describe("U-14 词表单一源(gapCause)", () => {
  it("filter 选项 = 权威全集 + 未分类(六新类进入权威全集)", () => {
    const values = GAP_CAUSE_OPTIONS.map((o) => o.value);
    for (const t of NEW_CAUSE_TYPES) {
      expect(values).toContain(t);
    }
    // 旧 4 类(机器值)+ 未分类保留
    expect(values).toEqual([
      "召回空",
      "召回不足",
      "reject",
      "low",
      ...NEW_CAUSE_TYPES,
      "未分类",
    ]);
  });

  it("六新类运营标签 = 参考词表逐词(忠实映射,不发明)", () => {
    for (const t of NEW_CAUSE_TYPES) {
      expect(gapCauseLabel(t)).toBe(t);
    }
  });

  it("六新类语义色调:内容过期/内容冲突=warning,检索/生成/引用异常=violet,内容缺失=critical", () => {
    expect(gapCauseTone("内容过期")).toBe("warning");
    expect(gapCauseTone("内容冲突")).toBe("warning");
    expect(gapCauseTone("检索异常")).toBe("violet");
    expect(gapCauseTone("生成异常")).toBe("violet");
    expect(gapCauseTone("引用异常")).toBe("violet");
    expect(gapCauseTone("内容缺失")).toBe("critical");
  });

  it("六新类均为权威分类(诊断结论 authoritative 形态)且结论非空", () => {
    for (const t of NEW_CAUSE_TYPES) {
      expect(gapCauseAvailable(t)).toBe(true);
      const conclusion = gapCauseConclusion(t);
      expect(conclusion).not.toBe("");
      expect(conclusion).not.toContain("证据不可用");
    }
  });
});

describe("U-14 GapCauseFilter 全词表选项", () => {
  it("下拉 = 全部原因 + 参考词表 8 词 + 拒答/低相关 + 未分类", () => {
    const { container } = render(<GapCauseFilter value="" onChange={() => {}} />);
    const select = container.querySelector("[data-filter-cause]") as HTMLSelectElement;
    expect(select).toBeTruthy();
    const words = Array.from(select.options).map((o) => o.textContent);
    expect(words[0]).toBe("全部原因");
    for (const word of REFERENCE_CAUSE_WORDS) {
      expect(words).toContain(word);
    }
    expect(words).toContain("拒答");
    expect(words).toContain("低相关");
    expect(words).toContain("未分类");
  });
});

describe("U-14 CauseBadge 新类徽章", () => {
  it.each(NEW_CAUSE_TYPES)("徽章 %s:data-gap-type 机器值恒存 + 参考词标签", (missType) => {
    const { container } = render(<CauseBadge missType={missType} />);
    const badge = container.querySelector("[data-gap-cause-badge]") as HTMLElement;
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("data-gap-type")).toBe(missType);
    expect(badge.textContent).toBe(missType);
    // 淡彩语法:color-mix 半透明底
    expect(badge.style.background).toContain("color-mix");
  });

  it("violet 淡彩紫(参考 PNG 语义色)用于检索/生成/引用异常", () => {
    const { container } = render(<CauseBadge missType="检索异常" />);
    const badge = container.querySelector("[data-gap-cause-badge]") as HTMLElement;
    // jsdom 将 #7c3aed 归一化为 rgb 形式
    expect(badge.style.color).toBe("rgb(124, 58, 237)");
  });
});

describe("U-14 DiagnosisConclusion 新类权威结论", () => {
  it.each(NEW_CAUSE_TYPES)("%s:authoritative 形态 + 徽章 + 证据规则转述", (missType) => {
    const { container } = render(<DiagnosisConclusion gap={makeGap(missType)} />);
    const panel = container.querySelector("[data-panel-conclusion]") as HTMLElement;
    expect(panel).toBeTruthy();
    expect(panel.getAttribute("data-conclusion-kind")).toBe("authoritative");
    const badge = panel.querySelector("[data-gap-cause-badge]") as HTMLElement;
    expect(badge.getAttribute("data-gap-type")).toBe(missType);
    expect(panel.textContent).toContain(missType);
    expect(panel.textContent).not.toContain("证据不可用");
  });
});
