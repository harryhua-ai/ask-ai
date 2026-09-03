import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SyncHistoryPanel } from "@/components/dataSources/SyncHistoryPanel";
import type { SyncRun, SyncRunList } from "@/types/api";

afterEach(cleanup);

const run = (overrides: Partial<SyncRun> = {}): SyncRun => ({
  id: 8,
  source_id: "source-a",
  triggered_by: "manual",
  request_id: 42,
  attempt: 2,
  recovery: true,
  status: "completed",
  stage: "DONE",
  counters: { docs_total: 12 },
  consistency: { missing: 2, orphan_count: 3 },
  execution_device: "cuda:0",
  started_at: "2026-09-03T01:00:00Z",
  finished_at: "2026-09-03T01:02:03Z",
  duration_seconds: 123,
  fallback_reason: null,
  fallback_detail: null,
  error_summary: null,
  sync_log: {
    status: "success",
    items_new: 2,
    chunks_written: 42,
    items_deleted: 1,
    items_unchanged: 9,
    error_detail: null,
  },
  ...overrides,
});

const history = (items: SyncRun[]): SyncRunList => ({ items, total: items.length, page: 1, size: 20 });

describe("SyncHistoryPanel", () => {
  it("显示文档、分块、一致性、设备和降级原因", () => {
    render(<SyncHistoryPanel runs={history([
      run({ fallback_reason: "CUDA unavailable", counters: { docs_total: 12, chunks_deleted: 5 } }),
      run({ id: 9, execution_device: "cpu", fallback_reason: null }),
    ])} />);
    expect(screen.getAllByText("新增文档 2")[0]).toBeInTheDocument();
    expect(screen.getAllByText("删除文档 1")[0]).toBeInTheDocument();
    expect(screen.getAllByText("未变更文档 9")[0]).toBeInTheDocument();
    expect(screen.getAllByText("分块 42")[0]).toBeInTheDocument();
    expect(screen.getAllByText("业务结果：成功")[0]).toBeInTheDocument();
    expect(screen.getAllByText("缺失 2")[0]).toBeInTheDocument();
    expect(screen.getAllByText("孤儿 3")[0]).toBeInTheDocument();
    expect(screen.getByText("已删除分块 5")).toBeInTheDocument();
    expect(screen.getByText("GPU")).toBeInTheDocument();
    expect(screen.getByText("CPU")).toBeInTheDocument();
    expect(screen.getByText("降级原因：CUDA unavailable")).toBeInTheDocument();
  });

  it("省略 sync_log 中缺失的文档变化与 counters 中缺失的删除分块数", () => {
    render(<SyncHistoryPanel runs={history([run({ counters: {}, sync_log: null })])} />);
    expect(screen.queryByText(/新增文档|删除文档|未变更文档|分块 42/)).not.toBeInTheDocument();
    expect(screen.queryByText(/已删除分块/)).not.toBeInTheDocument();
  });

  it.each([
    ["completed", "已完成"],
    ["failed", "失败"],
    ["interrupted", "已中断"],
  ] as const)("只从后端 status=%s 派生管理员状态", (status, label) => {
    render(<SyncHistoryPanel runs={history([run({ status })])} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("区分加载、空记录和错误状态，并允许重试加载", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<SyncHistoryPanel runs={undefined} isLoading />);
    expect(screen.getByText("正在加载同步历史…")).toBeInTheDocument();

    rerender(<SyncHistoryPanel runs={history([])} />);
    expect(screen.getByText("暂无同步记录")).toBeInTheDocument();

    rerender(<SyncHistoryPanel runs={undefined} error="历史记录加载失败" onRetry={onRetry} />);
    expect(screen.getByText("历史记录加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试加载" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("把运行 ID 和异常详情收在折叠的技术证据中", () => {
    render(<SyncHistoryPanel runs={history([run({
      fallback_detail: "CUDAError: out of memory",
      sync_log: {
        status: "failed",
        items_new: 0,
        chunks_written: 0,
        items_deleted: 0,
        items_unchanged: 0,
        error_detail: "connector timeout",
      },
    })])} />);
    const details = screen.getByText("技术证据").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details?.textContent).toContain("run_id: 8");
    expect(details?.textContent).toContain("request_id: 42");
    expect(details?.textContent).toContain("CUDAError: out of memory");
    expect(details?.textContent).toContain("connector timeout");
  });
});
