/**
 * 阶段⑯:Admin outcome 呈现分类纯函数。
 *
 * Refusal != Failure:is_answered=false 的对话按 trace 血统区分
 * 拒答(reject_short)/ 生成失败(generation_error)/ 服务繁忙(budget_declined),
 * 不得再把失败统一显示成「拒答」。
 */
import { describe, expect, it } from "vitest";

import { deriveOutcome } from "./outcome";

describe("deriveOutcome — Admin 对话 outcome 分类", () => {
  it("成功 → 已回答(success)", () => {
    expect(deriveOutcome(true, "rag")).toEqual({ label: "已回答", tone: "success" });
    expect(deriveOutcome(true, "social_reply")).toEqual({
      label: "已回答",
      tone: "success",
    });
    expect(deriveOutcome(true, undefined)).toEqual({ label: "已回答", tone: "success" });
  });

  it("generation_error → 生成失败(不再显示成拒答)", () => {
    // failure_kind(empty_generation/provider_error/stream_interrupted)由
    // trace_summary.failure_kind 单独下发;徽章按 trace type 判定
    expect(deriveOutcome(false, "generation_error")).toEqual({
      label: "生成失败",
      tone: "destructive",
    });
  });

  it("budget_declined → 服务繁忙(≠ 生成失败,≠ 拒答)", () => {
    expect(deriveOutcome(false, "budget_declined")).toEqual({
      label: "服务繁忙",
      tone: "warning",
    });
  });

  it("reject_short → 拒答", () => {
    expect(deriveOutcome(false, "reject_short")).toEqual({ label: "拒答", tone: "warning" });
  });

  it("无 trace/未知类型(旧数据)→ 拒答兜底,不虚构 outcome", () => {
    expect(deriveOutcome(false, undefined)).toEqual({ label: "拒答", tone: "warning" });
    expect(deriveOutcome(false, null)).toEqual({ label: "拒答", tone: "warning" });
    expect(deriveOutcome(false, "override")).toEqual({ label: "拒答", tone: "warning" });
  });
});
