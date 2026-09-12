import { describe, expect, it } from "vitest";
import {
  bucketCountsOf,
  bucketLabel,
  bucketOfDocument,
  bucketVariant,
  generationStatusLabel,
  generationStatusVariant,
  lifecycleLabel,
  lifecycleVariant,
  notServingReason,
  servingTimestamp,
} from "@/lib/dataSourceLifecycle";

// 合同:单一权威前端映射模块 —— L 轴/生成状态 → 中文运营标签 + badge 语义;
// 运营三桶(Current/Needs Attention/Retired)逐态映射;原因措辞唯一出处。
// 本文件证明逐态映射可解释性与「后端无此记录」缺席语义。

describe("L 轴标签与 badge 语义(逐态)", () => {
  it.each([
    ["discovered", "已发现未灌入"],
    ["active", "在服"],
    ["superseded", "已被接替"],
    ["missing_candidate", "源中缺失(宽限中)"],
    ["deleted", "已删除(墓碑)"],
  ])("%s → %s", (state, label) => {
    expect(lifecycleLabel(state)).toBe(label);
  });

  it("未知状态原文透传(不编造语义)", () => {
    expect(lifecycleLabel("some-future-state")).toBe("some-future-state");
    expect(lifecycleLabel(null)).toBe("未知状态");
  });

  it.each([
    ["active", "success"],
    ["missing_candidate", "warning"],
    ["superseded", "outline"],
    ["deleted", "outline"],
    ["discovered", "secondary"],
  ])("%s badge 变体 = %s", (state, variant) => {
    expect(lifecycleVariant(state)).toBe(variant);
  });
});

describe("生成状态标签与 badge 语义(逐态,P 轴无 ACTIVE)", () => {
  it.each([
    ["pending", "等待构建"],
    ["processing", "构建中"],
    ["ready", "构建完成"],
    ["failed", "构建失败"],
    ["retired", "已退役"],
  ])("%s → %s", (status, label) => {
    expect(generationStatusLabel(status)).toBe(label);
  });

  it.each([
    ["ready", "success"],
    ["failed", "destructive"],
    ["pending", "secondary"],
    ["processing", "warning"],
    ["retired", "outline"],
  ])("%s badge 变体 = %s", (status, variant) => {
    expect(generationStatusVariant(status)).toBe(variant);
  });

  it("未知生成状态原文透传", () => {
    expect(generationStatusLabel("mystery")).toBe("mystery");
  });
});

describe("运营三桶映射(逐态可解释)", () => {
  const base = {
    source_id: "src",
    title: "t",
    url: "u",
    lifecycle: "active",
    serving: true,
    current_version_seq: 1 as number | null,
    superseded_by: null as string | null,
    deleted_at: null as string | null,
  };

  it.each([
    ["active", "current"],
    ["missing_candidate", "attention"],
    ["superseded", "retired"],
    ["deleted", "retired"],
    ["discovered", "attention"],
  ])("lifecycle=%s → 桶 %s", (lifecycle, bucket) => {
    expect(bucketOfDocument({ ...base, lifecycle })).toBe(bucket);
  });

  it("active 但现行版本悬挂 → attention(不可证在服)", () => {
    expect(
      bucketOfDocument({ ...base, lifecycle: "active", serving: false, current_version_seq: null }),
    ).toBe("attention");
  });

  it("桶标签与 badge 变体", () => {
    expect(bucketLabel("current")).toBe("当前在服");
    expect(bucketLabel("attention")).toBe("需要关注");
    expect(bucketLabel("retired")).toBe("已退役");
    expect(bucketVariant("current")).toBe("success");
    expect(bucketVariant("attention")).toBe("warning");
    expect(bucketVariant("retired")).toBe("outline");
  });

  it("三桶计数:Current=active∧可解析;在服含宽限;Retired=superseded+deleted;余项=attention", () => {
    const counts = bucketCountsOf({
      lifecycle_counts: { active: 3, missing_candidate: 2, superseded: 4, deleted: 1, discovered: 1 },
      current_count: 2, // active 3 中 1 个悬挂
      serving_count: 4, // active 可解析 2 + missing_candidate 2
      ledger_total: 11,
    });
    expect(counts).toEqual({ current: 2, attention: 4, retired: 5 });
  });
});

describe("非在服/风险原因(权威字段;缺席 = 后端无此记录)", () => {
  const base = {
    source_id: "src",
    title: "t",
    url: "u",
    lifecycle: "active",
    serving: true,
    current_version_seq: 1 as number | null,
    superseded_by: null as string | null,
    superseded_at: null as string | null,
    deleted_at: null as string | null,
  };

  it("在服条目无原因(null)", () => {
    expect(notServingReason(base)).toBeNull();
  });

  it("missing_candidate:宽限在服原因", () => {
    const reason = notServingReason({ ...base, lifecycle: "missing_candidate" });
    expect(reason).toContain("缺失");
    expect(reason).toContain("宽限");
  });

  it("superseded:接替者 + 时间(权威字段)", () => {
    const reason = notServingReason({
      ...base,
      lifecycle: "superseded",
      superseded_by: "src/main/new.md",
      superseded_at: "2026-09-01T00:00:00+00:00",
    });
    expect(reason).toContain("src/main/new.md");
    expect(reason).toContain("2026-09-01");
  });

  it("superseded 无接替者记录 → 显示 后端无此记录", () => {
    const reason = notServingReason({ ...base, lifecycle: "superseded" });
    expect(reason).toContain("后端无此记录");
  });

  it("deleted:墓碑时间", () => {
    const reason = notServingReason({
      ...base,
      lifecycle: "deleted",
      deleted_at: "2026-09-02T08:00:00+00:00",
    });
    expect(reason).toContain("删除");
    expect(reason).toContain("2026-09-02");
  });

  it("discovered:仅发现未灌入", () => {
    expect(notServingReason({ ...base, lifecycle: "discovered" })).toContain("未灌入");
  });

  it("active 悬挂:现行版本缺席显式表达为 后端无此记录", () => {
    const reason = notServingReason({
      ...base,
      lifecycle: "active",
      serving: false,
      current_version_seq: null,
    });
    expect(reason).toContain("后端无此记录");
  });

  it("在服时间戳:权威时间可用,缺席为 null(不虚构)", () => {
    expect(servingTimestamp("2026-09-03T00:00:00+00:00")).toBe("2026-09-03T00:00:00+00:00");
    expect(servingTimestamp(null)).toBeNull();
    expect(servingTimestamp(undefined)).toBeNull();
  });
});
