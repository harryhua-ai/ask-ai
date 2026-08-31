import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Loader2,
} from "lucide-react";

import { usePreviewDirs } from "@/hooks/useDataSources";
import { ApiError } from "@/lib/api";

interface DirPickerProps {
  /** 数据源 root_path(已填才渲染本组件,但内部仍做空值兜底)。 */
  rootPath: string;
  /** 已选目录路径数组(相对 root_path)。 */
  value: string[];
  /** 勾选变更回调,传入新的目录数组(不可变更新)。 */
  onChange: (dirs: string[]) => void;
  /** 目录不存在(404)时展示的友好提示;不传则按错误显示(服务器路径模式需要真实报错)。 */
  missingHint?: string;
}

/**
 * 目录选择器:浏览 root_path 下子目录树(递归 2 层)+ Checkbox 勾选。
 * 顶层目录可展开/折叠显示第二层;勾选结果写入 include_dirs。
 * 数据由 usePreviewDirs 懒拉,rootPath 变才重拉(react-query cache)。
 */
export function DirPicker({ rootPath, value, onChange, missingHint }: DirPickerProps) {
  const { data, isLoading, error } = usePreviewDirs(rootPath);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (!rootPath) {
    return <p className="text-xs text-muted-foreground">请先填 root_path</p>;
  }
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> 加载目录...
      </div>
    );
  }
  if (error) {
    if (missingHint && error instanceof ApiError && error.status === 404) {
      return <p className="text-xs text-muted-foreground">{missingHint}</p>;
    }
    return (
      <p className="text-xs text-destructive">
        目录加载失败:{error instanceof Error ? error.message : "未知错误"}
      </p>
    );
  }

  const dirs = data?.dirs ?? [];
  if (dirs.length === 0) {
    return <p className="text-xs text-muted-foreground">该目录下无可选子目录</p>;
  }

  const toggleCheck = (p: string) => {
    onChange(value.includes(p) ? value.filter((v) => v !== p) : [...value, p]);
  };
  const toggleExpand = (p: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(p)) {
        next.delete(p);
      } else {
        next.add(p);
      }
      return next;
    });
  };

  return (
    <div className="max-h-60 overflow-auto rounded border p-2 text-sm">
      {dirs.map((d) => {
        const isExpanded = expanded.has(d.path);
        const hasChildren = d.children_count > 0;
        return (
          <div key={d.path} className="py-0.5">
            <div className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={value.includes(d.path)}
                onChange={() => toggleCheck(d.path)}
                className="h-3.5 w-3.5"
              />
              <button
                type="button"
                onClick={() => toggleExpand(d.path)}
                className="flex items-center gap-1 hover:underline disabled:opacity-50 disabled:no-underline"
                disabled={!hasChildren}
                aria-label={isExpanded ? "折叠" : "展开"}
              >
                {isExpanded ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
                {isExpanded ? (
                  <FolderOpen className="h-3 w-3" />
                ) : (
                  <Folder className="h-3 w-3" />
                )}
                <span>{d.name}</span>
              </button>
              {hasChildren && (
                <span className="text-xs text-muted-foreground">({d.children_count})</span>
              )}
            </div>
            {isExpanded &&
              d.children?.map((c) => (
                <div key={c.path} className="flex items-center gap-1 py-0.5 pl-5">
                  <input
                    type="checkbox"
                    checked={value.includes(c.path)}
                    onChange={() => toggleCheck(c.path)}
                    className="h-3.5 w-3.5"
                  />
                  <Folder className="h-3 w-3" />
                  <span>{c.name}</span>
                  {c.children_count > 0 && (
                    <span className="text-xs text-muted-foreground">
                      ({c.children_count})
                    </span>
                  )}
                </div>
              ))}
          </div>
        );
      })}
    </div>
  );
}
