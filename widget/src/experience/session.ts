// I-UX-001:站点会话级主动展开闸(冻结 §2.2/§2.11)。
//
// - 主动展开(C 自动展开 / 移动端 nudge 主动呈现)**每站点会话至多一次**;
// - 用户 minimize / dismiss / not-now → 本会话剩余时间内尊重,不再主动;
// - SPA 导航不得重触发(状态在 sessionStorage,与页面上下文无关);
// - sessionStorage 不可用(sandbox iframe / 隐私模式)→ 会话闸退化为
//   进程内内存闸(确定性:同一 JS 生命周期内仍然至多一次),不抛错。

const KEY_PREFIX = "ask-ai-exp:";

/** 会话闸状态:expanded = 已主动过;dismissed = 用户明确不要(更强)。 */
export type SessionGateValue = "expanded" | "dismissed";

const memoryGate = new Map<string, SessionGateValue>();

function storageKey(siteId: string | undefined): string {
  return `${KEY_PREFIX}${siteId ?? "default"}`;
}

function readGate(siteId: string | undefined, win: Window | null): SessionGateValue | null {
  try {
    const raw = win?.sessionStorage?.getItem(storageKey(siteId));
    return raw === "expanded" || raw === "dismissed" ? raw : null;
  } catch {
    return memoryGate.get(storageKey(siteId)) ?? null;
  }
}

function writeGate(
  siteId: string | undefined,
  value: SessionGateValue,
  win: Window | null,
): void {
  try {
    win?.sessionStorage?.setItem(storageKey(siteId), value);
  } catch {
    // sandbox/隐私模式:退化为进程内内存闸
  }
  memoryGate.set(storageKey(siteId), value);
}

/** 本会话是否已消费主动展开机会(含用户明确关闭)。 */
export function proactiveAlreadyUsed(
  siteId: string | undefined,
  win: Window | null = typeof window === "undefined" ? null : window,
): boolean {
  return readGate(siteId, win) !== null;
}

/** 用户本会话明确关闭(minimize/dismiss/not-now)→ 不再任何主动呈现。 */
export function userDismissedProactive(
  siteId: string | undefined,
  win: Window | null = typeof window === "undefined" ? null : window,
): boolean {
  return readGate(siteId, win) === "dismissed";
}

/** 标记主动展开已发生(每站点会话一次)。 */
export function markProactiveShown(
  siteId: string | undefined,
  win: Window | null = typeof window === "undefined" ? null : window,
): void {
  if (readGate(siteId, win) === null) {
    writeGate(siteId, "expanded", win);
  }
}

/** 标记用户明确关闭(覆盖 expanded;本会话剩余时间尊重)。 */
export function markProactiveDismissed(
  siteId: string | undefined,
  win: Window | null = typeof window === "undefined" ? null : window,
): void {
  writeGate(siteId, "dismissed", win);
}
