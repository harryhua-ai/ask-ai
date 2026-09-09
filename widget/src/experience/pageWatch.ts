// I-UX-001:SPA 页面上下文变化监听(冻结 §2.11)。
//
// - 变化时:重算问候/动作资格(冷启动表面跟随页面上下文);
// - 绝不:重触发主动展开(会话闸在 session.ts)、改写已开始的对话内容;
// - 宿主隔离:仅 patch history.pushState/replaceState 的通知能力(恢复原函数
//   语义不变,只追加回调),不改变宿主路由行为;轮询兜底覆盖未捕获的导航。
// - 环境不可用(SSR/沙箱)→ 返回 no-op 取消函数,不抛错。

export type Unsubscribe = () => void;

export function watchPageNavigation(onChange: (url: string) => void, win: Window | null): Unsubscribe {
  if (!win || typeof win.location === "undefined") return () => undefined;

  let lastUrl = safeHref(win);
  let stopped = false;

  const notify = () => {
    if (stopped) return;
    const current = safeHref(win);
    if (current !== lastUrl) {
      lastUrl = current;
      onChange(current);
    }
  };

  let restorePush: (() => void) | null = null;
  try {
    const history = win.history;
    if (history && typeof history.pushState === "function") {
      const originalPush = history.pushState.bind(history);
      const originalReplace = history.replaceState.bind(history);
      history.pushState = (...args: Parameters<History["pushState"]>) => {
        const result = originalPush(...args);
        notify();
        return result;
      };
      history.replaceState = (...args: Parameters<History["replaceState"]>) => {
        const result = originalReplace(...args);
        notify();
        return result;
      };
      restorePush = () => {
        history.pushState = originalPush;
        history.replaceState = originalReplace;
      };
    }
  } catch {
    restorePush = null;
  }

  try {
    win.addEventListener("popstate", notify);
    win.addEventListener("hashchange", notify);
  } catch {
    /* ignore */
  }

  // 轮询兜底(1.5s;覆盖无 history patch 场景,如沙箱 iframe 内的导航)
  const timer = win.setInterval(notify, 1500);

  return () => {
    stopped = true;
    win.clearInterval(timer);
    try {
      win.removeEventListener("popstate", notify);
      win.removeEventListener("hashchange", notify);
    } catch {
      /* ignore */
    }
    restorePush?.();
  };
}

function safeHref(win: Window): string {
  try {
    return win.location.href;
  } catch {
    return "";
  }
}
