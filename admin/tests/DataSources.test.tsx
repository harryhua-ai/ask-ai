import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DataSources from "@/pages/DataSources";

afterEach(cleanup);

// Mock 网络层 hooks,避免真实 fetch
vi.mock("@/hooks/useDataSources", () => ({
  useDataSources: () => ({ data: [], isLoading: false }),
  useCreateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useTriggerSync: () => ({ mutate: vi.fn(), isPending: false }),
  fetchPreviewBranches: vi.fn(),
}));

describe("DataSources", () => {
  it("renders title", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    expect(screen.getByText("数据源管理")).toBeInTheDocument();
  });

  it("shows empty state when no data sources", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    expect(screen.getByText("暂无数据源")).toBeInTheDocument();
  });

  it("opens create form when clicking new button", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DataSources />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByText("新增数据源"));
    expect(screen.getByText("创建")).toBeInTheDocument();
  });
});
