// 来源链接 URL 策略:协议白名单 + 域名白名单
// 拦截 javascript: / data: 等危险协议与非官方域名

const ALLOWED_PROTOCOLS = ["http:", "https:"];
const ALLOWED_HOSTS = [
  "github.com",
  "raw.githubusercontent.com",
  "camthink.ai",
  "wiki.camthink.ai",
  "docs.camthink.ai",
];

/**
 * 来源链接协议 + 域白名单校验:
 * - 仅允许 http/https 协议(拦截 javascript: / data:)
 * - 仅允许白名单域名(含子域名)
 */
export function isAllowedUrl(url: string): boolean {
  try {
    const u = new URL(url);
    if (!ALLOWED_PROTOCOLS.includes(u.protocol)) return false;
    return ALLOWED_HOSTS.some(
      (h) => u.hostname === h || u.hostname.endsWith("." + h),
    );
  } catch {
    return false;
  }
}
