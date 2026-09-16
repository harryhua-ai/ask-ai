// 安全 Markdown 渲染:DOMPurify 预清洗 + HTML 转义 + 有限格式化 + DOMPurify 兜底
// 防止 LLM 输出中的 XSS 注入(<script> / <img onerror> 等)

import DOMPurify from "dompurify";
import type { SourceLink } from "../types";
import { isAllowedUrl } from "./urlPolicy";

const ALLOWED_TAGS = ["p", "br", "strong", "em", "code", "pre", "h4", "span", "ul", "ol", "li", "a"];
const ALLOWED_ATTR = ["href", "target", "rel", "class", "title"];

/** Track C C-3:非可点击状态的真值 title(诚实呈现,不伪造导航)。 */
const NON_CLICKABLE_TITLES: Record<string, string> = {
  none: "此来源不提供外部链接",
  private: "此来源不对外公开",
  stale: "来源可能已移动或失效",
  legacy: "",
};

/** DOMPurify 清洗,移除危险标签/属性 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function unescapeHtml(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'");
}

/**
 * 安全 Markdown 渲染(三层防护):
 * 1. DOMPurify 预清洗原始输入 —— 直接移除 <script> / <img onerror> 等危险标签
 * 2. HTML 转义 —— 防止残余 HTML 字符被浏览器解析为标签
 * 3. 应用有限 Markdown 格式化(代码块/粗体/链接/列表等)
 * 4. DOMPurify 兜底 —— 防止格式化过程引入的残余风险
 */
export function renderMarkdownSafe(text: string, sources?: SourceLink[]): string {
  const cleaned = sanitizeHtml(text);
  let html = escapeHtml(cleaned);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_, linkText: string, rawUrl: string) => {
      const url = unescapeHtml(rawUrl.trim());
      if (isAllowedUrl(url)) {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${linkText}</a>`;
      }
      return linkText;
    },
  );
  html = html.replace(/^#{1,6} (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.+<\/li>\n?)+)/g, (m) => `<ul>${m.trim().replace(/\n/g, "")}</ul>`);
  if (sources && sources.length > 0) {
    const lines = html.split("\n");
    // CIT-01:代码块(<pre><code>)内的 [N] 是数组下标等代码内容,不是引用
    // 标记——整块跳过,防止引用处理吞掉代码内容或误挂徽标。
    let inPre = false;
    html = lines.map((line) => {
      if (!inPre && line.includes("<pre>")) {
        if (!line.includes("</pre>")) inPre = true;
        return line;
      }
      if (inPre) {
        if (line.includes("</pre>")) inPre = false;
        return line;
      }
      const found = new Set<number>();
      const cleaned = line.replace(/\[(\d+)\]/g, (_, n: string) => {
        const idx = parseInt(n, 10) - 1;
        if (sources[idx]) found.add(idx);
        return "";
      });
      if (found.size === 0) return cleaned;
      const icons = Array.from(found).map((i) => {
        const src = sources[i];
        // T29:数字徽标 —— 锚点文本 = 引用编号 n,title = 来源标题(转义,防属性逃逸/注入)
        // Issue #48 / Track C C-2/C-3:可点击性 = 后端显式 link_state 权威,
        // widget 不从 URL 字符串形状推断;isAllowedUrl 仅作纵深安全门
        // (只降级、不升级)。存量载荷(无 link_state 的历史会话)回退到
        // URL 安全门 + 非空守卫 —— 行为与历史基线一致,且关闭 href=""/
        // off-host/file:// 假链接(C-2:禁自跳转与死链)。
        const stateClickable =
          src.link_state === undefined
            ? Boolean(src.url) && isAllowedUrl(src.url)
            : src.link_state === "external";
        if (stateClickable && isAllowedUrl(src.url)) {
          return `<a href="${escapeHtml(src.url)}" title="${escapeHtml(src.title ?? "")}" class="ask-ai-ref" target="_blank" rel="noopener noreferrer">${i + 1}</a>`;
        }
        // 非 external 状态:真值静态徽标(无 <a>、无 href —— 禁伪造导航),
        // title 按 state 如实说明(C-3 truthful representation)。
        const reason =
          NON_CLICKABLE_TITLES[src.link_state ?? "legacy"] ?? NON_CLICKABLE_TITLES.legacy;
        return `<span class="ask-ai-ref ask-ai-ref-static" title="${escapeHtml(reason)}">${i + 1}</span>`;
      });
      const trimmed = cleaned.replace(/[。，、.;；\s]+$/, "");
      const isChinese = /[一-鿿]/.test(trimmed);
      const period = isChinese ? "。" : ".";
      return `${trimmed}${period} ${icons.join(" ")}`;
    }).join("\n");
  }
  html = html.replace(/\n/g, "<br>");
  return sanitizeHtml(html);
}
