/** V1.6.3 Wave 1 Track A — S1/S2 fetch 参数构建单元断言(BC 前端接线,禁静默回退)。
 *
 * 冻结契约(§3.5 能力矩阵):
 * - S1 /tech/performance:共享窗状态接入,from/to 真实发送;all/任意窗以显式起止
 *   表达;禁依赖 range 未知名 → 静默 7d 回退(任意窗以显式起止表达)。
 * - S2 /analytics/source-health:硬编码 days=30 → 绑定共享窗(以解析后的
 *   from/to 请求);既有 days 位置参数调用方(useDataSources)保持兼容。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockApiFetch } = vi.hoisted(() => ({ mockApiFetch: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiFetch: mockApiFetch,
}));

import { fetchTechPerformance, fetchSourceHealth } from "@/lib/api/techInsight";

beforeEach(() => {
  mockApiFetch.mockReset();
  mockApiFetch.mockResolvedValue({});
});

describe("S1 fetchTechPerformance 参数构建(IF-7 全词表)", () => {
  it("命名窗:range=<名> + 解析后的 from/to 真实发送", async () => {
    await fetchTechPerformance("30d");
    const url = mockApiFetch.mock.calls[0][0] as string;
    expect(url.startsWith("/tech/performance?")).toBe(true);
    expect(url).toContain("range=30d");
    expect(url).toContain("from=");
    expect(url).toContain("to=");
  });

  it("all:以显式起止表达(2000-01-01 锚点 → now),不发送 range 名(禁未知名静默回退)", async () => {
    await fetchTechPerformance("all");
    const url = mockApiFetch.mock.calls[0][0] as string;
    expect(url).toContain("from=2000-01-01");
    expect(url).toContain("to=");
    expect(url).not.toContain("range=");
  });

  it("显式起止:from=起日 00:00,to=结束日全天含;不发送 range 名", async () => {
    await fetchTechPerformance("range:2026-09-01/2026-09-09");
    const url = decodeURIComponent(mockApiFetch.mock.calls[0][0] as string);
    expect(url).toContain("from=2026-09-01T00:00:00");
    expect(url).toContain("to=2026-09-09T23:59:59");
    expect(url).not.toContain("range=");
  });

  it("默认窗 = 7d", async () => {
    await fetchTechPerformance();
    const url = mockApiFetch.mock.calls[0][0] as string;
    expect(url).toContain("range=7d");
  });
});

describe("S2 fetchSourceHealth 参数绑定", () => {
  it("共享窗:以 from/to 请求(非 days=30 硬编码)", async () => {
    await fetchSourceHealth({ from: "2026-09-06T00:00:00", to: "2026-09-13T23:59:59" });
    const url = decodeURIComponent(mockApiFetch.mock.calls[0][0] as string);
    expect(url.startsWith("/analytics/source-health?")).toBe(true);
    expect(url).toContain("from=2026-09-06T00:00:00");
    expect(url).toContain("to=2026-09-13T23:59:59");
    expect(url).not.toContain("days=");
  });

  it("既有 days 位置参数调用保持兼容(useDataSources 零改动)", async () => {
    await fetchSourceHealth(30);
    const url = mockApiFetch.mock.calls[0][0] as string;
    expect(url).toBe("/analytics/source-health?days=30");
  });
});
