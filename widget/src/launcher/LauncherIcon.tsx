// Issue #24 REV1:launcher 图标(语义 icon id → 兼容资产 / 权威内联 SVG)。
//
// - `current` 沿用既有 base64 PNG 资产(逐像素兼容,升级零外观变化);
// - 其余四个 icon 的 SVG 几何逐路径取自权威视觉设计参考
//   (/Users/harryhua/Downloads/buttons.html;bot-sparkle.svg /
//   bubble-sparkle-fill.svg / gravity-ui--face-robot-smile.svg /
//   bubble-sparkle.svg),不做近似重绘;
// - 内联矢量:零外链请求、CSP 兼容、currentColor 原生、高 DPI 清晰;
// - 几何是 HOW,可整体重构;持久身份(语义 id)不在本文件。

import type { LauncherIcon } from "../types";
import currentLauncherAsset from "../assets/CamThink.ai-black.png";

/** 兼容风格沿用既有资产(alt 置空:可访问名由按钮 aria-label 承担,不重复)。 */
function CurrentGlyph() {
  return <img className="ask-ai-fab-icon" src={currentLauncherAsset} alt="" />;
}

/** bot-sparkle:机器人 + 星光(描边;权威设计 bot-sparkle.svg)。 */
function BotSparkleGlyph() {
  return (
    <svg
      className="ask-ai-fab-glyph"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="presentation"
      aria-hidden="true"
    >
      <path
        strokeWidth={2}
        d="M9 11v2m6-2v2m-2-9H7a4 4 0 0 0-4 4v12h14a4 4 0 0 0 4-4v-4M20 2l.13.378a4 4 0 0 0 2.492 2.493L23 5l-.378.13a4 4 0 0 0-2.493 2.492L20 8l-.13-.378a4 4 0 0 0-2.492-2.493L17 5l.378-.13a4 4 0 0 0 2.493-2.492z"
      />
    </svg>
  );
}

/** bubble-sparkle-fill:气泡 + 星光·填充(权威设计 bubble-sparkle-fill.svg)。 */
function BubbleSparkleFillGlyph() {
  return (
    <svg className="ask-ai-fab-glyph" viewBox="0 0 24 24" role="presentation" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2c.863 0 1.701.11 2.5.315L14 4.252A8 8 0 0 0 4 12c0 1.334.325 2.617.94 3.766l.35.653l-.656 2.947l2.947-.655l.653.35A7.96 7.96 0 0 0 12 20a8 8 0 0 0 7.943-8.954l1.987-.236q.07.585.07 1.19c0 5.523-4.477 10-10 10a9.96 9.96 0 0 1-4.709-1.176L2 22l1.176-5.291A9.96 9.96 0 0 1 2 12C2 6.477 6.477 2 12 2m7.53-.68a.507.507 0 0 1 .94 0l.254.61a4.37 4.37 0 0 0 2.25 2.327l.717.32a.53.53 0 0 1 0 .962l-.758.338a4.36 4.36 0 0 0-2.22 2.25l-.246.566a.506.506 0 0 1-.934 0l-.247-.565a4.36 4.36 0 0 0-2.219-2.251l-.76-.338a.53.53 0 0 1 0-.963l.718-.32a4.37 4.37 0 0 0 2.251-2.325z"
      />
    </svg>
  );
}

/** robot-smile:机器人笑脸(权威设计 gravity-ui--face-robot-smile.svg)。 */
function RobotSmileGlyph() {
  return (
    <svg className="ask-ai-fab-glyph" viewBox="0 0 16 16" role="presentation" aria-hidden="true">
      <path
        fill="currentColor"
        d="M9.238 9.451a.75.75 0 1 1 1.024 1.096a3.316 3.316 0 0 1-4.524.004a.75.75 0 0 1 1.024-1.097a1.816 1.816 0 0 0 2.476-.003M6.25 5.5a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0v-1a.75.75 0 0 1 .75-.75m3.5 0a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0v-1a.75.75 0 0 1 .75-.75"
      />
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M8 0a.75.75 0 0 1 .75.75V2H11a3 3 0 0 1 3 3a2.19 2.19 0 0 1 1.5 2.081V9.42l-.007.176A2.19 2.19 0 0 1 14 11.5a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3A2.19 2.19 0 0 1 .507 9.595L.5 9.419V7.081C.5 6.137 1.104 5.3 2 5a3 3 0 0 1 3-3h2.25V.75A.75.75 0 0 1 8 0M5 3.5A1.5 1.5 0 0 0 3.5 5v1.081l-1.025.342A.69.69 0 0 0 2 7.08v2.34c0 .299.191.564.475.658l1.025.342v1.08A1.5 1.5 0 0 0 5 13h6a1.5 1.5 0 0 0 1.5-1.5v-1.081l1.025-.342A.69.69 0 0 0 14 9.42V7.081a.69.69 0 0 0-.475-.658L12.5 6.08V5A1.5 1.5 0 0 0 11 3.5z"
      />
    </svg>
  );
}

/** bubble-sparkle-outline:气泡 + 星光·描边(权威设计 bubble-sparkle.svg)。 */
function BubbleSparkleOutlineGlyph() {
  return (
    <svg
      className="ask-ai-fab-glyph"
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="presentation"
      aria-hidden="true"
    >
      <path d="M15.8 40A18 18 0 1 0 8 32.2L4 44Z" />
      <path
        strokeWidth={7.8}
        transform="translate(17.8 18.3) scale(0.32)"
        d="M25.875 3.944L29.39 17.23a1.94 1.94 0 0 0 1.38 1.379l13.287 3.515c1.924.51 1.924 3.24 0 3.75L30.769 29.39a1.94 1.94 0 0 0-1.379 1.38l-3.515 13.287c-.51 1.924-3.24 1.924-3.75 0L18.61 30.769a1.94 1.94 0 0 0-1.38-1.379L3.944 25.875c-1.924-.51-1.924-3.24 0-3.75l13.288-3.515a1.94 1.94 0 0 0 1.379-1.38l3.515-13.287c.51-1.924 3.24-1.924 3.75 0"
      />
    </svg>
  );
}

/** icon id → 图标渲染(唯一映射;注册表见 registry.ts)。 */
export function LauncherIcon({ icon }: { icon: LauncherIcon }) {
  switch (icon) {
    case "bot-sparkle":
      return <BotSparkleGlyph />;
    case "bubble-sparkle-fill":
      return <BubbleSparkleFillGlyph />;
    case "robot-smile":
      return <RobotSmileGlyph />;
    case "bubble-sparkle-outline":
      return <BubbleSparkleOutlineGlyph />;
    case "current":
    default:
      return <CurrentGlyph />;
  }
}
