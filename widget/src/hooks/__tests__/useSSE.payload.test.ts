import { describe, it, expect, beforeEach } from "vitest";
import { buildAskBody, consumeSSE } from "../useSSE";
import type { ChatMessage } from "../../types";

const HISTORY: ChatMessage[] = [
  { id: "1", type: "user", content: "第一问" },
  { id: "2", type: "assistant", content: "第一答" },
];

describe("buildAskBody(请求体契约)", () => {
  beforeEach(() => {
    localStorage.setItem("ask_ai_session_id", "sess-123");
  });

  it("legacy:精确键集合,不含任何 site 键", () => {
    const body = buildAskBody("NE503 功耗", HISTORY, "widget", ["att-1"]);
    expect(Object.keys(body).sort()).toEqual([
      "attachments",
      "channel",
      "conversation_history",
      "message",
      "session_id",
    ]);
    expect(body).toMatchObject({
      message: "NE503 功耗",
      channel: "widget",
      session_id: "sess-123",
      attachments: ["att-1"],
    });
    expect(body.conversation_history).toEqual([
      { role: "user", content: "第一问" },
      { role: "assistant", content: "第一答" },
    ]);
  });

  it("站点态:附加 site_id / page_context / language", () => {
    const body = buildAskBody("Is NE503 good?", [], "widget", [], {
      siteId: "camthink-store",
      pageContext: { url: "https://store.example/p", title: "NE503", language: "en-US" },
      language: "en",
    });
    expect(body.site_id).toBe("camthink-store");
    expect(body.page_context).toEqual({
      url: "https://store.example/p",
      title: "NE503",
      language: "en-US",
    });
    expect(body.language).toBe("en");
  });

  it("无 extra 时 language 键不出现(不发送空键)", () => {
    const body = buildAskBody("q", [], "widget", []);
    expect("language" in body).toBe(false);
    expect("site_id" in body).toBe(false);
    expect("page_context" in body).toBe(false);
  });
});

describe("consumeSSE:403 语义区分", () => {
  it("legacy 403 → 附件无权文案(既有契约不变)", async () => {
    const errors: string[] = [];
    await consumeSSE(new Response("", { status: 403 }), {
      onSources: () => {},
      onToken: () => {},
      onDone: () => {},
      onError: (m) => errors.push(m),
    });
    expect(errors).toEqual(["无权访问所选附件。"]);
  });

  it("站点受限 403 → 站点未授权文案", async () => {
    const errors: string[] = [];
    await consumeSSE(
      new Response("", { status: 403 }),
      { onSources: () => {}, onToken: () => {}, onDone: () => {}, onError: (m) => errors.push(m) },
      { siteRestricted: true },
    );
    expect(errors).toEqual(["此站点未被授权使用 Ask AI。"]);
  });
});
