/** C9 上传工具:文件批次切分 + 相对路径提取 + 系统/白名单过滤。 */

export interface UploadItem {
  file: File;
  /** 相对路径(目录上传时为 webkitRelativePath,单文件为文件名) */
  path: string;
}

const JUNK_BASENAMES = new Set([".ds_store", "thumbs.db", "desktop.ini"]);

/** 系统元数据文件(macOS .DS_Store/AppleDouble、Windows 缩略图等),永远不是语料。 */
export function isJunkPath(path: string): boolean {
  const norm = path.replace(/\\/g, "/").toLowerCase();
  const base = norm.split("/").pop() ?? "";
  if (JUNK_BASENAMES.has(base)) return true;
  if (base.startsWith("._")) return true;
  return norm.startsWith("__macosx/");
}

/** 把数组切成固定大小的批次(末批可能不足 size)。 */
export function splitIntoBatches<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];
  const batches: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    batches.push(items.slice(i, i + size));
  }
  return batches;
}

/** File 列表 → 上传项(路径取 webkitRelativePath,缺省用文件名)。 */
export function toUploadItems(files: File[]): UploadItem[] {
  return files.map((f) => ({
    file: f,
    path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name,
  }));
}

/**
 * 按源白名单后缀过滤(空=全部保留);系统垃圾文件即使命中也跳过。
 * 返回保留与被跳过两组,调用方据此提示"跳过 N 个"并只上传保留项。
 */
export function filterByWhitelist(
  items: UploadItem[],
  types: string[],
): { kept: UploadItem[]; skipped: UploadItem[] } {
  const whitelist = types
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean)
    .map((t) => (t.startsWith(".") ? t : `.${t}`));
  const kept: UploadItem[] = [];
  const skipped: UploadItem[] = [];
  for (const it of items) {
    if (isJunkPath(it.path)) {
      skipped.push(it);
      continue;
    }
    if (whitelist.length === 0) {
      kept.push(it);
      continue;
    }
    const base = it.path.replace(/\\/g, "/").split("/").pop() ?? "";
    const ext = base.slice(base.lastIndexOf(".")).toLowerCase();
    if (whitelist.includes(ext)) kept.push(it);
    else skipped.push(it);
  }
  return { kept, skipped };
}
