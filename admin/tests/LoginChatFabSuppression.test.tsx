/** V-2 终局视觉修复验收:LoginChat 浮动 FAB 在 KB-OPS-V163-002 知识运营面抑制,其余面保持。 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LoginChat } from "@/components/LoginChat";

// FAB(launcher)仅在 site-config 解析落定后渲染;jsdom 中 mock 该请求为最小成功响应,
// 使 launcher 呈现状态机进入 resolved,`.ask-ai-fab` 稳定出现。
vi.stubGlobal(
  "fetch",
  vi.fn(async () => new Response(JSON.stringify({ launcher_presentation: null }), { status: 200 })),
);

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <LoginChat />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const AFFECTED = [
  ["数据源列表", "/data-sources"],
  ["数据源详情", "/data-sources/store-woo"],
  ["技术洞察", "/analytics"],
] as const;

const UNAFFECTED = [["对话审查", "/conversations"]] as const;

describe("LoginChat FAB KB-OPS suppression (V-2)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ launcher_presentation: null }), { status: 200 }),
      ),
    );
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it.each(AFFECTED)("受抑面 %s(%s) 不渲染浮动 FAB", (_name, path) => {
    const { container } = renderAt(path);
    expect(container.querySelector("#ask-ai-widget-root .ask-ai-fab")).toBeNull();
  });

  it.each(UNAFFECTED)("非受抑面 %s(%s) 仍渲染浮动 FAB", async (_name, path) => {
    const { container } = renderAt(path);
    await waitFor(
      () => expect(container.querySelector("#ask-ai-widget-root .ask-ai-fab")).not.toBeNull(),
      { timeout: 3000 },
    );
  });
});
