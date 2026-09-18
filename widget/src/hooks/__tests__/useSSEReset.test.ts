import { describe, it, expect, beforeEach } from "vitest";
import { buildAskBody, rotateSessionId } from "../useSSE";
import type { ChatMessage } from "../../types";

// #87 REPLAN(a):「新对话」= 显式轮换 ask_ai_session_id。
// 冻结语义(A 2026-09-18,PR #98 评论 5729885652):
// - session_id 只能被显式「新对话」改变;普通 ask / 页面刷新一律保持原值;
// - 轮换后第一个 ask 携带新 session_id(空 history 由调用方清 transcript 保证)。

const HISTORY: ChatMessage[] = [{ id: "1", type: "user", content: "第一问" }];

describe("rotateSessionId(#87 新对话轮换原语)", () => {
  beforeEach(() => {
    localStorage.setItem("ask_ai_session_id", "sess-before");
  });

  it("显式轮换返回新 id,且后续 ask 使用新 id", () => {
    const rotated = rotateSessionId();
    expect(rotated).not.toBe("sess-before");
    const body = buildAskBody("下一问", HISTORY, "widget");
    expect(body.session_id).toBe(rotated);
  });

  it("未轮换时普通 ask 保持原 session_id(刷新/连续提问不改变身份)", () => {
    expect(buildAskBody("问1", [], "widget").session_id).toBe("sess-before");
    expect(buildAskBody("问2", HISTORY, "widget").session_id).toBe("sess-before");
  });

  it("两次轮换产生互不相同的新 id(每次新对话都是新 Thread 身份)", () => {
    const first = rotateSessionId();
    const second = rotateSessionId();
    expect(first).not.toBe(second);
    expect(buildAskBody("问", [], "widget").session_id).toBe(second);
  });

  it("轮换是无网络动作:只写 localStorage,不发任何请求", () => {
    const before = localStorage.getItem("ask_ai_session_id");
    rotateSessionId();
    expect(localStorage.getItem("ask_ai_session_id")).not.toBe(before);
  });
});
