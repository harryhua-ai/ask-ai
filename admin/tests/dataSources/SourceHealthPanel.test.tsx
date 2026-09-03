import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SourceHealthPanel } from "@/components/dataSources/SourceHealthPanel";
import type { SourceHealthDimension } from "@/types/api";

afterEach(cleanup);

const dimension = (state: SourceHealthDimension["state"], evidence: string | null): SourceHealthDimension => ({
  state,
  evidence,
  as_of: "2026-09-03T01:02:03Z",
});

describe("SourceHealthPanel", () => {
  it("呈现五个健康维度的状态、证据和截至时间", () => {
    render(
      <SourceHealthPanel
        connectivity={dimension("HEALTHY", "数据源已启用")}
        sync={dimension("DEGRADED", "窗口内同步 3/4 次成功")}
        coverage={dimension("HEALTHY", "文档 12，分块 42")}
        freshness={dimension("HEALTHY", "最近同步 2026-09-03T01:02:03Z")}
        consistency={dimension("DEGRADED", "缺失 2，孤儿 3")}
      />,
    );
    for (const label of ["连接", "同步", "覆盖", "新鲜度", "一致性", "健康", "降级", "数据源已启用", "窗口内同步 3/4 次成功", "截至 2026-09-03T01:02:03Z"]) {
      expect(screen.getAllByText(label, { exact: false }).length).toBeGreaterThan(0);
    }
  });

  it("将 RECOVERING 作为同步健康的覆盖态", () => {
    render(
      <SourceHealthPanel
        activeState="RECOVERING"
        connectivity={dimension("HEALTHY", "数据源已启用")}
        sync={dimension("CRITICAL", "上一轮失败")}
        coverage={dimension("HEALTHY", "文档 12")}
        freshness={dimension("HEALTHY", "最近同步")}
        consistency={dimension("HEALTHY", "缺失 0，孤儿 0")}
      />,
    );
    expect(screen.getByText("恢复中")).toBeInTheDocument();
    expect(screen.getByText("上一轮失败")).toBeInTheDocument();
  });

  it("没有证据时不保留健康状态", () => {
    render(
      <SourceHealthPanel
        connectivity={dimension("HEALTHY", null)}
        sync={dimension("UNKNOWN", null)}
        coverage={dimension("UNKNOWN", null)}
        freshness={dimension("UNKNOWN", null)}
        consistency={dimension("UNKNOWN", null)}
      />,
    );
    expect(screen.queryByText("健康", { exact: true })).not.toBeInTheDocument();
    expect(screen.getAllByText("证据不足").length).toBeGreaterThan(0);
  });

  it("对不足证据提供明确提示，并将缺失与孤儿事实分开显示", () => {
    render(
      <SourceHealthPanel
        connectivity={dimension("INSUFFICIENT_DATA", null)}
        sync={dimension("UNKNOWN", null)}
        coverage={dimension("UNKNOWN", null)}
        freshness={dimension("UNKNOWN", null)}
        consistency={dimension("DEGRADED", "缺失 2，孤儿 3")}
      />,
    );
    expect(screen.getAllByText("证据不足").length).toBeGreaterThan(0);
    expect(screen.getByText("缺失 2")).toBeInTheDocument();
    expect(screen.getByText("孤儿 3")).toBeInTheDocument();
  });

  it("校验失败后缀不并入孤儿事实行(整体呈现)", () => {
    // consistencyDimension 在 verification_failed 时 evidence 带后缀
    // "；校验失败"——拆分正则不得把它吞进「孤儿」值里。
    render(
      <SourceHealthPanel
        connectivity={dimension("UNKNOWN", null)}
        sync={dimension("UNKNOWN", null)}
        coverage={dimension("UNKNOWN", null)}
        freshness={dimension("UNKNOWN", null)}
        consistency={dimension("UNKNOWN", "缺失 2，孤儿 3；校验失败")}
      />,
    );
    expect(screen.getByText("缺失 2，孤儿 3；校验失败")).toBeInTheDocument();
    expect(screen.queryByText("孤儿 3；校验失败")).not.toBeInTheDocument();
  });
});
