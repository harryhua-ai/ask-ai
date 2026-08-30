/** C9 上传工具:文件批次切分 + webkit 相对路径提取。 */

export interface UploadItem {
  file: File;
  /** 相对路径(目录上传时为 webkitRelativePath,单文件为文件名) */
  path: string;
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
