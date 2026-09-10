// Issue #21 验收测试:当前 vs 历史健康语义在 Admin 呈现层显式分离。
//
// 覆盖(冻结契约):
// - SourceHealthPanel(W2 /sync-health 直呈视图):30 天同步维显式标注
//   「同步(历史30天)」,其 critical 态不得被读成当前严重度;当前态维
//   (连接/覆盖/新鲜度/一致性)标签不变、保持主位;
// - W2 overall 徽章词表不变(前端只本地化,不重判);
// - Analytics SourceHealthSummary:历史低成功率用显式历史措辞
//   (「历史低成功率 N」),不再出现无历史限定的「严重 N」;容器携带
//   historical_reliability 信号标注;
// - 运行时回退证据(fallbackLabel)呈现不变 —— 成功回退是历史/运行时
//   证据,不改判当前健康。

import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SourceHealthPanel } from "@/components/dataSources/SourceHealthPanel";
import { SourceHealthSummary } from "@/pages/Analytics";
import { fallbackLabel } from "@/lib/dataSourceObservability";
import type { SyncHealthItem } from "@/types/api";

afterEach(cleanup);

const panelItem: SyncHealthItem = {
  source_id: "src-a",
  source_type: "web_crawl",
  enabled: true,
  expected_state: "REQUIRED",
  overall: "HEALTHY",
  recovering: false,
  document_count: 128,
  connectivity: { state: "ok", evidence: "latest run #9 success@DONE", as_of: "2026-09-10T00:00:00Z" },
  sync: { state: "critical", evidence: "1/40 syncs succeeded in 30d (历史参考)", as_of: "2026-09-10T00:00:00Z" },
  coverage: { state: "ok", evidence: "extracted=128/128 accepted", as_of: "2026-09-10T00:00:00Z" },
  freshness: { state: "fresh", evidence: "last success 3600s ago (threshold=172800s)", as_of: "2026-09-10T00:00:00Z" },
  consistency: { state: "ok", evidence: "missing=0, extra_orphan=0", as_of: "2026-09-10T00:00:00Z" },
} as unknown as SyncHealthItem;

describe("#21 SourceHealthPanel —— 30 天同步维显式标注历史", () => {
  it("同步维标签为「同步(历史30天)」,critical 态徽章落在历史卡片内", () => {
    render(<SourceHealthPanel health={panelItem} />);
    expect(screen.getByText("同步(历史30天)")).toBeInTheDocument();
    // 该维仍是 W2 词表原文(critical → 严重),但语义由历史卡片标题限定
    const syncCritical = screen.getByText("严重");
    expect(syncCritical).toBeInTheDocument();
  });

  it("当前态维标签不变且保持主位", () => {
    render(<SourceHealthPanel health={panelItem} />);
    for (const label of ["连接", "覆盖", "新鲜度", "一致性"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("数据源健康")).toBeInTheDocument();
    expect(screen.getByText("健康")).toBeInTheDocument(); // overall HEALTHY 徽章词表不变
  });

  it("overall 与维度徽章不引入新词表(前端只本地化)", () => {
    render(<SourceHealthPanel health={panelItem} />);
    expect(screen.getAllByText("正常").length).toBe(3); // connectivity/coverage/consistency ok
    expect(screen.getByText(/missing=0/)).toBeInTheDocument(); // evidence 原样直呈
  });
});

describe("#21 Analytics 历史可靠性摘要", () => {
  it("critical 计数用「历史低成功率」,不出现无历史限定的「严重」", () => {
    render(
      <MemoryRouter>
        <SourceHealthSummary
          items={[{ health: "critical" }, { health: "critical" }, { health: "healthy" }, { health: "degraded" }]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/历史低成功率 2/)).toBeInTheDocument();
    expect(screen.queryByText(/^严重/)).not.toBeInTheDocument();
    expect(screen.getByText(/正常 1/)).toBeInTheDocument();
    expect(screen.getByText(/偏低 1/)).toBeInTheDocument();
    expect(screen.getByText("数据源历史可靠性(近 30 天)")).toBeInTheDocument();
    expect(
      document.querySelector('[data-source-health-signal="historical_reliability"]'),
    ).not.toBeNull();
  });
});

describe("#21 运行时回退证据呈现不变", () => {
  it("fallback_reason 仍以「降级原因」呈现(历史/运行时证据,非当前严重度)", () => {
    expect(fallbackLabel("cuda_oom")).toBe("降级原因：cuda_oom");
  });
});
