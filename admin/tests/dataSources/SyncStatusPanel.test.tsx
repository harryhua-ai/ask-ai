import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SyncStatusPanel } from "@/components/dataSources/SyncStatusPanel";
import type { SyncStage, SyncStatusItem } from "@/types/api";
import { stageLabel } from "@/lib/dataSourceObservability";

afterEach(cleanup);

const status = (overrides: Partial<SyncStatusItem> = {}): SyncStatusItem => ({
  source_id: "source-a",
  state: "RUNNING",
  stage: "FETCH",
  stage_current: 3,
  stage_total: 12,
  counters: { docs_total: 12, docs_processed: 3, chunks_written: 8 },
  execution_device: "cuda:0",
  request_id: 42,
  attempt: 2,
  recovering: false,
  started_at: "2026-09-03T01:00:00Z",
  updated_at: "2026-09-03T01:00:01Z",
  ...overrides,
});

describe("SyncStatusPanel", () => {
  it("显示所有规范阶段的中文名称", () => {
    const stages: SyncStage[] = ["DISCOVER", "SAFETY_FILTER", "FETCH", "PARSE", "CHUNK", "EMBED", "INDEX", "CONSISTENCY", "DONE"];
    render(<>{stages.map((stage) => <SyncStatusPanel key={stage} status={status({ stage })} />)}</>);

    for (const stage of stages) expect(screen.getByText(stageLabel(stage))).toBeInTheDocument();
  });

  it("仅在阶段总数可靠时显示真实百分比", () => {
    const { rerender } = render(<SyncStatusPanel status={status()} />);
    expect(screen.getByText("3/12 · 25%")).toBeInTheDocument();

    rerender(<SyncStatusPanel status={status({ stage_total: null })} />);
    expect(screen.getByText("已处理 3 项")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("仅在后端给出删除分块数时显示该计数", () => {
    const { rerender } = render(<SyncStatusPanel status={status({ counters: { chunks_written: 8, chunks_deleted: 2 } })} />);
    expect(screen.getByText("已删除分块 2")).toBeInTheDocument();

    rerender(<SyncStatusPanel status={status({ counters: { chunks_written: 8 } })} />);
    expect(screen.queryByText(/已删除分块/)).not.toBeInTheDocument();
  });

  it("显示有证据的无上游变更短路结果", () => {
    render(<SyncStatusPanel status={status({ state: "COMPLETED", counters: { docs_total: 0, items_unchanged: 12 } })} />);
    expect(screen.getByText("无上游变更 · 已检查 · 跳过灌入")).toBeInTheDocument();
  });

  it.each([
    ["FAILED", "失败"],
    ["INTERRUPTED", "已中断"],
    ["RECOVERING", "恢复中"],
  ] as const)("将 %s 同步状态呈现为 %s", (state, label) => {
    render(<SyncStatusPanel status={status({ state })} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("将请求标识和 CUDA 异常收在折叠的技术证据中，并暴露重试回调", () => {
    const onRetry = vi.fn();
    render(
      <SyncStatusPanel
        status={status({ state: "FAILED" })}
        onRetry={onRetry}
        technicalEvidence={{ exception_class: "CUDAOutOfMemoryError" }}
      />,
    );

    const details = screen.getByText("技术证据").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details?.textContent).toContain("request_id: 42");
    expect(details?.textContent).toContain("attempt: 2");
    expect(details?.textContent).toContain("CUDAOutOfMemoryError");
    fireEvent.click(screen.getByRole("button", { name: "重新同步" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
