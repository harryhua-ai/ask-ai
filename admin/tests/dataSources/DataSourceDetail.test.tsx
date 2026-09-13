import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSourceDetail from "@/pages/DataSourceDetail";
import {
  useDataSources,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
  useTriggerSync,
} from "@/hooks/useDataSources";
import {
  useSourceDocuments,
  useSourceDocumentTruth,
  useSourceGenerations,
} from "@/hooks/useDataSourceWorkspace";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: vi.fn(() => ({ data: [], isLoading: false })),
  useTriggerSync: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useSyncHealth: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSyncRuns: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useSyncStatus: vi.fn(() => ({ data: { items: [] }, isLoading: false })),
  useSourceHealth: vi.fn(() => ({ data: undefined, isLoading: false })),
  useAttentionSummary: vi.fn(() => ({ data: undefined, isLoading: false })),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useDataSourceWorkspace", () => ({
  useSourceDocuments: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })),
  useSourceDocumentTruth: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })),
  useSourceGenerations: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const sourceFixture = {
  id: "wiki-documents-local",
  type: "github",
  product: "wiki",
  enabled: true,
  config: { repo_url: "https://github.com/camthink-ai/wiki.git" },
  sync_interval: "24h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_sync: "2026-09-01T02:00:00Z",
  last_sync_status: "success",
  last_sync_error: null,
  lifecycle_state: null,
  lifecycle_since: null,
  lifecycle_error: null,
};

const documentsFixture = {
  source_id: "wiki-documents-local",
  total: 2,
  ledger_total: 6,
  page: 1,
  size: 20,
  lifecycle_counts: { active: 2, missing_candidate: 1, superseded: 2, deleted: 1, discovered: 0 },
  serving_count: 3,
  current_count: 2,
  items: [
    {
      source_id: "wiki-documents-local/main/alive.md",
      title: "Alive Doc",
      url: "https://git.local/main/alive.md",
      branch: "main",
      source_type: "github",
      product: "wiki",
      lifecycle: "active",
      serving: true,
      chunk_count: 3,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: "2026-09-01T00:00:00+00:00",
      current_version_seq: 1,
      generation_ordinal: 4,
    },
    {
      source_id: "wiki-documents-local/main/old.md",
      title: "Old Doc",
      url: "https://git.local/main/old.md",
      branch: "main",
      source_type: "github",
      product: "wiki",
      lifecycle: "superseded",
      serving: false,
      chunk_count: 2,
      created_at: "2026-08-01T00:00:00+00:00",
      updated_at: "2026-09-02T00:00:00+00:00",
      current_version_seq: 2,
      generation_ordinal: 4,
    },
  ],
};

const truthFixture = {
  source_id: "wiki-documents-local",
  doc_source_id: "wiki-documents-local/main/old.md",
  title: "Old Doc",
  url: "https://git.local/main/old.md",
  branch: "main",
  source_type: "github",
  product: "wiki",
  lifecycle: "superseded",
  serving: false,
  chunk_count: 2,
  created_at: "2026-08-01T00:00:00+00:00",
  updated_at: "2026-09-02T00:00:00+00:00",
  superseded_by: "wiki-documents-local/main/new.md",
  superseded_at: "2026-09-02T00:00:00+00:00",
  deleted_at: null,
  current_version: {
    id: "0b9e6c33-0000-0000-0000-000000000001",
    version_seq: 2,
    status: "superseded",
    title: "Old Doc",
    url: "https://git.local/main/old.md",
    chunk_count: 2,
    chunks_total: 2,
    source_version: null,
    valid_from: "2026-08-01T00:00:00+00:00",
    valid_to: "2026-09-02T00:00:00+00:00",
    superseded_by_version_id: null,
    generation_id: "0b9e6c33-0000-0000-0000-000000000002",
    generation_ordinal: 4,
  },
  generation: {
    id: "0b9e6c33-0000-0000-0000-000000000002",
    ordinal: 4,
    status: "retired",
    doc_count: 5,
    chunk_count: 20,
    failure: null,
    created_at: "2026-08-01T00:00:00+00:00",
    ready_at: "2026-08-01T00:01:00+00:00",
    activated_at: "2026-08-01T00:02:00+00:00",
    withdrawn_at: "2026-09-02T00:00:00+00:00",
    retired_at: "2026-09-02T00:00:00+00:00",
    gc_eligible_at: "2026-09-09T00:00:00+00:00",
    purged_at: null,
  },
};

const generationsFixture = {
  source_id: "wiki-documents-local",
  total: 2,
  serving_ordinals: [4],
  items: [
    {
      id: "0b9e6c33-0000-0000-0000-000000000003",
      ordinal: 5,
      status: "failed",
      doc_count: 0,
      chunk_count: 0,
      failure: { error: "embedder 返回 0 向量,期望 12", stage: "embed" },
      created_at: "2026-09-03T00:00:00+00:00",
      ready_at: null,
      activated_at: null,
      withdrawn_at: null,
      retired_at: null,
      gc_eligible_at: null,
      purged_at: null,
    },
    {
      id: "0b9e6c33-0000-0000-0000-000000000002",
      ordinal: 4,
      status: "retired",
      doc_count: 5,
      chunk_count: 20,
      failure: null,
      created_at: "2026-08-01T00:00:00+00:00",
      ready_at: "2026-08-01T00:01:00+00:00",
      activated_at: "2026-08-01T00:02:00+00:00",
      withdrawn_at: "2026-09-02T00:00:00+00:00",
      retired_at: "2026-09-02T00:00:00+00:00",
      gc_eligible_at: "2026-09-09T00:00:00+00:00",
      purged_at: null,
    },
  ],
};

function mockDefaults() {
  vi.mocked(useDataSources).mockReturnValue({ data: [sourceFixture], isLoading: false } as never);
  vi.mocked(useTriggerSync).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never);
  vi.mocked(useSyncStatus).mockReturnValue({
    data: { items: [] },
    isLoading: false,
  } as never);
  vi.mocked(useSyncHealth).mockReturnValue({
    data: { items: [] },
    isLoading: false,
  } as never);
  vi.mocked(useSyncRuns).mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useSourceDocuments).mockReturnValue({
    data: documentsFixture,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useSourceDocumentTruth).mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useSourceGenerations).mockReturnValue({
    data: generationsFixture,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
}

function renderDetail(
  sourceId = "wiki-documents-local",
  overrides?: () => void,
) {
  mockDefaults();
  overrides?.();
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/data-sources/${sourceId}`]}>
        <Routes>
          <Route path="/data-sources" element={<div>list-page</div>} />
          <Route path="/data-sources/:sourceId" element={<DataSourceDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DataSourceDetail 详情工作面", () => {
  it("身份/配置摘要:产品线、类型中文标签、同步间隔、来源地址可见", () => {
    renderDetail();
    expect(screen.getAllByText("wiki").length).toBeGreaterThan(0);
    // A-P1-05(audit):运营呈现词表 github→Wiki(仅呈现映射,source_type 真值不变)
    expect(screen.getAllByText("Wiki").length).toBeGreaterThan(0);
    // v1.6.3 B1:同步间隔以人性化 周期 呈现(同步状态卡),原文 24h 保留于编辑抽屉
    expect(screen.getByText(/同步周期/)).toBeInTheDocument();
    expect(screen.getByText("每 24 小时")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/camthink-ai/wiki.git")).toBeInTheDocument();
  });

  it("源配置行不存在 → 显式 后端无此记录(不虚构)", () => {
    renderDetail("not-configured-source");
    expect(screen.getByText("后端无此记录")).toBeInTheDocument();
  });

  it("运营三桶可见且计数来自权威聚合(当前在服/需要关注/已退役)", () => {
    renderDetail();
    // bucketCountsOf: current=2;retired=2+1=3;attention=6-2-3=1
    expect(screen.getByText("当前在服 2")).toBeInTheDocument();
    expect(screen.getByText("需要关注 1")).toBeInTheDocument();
    expect(screen.getByText("已退役 3")).toBeInTheDocument();
    // v1.6.3 B1:总量注记收敛为 共 N 条(账本 6)
    expect(screen.getAllByText(/账本 6/).length).toBeGreaterThan(0);
  });

  it("内容清单行:L 轴中文标签 + 在服徽章 + 分块数 + 权威更新时间", () => {
    renderDetail();
    expect(screen.getByText("Alive Doc")).toBeInTheDocument();
    expect(screen.getByText("Old Doc")).toBeInTheDocument();
    // A-P2-02(audit):serving=true → 正常(绿);不再呈现 在服/不在服 红
    expect(screen.getAllByText("正常").length).toBeGreaterThan(0);
    // v1.6.3 B1 收敛:状态列 = 运营桶词表(已退役);L 轴中文标签移至展开真相
    expect(screen.getAllByText("已退役").length).toBeGreaterThan(0);
    // 更新时间 = 人性化相对时间,精确 ISO 保留在 title 属性
    expect(screen.getAllByText(/天前|小时前|个月前|刚刚/).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle("2026-09-01T00:00:00+00:00").length).toBeGreaterThan(0);
  });

  it("搜索与生命周期过滤触发清单查询(单一权威映射模块消费标签)", async () => {
    renderDetail();
    fireEvent.change(screen.getByLabelText("搜索知识内容"), {
      target: { value: "alive" },
    });
    await waitFor(() =>
      expect(useSourceDocuments).toHaveBeenLastCalledWith(
        "wiki-documents-local",
        expect.objectContaining({ search: "alive" }),
      ),
    );
    fireEvent.change(screen.getByLabelText("按生命周期过滤"), {
      target: { value: "deleted" },
    });
    await waitFor(() =>
      expect(useSourceDocuments).toHaveBeenLastCalledWith(
        "wiki-documents-local",
        expect.objectContaining({ lifecycle: "deleted" }),
      ),
    );
  });

  it("行展开单条真相:非在服原因(权威字段)+ 版本/生成归属 + canonical 身份", async () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceDocumentTruth).mockReturnValue({
        data: truthFixture,
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    fireEvent.click(screen.getAllByRole("button", { name: /查看真相/ })[1]);
    await waitFor(() =>
      expect(useSourceDocumentTruth).toHaveBeenCalledWith(
        "wiki-documents-local",
        "wiki-documents-local/main/old.md",
      ),
    );
    // 原因来自权威字段(接替者)
    expect(screen.getByText(/已被 wiki-documents-local\/main\/new.md 接替/)).toBeInTheDocument();
    // 版本与生成归属(v1.6.3 B1 词语:当前有效版本 / 生成真相)
    expect(screen.getByText(/当前有效版本/)).toBeInTheDocument();
    expect(screen.getAllByText(/v2/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/生成真相/).length).toBeGreaterThan(0);
    expect(screen.getByText("#4")).toBeInTheDocument();
    // A-P1-03 同口径(audit 附录 C):canonical 身份收进行头 title,不再作副行文本
    expect(screen.getByTitle(/wiki-documents-local\/main\/old\.md/)).toBeInTheDocument();
    // A-P3-02(audit):「生效自」人类化时间,不裸 ISO
    expect(screen.queryByText(/生效自 \d{4}-\d{2}-\d{2}T/)).not.toBeInTheDocument();
  });

  it("真相中现行版本缺席 → 显式 后端无此记录", async () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceDocumentTruth).mockReturnValue({
        data: { ...truthFixture, current_version: null, generation: null },
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    // A-P3-01:真相行 = 匹配 doc_source_id 的行下原地展开(fixture 真相为 old.md 行)
    fireEvent.click(screen.getAllByRole("button", { name: /查看真相/ })[1]);
    await waitFor(() =>
      expect(screen.getByText(/当前有效版本:/)).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/后端无此记录/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/生成真相/).length).toBeGreaterThan(0);
  });

  it("生成可见性:失败代显示失败证据,在服代打标", () => {
    renderDetail();
    expect(screen.getByText("构建失败")).toBeInTheDocument();
    expect(screen.getByText(/embedder 返回 0 向量/)).toBeInTheDocument();
    expect(screen.getAllByText("已退役").length).toBeGreaterThan(0); // retired 代标签 + 运营桶词
    // 在服代标记(ordinal=4)
    expect(screen.getByText("在服代")).toBeInTheDocument();
  });

  it("生成记录缺席 → 显式 后端无此记录", () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceGenerations).mockReturnValue({
        data: { source_id: "wiki-documents-local", total: 0, serving_ordinals: [], items: [] },
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    expect(screen.getByText(/该源尚无索引生成记录/)).toBeInTheDocument();
  });

  it("清单为空 → 空态(不伪装数据)", () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceDocuments).mockReturnValue({
        data: { ...documentsFixture, total: 0, items: [] },
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    expect(screen.getByText("该源暂无账本文档")).toBeInTheDocument();
  });

  it("清单加载失败 → LoadError 三态纪律", () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceDocuments).mockReturnValue({
        data: undefined,
        isLoading: false,
        isError: true,
        error: new Error("boom"),
        refetch: vi.fn(),
      } as never);
    });
    expect(screen.getByText("加载失败")).toBeInTheDocument();
  });

  it("同步与健康面板复用(当前同步/数据源健康/最近同步同屏)", () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSyncStatus).mockReturnValue({
        data: {
          items: [
            {
              source_id: "wiki-documents-local",
              state: "RUNNING",
              request_id: 42,
              attempt: 1,
              recovering: false,
              stage: "EMBED",
              stage_current: 3,
              stage_total: 12,
              counters: null,
              execution_device: null,
              started_at: null,
              updated_at: null,
            },
          ],
        },
        isLoading: false,
      } as never);
      // v1.6.3 B1:进行中同步收敛进 活动时间线(sync-runs running 行 → 同步进行中)
      vi.mocked(useSyncRuns).mockReturnValue({
        data: {
          items: [
            {
              id: 99,
              source_id: "wiki-documents-local",
              triggered_by: "manual",
              status: "running",
              started_at: "2026-09-10T00:00:00+00:00",
              counters: null,
              sync_log: null,
            },
          ],
          total: 1,
          page: 1,
          size: 20,
        },
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    expect(screen.getByText("同步进行中")).toBeInTheDocument();
  });

  it("翻页触发清单查询分页参数", async () => {
    renderDetail("wiki-documents-local", () => {
      vi.mocked(useSourceDocuments).mockReturnValue({
        data: { ...documentsFixture, total: 25 },
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      } as never);
    });
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(useSourceDocuments).toHaveBeenLastCalledWith(
        "wiki-documents-local",
        expect.objectContaining({ page: 2 }),
      ),
    );
  });
});
