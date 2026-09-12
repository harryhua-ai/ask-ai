/**
 * v1.6.3 B1(KB-OPS-V163-002):运营呈现映射模块 @/lib/dataSourceOps 行为测试。
 *
 * 冻结纪律:
 * - 所有状态/原因/时间映射只消费**后端权威值**(documents 聚合投影、
 *   last_sync_*、/sync-health overall、sync_runs/sync_log、index_generations);
 * - 禁止前端重判健康/归因/生命周期;无证据 → 显式「待分类/—」,不编造。
 */

import { describe, it, expect } from "vitest";
import {
  relativeTime,
  operatorStateOf,
  attentionReasonClasses,
  humanizeInterval,
  buildSyncActivity,
  type AttentionSummaryItem,
} from "@/lib/dataSourceOps";
import type { SyncRun } from "@/types/api";

const NOW = new Date("2026-09-13T12:00:00Z");

function isoAgo(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe("relativeTime(人性化主时间,精确时间由调用方以 title 保留)", () => {
  it("null/非法输入 → null(调用方呈现 —,不编造)", () => {
    expect(relativeTime(null, NOW)).toBeNull();
    expect(relativeTime("not-a-date", NOW)).toBeNull();
  });

  it("刚刚 / 分钟 / 小时 / 天 / 个月分层", () => {
    expect(relativeTime(isoAgo(30), NOW)).toBe("刚刚");
    expect(relativeTime(isoAgo(5 * 60), NOW)).toBe("5分钟前");
    expect(relativeTime(isoAgo(2 * 3600), NOW)).toBe("2小时前");
    expect(relativeTime(isoAgo(3 * 86400), NOW)).toBe("3天前");
    expect(relativeTime(isoAgo(45 * 86400), NOW)).toBe("2个月前");
  });

  it("超过 2 个月退回精确日期(避免失真)", () => {
    expect(relativeTime(isoAgo(100 * 86400), NOW)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("operatorStateOf(操作者状态 = 后端权威值的呈现映射,非前端重判)", () => {
  const base = {
    enabled: true,
    lastSyncStatus: "success" as string | null,
    attentionCount: 0 as number | null,
    syncHealthOverall: "HEALTHY" as string | null,
  };

  it("禁用源 → 已禁用(后端 enabled 权威)", () => {
    const s = operatorStateOf({ ...base, enabled: false });
    expect(s.label).toBe("已禁用");
    expect(s.tone).toBe("disabled");
  });

  it("最近同步失败(后端 last_sync_status=failed)→ 同步失败", () => {
    const s = operatorStateOf({ ...base, lastSyncStatus: "failed" });
    expect(s.label).toBe("同步失败");
    expect(s.tone).toBe("failed");
  });

  it("attention_count>0(权威聚合投影)→ 需处理", () => {
    const s = operatorStateOf({ ...base, attentionCount: 3 });
    expect(s.label).toBe("需处理");
    expect(s.tone).toBe("attention");
  });

  it("/sync-health overall=ACTION_REQUIRED → 需处理", () => {
    const s = operatorStateOf({ ...base, syncHealthOverall: "ACTION_REQUIRED" });
    expect(s.label).toBe("需处理");
  });

  it("中间态:RECOVERING/STALE/PARTIAL → 恢复中/过期/部分(amber)", () => {
    expect(operatorStateOf({ ...base, syncHealthOverall: "RECOVERING" }).tone).toBe("intermediate");
    expect(operatorStateOf({ ...base, syncHealthOverall: "STALE" }).label).toBe("过期");
    expect(operatorStateOf({ ...base, syncHealthOverall: "PARTIAL" }).tone).toBe("intermediate");
  });

  it("证据不足(EMPTY_*/INSUFFICIENT_DATA)→ 待分类,不伪装正常", () => {
    for (const overall of ["EMPTY_UNEXPECTED", "EMPTY_EXPECTED", "INSUFFICIENT_DATA"]) {
      const s = operatorStateOf({ ...base, syncHealthOverall: overall });
      expect(s.label).toBe("待分类");
      expect(s.tone).toBe("unclassified");
    }
  });

  it("健康 + 零需处理 → 正常", () => {
    const s = operatorStateOf({ ...base });
    expect(s.label).toBe("正常");
    expect(s.tone).toBe("ok");
  });

  it("EXCLUDED → 已排除(outline)", () => {
    const s = operatorStateOf({ ...base, syncHealthOverall: "EXCLUDED" });
    expect(s.label).toBe("已排除");
  });

  it("无任何证据 → 待分类(不默认健康)", () => {
    const s = operatorStateOf({
      enabled: true,
      lastSyncStatus: null,
      attentionCount: null,
      syncHealthOverall: null,
    });
    expect(s.label).toBe("待分类");
    expect(s.tone).toBe("unclassified");
  });

  it("删除生命周期 delete_failed → 删除失败(权威 lifecycle_state)", () => {
    const s = operatorStateOf({ ...base, lifecycleState: "delete_failed" });
    expect(s.label).toBe("删除失败");
    expect(s.tone).toBe("failed");
  });
});

describe("attentionReasonClasses(需处理原因摘要 = 权威生命周期计数的投影)", () => {
  it("逐类投影,只列非零类,不发明引用校验等无权威语义", () => {
    const lines = attentionReasonClasses(
      { missing_candidate: 2, discovered: 0, superseded: 1, deleted: 0 },
      3, // missing 2 + active 悬挂 1
    );
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain("2 项源内容缺失");
    expect(lines[0]).toContain("缺席宽限");
    expect(lines[1]).toContain("1 项现行版本缺失");
  });

  it("discovered 类单独成行", () => {
    const lines = attentionReasonClasses({ discovered: 4 }, 4);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("4 项已发现");
    expect(lines[0]).toContain("尚未灌入");
  });

  it("attention=0 → 空摘要", () => {
    expect(attentionReasonClasses({ active: 5 }, 0)).toEqual([]);
  });
});

describe("humanizeInterval(同步周期人性化,原文兜底)", () => {
  it("小时/分钟", () => {
    expect(humanizeInterval("24h")).toBe("每 24 小时");
    expect(humanizeInterval("1h")).toBe("每 1 小时");
    expect(humanizeInterval("30m")).toBe("每 30 分钟");
  });
  it("无法解析 → 原文(不编造)", () => {
    expect(humanizeInterval("60")).toBe("60");
    expect(humanizeInterval("")).toBe("—");
  });
});

function mkRun(over: Partial<SyncRun> & { id: number }): SyncRun {
  return {
    source_id: "s",
    triggered_by: "cron",
    status: "completed",
    started_at: isoAgo(3600),
    ...over,
  } as SyncRun;
}

describe("buildSyncActivity(异常优先活动时间线;常规无变更压缩)", () => {
  it("失败运行为红色异常事件,携带错误摘要", () => {
    const { events } = buildSyncActivity(
      [mkRun({ id: 1, status: "failed", error_summary: "sitemap 请求超时", started_at: isoAgo(600) })],
      [],
      NOW,
    );
    const failed = events.find((e) => e.tone === "red");
    expect(failed?.title).toContain("同步失败");
    expect(JSON.stringify(failed?.meta)).toContain("sitemap 请求超时");
  });

  it("业务结果 partial → amber 部分成功;有变更成功 → green;进行中 → 信息事件", () => {
    const { events } = buildSyncActivity(
      [
        mkRun({ id: 2, status: "completed", sync_log: { status: "partial", items_new: 0, chunks_written: 5, items_deleted: 0, items_unchanged: 3, error_detail: null }, started_at: isoAgo(600) }),
        mkRun({ id: 3, status: "completed", sync_log: { status: "success", items_new: 2, chunks_written: 9, items_deleted: 1, items_unchanged: 0, error_detail: null }, started_at: isoAgo(1200) }),
        mkRun({ id: 4, status: "running", started_at: isoAgo(60) }),
      ],
      [],
      NOW,
    );
    expect(events.find((e) => e.tone === "amber")?.title).toContain("部分成功");
    expect(events.find((e) => e.tone === "green")?.title).toContain("同步完成");
    expect(events.find((e) => e.tone === "info")?.title).toContain("同步进行中");
  });

  it("常规无变更成功运行被压缩成组,不逐条刷屏", () => {
    const runs = [
      mkRun({ id: 10, status: "completed", sync_log: { status: "success", items_new: 0, chunks_written: 0, items_deleted: 0, items_unchanged: 12, error_detail: null }, started_at: isoAgo(3600) }),
      mkRun({ id: 11, status: "completed", sync_log: { status: "success", items_new: 0, chunks_written: 0, items_deleted: 0, items_unchanged: 12, error_detail: null }, started_at: isoAgo(7200) }),
      mkRun({ id: 12, status: "completed", sync_log: { status: "success", items_new: 0, chunks_written: 0, items_deleted: 0, items_unchanged: 12, error_detail: null }, started_at: isoAgo(10800) }),
    ];
    const { events, routineGroup } = buildSyncActivity(runs, [], NOW);
    expect(routineGroup?.count).toBe(3);
    expect(events.find((e) => e.kind === "routine-group")).toBeTruthy();
    // 无变更运行不逐条成卡
    expect(events.filter((e) => e.kind === "run" && e.tone === "gray")).toHaveLength(0);
  });

  it("生成失败为红色事件;时间线按时间倒序,异常不因排序被淹没", () => {
    const { events } = buildSyncActivity(
      [mkRun({ id: 20, status: "completed", sync_log: { status: "success", items_new: 1, chunks_written: 2, items_deleted: 0, items_unchanged: 0, error_detail: null }, started_at: isoAgo(300) })],
      [
        {
          id: "g1",
          ordinal: 8,
          status: "failed",
          doc_count: 0,
          chunk_count: 0,
          failure: { error: "embedder 返回 0 向量" },
          created_at: isoAgo(120),
          ready_at: null,
          activated_at: null,
          withdrawn_at: null,
          retired_at: null,
          gc_eligible_at: null,
          purged_at: null,
        },
      ],
      NOW,
    );
    const genFail = events.find((e) => e.tone === "red");
    expect(genFail?.title).toContain("索引生成");
    expect(genFail?.title).toContain("#8");
    const times = events.filter((e) => e.timeIso).map((e) => new Date(e.timeIso as string).getTime());
    expect(times.length).toBeGreaterThan(1);
    expect(times[0]).toBeGreaterThan(times[1]); // 倒序(最新在前)
    // 异常(红色)事件位于时间线首位(异常优先)
    expect(events[0].tone).toBe("red");
  });
});

describe("AttentionSummaryItem 形状(与后端投影契约一致)", () => {
  it("逐源桶聚合字段齐全", () => {
    const item: AttentionSummaryItem = {
      source_id: "s",
      ledger_total: 6,
      current_count: 3,
      serving_count: 5,
      retired_count: 1,
      attention_count: 2,
      lifecycle_counts: { active: 3, missing_candidate: 2, superseded: 1 },
    };
    expect(item.attention_count).toBe(item.ledger_total - item.current_count - item.retired_count);
  });
});
