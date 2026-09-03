import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SyncHistoryPanel } from "@/components/dataSources/SyncHistoryPanel";
import type { SyncRun, SyncRunList } from "@/types/api";

afterEach(cleanup);

const run = (overrides: Partial<SyncRun> = {}): SyncRun => ({
  id: 8,
  source_id: "source-a",
  status: "completed",
  state: "COMPLETED",
  stage: "DONE",
  counters: { docs_total: 12, docs_processed: 12, chunks_written: 42 },
  consistency: { missing: 2, orphan_count: 3 },
  device: "cuda:0",
  started_at: "2026-09-03T01:00:00Z",
  finished_at: "2026-09-03T01:02:03Z",
  ...overrides,
});

const history = (items: SyncRun[]): SyncRunList => ({ items, total: items.length, page: 1, size: 20 });

describe("SyncHistoryPanel", () => {
  it("显示文档、分块、一致性、设备和降级原因", () => {
    render(<SyncHistoryPanel runs={history([
      run({ fallback_reason: "CUDA unavailable", counters: { docs_total: 12, docs_processed: 12, chunks_written: 42, chunks_deleted: 5 } }),
      run({ id: 9, device: "cpu", fallback_reason: null }),
    ])} />);
    expect(screen.getAllByText("文档 12")[0]).toBeInTheDocument();
    expect(screen.getAllByText("分块 42")[0]).toBeInTheDocument();
    expect(screen.getAllByText("缺失 2")[0]).toBeInTheDocument();
    expect(screen.getAllByText("孤儿 3")[0]).toBeInTheDocument();
    expect(screen.getByText("已删除分块 5")).toBeInTheDocument();
    expect(screen.getByText("GPU")).toBeInTheDocument();
    expect(screen.getByText("CPU")).toBeInTheDocument();
    expect(screen.getByText("降级原因：CUDA unavailable")).toBeInTheDocument();
  });

  it("以已处理文档标注 docs_processed 回退，并省略缺失的删除分块数", () => {
    render(<SyncHistoryPanel runs={history([run({ counters: { docs_processed: 4, chunks_written: 7 } })])} />);
    expect(screen.getByText("已处理文档 4")).toBeInTheDocument();
    expect(screen.queryByText(/已删除分块/)).not.toBeInTheDocument();
  });

  it.each([
    ["failed", "FAILED", "失败"],
    ["interrupted", "INTERRUPTED", "已中断"],
    ["running", "RECOVERING", "恢复中"],
  ] as const)("显示 %s 的管理员状态 %s", (status, state, label) => {
    render(<SyncHistoryPanel runs={history([run({ status, state })])} />);
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
    render(<SyncHistoryPanel runs={history([run({ request_id: 42, error_summary: "CUDAError: out of memory" })])} />);
    const details = screen.getByText("技术证据").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details?.textContent).toContain("run_id: 8");
    expect(details?.textContent).toContain("request_id: 42");
    expect(details?.textContent).toContain("CUDAError: out of memory");
  });
});
