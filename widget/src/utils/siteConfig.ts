// 站点体验配置获取与 starters 解析(MSW)。
// fail-safe 契约:site-config 拉取失败(403/网络错)不阻断 Widget —— 回退默认
// 体验;site_id 仍随 ask 发送,由服务端裁决(未授权 → SSE 层可见失败)。
import type { SiteExperienceConfig } from "../types";

/** 拉取站点体验配置;非 2xx 抛错(含状态码)。 */
export async function fetchSiteConfig(
  apiUrl: string,
  siteId: string,
  signal?: AbortSignal,
): Promise<SiteExperienceConfig> {
  const resp = await fetch(
    `${apiUrl}/api/widget/site-config?site_id=${encodeURIComponent(siteId)}`,
    { signal },
  );
  if (!resp.ok) {
    throw new Error(`site-config ${resp.status}`);
  }
  return resp.json();
}

/** starters 解析:站点有效 starters 优先(≤8 条),否则回退默认(legacy 行为)。 */
export function resolveStarters(
  site: SiteExperienceConfig | null,
  defaults: string[],
): string[] {
  const starters = site?.starters;
  return Array.isArray(starters) && starters.length > 0
    ? starters.slice(0, 8)
    : defaults;
}
