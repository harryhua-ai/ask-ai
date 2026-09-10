// Issue #24 REV1:canonical launcher 渲染组件(Widget 实体与 Admin 实时预览共用同一
// 视觉契约 —— 预览 = 加载真实 widget 产物的 iframe,不存在第二套渲染实现)。
//
// - 按钮承载可访问名(aria-label),图标不作为唯一命名机制;装饰 SVG aria-hidden;
// - data-launcher-icon / data-launcher-shape / data-ask-ai-theme 驱动 CSS;
// - I-UX-001:data-launcher-motion(注意力动效)/ data-launcher-size(S/M/L)/
//   data-launcher-brand(品牌面;brandStyle 直接落色,独立于聊天窗主题);
// - `current` 形状由遗留渲染器拥有(52px/12px 圆角方,medium 逐像素兼容);
//   round/rounded-square 仅对 REV1 矢量图标生效;
// - 几何/配色细节在 widget.css 与本目录(SVG),行为零变化(纯呈现)。

import type { CSSProperties } from "react";
import type { LauncherIcon, LauncherShape, LauncherTheme } from "../types";
import type { LauncherMotion, LauncherSize } from "../experience/launcher";
import { LauncherIcon as LauncherIconGlyph } from "./LauncherIcon";

export interface LauncherProps {
  icon: LauncherIcon;
  shape: LauncherShape;
  /** 已消解的落地主题(auto 在 registry 中按系统偏好消解)。 */
  theme: LauncherTheme;
  /** 可访问名(按钮级;不依赖图标)。 */
  label: string;
  onOpen: () => void;
  /** I-UX-001:注意力动效预设(默认 subtle_glow;reduced-motion 由 CSS 守卫)。 */
  motion?: LauncherMotion;
  /** I-UX-001:尺寸预设(默认 medium = 既有 52px)。 */
  size?: LauncherSize;
  /** I-UX-001:品牌面覆写(brand=match/custom 的落色;独立于聊天窗主题)。 */
  brandStyle?: CSSProperties;
}

export function Launcher({ icon, shape, theme, label, onOpen, motion, size, brandStyle }: LauncherProps) {
  return (
    <button
      type="button"
      className="ask-ai-fab"
      data-launcher-icon={icon}
      data-launcher-shape={shape}
      data-ask-ai-theme={theme}
      data-launcher-motion={motion ?? "subtle_glow"}
      data-launcher-size={size ?? "medium"}
      style={brandStyle}
      aria-label={label}
      aria-haspopup="dialog"
      onClick={onOpen}
    >
      <LauncherIconGlyph icon={icon} />
    </button>
  );
}

export interface LauncherPillProps {
  /** 已消解的落地主题(auto 在 registry 中按系统偏好消解;驱动阴影/对峙对比)。 */
  theme: LauncherTheme;
  /** 可访问名(按钮级;可见品牌文案恒为「Ask AI」)。 */
  label: string;
  onOpen: () => void;
  /** 注意力动效预设(默认 subtle_glow;reduced-motion 由 CSS 守卫)。 */
  motion?: LauncherMotion;
  /** 尺寸预设(默认 medium ≈40–44px 高)。 */
  size?: LauncherSize;
  /** 品牌面覆写(brand=match/custom 的落色;独立于聊天窗主题)。 */
  brandStyle?: CSSProperties;
}

/**
 * V2.3 矫正(#39):品牌「✦ Ask AI」紧凑胶囊 launcher —— 新站点/新配置默认呈现。
 * 与 Launcher(图标 FAB)同一交互契约(按钮可访问名 / aria-haspopup / onOpen),
 * 仅呈现不同;目标高度 ≈40–44px,圆角胶囊几何,restrained 阴影。
 */
export function LauncherPill({ theme, label, onOpen, motion, size, brandStyle }: LauncherPillProps) {
  return (
    <button
      type="button"
      className="ask-ai-launcher-pill"
      data-ask-ai-theme={theme}
      data-launcher-motion={motion ?? "subtle_glow"}
      data-launcher-size={size ?? "medium"}
      style={brandStyle}
      aria-label={label}
      aria-haspopup="dialog"
      onClick={onOpen}
    >
      <span className="ask-ai-launcher-pill-glyph" aria-hidden="true">
        ✦
      </span>
      <span className="ask-ai-launcher-pill-text">Ask AI</span>
    </button>
  );
}
