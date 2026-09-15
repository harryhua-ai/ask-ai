/**
 * #71 Authoritative membership currency — Admin presentation mapping tests.
 *
 * 冻结纪律(与 dataSourceOps.test.ts 一致):只消费后端持久权威真值
 * (DataSource.membership_status 等),前端零重判。已知成员漂移未解决时,
 * 数据源列表/详情徽章不得呈现「正常」。
 */

import { describe, it, expect } from "vitest";
import { operatorStateOf } from "@/lib/dataSourceOps";

describe("operatorStateOf(#71 成员货币真值呈现)", () => {
  const base = {
    enabled: true,
    lastSyncStatus: "success" as string | null,
    attentionCount: 0 as number | null,
    syncHealthOverall: "HEALTHY" as string | null,
  };

  it("membership_status=stale(已知漂移未解决)→ 成员漂移,绝非 正常", () => {
    const s = operatorStateOf({ ...base, membershipStatus: "stale" });
    expect(s.key).toBe("membership_drift");
    expect(s.label).toBe("成员漂移");
    expect(s.tone).not.toBe("ok");
  });

  it("membership_status=failed(对账失败)→ 对账失败,绝非 正常", () => {
    const s = operatorStateOf({ ...base, membershipStatus: "failed" });
    expect(s.key).toBe("membership_reconciliation_failed");
    expect(s.label).toBe("对账失败");
    expect(s.tone).not.toBe("ok");
  });

  it("drift 优先于 attention(更精确的真值优先呈现)", () => {
    const s = operatorStateOf({ ...base, membershipStatus: "stale", syncHealthOverall: "ACTION_REQUIRED" });
    expect(s.key).toBe("membership_drift");
  });

  it("membership_status=unsupported / null → 不改变既有呈现(不越权降级)", () => {
    expect(operatorStateOf({ ...base, membershipStatus: "unsupported" }).key).toBe("ok");
    expect(operatorStateOf({ ...base }).key).toBe("ok");
  });

  it("membership_status=current → 正常(真值健康)", () => {
    expect(operatorStateOf({ ...base, membershipStatus: "current" }).label).toBe("正常");
  });
});
