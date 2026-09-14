import { describe, expect, it } from "vitest";
import {
  documentDeltaSummary,
  hasAuthoritativeDocumentDelta,
} from "@/lib/syncDeltaPresentation";

describe("#65 sync delta presentation", () => {
  it("renders only the explicit document-level delta contract", () => {
    const log = {
      items_new: 99,
      items_deleted: 88,
      items_unchanged: 77,
      chunks_written: 66,
      delta_counts: {
        schema_version: 1,
        unit: "document",
        new_count: 2,
        new_unit: "document",
        updated_count: 3,
        updated_unit: "document",
        retired_count: 1,
        retired_unit: "document",
        unchanged_count: 4,
        unchanged_unit: "document",
      },
    };

    expect(hasAuthoritativeDocumentDelta(log)).toBe(true);
    expect(documentDeltaSummary(log)).toEqual([
      "新增知识 2",
      "更新知识 3",
      "淘汰知识 1",
      "未变更知识 4",
    ]);
  });

  it("does not infer document changes from historical mixed fields", () => {
    const log = {
      items_new: 2,
      items_deleted: 1,
      items_unchanged: 4,
      chunks_written: 99,
      delta_counts: null,
    };

    expect(hasAuthoritativeDocumentDelta(log)).toBe(false);
    expect(documentDeltaSummary(log)).toEqual(["变更单位不可用（历史记录）"]);
  });
});
