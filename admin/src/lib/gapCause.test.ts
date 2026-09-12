import { describe, it, expect } from "vitest";
import {
  gapCauseLabel,
  gapCauseTone,
  gapCauseConclusion,
  gapCauseAvailable,
  gapStatusLabel,
  GAP_CAUSE_OPTIONS,
} from "./gapCause";

/**
 * v1.6.3 B2 — 权威原因分类映射测试(KB-OPS-V163-002 §5.3)。
 *
 * 纪律:UI 只能在权威数据支持时呈现原因;映射必须是后端分类语义的忠实
 * 运营词转述(召回空/召回不足/reject/low 来自 GET /analytics/coverage-gaps
 * 的权威分类,语义见 backend/api/admin/analytics.py docstring);
 * 无权威分类 → 未分类,绝不发明 taxonomy(知识缺失/服务知识不完整等
 * 恢复设计词只映射到语义一致的权威分类上)。
 */
describe("gapCause 权威原因映射(KB-OPS-V163-002 §5.3)", () => {
  it("召回空 → 知识缺失(已回答但未检索到任何知识来源)", () => {
    expect(gapCauseLabel("召回空")).toBe("知识缺失");
    expect(gapCauseTone("召回空")).toBe("critical");
    expect(gapCauseAvailable("召回空")).toBe(true);
    expect(gapCauseConclusion("召回空")).toContain("未检索到");
  });

  it("召回不足 → 服务知识不完整(有来源但覆盖不完整)", () => {
    expect(gapCauseLabel("召回不足")).toBe("服务知识不完整");
    expect(gapCauseAvailable("召回不足")).toBe(true);
    expect(gapCauseConclusion("召回不足")).toContain("不完整");
  });

  it("reject → 拒答(未回答);low → 低相关(置信度低)", () => {
    expect(gapCauseLabel("reject")).toBe("拒答");
    expect(gapCauseLabel("low")).toBe("低相关");
    expect(gapCauseAvailable("reject")).toBe(true);
    expect(gapCauseAvailable("low")).toBe(true);
  });

  it("无权威分类(null/undefined/未分类)→ 未分类 + 证据不可用结论,不虚构", () => {
    expect(gapCauseLabel(null)).toBe("未分类");
    expect(gapCauseLabel(undefined)).toBe("未分类");
    expect(gapCauseLabel("未分类")).toBe("未分类");
    expect(gapCauseAvailable(null)).toBe(false);
    expect(gapCauseAvailable("未分类")).toBe(false);
    expect(gapCauseConclusion("未分类")).toContain("证据不可用");
    expect(gapCauseConclusion(null)).toContain("证据不可用");
  });

  it("未知机器类型原样透传(不假装翻译),但按不可用处理", () => {
    expect(gapCauseLabel("some_future_type")).toBe("some_future_type");
    expect(gapCauseAvailable("some_future_type")).toBe(false);
  });

  it("筛选选项 = 权威分类全集 + 未分类;不含恢复设计中无权威支撑的词(内容过期/引用异常等)", () => {
    const values = GAP_CAUSE_OPTIONS.map((o) => o.value);
    for (const v of ["reject", "low", "召回空", "召回不足", "未分类"]) {
      expect(values).toContain(v);
    }
    expect(values).not.toContain("内容过期");
    expect(values).not.toContain("引用异常");
    expect(values).not.toContain("生成异常");
  });
});

describe("gapStatus 状态映射(权威 open/resolved → 运营状态)", () => {
  it("open → 需要处理;resolved → 已解决", () => {
    expect(gapStatusLabel("open")).toBe("需要处理");
    expect(gapStatusLabel("resolved")).toBe("已解决");
  });

  it("v1.6.3 无 观察中 状态:未知状态原样透传,不映射为观察中", () => {
    expect(gapStatusLabel("observing")).toBe("observing");
    expect(gapStatusLabel("observing")).not.toBe("观察中");
  });
});
