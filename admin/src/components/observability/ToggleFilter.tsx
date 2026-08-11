/** 单 toggle 按钮(active/inactive 两态,Phase 2 快速筛选栏用)。 */
export default function ToggleFilter({
  label,
  active,
  onToggle,
  color = "var(--acc)",
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
  color?: string;
}) {
  return (
    <button
      type="button"
      data-active={active}
      data-toggle={label}
      onClick={onToggle}
      className="h-8 rounded-md border px-3 text-[12px] transition"
      style={{
        background: active ? color : "var(--panel)",
        borderColor: active ? color : "var(--bd)",
        color: active ? "#fff" : "var(--t2)",
      }}
    >
      {label}
    </button>
  );
}
