import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ===========================================================================
// #59 G1 — 回答缺口队列空态四态区分(C2 聚类陈旧/不可用解释 + C3 空态视觉区分)
//
// 契约(Implementation Contract / gap matrix G1,artifact agent/59 @ c5329c5):
// - 空态必须按 客户端筛选真值 + 服务端 availability 真值 分支为四种互斥状态,
//   以 data-gap-empty-state={filtered|zero|no-data|stale} 机器可读标注;
// - no-data(聚类总数 0)不得暗示「无缺口」:可能尚未执行聚类,或最近一次
//   聚类未发现缺口(不发明刷新溯源,不区分两者);
// - stale(分类覆盖上界早于窗口起点)琥珀色陈旧横幅,不暗示无缺口;
// - filtered 保留既有文案 + 扩大时间范围提示;zero = 全部时间+无筛选真实零态;
// - 不得制造零、不得重加趋势/分布、不得引入 refresh/resolve 控件。
// ===========================================================================

const { mockAnswerGaps } = vi.hoisted(() => ({
  mockAnswerGaps: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, fetchAnswerGaps: mockAnswerGaps };
});

import AnswerGapsTab from "@/pages/analytics/AnswerGapsTab";

/** GET /tech/answer-gaps 投影形状 mock(空队列基线;availability 为 #59 G1 新增可选真值)。 */
function payload(overrides: Record<string, unknown> = {}) {
  return {
    items: [],
    total: 0,
    page: 1,
    size: 10,
    miss_type_summary: {},
    availability: { gap_clusters_total: 4, classification_covered_through: null },
    ...overrides,
  };
}

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AnswerGapsTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function emptyStateEl(): HTMLElement | null {
  return document.querySelector("[data-gap-empty-state]");
}

async function expectEmptyState(): Promise<HTMLElement> {
  return waitFor(() => {
    const el = emptyStateEl();
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
}

afterEach(() => {
  cleanup();
  mockAnswerGaps.mockReset();
});

describe("AnswerGapsTab 空态四态区分(#59 G1)", () => {
  it("no-data:聚类总数 0 → 暂无缺口聚类证据(不暗示无缺口,不与筛选空态混同)", async () => {
    mockAnswerGaps.mockResolvedValue(
      payload({
        total: 0,
        availability: { gap_clusters_total: 0, classification_covered_through: null },
      }),
    );
    renderTab();
    const el = await expectEmptyState();
    expect(el.getAttribute("data-gap-empty-state")).toBe("no-data");
    const text = el.textContent ?? "";
    expect(text).toContain("暂无缺口聚类证据");
    expect(text).toContain("尚未执行聚类");
    // 不得制造零、不得暗示无缺口、不得复用单一混同文案
    expect(text).not.toContain("当前没有答案缺口");
    expect(text).not.toContain("当前筛选条件下无答案缺口证据");
  });

  it("stale:分类覆盖上界早于窗口起点 → 陈旧横幅(琥珀语义,不暗示无缺口)", async () => {
    mockAnswerGaps.mockResolvedValue(
      payload({
        total: 0,
        availability: {
          gap_clusters_total: 4,
          classification_covered_through: "2026-08-25T00:00:00+00:00",
        },
      }),
    );
    renderTab();
    const el = await expectEmptyState();
    expect(el.getAttribute("data-gap-empty-state")).toBe("stale");
    const text = el.textContent ?? "";
    expect(text).toContain("聚类证据覆盖至");
    expect(text).toContain("2026-08-25");
    expect(text).toContain("此后数据尚未聚合");
    expect(text).not.toContain("暂无缺口聚类证据");
    expect(text).not.toContain("当前没有答案缺口");
  });

  it("filtered:窗口收窄且覆盖新鲜 → 既有筛选空态文案 + 扩大时间范围提示", async () => {
    // 覆盖上界在 7d 窗口起点之内(1 天前)→ 非陈旧,窗口内真实无近期证据
    const fresh = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    mockAnswerGaps.mockResolvedValue(
      payload({
        total: 0,
        availability: {
          gap_clusters_total: 4,
          classification_covered_through: fresh,
        },
      }),
    );
    renderTab();
    const el = await expectEmptyState();
    expect(el.getAttribute("data-gap-empty-state")).toBe("filtered");
    const text = el.textContent ?? "";
    expect(text).toContain("当前筛选条件下无答案缺口证据");
    expect(text).toContain("可尝试扩大时间范围");
    expect(text).not.toContain("聚类证据覆盖至");
    expect(text).not.toContain("暂无缺口聚类证据");
  });

  it("zero:全部时间 + 无筛选而队列为空 → 真实零态(与其余三态互斥且视觉可分)", async () => {
    const fresh = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    mockAnswerGaps.mockResolvedValue(
      payload({
        total: 0,
        availability: {
          gap_clusters_total: 4,
          classification_covered_through: fresh,
        },
      }),
    );
    renderTab();
    await expectEmptyState();
    // 切到 全部时间(all):无 status/cause/q 筛选,队列仍空而聚类总数 >0 → zero
    fireEvent.change(screen.getByLabelText("分析时间窗"), {
      target: { value: "all" },
    });
    await waitFor(() => {
      expect(emptyStateEl()?.getAttribute("data-gap-empty-state")).toBe("zero");
    });
    const text = emptyStateEl()?.textContent ?? "";
    expect(text).toContain("当前没有答案缺口");
    expect(text).not.toContain("可尝试扩大时间范围");
    expect(text).not.toContain("暂无缺口聚类证据");
    expect(text).not.toContain("聚类证据覆盖至");
  });
});
