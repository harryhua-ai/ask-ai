// Issue #24:launcher 图标(语义风格 → 内联 SVG/兼容资产)。
//
// - `current` 沿用既有 base64 PNG 资产(逐像素兼容,升级零外观变化);
// - 其余风格为内联矢量(零外链请求、currentColor/主题 token 原生、高 DPI 清晰);
// - 几何为 HOW,可整体重构;持久身份(语义 id)不在本文件。

import type { LauncherStyle } from "../types";
import currentLauncherAsset from "../assets/CamThink.ai-black.png";

/** 兼容风格沿用既有资产(alt 置空:可访问名由按钮 aria-label 承担,不重复)。 */
function CurrentGlyph() {
  return <img className="ask-ai-fab-icon" src={currentLauncherAsset} alt="" />;
}

/** assistant-spark:品牌渐变圆盘 + 四芒星火花(现代 AI 助手/智能)。 */
function SparkGlyph() {
  return (
    <svg className="ask-ai-fab-glyph" viewBox="0 0 24 24" role="presentation" aria-hidden="true">
      <defs>
        <linearGradient id="ask-ai-spark-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff7a33" />
          <stop offset="1" stopColor="#e03d00" />
        </linearGradient>
      </defs>
      <circle cx="12" cy="12" r="12" fill="url(#ask-ai-spark-bg)" />
      <path
        d="M12 4.6c.62 4.1 2.6 6.08 6.7 6.7-4.1.62-6.08 2.6-6.7 6.7-.62-4.1-2.6-6.08-6.7-6.7 4.1-.62 6.08-2.6 6.7-6.7z"
        fill="#ffffff"
      />
      <circle cx="17.6" cy="6.4" r="1.15" fill="#ffd9c2" />
    </svg>
  );
}

/** chat-bubble:对话气泡 + 三点(会话中心;currentColor 随主题翻转)。 */
function BubbleGlyph() {
  return (
    <svg className="ask-ai-fab-glyph" viewBox="0 0 24 24" role="presentation" aria-hidden="true">
      <path
        d="M20 2.5H4A2.5 2.5 0 0 0 1.5 5v10A2.5 2.5 0 0 0 4 17.5h3.2v2.9c0 .74.85 1.15 1.43.7l4.47-3.6H20a2.5 2.5 0 0 0 2.5-2.5V5A2.5 2.5 0 0 0 20 2.5z"
        fill="currentColor"
      />
      <circle cx="7.2" cy="10" r="1.5" fill="var(--ask-ai-launcher-surface, #111111)" />
      <circle cx="12" cy="10" r="1.5" fill="var(--ask-ai-launcher-surface, #111111)" />
      <circle cx="16.8" cy="10" r="1.5" fill="var(--ask-ai-launcher-surface, #111111)" />
    </svg>
  );
}

/** orbit-neural:细线轨道 + 节点(技术/智能系统; restrained)。 */
function OrbitGlyph() {
  return (
    <svg className="ask-ai-fab-glyph" viewBox="0 0 24 24" role="presentation" aria-hidden="true">
      <ellipse
        cx="12"
        cy="12"
        rx="9.2"
        ry="4.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        transform="rotate(-28 12 12)"
      />
      <ellipse
        cx="12"
        cy="12"
        rx="9.2"
        ry="4.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        opacity="0.45"
        transform="rotate(32 12 12)"
      />
      <circle cx="12" cy="12" r="2.4" fill="var(--ask-ai-launcher-accent, #f24a00)" />
      <circle cx="19.4" cy="8.2" r="1.35" fill="currentColor" />
      <circle cx="4.9" cy="15.4" r="1.35" fill="currentColor" />
    </svg>
  );
}

/** 风格 id → 图标渲染(唯一映射;注册表见 registry.ts)。 */
export function LauncherIcon({ style }: { style: LauncherStyle }) {
  switch (style) {
    case "assistant-spark":
      return <SparkGlyph />;
    case "chat-bubble":
      return <BubbleGlyph />;
    case "orbit-neural":
      return <OrbitGlyph />;
    case "current":
    default:
      return <CurrentGlyph />;
  }
}
