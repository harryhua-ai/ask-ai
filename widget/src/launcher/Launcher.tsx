// Issue #24:canonical launcher 渲染组件(Widget 实体与 Admin 实时预览共用同一
// 视觉契约 —— 预览 = 加载真实 widget 产物的 iframe,不存在第二套渲染实现)。
//
// - 按钮承载可访问名(aria-label),图标不作为唯一命名机制(§11);
// - data-launcher-style / data-ask-ai-theme 驱动 CSS 令牌与风格选择;
// - 几何/配色细节在 widget.css(令牌)与本目录(SVG),行为零变化(纯呈现)。

import type { LauncherStyle, LauncherTheme } from "../types";
import { LauncherIcon } from "./LauncherIcon";

export interface LauncherProps {
  style: LauncherStyle;
  /** 已消解的落地主题(auto 在 registry 中按系统偏好消解)。 */
  theme: LauncherTheme;
  /** 可访问名(按钮级;不依赖图标)。 */
  label: string;
  onOpen: () => void;
}

export function Launcher({ style, theme, label, onOpen }: LauncherProps) {
  return (
    <button
      type="button"
      className="ask-ai-fab"
      data-launcher-style={style}
      data-ask-ai-theme={theme}
      aria-label={label}
      aria-haspopup="dialog"
      onClick={onOpen}
    >
      <LauncherIcon style={style} />
    </button>
  );
}
