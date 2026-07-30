import { Button } from "@/components/ui/button";

interface PaginationProps {
  /** 当前页码（从 1 开始） */
  page: number;
  /** 翻页回调，接收新的页码 */
  onPageChange: (page: number) => void;
  /** 是否还有下一页，默认 true。为 false 时禁用「下一页」按钮 */
  hasMore?: boolean;
}

/**
 * 极简分页组件：上一页 / 当前页码 / 下一页。
 * 提取自用户管理页面的内联分页，可在其他列表页复用。
 */
export function Pagination({ page, onPageChange, hasMore = true }: PaginationProps) {
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
      >
        上一页
      </Button>
      <span className="text-sm">第 {page} 页</span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(page + 1)}
        disabled={!hasMore}
      >
        下一页
      </Button>
    </div>
  );
}
