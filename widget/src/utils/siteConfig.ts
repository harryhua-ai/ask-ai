// 站点体验配置获取与 starters 解析(MSW)。
// fail-safe 契约:site-config 拉取失败(403/网络错)不阻断 Widget —— 回退默认
// 体验;site_id 仍随 ask 发送,由服务端裁决(未授权 → SSE 层可见失败)。
import type { SiteExperienceConfig } from "../types";

/**
 * Issue #33:launcher 外观权威解析的确定性上界(PENDING ≠ FAILED)。
 * 超时 = RESOLUTION_FAILED → 确定性回退默认可用外观(绝不永久空白)。
 * 取值须覆盖慢网(3G 级 RTT)下正常到达的配置,又不让 launcher 长期缺席。
 */
export const LAUNCHER_RESOLUTION_TIMEOUT_MS = 5000;

/** 拉取站点体验配置;非 2xx 抛错(含状态码)。
 *  ML 闭环(G-L5):language 可选 —— 服务端按归一化语言返回本地化
 *  welcome/starters 变体,无变体时回落站点默认。 */
export async function fetchSiteConfig(
  apiUrl: string,
  siteId: string,
  options?: { language?: string; signal?: AbortSignal },
): Promise<SiteExperienceConfig> {
  const params = new URLSearchParams({ site_id: siteId });
  if (options?.language) params.set("language", options.language);
  const resp = await fetch(
    `${apiUrl}/api/widget/site-config?${params.toString()}`,
    { signal: options?.signal },
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
