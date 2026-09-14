/**
 * Track F(证据聚合)Wave 1 组件测试 — U-17/U-18/U-19 前端呈现契约。
 *
 * 冻结语义(track-f-contract / matrix-TI TI-12/TI-27/TI-33):
 * - meta 行三项计数并排(相关提问·受影响回答·涉及用户);「涉及用户」
 *   只来自后端权威聚合;unavailable → 诚实「证据不可用」,禁编造计数;
 * - 源卡 = 后端归因投影呈现 + /data-sources/:id 真实深链;无证据 → 诚实空态;
 * - 主题列:权威主题真值 → 主题主行 + 代表问句副行;无主题 → 回退代表问句。
 * 本文件零生产代码推断:所有 unavailable 路径由后端 users_available/topic=null 驱动。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AnswerGapItem } from "@/lib/api/techInsight";
import type {
  GapSourceAttribution,
  GapTopicProjection,
  GapUsersProjection,
} from "@/lib/api/techEvidence";

const { mockGapUsers, mockGapSources, mockGapTopic } = vi.hoisted(() => ({
  mockGapUsers: vi.fn(),
  mockGapSources: vi.fn(),
  mockGapTopic: vi.fn(),
}));

vi.mock("@/lib/api/techEvidence", () => ({
  fetchGapUsers: mockGapUsers,
  fetchGapSources: mockGapSources,
  fetchGapTopic: mockGapTopic,
}));

import { PanelStats } from "@/pages/analytics/PanelStats";
import { GapTopicCell } from "@/pages/analytics/GapTopicCell";

const GAP: AnswerGapItem = {
  id: "g1",
  cluster_type: "gap",
  representative_question: "NE101 是否支持 PoE",
  sample_questions: ["NE101 是否支持 PoE", "NE101 PoE 标准是什么"],
  question_count: 23,
  impacted_answer_count: 18,
  status: "open",
  miss_type: "知识缺失",
  miss_type_breakdown: { 知识缺失: 18 },
  last_seen_at: "2026-09-13T10:00:00Z",
  period_start: null,
  period_end: null,
  created_at: "2026-09-10T10:00:00Z",
};

const USERS_OK: GapUsersProjection = {
  gap_id: "g1",
  window: { preset: "all", from: null, to: null },
  conversations_in_window: 18,
  conversations_with_session_identity: 18,
  conversations_without_session_identity: 0,
  distinct_sessions: 17,
  users: 17,
  users_available: true,
  unavailable_reason: null,
};

const SOURCES_OK: GapSourceAttribution = {
  gap_id: "g1",
  conversations_total: 18,
  citing_conversations_total: 12,
  items: [
    {
      source_id: "wf-woo-ne101",
      source_type: "woocommerce",
      product: "ne101",
      citing_conversations: 9,
      evidence_rule: "conversation_citation_identity_match",
    },
  ],
  unmatched_citations: [],
};

const TOPIC_OK: GapTopicProjection = {
  gap_id: "g1",
  topic: "NE101 PoE",
  derivation: "cross_question_common_factor",
  corpus_size: 2,
  fallback: "NE101 是否支持 PoE",
};

function renderUi(node: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGapUsers.mockResolvedValue(USERS_OK);
  mockGapSources.mockResolvedValue(SOURCES_OK);
  mockGapTopic.mockResolvedValue(TOPIC_OK);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Track F PanelStats — U-17 用户聚合(TI-27)", () => {
  it("meta 行三项计数并排;涉及用户=权威聚合值(参考 PNG 呈现)", async () => {
    renderUi(<PanelStats gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-panel-stats]")?.textContent).toContain(
        "23 次相关提问",
      );
      expect(document.querySelector("[data-panel-stats]")?.textContent).toContain(
        "18 次受影响回答",
      );
      expect(document.querySelector("[data-panel-users]")?.textContent).toBe(
        "涉及 17 个用户",
      );
    });
    // 聚合窗透传:默认 all(IF-7 接线点为 window prop)
    // INT 接线收口:PanelStats 增加可选 from/to 形参(显式起止窗),默认 undefined
    expect(mockGapUsers).toHaveBeenCalledWith("g1", "all", undefined, undefined);
  });

  it("window prop 透传给权威聚合端点(聚合窗=所选分析窗)", async () => {
    renderUi(<PanelStats gap={GAP} window="7d" />);
    await waitFor(() => {
      expect(mockGapUsers).toHaveBeenCalledWith("g1", "7d", undefined, undefined);
    });
  });

  it("身份真值不足 → 诚实 unavailable,不编造计数", async () => {
    mockGapUsers.mockResolvedValue({
      ...USERS_OK,
      users: null,
      users_available: false,
      unavailable_reason: "session_identity_insufficient",
      conversations_without_session_identity: 18,
      distinct_sessions: 0,
    });
    renderUi(<PanelStats gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-panel-users]")?.textContent).toBe(
        "涉及用户 证据不可用",
      );
    });
    // 禁编造:不可用态不得出现任何数字计数
    expect(document.querySelector("[data-panel-users]")?.textContent).not.toMatch(/\d/);
  });

  it("聚合端点读取失败 → 诚实 unavailable(零前端估算)", async () => {
    mockGapUsers.mockRejectedValue(new Error("network"));
    renderUi(<PanelStats gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-panel-users]")?.textContent).toContain(
        "证据不可用",
      );
    });
  });
});

describe("Track F PanelStats — U-18 相关数据源(TI-33)", () => {
  it("源卡呈现类型/产品 + 真实深链 /data-sources/:id + 外链 icon", async () => {
    renderUi(<PanelStats gap={GAP} />);
    await waitFor(() => {
      const card = document.querySelector("[data-source-card]");
      expect(card).toBeTruthy();
      expect(card?.getAttribute("href")).toBe("/data-sources/wf-woo-ne101");
      expect(card?.getAttribute("data-source-id")).toBe("wf-woo-ne101");
      expect(card?.textContent).toContain("woocommerce");
      expect(card?.textContent).toContain("ne101");
      expect(document.querySelector("[data-source-external]")).toBeTruthy();
    });
  });

  it("无归因证据 → 诚实空态,零猜测", async () => {
    mockGapSources.mockResolvedValue({
      ...SOURCES_OK,
      items: [],
      citing_conversations_total: 0,
    });
    renderUi(<PanelStats gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-sources-unavailable]")).toBeTruthy();
    });
    expect(document.querySelector("[data-source-card]")).toBeNull();
  });
});

describe("Track F GapTopicCell — U-19 主题列(TI-12)", () => {
  it("权威主题真值 → 主题主行 + 代表问句副行(参考 PNG 主题式标题)", async () => {
    const { container } = renderUi(<GapTopicCell gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-gap-topic]")?.textContent).toBe("NE101 PoE");
      expect(document.querySelector("[data-gap-question]")?.textContent).toBe(
        "NE101 是否支持 PoE",
      );
    });
    // 零编造:主题值与后端投影逐字一致
    expect(container.textContent).not.toContain("支持信息缺失");
  });

  it("无主题(topic=null)→ 回退代表问句主行 + 样例问句副行(既有呈现逐字保留)", async () => {
    mockGapTopic.mockResolvedValue({
      ...TOPIC_OK,
      topic: null,
      derivation: null,
    });
    renderUi(<GapTopicCell gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-gap-topic]")).toBeNull();
      expect(document.querySelector("[data-gap-question]")?.textContent).toBe(
        "NE101 是否支持 PoE",
      );
      expect(document.querySelector("[data-gap-sample]")?.textContent).toBe(
        "NE101 PoE 标准是什么",
      );
    });
  });

  it("主题端点读取失败 → 回退代表问句(不闪不造)", async () => {
    mockGapTopic.mockRejectedValue(new Error("network"));
    renderUi(<GapTopicCell gap={GAP} />);
    await waitFor(() => {
      expect(document.querySelector("[data-gap-question]")?.textContent).toBe(
        "NE101 是否支持 PoE",
      );
    });
    expect(document.querySelector("[data-gap-topic]")).toBeNull();
  });
});

// smoke:两组件可同渲染(面板结构无跨文件耦合)
describe("Track F 组件冒烟", () => {
  it("PanelStats+GapTopicCell 并存渲染无异常", async () => {
    renderUi(
      <div>
        <GapTopicCell gap={GAP} />
        <PanelStats gap={GAP} window="today" />
      </div>,
    );
    await waitFor(() => {
      expect(document.querySelector("[data-panel-stats]")?.textContent).toContain(
        "23 次相关提问",
      );
      expect(document.querySelector("[data-source-card]")?.getAttribute("href")).toBe(
        "/data-sources/wf-woo-ne101",
      );
    });
    expect(mockGapUsers).toHaveBeenCalledWith("g1", "today", undefined, undefined);
  });
});
