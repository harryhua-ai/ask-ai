import { describe, it, expect } from "vitest";
import { attentionReasonClasses, bannerActionsOf } from "./dataSourceOps";

/**
 * Issue #113:横幅分类真相 —— Needs Attention 必须区分「可修复缺席」与
 * 「范围外排除行」(include_dirs/file_types 等政策范围外;存在性未知),
 * repair-all 不得再把自己呈现为修不好的行的动作。
 * R2 修正(A REQUEST_CHANGES):范围外排除 ≠ 文件物理丢失 —— 文案/计数
 * 不得标注确定性丢失;物理缺失在显式退休时由服务端逐行验证。
 */

describe("bannerActionsOf(Issue #113 AC2 横幅动作分类)", () => {
  it("全部为范围外孤儿(179/179 生产事件形态)⇒ 不呈现修复,呈现退休", () => {
    const actions = bannerActionsOf({ attentionCount: 179, orphanCount: 179 });
    expect(actions.showRepair).toBe(false);
    expect(actions.repairCount).toBe(0);
    expect(actions.showRetire).toBe(true);
    expect(actions.orphanCount).toBe(179);
  });

  it("混合 ⇒ 修复/退休双动作,计数如实拆分", () => {
    const actions = bannerActionsOf({ attentionCount: 182, orphanCount: 179 });
    expect(actions.showRepair).toBe(true);
    expect(actions.repairCount).toBe(3);
    expect(actions.showRetire).toBe(true);
    expect(actions.orphanCount).toBe(179);
  });

  it("零孤儿 ⇒ 维持既有单修复动作(行为不变)", () => {
    const actions = bannerActionsOf({ attentionCount: 5, orphanCount: 0 });
    expect(actions.showRepair).toBe(true);
    expect(actions.repairCount).toBe(5);
    expect(actions.showRetire).toBe(false);
  });

  it("无需处理 ⇒ 双动作都不呈现", () => {
    const actions = bannerActionsOf({ attentionCount: 0, orphanCount: 0 });
    expect(actions.showRepair).toBe(false);
    expect(actions.showRetire).toBe(false);
  });

  it("孤儿计数钳制在 attention 计数内(后端真值不一致时不越界呈现)", () => {
    const actions = bannerActionsOf({ attentionCount: 2, orphanCount: 179 });
    expect(actions.orphanCount).toBe(2);
    expect(actions.repairCount).toBe(0);
    expect(actions.showRepair).toBe(false);
  });
});

describe("attentionReasonClasses(Issue #113 孤儿原因行)", () => {
  it("孤儿计数 > 0 ⇒ 呈现范围外孤儿原因行(不可修复语义)", () => {
    const lines = attentionReasonClasses({ missing_candidate: 179 }, 179, 179);
    expect(lines.some((l) => l.includes("范围外") && l.includes("179"))).toBe(true);
  });

  it("范围外排除文案不宣称「文件已丢失」(R2:存在性未知,退休前服务端验证)", () => {
    const lines = attentionReasonClasses({ missing_candidate: 5 }, 5, 5);
    const orphanLine = lines.find((l) => l.includes("范围外"));
    expect(orphanLine).toBeTruthy();
    expect(orphanLine).not.toContain("已丢失");
    expect(orphanLine).toContain("存在性未知");
    expect(orphanLine).toContain("验证物理缺失");
  });

  it("孤儿为零 ⇒ 不新增原因行(既有呈现不变)", () => {
    const lines = attentionReasonClasses({ missing_candidate: 3 }, 3, 0);
    expect(lines.some((l) => l.includes("范围外"))).toBe(false);
    expect(lines.length).toBe(1);
  });
});
