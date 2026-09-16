import { describe, it, expect } from "vitest";
import { bucketOfDocument, isRetiredLifecycle } from "./dataSourceLifecycle";

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
