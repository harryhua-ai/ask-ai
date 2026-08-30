import { describe, it, expect } from "vitest";
import { splitIntoBatches, toUploadItems } from "./upload";

describe("splitIntoBatches", () => {
  it("120 项按 50 切批 → 50/50/20", () => {
    const items = Array.from({ length: 120 }, (_, i) => i);
    const batches = splitIntoBatches(items, 50);
    expect(batches.map((b) => b.length)).toEqual([50, 50, 20]);
  });

  it("不足一批 → 单批", () => {
    expect(splitIntoBatches([1, 2, 3], 50).map((b) => b.length)).toEqual([3]);
  });

  it("size 非法(<=0)→ 不切分,原样单批返回", () => {
    expect(splitIntoBatches([1, 2], 0)).toEqual([[1, 2]]);
  });
});

describe("toUploadItems", () => {
  it("优先 webkitRelativePath,缺省回退文件名", () => {
    const withPath = {
      name: "a.md",
      webkitRelativePath: "knowledge/docs/a.md",
    } as File;
    const plain = { name: "b.md" } as File;
    const items = toUploadItems([withPath, plain]);
    expect(items[0].path).toBe("knowledge/docs/a.md");
    expect(items[1].path).toBe("b.md");
  });
});
