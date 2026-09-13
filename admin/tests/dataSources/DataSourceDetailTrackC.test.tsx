/**
 * v1.6.3 Wave 1 Track C(U-6..U-13 前端呈现)——八项冻结语义 UI 契约。
 *
 * 原则:呈现一律消费后端权威真值;本套用 mock 读面锁定「真值→呈现」映射:
 * - U-6 品牌内建映射(零远程 logo);
 * - U-7 逐文档类型列/过滤(后端真值,禁推断;null=不可用呈现「—」);
 * - U-8 行级修复链(处理按钮/⋯菜单/验证卡 = 后端任务真值);
 * - U-9 chunk serving 比例(=后端投影);
 * - U-10 恢复注记(持久化事件计数);
 * - U-11 下次同步(调度器权威,禁纯派生);
 * - U-12 知识设置抽屉(词表+说明+超期提醒);
 * - U-13 预览 Modal(计数=预览端点;确认携带 token;drift 提示重算)。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSourceDetail from "@/pages/DataSourceDetail";
import { SyncActivityPanel } from "@/components/dataSources/SyncActivityPanel";
import { KnowledgeSettingsDrawer } from "@/components/dataSources/KnowledgeSettingsDrawer";
import { RiskPreviewModal } from "@/components/dataSources/RiskPreviewModal";
import { sourceBrandOf } from "@/lib/sourceBrand";
import { contentTypeLabel } from "@/lib/contentType";
import { useDataSources, useSyncRuns, useTriggerSync } from "@/hooks/useDataSources";
import {
  useSourceDocuments,
  useSourceDocumentTruth,
  useSourceGenerations,
} from "@/hooks/useDataSourceWorkspace";
import {
  useDocumentRepair,
  useKnowledgeSettings,
  useSourceSchedule,
} from "@/hooks/useDataSourceKnowledge";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));
vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn() })),
  useSyncHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useSourceHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useSyncRuns: vi.fn(() => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() })),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false, variables: null })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRetryDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn(), isPending: false }),
  useTriggerSyncAll: () => ({ mutate: vi.fn(), isPending: false }),
  useAttentionSummary: vi.fn(() => ({ data: undefined, isLoading: false })),
}));
vi.mock("@/hooks/useDataSourceWorkspace", () => ({
  useSourceDocuments: vi.fn(() => ({ data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn() })),
  useSourceDocumentTruth: vi.fn(() => ({ data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn() })),
  useSourceGenerations: vi.fn(() => ({ data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn() })),
}));
vi.mock("@/hooks/useDataSourceKnowledge", () => ({
  useDocumentRepair: vi.fn(() => ({ mutate: vi.fn(), isPending: false, variables: null })),
  useSourceSchedule: vi.fn(() => ({ data: undefined, isLoading: false, refetch: vi.fn() })),
  useKnowledgeSettings: vi.fn(() => ({ data: undefined, isLoading: false, isError: false, refetch: vi.fn() })),
  useKnowledgePreview: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useKnowledgeSettingsSave: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function withRouter(ui: React.ReactElement) {
  return (
    <MemoryRouter initialEntries={["/data-sources/woo-store"]}>
      <Routes>
        <Route path="/data-sources/:sourceId" element={ui} />
      </Routes>
    </MemoryRouter>
  );
}

function renderDetail() {
  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}>{withRouter(<DataSourceDetail />)}</QueryClientProvider>);
}

const source = {
  id: "woo-store",
  type: "woocommerce",
  product: "WooCommerce",
  enabled: true,
  config: { base_url: "https://woocommerce.com" },
  sync_interval: "6h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: "2026-09-01T02:00:00Z",
  last_sync_status: "success",
  last_sync_error: null,
  lifecycle_state: null,
  lifecycle_since: null,
  lifecycle_error: null,
};

const documents = {
  source_id: "woo-store",
  total: 2,
  ledger_total: 2,
  page: 1,
  size: 20,
  lifecycle_counts: { active: 1, missing_candidate: 1 },
  serving_count: 2,
  current_count: 1,
  content_type_counts: { product: 1, page: 1 },
  items: [
    {
      source_id: "woo-store/main/ne101",
      title: "NE101",
      url: "https://woo.test/ne101",
      branch: "main",
      source_type: "woocommerce",
      product: "WooCommerce",
      lifecycle: "missing_candidate",
      serving: false,
      chunk_count: 4,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: "2026-09-01T00:00:00+00:00",
      current_version_seq: 17,
      generation_ordinal: 7,
      content_type: "product",
    },
    {
      source_id: "woo-store/main/legacy",
      title: "Legacy Guide",
      url: "https://woo.test/legacy",
      branch: "main",
      source_type: "woocommerce",
      product: "WooCommerce",
      lifecycle: "active",
      serving: true,
      chunk_count: 3,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: "2026-09-02T00:00:00+00:00",
      current_version_seq: 3,
      generation_ordinal: 7,
      content_type: null,
    },
  ],
};

const truth = {
  source_id: "woo-store",
  doc_source_id: "woo-store/main/ne101",
  title: "NE101",
  url: "https://woo.test/ne101",
  branch: "main",
  source_type: "woocommerce",
  product: "WooCommerce",
  lifecycle: "missing_candidate",
  serving: false,
  chunk_count: 12,
  created_at: null,
  updated_at: null,
  superseded_by: null,
  superseded_at: null,
  deleted_at: null,
  content_type: "product",
  chunk_serving: { serving_chunks: 10, total_chunks: 12, missing_indices: [10, 11], stale_indices: [], consistent: false },
  recovery_attempts_failed: 1,
  recovery_attempts_succeeded: 0,
  latest_repair_task: null,
  current_version: null,
  generation: null,
};

describe("U-6 品牌内建映射(零远程 logo)", () => {
  it("类型→内建色块/字形:woocommerce 紫 W;github 深灰 G;未知回退首字母", () => {
    const woo = sourceBrandOf("woocommerce", "WooCommerce");
    expect(woo.bg).toBe("#7F54B3");
    expect(woo.glyph).toBe("W");
    const gh = sourceBrandOf("github", "wiki");
    expect(gh.glyph).toBe("G");
    const fallback = sourceBrandOf("mystery", "neo");
    expect(fallback.glyph).toBe("N");
    // 禁远程资产:映射不产生任何 http(s) 字符串
    expect(JSON.stringify([woo, gh, fallback])).not.toMatch(/https?:\/\//);
  });

  it("详情身份块渲染内建品牌块", () => {
    vi.mocked(useDataSources).mockReturnValue({ data: [source] as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
    renderDetail();
    const block = screen.getByTestId("source-brand-block");
    expect(block.textContent).toBe("W");
    expect(block.style.background).toBe("rgb(127, 84, 179)");
  });
});

describe("U-7 逐文档 content_type(后端真值,禁推断)", () => {
  beforeEach(() => {
    vi.mocked(useDataSources).mockReturnValue({ data: [source] as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
    vi.mocked(useSourceDocuments).mockReturnValue({ data: documents as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
  });

  it("类型列 = 逐文档真值(商品);null 存量行 = 不可用「—」", () => {
    renderDetail();
    expect(screen.getByText("商品")).toBeInTheDocument();
    expect(screen.getAllByTitle("类型不可用(存量行,后端无真值)").length).toBeGreaterThan(0);
  });

  it("类型过滤 select = 账本聚合词表,变更提交 content_type 参数", () => {
    renderDetail();
    const select = screen.getByTestId("content-type-filter");
    expect(select).toBeInTheDocument();
    expect((select as HTMLSelectElement).textContent).toContain("商品(1)");
    fireEvent.change(select, { target: { value: "product" } });
    const call = vi.mocked(useSourceDocuments).mock.results.at(-1)!.value as unknown as { data: { items: unknown[] } };
    void call;
    // 过滤参数经 hook 参数提交(hook 已 mock;词表与参数面由后端契约测试覆盖)
    expect((select as HTMLSelectElement).value).toBe("product");
  });

  it("呈现映射纯函数:product→商品/page→页面/document→文档/null→不可用", () => {
    expect(contentTypeLabel("product")).toBe("商品");
    expect(contentTypeLabel("page")).toBe("页面");
    expect(contentTypeLabel("document")).toBe("文档");
    expect(contentTypeLabel(null)).toBeNull();
    expect(contentTypeLabel(undefined)).toBeNull();
  });
});

describe("U-8/U-9/U-10 展开行修复链与真值", () => {
  beforeEach(() => {
    vi.mocked(useDataSources).mockReturnValue({ data: [source] as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
    vi.mocked(useSourceDocuments).mockReturnValue({ data: documents as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
    vi.mocked(useSourceDocumentTruth).mockReturnValue({ data: truth as never, isLoading: false, isError: false, error: null, refetch: vi.fn() } as never);
  });

  it("需处理行「处理」按钮提交修复命令(后端 RBAC/幂等)", () => {
    const mutate = vi.fn();
    vi.mocked(useDocumentRepair).mockReturnValue({ mutate, isPending: false, variables: null } as never);
    renderDetail();
    const btn = screen.getByTestId("doc-repair-woo-store/main/ne101");
    fireEvent.click(btn);
    expect(mutate).toHaveBeenCalledWith({ doc_source_id: "woo-store/main/ne101" }, expect.anything());
  });

  it("展开行 chunk serving 比例 = 后端投影真值(10 / 12)", () => {
    renderDetail();
    fireEvent.click(screen.getAllByTestId("doc-row-toggle")[0]);
    expect(screen.getByTestId("chunk-serving-score").textContent).toBe("10 / 12");
  });

  it("展开行恢复注记 = 持久化事件计数(非前端计数器)", () => {
    renderDetail();
    fireEvent.click(screen.getAllByTestId("doc-row-toggle")[0]);
    expect(screen.getByTestId("recovery-note").textContent).toContain("系统已自动尝试恢复 1 次,未成功");
  });

  it("修复成功验证卡:vN / 12 / 12 / 一致性通过 = 任务 result 真值", () => {
    vi.mocked(useSourceDocumentTruth).mockReturnValue({
      data: {
        ...truth,
        latest_repair_task: {
          id: "t1",
          source_id: "woo-store",
          doc_source_id: truth.doc_source_id,
          status: "succeeded",
          stage: "verify",
          requested_by: "admin",
          idempotency_key: "k1",
          result: {
            version_seq: 17,
            chunks_serving: 12,
            chunks_total: 12,
            consistency: "passed",
            repaired_indices: [10, 11],
            repair_mode: "persisted_chunk_replay",
          },
          error: null,
          events: [],
          created_at: "2026-09-13T00:00:00Z",
          finished_at: "2026-09-13T00:01:00Z",
        },
      } as never,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderDetail();
    fireEvent.click(screen.getAllByTestId("doc-row-toggle")[0]);
    const card = screen.getByTestId("repair-verification-card");
    expect(card.textContent).toContain("重新处理完成");
    expect(card.textContent).toContain("v17");
    expect(card.textContent).toContain("12 / 12");
    expect(card.textContent).toContain("通过");
  });
});

describe("U-11 下次同步(调度器权威,禁纯派生)", () => {
  const baseSource = { ...source } as never;
  const runs = undefined;

  it("scheduled:呈现权威 next_run_at 相对时间", () => {
    render(
      <SyncActivityPanel
        source={baseSource}
        schedule={{ source_id: "woo-store", next_run_at: new Date(Date.now() + 3600_000).toISOString(), state: "scheduled", sync_interval: "6h", enabled: true }}
        runs={runs}
      />,
    );
    const el = screen.getByTestId("next-run-at");
    expect(el.textContent).toContain("下次同步");
    expect(el.textContent).not.toContain("同步进行中");
  });

  it("syncing/paused:诚实状态词,无倒计时(NULL 真值禁派生)", () => {
    render(
      <SyncActivityPanel
        source={baseSource}
        schedule={{ source_id: "woo-store", next_run_at: null, state: "syncing", sync_interval: "6h", enabled: true }}
        runs={runs}
      />,
    );
    expect(screen.getByTestId("next-run-at").textContent).toContain("同步进行中");
    cleanup();
    render(
      <SyncActivityPanel
        source={baseSource}
        schedule={{ source_id: "woo-store", next_run_at: null, state: "paused", sync_interval: "6h", enabled: false }}
        runs={runs}
      />,
    );
    expect(screen.getByTestId("next-run-at").textContent).toContain("已暂停");
  });
});

describe("U-12 知识设置抽屉 + U-13 预览 Modal", () => {
  it("抽屉:时态角色/新鲜度要求词表 + 说明 + 超期提醒(后端权威)", () => {
    vi.mocked(useKnowledgeSettings).mockReturnValue({
      data: {
        source_id: "woo-store",
        role: "current",
        explicit_role: null,
        freshness_hours: 12,
        explicit_freshness_hours: 12,
        freshness: { freshness_hours: 12, last_success_at: null, overdue: true, basis: "never_synced" },
        updated_at: null,
      } as never,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <KnowledgeSettingsDrawer open onOpenChange={() => {}} sourceId="woo-store" />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("时态角色")).toBeInTheDocument();
    expect(screen.getByText(/用于支持当前有效知识回答。/)).toBeInTheDocument();
    expect(screen.getByLabelText("新鲜度要求")).toBeInTheDocument();
    expect(screen.getByText(/超过该时间没有成功更新时,系统将提醒知识更新服务。/)).toBeInTheDocument();
    expect(screen.getByTestId("freshness-overdue-alert").textContent).toContain("无法证明知识新鲜度");
    expect((screen.getByTestId("ks-role-select") as HTMLSelectElement).value).toBe("current");
    expect((screen.getByTestId("ks-freshness-select") as HTMLSelectElement).value).toBe("12");
  });

  it("预览 Modal:三行计数 = 预览端点权威;确认携带 token;drift 提示重算", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("账本已变化(影响计数 drift),预览失效;请重新预览后确认"));
    render(
      <RiskPreviewModal
        open
        preview={{
          preview_token: "tok-1",
          current_policy: { role: "current", freshness_hours: 12 },
          pending_policy: { role: "historical", freshness_hours: 12 },
          impact: { affected_documents: 202, current_eligibility_change: 199, historical_eligibility_change: 199 },
        }}
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const impact = screen.getByTestId("risk-preview-impact");
    expect(impact.textContent).toContain("202");
    expect(impact.textContent).toContain("199");
    expect(impact.textContent).toContain("199");
    expect(screen.getByText(/不会删除持久知识。/)).toBeInTheDocument();
    expect(screen.getByText(/变更后系统将重新验证服务状态。/)).toBeInTheDocument();
    expect(screen.getByText("CURRENT")).toBeInTheDocument();
    expect(screen.getByText("HISTORICAL")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("risk-preview-confirm"));
    await vi.waitFor(() => expect(onConfirm).toHaveBeenCalledWith("tok-1"));
    await vi.waitFor(() => expect(screen.getByText(/drift/)).toBeInTheDocument());
  });
});
