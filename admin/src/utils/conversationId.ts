/** Stable administrator-facing rendering of the authoritative conversation id. */
export function conversationIdLabel(id: string): string {
  const value = id.trim();
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}
