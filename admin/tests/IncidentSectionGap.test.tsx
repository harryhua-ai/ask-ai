import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ===========================================================================
// Issue #58 r5 GAP_ONLY focused tests(矩阵 A1 PARTIAL + A4 MISSING 最小边界)
//
// B1(A1):失败行主行携带已取回权威字段的事实性 impact 短语 ——
//   生成失败:影响 N 篇文档 / M 块构建产物(计数>0 才呈现);
//   同步失败:第 k 次尝试 / 耗时 t 秒(字段存在才呈现);
//   raw 错误串/failure JSON 不回主行,仍只进折叠证据(details)。
// B2(A4):渲染层按 (sourceId, typeKey) 分组 —— 组头=最高严重度+最新时间+
//   ×N 徽章+组级下钻 href;组可展开,成员逐事件保留各自 evidence details
//   与独立 href;异源同类不并组;严重度优先排序不回退;头部诚实计数
//   「共 N 起 · 显示前 M」。仅在已取回 latest-N 上聚合(零新端点/零重算)。
// ===========================================================================

const { mockSyncIncidents, mockGenerationEvents } = vi.hoisted(() => ({
  mockSyncIncidents: vi.fn(),
  mockGenerationEvents: vi.fn(),
}));

vi.mock("@/lib/api/techInsight", () => ({
  fetchSyncIncidents: mockSyncIncidents,
  fetchGenerationEvents: mockGenerationEvents,
}));

import { IncidentSection } from "@/pages/analytics/IncidentSection";

const EMPTY_SYNC = {
  failed: { items: [], total: 0, page: 1, size: 10 },
  interrupted: { items: [], total: 0, page: 1, size: 10 },
};
const EMPTY_GEN = { items: [], total: 0 };

/** 同步运行权威字段 fixture(GET /sync-runs 形状)。 */
function syncRun(overrides: Record<string, unknown> = {}) {
  return {
    id: 101,
    source_id: "wiki-documents-local",
    triggered_by: "cron",
    request_id: 7,
    attempt: 2,
    recovery: false,
    status: "failed",
    started_at: "2026-09-10T02:00:00Z",
    finished_at: "2026-09-10T02:05:00Z",
    duration_seconds: 300,
    stage: "fetch",
    counters: {},
    consistency: null,
    execution_device: null,
    fallback_reason: null,
    fallback_detail: null,
    error_summary: "clone 失败:auth required",
    ingestion_skipped: false,
    sync_log: null,
    ...overrides,
  };
}

function syncPayload(
  failedItems: ReturnType<typeof syncRun>[],
  failedTotal?: number,
) {
  return {
    failed: {
      items: failedItems,
      total: failedTotal ?? failedItems.length,
      page: 1,
      size: 10,
    },
    interrupted: { items: [], total: 0, page: 1, size: 10 },
  };
}

/** 生成事件权威字段 fixture(GET /tech/generation-events 形状)。 */
function genEvent(overrides: Record<string, unknown> = {}) {
  return {
    generation_id: "11111111-1111-4111-8111-111111111111",
    ordinal: 1,
    source_id: "ne301-docs",
    status: "failed",
    severity: "error",
    doc_count: 3,
    chunk_count: 12,
    failure: { error: "doc build failures", docs: ["d1"] },
    reason_summary: "doc build failures",
    created_at: "2026-09-09T10:00:00Z",
    activated_at: null,
    retired_at: null,
    event_at: "2026-09-09T10:00:00Z",
    ...overrides,
  };
}

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <IncidentSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function renderWithIncidents(sync: unknown, gen: unknown) {
  mockSyncIncidents.mockResolvedValue(sync);
  mockGenerationEvents.mockResolvedValue(gen);
  renderSection();
  await screen.findByText("同步 / 索引 / 生成事件");
  await waitFor(() => {
    const settled =
      document.querySelector("[data-incident-list]") ||
      screen.queryByText("无同步 / 索引 / 生成失败事件");
    expect(settled).toBeTruthy();
  });
}

afterEach(() => {
  cleanup();
  mockSyncIncidents.mockReset();
  mockSyncIncidents.mockResolvedValue(EMPTY_SYNC);
  mockGenerationEvents.mockReset();
  mockGenerationEvents.mockResolvedValue(EMPTY_GEN);
});

mockSyncIncidents.mockResolvedValue(EMPTY_SYNC);
mockGenerationEvents.mockResolvedValue(EMPTY_GEN);

// ====================  B1(A1):失败行 impact 短语  ====================

describe("B1:失败行主行携带权威字段 impact 短语(raw 不回主行)", () => {
  it("generation_failed 主行含 影响 N 篇文档 / M 块构建产物;raw reason_summary 只在折叠证据", async () => {
    await renderWithIncidents(EMPTY_SYNC, { items: [genEvent()], total: 1 });
    const row = document.querySelector(
      '[data-incident-row][data-incident-type="generation_failed"]',
    ) as HTMLElement;
    expect(row).toBeTruthy();
    const note = row.querySelector("[data-incident-note]");
    expect(note).toBeTruthy();
    expect(note?.textContent).toContain("影响 3 篇文档");
    expect(note?.textContent).toContain("12 块构建产物");
    // raw 串不回主行(note 不含 raw;证据区折叠保留)
    expect(note?.textContent).not.toContain("doc build failures");
    const details = row.querySelector(
      "[data-incident-evidence]",
    ) as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("doc build failures");
  });

  it("计数为 0 时诚实缺省:不编造 0 计数短语", async () => {
    await renderWithIncidents(
      EMPTY_SYNC,
      { items: [genEvent({ chunk_count: 0 })], total: 1 },
    );
    const note = document.querySelector(
      '[data-incident-row][data-incident-type="generation_failed"] [data-incident-note]',
    );
    expect(note?.textContent).toContain("影响 3 篇文档");
    expect(note?.textContent).not.toContain("0 块");
  });

  it("sync_failed 主行含 第 k 次尝试 / 耗时 t 秒;raw error_summary 只在折叠证据", async () => {
    await renderWithIncidents(syncPayload([syncRun()]), undefined);
    const row = document.querySelector(
      '[data-incident-row][data-incident-type="sync_failed"]',
    ) as HTMLElement;
    expect(row).toBeTruthy();
    const note = row.querySelector("[data-incident-note]");
    expect(note).toBeTruthy();
    expect(note?.textContent).toContain("第 2 次尝试");
    expect(note?.textContent).toContain("耗时 300s");
    // raw 错误串不回主行
    expect(note?.textContent).not.toContain("clone 失败");
    const details = row.querySelector(
      "[data-incident-evidence]",
    ) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("clone 失败:auth required");
  });

  it("retired 行为不回归:运营摘要仍为 reason_summary,不掺 impact 短语", async () => {
    await renderWithIncidents(
      EMPTY_SYNC,
      {
        items: [
          genEvent({
            status: "retired",
            severity: "info",
            failure: null,
            reason_summary: "知识已从在服集撤出(被新一代接替)",
            event_at: "2026-09-12T10:00:00Z",
          }),
        ],
        total: 1,
      },
    );
    const row = document.querySelector(
      '[data-incident-row][data-incident-type="generation_retired"]',
    ) as HTMLElement;
    expect(row?.getAttribute("data-severity")).toBe("info");
    const note = row.querySelector("[data-incident-note]");
    expect(note?.textContent).toBe("知识已从在服集撤出(被新一代接替)");
    expect(note?.textContent).not.toContain("篇文档");
  });
});

// ====================  B2(A4):(sourceId, typeKey) 分组、可审计  ====================

describe("B2:同源同类多事件 ×N 分组,组内逐事件证据与 href 保留", () => {
  function threeSameSourceFailures() {
    return syncPayload([
      syncRun({
        id: 301,
        attempt: 3,
        started_at: "2026-09-13T02:00:00Z",
        duration_seconds: 420,
      }),
      syncRun({
        id: 202,
        attempt: 2,
        started_at: "2026-09-12T02:00:00Z",
        duration_seconds: 360,
      }),
      syncRun({
        id: 103,
        attempt: 1,
        started_at: "2026-09-11T02:00:00Z",
        duration_seconds: 300,
      }),
    ]);
  }

  it("3 条同源 sync_failed → 1 组:组头 ×N + 最高严重度 + 最新时间 + 组级下钻 href", async () => {
    await renderWithIncidents(threeSameSourceFailures(), undefined);
    // 组容器恰好 1 个,组头为唯一可见事件行(重复不挤占可见位)
    const groups = document.querySelectorAll("[data-incident-group]");
    expect(groups.length).toBe(1);
    const header = groups[0].querySelector(
      ":scope > [data-incident-row]",
    ) as HTMLElement;
    expect(header).toBeTruthy();
    expect(header.getAttribute("data-source-id")).toBe("wiki-documents-local");
    expect(header.getAttribute("data-severity")).toBe("error");
    expect(header.getAttribute("href")).toBe(
      `/data-sources/${encodeURIComponent("wiki-documents-local")}`,
    );
    // ×N 徽章 + 最新时间
    const count = header.querySelector("[data-incident-group-count]");
    expect(count?.textContent).toContain("×3");
    expect(header.textContent).toContain("9/13/2026");
  });

  it("组展开后成员逐事件保留:各自 href、severity、折叠 evidence(含各自 attempt)", async () => {
    await renderWithIncidents(threeSameSourceFailures(), undefined);
    const group = document.querySelector("[data-incident-group]") as HTMLElement;
    // 展开前成员不渲染(分组诚实聚合,不重复铺行)
    expect(
      group.querySelectorAll("[data-incident-group-members] [data-incident-row]").length,
    ).toBe(0);
    fireEvent.click(
      group.querySelector("[data-incident-group-toggle]") as HTMLElement,
    );
    await waitFor(() => {
      const members = group.querySelectorAll(
        "[data-incident-group-members] [data-incident-row]",
      );
      expect(members.length).toBe(3);
    });
    const members = Array.from(
      group.querySelectorAll("[data-incident-group-members] [data-incident-row]"),
    ) as HTMLElement[];
    // 每个成员:独立下钻 href + 各自折叠证据(逐事件可审计)
    for (const m of members) {
      expect(m.getAttribute("href")).toBe(
        `/data-sources/${encodeURIComponent("wiki-documents-local")}`,
      );
      const d = m.querySelector("[data-incident-evidence]") as HTMLDetailsElement;
      expect(d).toBeTruthy();
      expect(d.open).toBe(false);
    }
    const attempts = members.map(
      (m) =>
        (m.querySelector("[data-incident-evidence]") as HTMLElement).textContent,
    );
    expect(attempts.some((t) => t?.includes("attempt: 1"))).toBe(true);
    expect(attempts.some((t) => t?.includes("attempt: 2"))).toBe(true);
    expect(attempts.some((t) => t?.includes("attempt: 3"))).toBe(true);
    // 成员各自 impact 短语保留(B1 不因分组丢失)
    const notes = members.map((m) => m.querySelector("[data-incident-note]")?.textContent);
    expect(notes.some((t) => t?.includes("耗时 420s"))).toBe(true);
  });

  it("异源同类不并组:2 源各 1 条 + 第 3 源 2 条 → 2 个单例行 + 1 个 ×2 组", async () => {
    await renderWithIncidents(
      syncPayload([
        syncRun({ id: 1, source_id: "alpha-src" }),
        syncRun({ id: 2, source_id: "beta-src" }),
        syncRun({ id: 3, source_id: "gamma-src", started_at: "2026-09-13T02:00:00Z" }),
        syncRun({ id: 4, source_id: "gamma-src", started_at: "2026-09-12T02:00:00Z" }),
      ]),
      undefined,
    );
    expect(document.querySelectorAll("[data-incident-group]").length).toBe(1);
    const group = document.querySelector("[data-incident-group]") as HTMLElement;
    expect(group.getAttribute("data-source-id")).toBe("gamma-src");
    expect(
      group.querySelector("[data-incident-group-count]")?.textContent,
    ).toContain("×2");
    // 非重复事件仍为独立行(未被分组吞并);组只占一个可见位
    const slots = document.querySelectorAll("[data-incident-list] > *");
    expect(slots.length).toBe(3); // alpha 单例 + beta 单例 + gamma 组
    const singletonRows = document.querySelectorAll(
      "[data-incident-list] > [data-incident-row]",
    );
    expect(singletonRows.length).toBe(2);
    const sources = Array.from(singletonRows).map((r) =>
      r.getAttribute("data-source-id"),
    );
    expect(sources).toContain("alpha-src");
    expect(sources).toContain("beta-src");
  });

  it("严重度优先排序不回退:error 组先于更新的 info 单例行", async () => {
    await renderWithIncidents(
      threeSameSourceFailures(),
      {
        items: [
          genEvent({
            status: "retired",
            severity: "info",
            failure: null,
            reason_summary: "知识已从在服集撤出(被新一代接替)",
            source_id: "legacy-src",
            event_at: "2026-09-14T10:00:00Z",
          }),
        ],
        total: 1,
      },
    );
    const list = document.querySelector("[data-incident-list]") as HTMLElement;
    const first = list.firstElementChild as HTMLElement;
    expect(first.getAttribute("data-incident-group")).not.toBeNull();
    expect(first.getAttribute("data-severity")).toBe("error");
    const last = list.lastElementChild as HTMLElement;
    expect(last.getAttribute("data-incident-row")).not.toBeNull();
    expect(last.getAttribute("data-severity")).toBe("info");
  });

  it("头部诚实计数:共 N 起 · 显示前 M 起(权威 payload total,防截断静默)", async () => {
    await renderWithIncidents(syncPayload([syncRun(), syncRun({ id: 2 }), syncRun({ id: 3 })], 5), undefined);
    const total = document.querySelector("[data-incident-total]");
    expect(total).toBeTruthy();
    expect(total?.textContent).toContain("共 5 起");
    expect(total?.textContent).toContain("显示前 3 起");
  });
});
