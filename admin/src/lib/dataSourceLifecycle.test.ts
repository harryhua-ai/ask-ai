import { describe, it, expect } from "vitest";
import {
  bucketOfDocument,
  isRetiredLifecycle,
  linkStateLabel,
  servingProjectionNote,
} from "./dataSourceLifecycle";

/** Issue #83:退役生命周期(superseded/deleted)不得提供 repair 入口。 */
describe("isRetiredLifecycle 退役判定(Issue #83)", () => {
  it("superseded 与 deleted(墓碑)= 退役", () => {
    expect(isRetiredLifecycle("superseded")).toBe(true);
    expect(isRetiredLifecycle("deleted")).toBe(true);
  });

  it("可服务/宽限生命周期非退役(repair 入口保留)", () => {
    expect(isRetiredLifecycle("active")).toBe(false);
    expect(isRetiredLifecycle("missing_candidate")).toBe(false);
    expect(isRetiredLifecycle("discovered")).toBe(false);
  });

  it("未知/缺席状态非退役(原文透传语义,不静默改判)", () => {
    expect(isRetiredLifecycle("some_new_state")).toBe(false);
    expect(isRetiredLifecycle(null)).toBe(false);
    expect(isRetiredLifecycle(undefined)).toBe(false);
  });

  it("与 bucketOfDocument retired 桶同一词表(两映射不漂移)", () => {
    for (const lifecycle of [
      "active",
      "missing_candidate",
      "discovered",
      "superseded",
      "deleted",
    ]) {
      expect(isRetiredLifecycle(lifecycle)).toBe(
        bucketOfDocument({ lifecycle, serving: false }) === "retired",
      );
    }
  });
});

/** Issue #55:Inspector link_state 呈现词表(#48 冻结词表的展示映射)。 */
describe("linkStateLabel(Issue #55)", () => {
  it("四态各有确定文案,不发明新状态", () => {
    expect(linkStateLabel("external")).toBe("可点击(外部直达)");
    expect(linkStateLabel("none")).toBe("无外部目的地");
    expect(linkStateLabel("private")).toBe("非公开,不提供外链");
    expect(linkStateLabel("stale")).toBe("可能已失效,不保证可达");
  });

  it("缺席/未知状态显式呈现,不伪造", () => {
    expect(linkStateLabel(null)).toBe("不可用");
    expect(linkStateLabel(undefined)).toBe("不可用");
    expect(linkStateLabel("some_new_state")).toBe("不可用");
  });
});

/** Issue #55:退役文档的 chunk 投影是审计口径,不得呈现为「不完整/健康」。 */
describe("servingProjectionNote(Issue #55)", () => {
  it("退役(superseded/deleted)= 审计口径注记", () => {
    expect(servingProjectionNote("deleted")).toMatch(/审计/);
    expect(servingProjectionNote("superseded")).toMatch(/审计/);
  });

  it("可服务生命周期无注记(呈现既有在服/不完整语义)", () => {
    expect(servingProjectionNote("active")).toBeNull();
    expect(servingProjectionNote("missing_candidate")).toBeNull();
    expect(servingProjectionNote("discovered")).toBeNull();
  });
});
