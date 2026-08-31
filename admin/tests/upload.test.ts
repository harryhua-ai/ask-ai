import { describe, it, expect } from "vitest";
import { splitIntoBatches, toUploadItems, isJunkPath, filterByWhitelist } from "@/utils/upload";
import type { UploadItem } from "@/utils/upload";

function fakeFile(name: string, relPath?: string): File {
  const f = { name } as File;
  if (relPath !== undefined) {
    Object.defineProperty(f, "webkitRelativePath", { value: relPath });
  }
  return f;
}

function itemsOf(...paths: string[]): UploadItem[] {
  return paths.map((p) => {
    const base = p.split("/").pop() ?? p;
    return { file: fakeFile(base, p), path: p };
  });
}

describe("splitIntoBatches", () => {
  it("按固定大小切分,末批可不足", () => {
    const batches = splitIntoBatches([1, 2, 3, 4, 5], 2);
    expect(batches).toEqual([[1, 2], [3, 4], [5]]);
  });

  it("size<=0 时整体单批返回", () => {
    expect(splitIntoBatches([1, 2], 0)).toEqual([[1, 2]]);
  });
});

describe("toUploadItems", () => {
  it("目录上传取 webkitRelativePath,单文件退回文件名", () => {
    const [a, b] = toUploadItems([fakeFile("a.md", "docs/a.md"), fakeFile("b.md")]);
    expect(a.path).toBe("docs/a.md");
    expect(b.path).toBe("b.md");
  });
});

describe("isJunkPath", () => {
  it("识别 macOS/Windows 系统元数据文件", () => {
    expect(isJunkPath(".DS_Store")).toBe(true);
    expect(isJunkPath("docs/.DS_Store")).toBe(true);
    expect(isJunkPath("docs/._report.md")).toBe(true); // AppleDouble
    expect(isJunkPath("__MACOSX/docs/a.md")).toBe(true);
    expect(isJunkPath("Thumbs.db")).toBe(true);
    expect(isJunkPath("desktop.ini")).toBe(true);
  });

  it("正常语料文件不算垃圾", () => {
    expect(isJunkPath("docs/report.md")).toBe(false);
    expect(isJunkPath("docs/setup.sh")).toBe(false);
    expect(isJunkPath("docs/.hidden.md")).toBe(false);
  });
});

describe("filterByWhitelist", () => {
  it("按白名单后缀过滤,垃圾文件即使命中白名单也跳过", () => {
    const all = itemsOf("a.md", "b.txt", "sub/.DS_Store", "c.md", "._d.md");
    const { kept, skipped } = filterByWhitelist(all, [".md"]);
    expect(kept.map((i) => i.path)).toEqual(["a.md", "c.md"]);
    expect(skipped.map((i) => i.path)).toEqual(["b.txt", "sub/.DS_Store", "._d.md"]);
  });

  it("白名单为空=全部保留(垃圾文件仍跳过)", () => {
    const all = itemsOf("a.md", "b.unknownext", ".DS_Store");
    const { kept, skipped } = filterByWhitelist(all, []);
    expect(kept.map((i) => i.path)).toEqual(["a.md", "b.unknownext"]);
    expect(skipped).toHaveLength(1);
  });

  it("白名单带大写或无点前缀时归一化匹配", () => {
    const all = itemsOf("A.MD", "b.sh", "c.txt");
    const { kept, skipped } = filterByWhitelist(all, ["md", ".SH"]);
    expect(kept.map((i) => i.path)).toEqual(["A.MD", "b.sh"]);
    expect(skipped.map((i) => i.path)).toEqual(["c.txt"]);
  });

  it("无后缀文件在非空白名单下被跳过", () => {
    const all = itemsOf("README", "a.md");
    const { kept, skipped } = filterByWhitelist(all, [".md"]);
    expect(kept.map((i) => i.path)).toEqual(["a.md"]);
    expect(skipped.map((i) => i.path)).toEqual(["README"]);
  });

  it("全部被过滤时 kept 为空(调用方据此回滚空源)", () => {
    const { kept } = filterByWhitelist(itemsOf(".DS_Store", "._x.md"), []);
    expect(kept).toHaveLength(0);
  });
});
