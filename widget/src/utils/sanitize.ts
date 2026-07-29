// 安全 Markdown 渲染:DOMPurify 预清洗 + HTML 转义 + 有限格式化 + DOMPurify 兜底
// 防止 LLM 输出中的 XSS 注入(<script> / <img onerror> 等)

import DOMPurify from "dompurify";

const ALLOWED_TAGS = ["p", "br", "strong", "em", "code", "pre", "h4", "ul", "ol", "li", "a"];
const ALLOWED_ATTR = ["href", "target", "rel"];

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

/**
 * 安全 Markdown 渲染(三层防护):
 * 1. DOMPurify 预清洗原始输入 —— 直接移除 <script> / <img onerror> 等危险标签
 * 2. HTML 转义 —— 防止残余 HTML 字符被浏览器解析为标签
 * 3. 应用有限 Markdown 格式化(代码块/粗体/列表等)
 * 4. DOMPurify 兜底 —— 防止格式化过程引入的残余风险
 */
export function renderMarkdownSafe(text: string): string {
  // 预清洗:先移除危险标签(img/script 等),避免 onerror 等属性出现在输出中
  const cleaned = sanitizeHtml(text);
  let html = escapeHtml(cleaned);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^#{1,6} (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
  html = html.replace(/\n/g, "<br>");
  return sanitizeHtml(html);
}
