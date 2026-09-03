/**
 * P1 生成可靠性 — Widget SSE 流消费端契约(AC-07)。
 *
 * 验证真实 Widget 流消费路径(consumeSSE,useSSE 内部复用)对失败信号的
 * 处理:后端新增 error 事件、既有 declined 事件都必须变成用户可见回调,
 * 未知事件不得崩溃(向后兼容旧服务端)。
 */
import { describe, expect, it, vi } from "vitest";

import { consumeSSE } from "../useSSE";
import type { SSECallbacks } from "../useSSE";

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

function makeCallbacks() {
  return {
    onSources: vi.fn(),
    onToken: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  } satisfies SSECallbacks & Record<string, ReturnType<typeof vi.fn>>;
}

function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("consumeSSE — 正常流(REL-G004)", () => {
  it("sources → token → done 依次分发,done 恰好一次", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("sources", { conversation_id: "c1", sources: [{ url: "u" }] }),
      sse("token", { content: "Hello" }),
      sse("token", { content: " world" }),
      sse("done", { conversation_id: "c1" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onSources).toHaveBeenCalledWith([{ url: "u" }], "c1");
    expect(cb.onToken).toHaveBeenNthCalledWith(1, "Hello");
    expect(cb.onToken).toHaveBeenNthCalledWith(2, " world");
    expect(cb.onDone).toHaveBeenCalledTimes(1);
    expect(cb.onDone).toHaveBeenCalledWith("c1");
    expect(cb.onError).not.toHaveBeenCalled();
  });
});

describe("consumeSSE — 失败信号可见(REL-G001/002/003)", () => {
  it("error 事件分发 onError(消息 + kind)", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("token", { content: "服务暂时不可用,请稍后再试。" }),
      sse("error", {
        conversation_id: "c1",
        kind: "empty_generation",
        message: "服务暂时不可用,请稍后再试。",
      }),
      sse("done", { conversation_id: "c1" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onError).toHaveBeenCalledWith(
      "服务暂时不可用,请稍后再试。",
      { kind: "empty_generation" },
    );
    expect(cb.onDone).toHaveBeenCalledWith("c1");
  });

  it("declined 事件(预算熔断)分发 onError(reason)", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("declined", { reason: "服务繁忙,请稍后再试" }),
      sse("done", { conversation_id: "c2" }),
    ]);
    await consumeSSE(resp, cb);
    // 阶段⑯:declined 回调恒带 meta(旧调用方按位置参数消费,兼容);reason 缺失回落中文常量
    expect(cb.onError).toHaveBeenCalledWith("服务繁忙,请稍后再试", {
      messageKey: undefined,
    });
    expect(cb.onDone).toHaveBeenCalledWith("c2");
  });
});

describe("consumeSSE — 阶段⑯:本地化与 message_key 兼容", () => {
  it("error 事件透传 message_key(message 恒为主显示,旧字段不缺位)", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("error", {
        conversation_id: "c1",
        kind: "provider_error",
        message: "The service is temporarily unavailable. Please try again later.",
        message_key: "service_unavailable",
      }),
      sse("done", { conversation_id: "c1" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onError).toHaveBeenCalledWith(
      "The service is temporarily unavailable. Please try again later.",
      { kind: "provider_error", messageKey: "service_unavailable" },
    );
  });

  it("message 缺失时回落注入的双语兜底(而非固定中文)", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("error", { conversation_id: "c1", kind: "empty_generation" }),
      sse("done", { conversation_id: "c1" }),
    ]);
    await consumeSSE(resp, cb, {
      messages: {
        serviceUnavailable: "EN fallback",
        budgetDeclined: "EN busy",
      },
    });
    expect(cb.onError).toHaveBeenCalledWith("EN fallback", {
      kind: "empty_generation",
      messageKey: undefined,
    });
  });

  it("不传 messages 时保持既有中文兜底(向后兼容)", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("error", { conversation_id: "c1", kind: "provider_error" }),
      sse("done", { conversation_id: "c1" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onError).toHaveBeenCalledWith("服务暂时不可用,请稍后再试。", {
      kind: "provider_error",
      messageKey: undefined,
    });
  });

  it("declined 透传 message_key 并回落注入的 busy 文案", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("declined", {
        reason: "The service is busy right now. Please try again shortly.",
        message_key: "budget_declined",
        conversation_id: "c9",
      }),
      sse("done", { conversation_id: "c9" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onError).toHaveBeenCalledWith(
      "The service is busy right now. Please try again shortly.",
      { messageKey: "budget_declined" },
    );
  });
});

describe("consumeSSE — 健壮性", () => {
  it("未知事件类型忽略,不崩溃不误报", async () => {
    const cb = makeCallbacks();
    const resp = sseResponse([
      sse("future_event", { foo: 1 }),
      sse("done", { conversation_id: "c3" }),
    ]);
    await consumeSSE(resp, cb);
    expect(cb.onDone).toHaveBeenCalledTimes(1);
    expect(cb.onError).not.toHaveBeenCalled();
  });

  it("非 2xx HTTP 响应不作为 SSE 解析,走 onError 固定文案", async () => {
    const cb = makeCallbacks();
    await consumeSSE(new Response("boom", { status: 500 }), cb);
    expect(cb.onSources).not.toHaveBeenCalled();
    expect(cb.onToken).not.toHaveBeenCalled();
    expect(cb.onDone).not.toHaveBeenCalled();
    expect(cb.onError).toHaveBeenCalledTimes(1);
    expect(String(cb.onError.mock.calls[0][0])).toContain("服务暂时不可用");
  });
});
