/** #68:卡片级 Country/Entry 紧凑元数据(权威值;Unknown 中性呈现)。
 *
 * 展示语义与后端呈现门同源:country 为 null 即 Unknown(legacy 启发式
 * 值不进入地理事实);entry 为 null 即无站点身份(不从 channel/URL 猜测)。
 * 完整值放在 title(悬停可见),不新增表格列、不降问题优先级。
 */
export function GeoEntryMeta({
  country,
  entry,
}: {
  country?: string | null;
  entry?: { site_id: string; display_name: string } | null;
}) {
  const title = [
    `国家/地区：${country ?? "未知"}`,
    entry ? `访问入口：${entry.display_name}（${entry.site_id}）` : "访问入口：未知",
  ].join("\n");
  return (
    <span
      data-geo-entry
      className="shrink-0 text-[11px] text-muted-foreground"
      title={title}
    >
      {country ?? "未知"} · {entry?.display_name ?? "未知"}
    </span>
  );
}
