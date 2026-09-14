import { describe, expect, it } from "vitest";
import { conversationIdLabel } from "@/utils/conversationId";

describe("conversationIdLabel", () => {
  it("keeps the canonical id visible in a compact stable form", () => {
    const id = "123e4567-e89b-12d3-a456-426614174000";
    expect(conversationIdLabel(id)).toBe("123e4567…4000");
  });

  it("does not create a display id for short or blank values", () => {
    expect(conversationIdLabel("abc")).toBe("abc");
    expect(conversationIdLabel("  ")).toBe("");
  });
});
