/**
 * Ownership: Integration(共享工具,Wave 0B 落位)— Analytics 面板共用。
 * Wave 1 边界:纯展示工具;若 Track E(观察历史)需要新增时间语义,
 * 不得修改本函数既有行为(队列 recency / GapPanel / 会话证据共用)。
 */

/** 相对时间(权威 last_seen_at → 「N 小时前」;null → 证据不可用)。 */
export function relTime(iso: string | null): string {
  if (!iso) return "证据不可用";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "证据不可用";
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}
