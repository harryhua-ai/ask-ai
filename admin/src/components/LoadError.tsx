/** AFP-CLOSURE-01:请求失败显式态(REQUEST_FAILURE ≠ EMPTY_DATA)。
 *
 * 查询失败必须以本组件呈现,不得渲染为空表/零值 KPI/常规空文案;
 * 语义上与 NoPermission(无权限)、各页空态(「暂无 X」)三态互斥可辨。
 *
 * compact 变体用于「已有上一批成功数据、后台刷新失败」场景:横幅提示
 * 失败,同时保留既有内容(不把最后已知数据替换成整页错误)。
 */

interface Props {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}

export default function LoadError({ error, onRetry, compact = false }: Props) {
  const detail =
    error instanceof Error && error.message ? error.message : "请求失败,请稍后再试";
  return (
    <div
      data-load-error
      data-compact={compact || undefined}
      role="alert"
      className={
        compact
          ? "mb-3 rounded-lg border p-3 text-[13px]"
          : "rounded-lg border p-8 text-center"
      }
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className={`font-medium text-[var(--err)] ${compact ? "" : "text-[15px]"}`}>
        加载失败
      </div>
      <div className={`mt-1 text-[var(--t2)] ${compact ? "" : "text-[13px]"}`}>{detail}</div>
      {onRetry && (
        <button
          type="button"
          data-load-error-retry
          onClick={onRetry}
          className="mt-3 rounded-md border px-3 py-1.5 text-[13px] text-[var(--t1)] hover:bg-accent"
          style={{ borderColor: "var(--bd)" }}
        >
          重试
        </button>
      )}
    </div>
  );
}
