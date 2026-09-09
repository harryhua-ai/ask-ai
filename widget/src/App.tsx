import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import type { WidgetConfig, ChatMessage, SiteExperienceConfig, TrustedActionRef } from "./types";
import { useSSE } from "./hooks/useSSE";
import { collectPageContext } from "./utils/pageContext";
import {
  readBrowserLanguage,
  readHtmlLang,
  resolveAskLanguage,
  resolveUiLanguage,
  type LanguageResolutionInput,
} from "./utils/language";
import { uiStrings } from "./i18n";
import { ChatPanel } from "./components/ChatPanel";
import { ContextualNudge, EntryPill, MiniConversationEntry } from "./components/EntrySurfaces";
import { Launcher } from "./launcher/Launcher";
import {
  legacyStyleToIcon,
  resolveLauncherIcon,
  resolveLauncherShape,
  resolveLauncherThemePref,
  resolveLocalLauncherAppearance,
  useResolvedTheme,
} from "./launcher/registry";
import {
  resolveEntryMode,
  resolveProactiveTiming,
  proactiveCapable,
  proactiveDelayMs,
  isMobileViewport,
} from "./experience/entry";
import {
  proactiveAlreadyUsed,
  userDismissedProactive,
  markProactiveShown,
  markProactiveDismissed,
} from "./experience/session";
import { resolveEngagement } from "./experience/greeting";
import { selectTrustedActions, buildActionQuery } from "./experience/actions";
import { resolveChatThemeMode, resolveChatThemeTokens, resolveChatSize } from "./experience/theme";
import {
  resolveLauncherMotion,
  resolveLauncherSize,
  resolveLauncherBrand,
  resolveLauncherCustomColor,
} from "./experience/launcher";
import { watchPageNavigation } from "./experience/pageWatch";
import {
  fetchSiteConfig,
  resolveStarters,
  stripLauncherAppearance,
  LAUNCHER_RESOLUTION_TIMEOUT_MS,
} from "./utils/siteConfig";

// legacy 兜底推荐问题按 UI 语言双变体(G-L4/G-L5:站点 starters 缺失时的回落)
const DEFAULT_STARTERS: Record<"en" | "zh", string[]> = {
  en: [
    "Which product fits my project?",
    "Compare NE503 and NE301",
    "What interfaces does NE503 support?",
    "How do I get started with NeoMind?",
  ],
  zh: [
    "NE503 支持哪些接口?",
    "如何开始使用 NeoMind?",
    "NE101 的功耗是多少?",
    "AIToolStack 有哪些功能?",
  ],
};

export function App({ config }: { config: WidgetConfig }) {
  const [isOpen, setIsOpen] = useState(false);
  // I-UX-001 入口状态机:mini(C 表面,仅桌面 mini_entry)与 nudge 揭示
  const [miniOpen, setMiniOpen] = useState(false);
  const [nudgeVisible, setNudgeVisible] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // MSW:站点体验配置(启动时按 siteId 拉取;失败 fail-safe 回退默认体验,
  // site_id 仍随 ask 发送,由服务端裁决 → SSE 层可见「站点未授权」失败)
  const [siteConfig, setSiteConfig] = useState<SiteExperienceConfig | null>(null);

  // ML 闭环:UI_LANGUAGE 与 ANSWER_LANGUAGE 分离。
  // 解析链(冻结):宿主显式配置 → <html lang> → 站点默认语言 → 浏览器语言 → en。
  // <html lang> 每次打开面板/发送时重读 → SPA 页内热切换生效(G-L2 闭环)。
  const resolveInput = useCallback((): LanguageResolutionInput => {
    return {
      configLanguage: config.language,
      htmlLang: typeof document !== "undefined" ? readHtmlLang(document) : null,
      siteLanguage: siteConfig?.language,
      browserLanguage:
        typeof navigator !== "undefined" ? readBrowserLanguage(navigator) : null,
    };
  }, [config.language, siteConfig]);

  const [uiLang, setUiLang] = useState<"en" | "zh">(() =>
    resolveUiLanguage({
      configLanguage: config.language,
      htmlLang: typeof document !== "undefined" ? readHtmlLang(document) : null,
      browserLanguage:
        typeof navigator !== "undefined" ? readBrowserLanguage(navigator) : null,
    }),
  );
  // 阶段⑯:UI 语言对应的客户端兜底文案(服务端 message 恒为主显示)
  const { ask, uploadFiles } = useSSE(config.apiUrl, {
    serviceUnavailable: uiStrings(uiLang).serviceUnavailable,
    budgetDeclined: uiStrings(uiLang).serviceBusy,
  });

  // 站点体验配置按当前 UI 语言拉取本地化 welcome/starters(G-L5);
  // UI 语言变化(页内热切换)时重新拉取。
  //
  // Issue #33 首绘正确性 —— launcher 外观解析状态机:
  //   UNRESOLVED(权威 site-config 未到达:不绘制 provisional 外观)
  //     → RESOLVED(权威值到达;或嵌入级本地终值/legacy 无站点 → 免等)
  //   UNRESOLVED → FAILED(失败或外观期限到,确定性回退默认外观,绝不永久空白)
  // PENDING ≠ FAILED:仅初始解析失败才进入 FAILED;已 RESOLVED 后的
  // uiLang 重拉失败保留既有权威外观(不隐藏、不回退)。
  //
  // REV1 生命周期解耦:外观期限只是**状态转换点**,不取消请求 ——
  // site-config 的 welcome/starters/本地化检索生命周期独立于外观解析:
  //   - 期限前成功:UNRESOLVED → RESOLVED,首见=权威外观;
  //   - 期限后迟到成功:非外观字段照常消费(setSiteConfig),外观维度被
  //     stripLauncherAppearance 剥离 → 回退外观保持稳定,零二次闪变;
  //   - 期限后失败:非外观失败语义与现状一致(默认体验)。
  const localAppearance = resolveLocalLauncherAppearance(config);
  const [appearancePhase, setAppearancePhase] = useState<"unresolved" | "resolved" | "failed">(
    () => (localAppearance || !config.siteId ? "resolved" : "unresolved"),
  );
  // 异步回调内读取最新相位用(状态 closure 会因 effect 重跑而陈旧)
  const appearancePhaseRef = useRef(appearancePhase);
  const transitionAppearancePhase = (next: "resolved" | "failed") => {
    appearancePhaseRef.current = next;
    setAppearancePhase(next);
  };
  useEffect(() => {
    if (!config.siteId) return;
    // 外观期限:仅推动状态机转换;绝不 abort 请求(REV1)
    const timer = window.setTimeout(() => {
      if (appearancePhaseRef.current === "unresolved") {
        transitionAppearancePhase("failed");
      }
    }, LAUNCHER_RESOLUTION_TIMEOUT_MS);
    let cancelled = false;
    fetchSiteConfig(config.apiUrl, config.siteId, { language: uiLang })
      .then((cfg) => {
        if (cancelled) return;
        if (appearancePhaseRef.current === "unresolved") {
          setSiteConfig(cfg);
          transitionAppearancePhase("resolved");
        } else if (appearancePhaseRef.current === "failed") {
          // 迟到成功:非外观语义照常消费;外观维度剥离(无二次闪变)
          setSiteConfig(stripLauncherAppearance(cfg));
        } else {
          setSiteConfig(cfg);
        }
      })
      .catch(() => {
        if (cancelled) return;
        // 保持默认体验;不做二次降级提示,失败在 ask 时服务端可见
        if (appearancePhaseRef.current === "unresolved") {
          transitionAppearancePhase("failed");
        }
      })
      .finally(() => {
        window.clearTimeout(timer);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [config.apiUrl, config.siteId, uiLang]);

  // ------------------------------------------------------------------
  // I-UX-001:入口模式 / 主动展开 / 参与上下文 / 主题(全部确定性解析)
  // ------------------------------------------------------------------
  const entryMode = resolveEntryMode(config, siteConfig);
  const proactiveTiming = resolveProactiveTiming(config, siteConfig);
  const mobile = isMobileViewport(typeof window === "undefined" ? null : window);

  // 参与上下文:问候与动作资格的唯一真相;SPA 导航时经 pageTick 重算
  const [pageTick, setPageTick] = useState(0);
  useEffect(() => watchPageNavigation(() => setPageTick((n) => n + 1), typeof window === "undefined" ? null : window), []);

  const engagement = useMemo(() => {
    void pageTick; // URL/title 变化 → 重算
    const pc = collectPageContext();
    const preview = !!config.previewMode;
    return resolveEngagement({
      site: siteConfig,
      // 预览模式:不采集宿主真实页面,仅消费预览上下文(受信同级)
      hostContext: preview ? null : pc,
      url: preview ? "https://preview.invalid/" : pc.url ?? "",
      title: preview ? config.previewTitle ?? "" : pc.title ?? "",
      lang: uiLang,
      previewPageType: config.previewPageType,
      previewProduct: config.previewProduct,
      previewTitle: config.previewTitle,
    });
  }, [siteConfig, uiLang, pageTick, config.previewMode, config.previewPageType, config.previewProduct, config.previewTitle]);

  // Trusted Actions:服务端仅下发 verified/published;此处按上下文选取(C≤2/聊天≤3)
  // 预览模式:动作由 Admin 预览注入(previewActions);生产 = 站点配置下发
  const effectiveActions =
    (config.previewMode && config.previewActions?.length
      ? config.previewActions
      : siteConfig?.trusted_actions) ?? [];
  const miniActions = useMemo(
    () => selectTrustedActions(effectiveActions, engagement, 2),
    [effectiveActions, engagement],
  );
  const chatColdActions = useMemo(
    () => selectTrustedActions(effectiveActions, engagement, 3),
    [effectiveActions, engagement],
  );

  // 聊天窗主题(ASK-AI 自有 token;match 模式读宿主可信信号)
  const chatThemeMode = resolveChatThemeMode(config, siteConfig);
  const chatTheme = useMemo(
    () =>
      resolveChatThemeTokens(
        chatThemeMode,
        config,
        siteConfig,
        typeof document === "undefined" ? null : document,
      ),
    [chatThemeMode, config, siteConfig],
  );

  // 启动器动效/尺寸/品牌(独立于聊天窗主题)
  const launcherMotion = resolveLauncherMotion(config, siteConfig);
  const launcherSize = resolveLauncherSize(config, siteConfig);
  const launcherBrand = resolveLauncherBrand(config, siteConfig);
  const launcherCustomColor = resolveLauncherCustomColor(config, siteConfig);
  // brand=match → 消费聊天窗主题解析出的宿主 accent;custom → 显式色;askai → 默认
  const launcherBrandStyle =
    launcherBrand === "custom" && launcherCustomColor
      ? { background: launcherCustomColor, color: readableOn(launcherCustomColor) }
      : launcherBrand === "match" && chatTheme.tokens["--ask-ai-primary"]
        ? { background: chatTheme.tokens["--ask-ai-primary"], color: chatTheme.tokens["--ask-ai-on-primary"] }
        : undefined;

  const starters =
    messages.length === 0 ? resolveStarters(siteConfig, DEFAULT_STARTERS[uiLang]) : [];
  const welcome = messages.length === 0 ? siteConfig?.welcome : undefined;
  const strings = uiStrings(uiLang);

  // Issue #24 REV1:launcher 统一外观解析(icon × shape × theme)。
  const launcherIcon = resolveLauncherIcon(
    config.launcherIcon ??
      legacyStyleToIcon(config.launcherStyle) ??
      siteConfig?.launcher_icon ??
      legacyStyleToIcon(siteConfig?.launcher_style),
  );
  const launcherShape = resolveLauncherShape(
    config.launcherShape ?? siteConfig?.launcher_shape,
  );
  const launcherThemePref = resolveLauncherThemePref(
    config.launcherTheme ?? siteConfig?.launcher_theme,
  );
  const launcherTheme = useResolvedTheme(launcherThemePref);

  // ------------------------------------------------------------------
  // I-UX-001:主动展开(冻结 §2.2/§2.3)
  //   桌面 mini_entry → 延迟后 C 自动展开(每站点会话一次;不自动收起);
  //   移动端(任何入口)→ 主动呈现一律为 B nudge,绝不自动展开完整 C/聊天。
  //   依赖门:外观解析已落定(避免慢网下 C 以空配置展开);SPA 不重触发
  //   (会话闸在 sessionStorage;本 effect 不依赖页面上下文)。
  // ------------------------------------------------------------------
  useEffect(() => {
    if (config.previewMode && appearancePhase === "unresolved") return;
    if (!config.previewMode && appearancePhase !== "resolved") return;
    if (userDismissedProactive(config.siteId) || proactiveAlreadyUsed(config.siteId)) return;
    if (isOpen || miniOpen || nudgeVisible) return;
    // B 作为显式入口模式:nudge 即入口呈现,立即显示(dismiss 后回落 pill)
    if (entryMode === "nudge") {
      setNudgeVisible(true);
      return;
    }
    // 主动展开 = C 专属(桌面 C 自动展开;移动端主动呈现 = B,冻结 §2.3)
    if (!proactiveCapable(entryMode)) return;
    const delay = proactiveDelayMs(proactiveTiming);
    if (delay === null) return;
    const timer = window.setTimeout(() => {
      if (isOpen || miniOpen) return;
      markProactiveShown(config.siteId);
      if (isMobileViewport(window)) {
        setNudgeVisible(true); // 移动端主动呈现 = B(冻结 §2.3)
      } else {
        setMiniOpen(true); // 桌面 C 自动展开(冻结 §2.2)
      }
    }, delay);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 主动展开每会话一次;不随界面状态重排
  }, [appearancePhase, entryMode, proactiveTiming, config.siteId, config.previewMode]);

  // C/nudge 关闭 = 用户明确不要(本会话剩余时间尊重)
  const dismissMini = useCallback(() => {
    setMiniOpen(false);
    markProactiveDismissed(config.siteId);
  }, [config.siteId]);
  const dismissNudge = useCallback(() => {
    setNudgeVisible(false);
    markProactiveDismissed(config.siteId);
  }, [config.siteId]);

  const openPanel = useCallback(() => {
    // 打开面板时重读页面语言(SPA 路由切换后 UI 跟随)
    setUiLang(resolveUiLanguage(resolveInput()));
    setMiniOpen(false);
    setIsOpen(true);
  }, [resolveInput]);

  // 桌面 mini_entry:launcher 点击 → 展开 C(与主动展开同一表面;§2.6 生长叙事)
  const expandMini = useCallback(() => {
    setUiLang(resolveUiLanguage(resolveInput()));
    setMiniOpen(true);
  }, [resolveInput]);

  // 会话开始后的冷启动清理:C/nudge 表面退场(消息优先)
  const conversationStarted = messages.length > 0;
  useEffect(() => {
    if (conversationStarted) {
      setMiniOpen(false);
      setNudgeVisible(false);
    }
  }, [conversationStarted]);

  const startConversation = useCallback(
    (text: string) => {
      openPanel();
      void handleSendRef.current?.(text, []);
    },
    [openPanel],
  );

  const handleColdAction = useCallback(
    (action: TrustedActionRef) => {
      const bound = buildActionQuery(action, engagement) ?? action.label;
      startConversation(bound);
    },
    [engagement, startConversation],
  );

  const handleSend = useCallback(async (text: string, attachmentIds: string[]) => {
    // ML 闭环:发送时实时解析(G-L2 热切换 + G-L3 浏览器兜底);
    // ANSWER_LANGUAGE 随 ask 发送,服务端作为默认答案语境消费(G-L1)。
    const input = resolveInput();
    const langNow = resolveUiLanguage(input);
    const askLanguage = resolveAskLanguage(input);
    setUiLang(langNow);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      type: "user",
      content: text,
      attachments: attachmentIds.length
        ? attachmentIds.map((id) => ({ id, filename: id.slice(0, 8), kind: "log", status: "ready" as const }))
        : undefined,
    };
    setMessages((prev) => [...prev, userMsg]);

    // I-UX-001 预览模式(Admin 实时预览):复用真实渲染路径,但绝不产生
    // 真实 /ask 流量;以确定性本地回显演示会话形态(非 TA Test —— 那走真实管道)。
    if (config.previewMode) {
      const previewId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        { id: previewId, type: "assistant", content: uiStrings(langNow).previewNotice },
      ]);
      return;
    }

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, type: "assistant", content: "" }]);
    setIsStreaming(true);

    // try/finally 确保 isStreaming 总是被重置,即使 fetch 抛错或 SSE 提前返回(resp.body 为空 / resp.ok 为 false)
    try {
      await ask(text, messages, config.channel ?? "widget", {
        onSources: (sources, convId) => {
          setConversationId(convId);
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)),
          );
        },
        onToken: (token) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + token } : m,
            ),
          );
        },
        onDone: (convId) => {
          setConversationId(convId);
          // PC-01 客户端最后防线:流结束仍无任何内容(如旧版后端零内容完成)
          // → 显示失败文案,绝不留空白气泡伪装成功
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId && !m.content
                ? { ...m, content: uiStrings(langNow).serviceUnavailable }
                : m,
            ),
          );
        },
        onError: (errMsg, meta) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m;
              // 流中断(PC-03):部分内容保留,失败提示追加其后,不覆盖已有输出
              if (meta?.kind === "stream_interrupted") {
                return { ...m, content: m.content ? `${m.content}\n\n${errMsg}` : errMsg };
              }
              return { ...m, content: errMsg };
            }),
          );
        },
      }, attachmentIds, {
        siteId: config.siteId,
        pageContext: collectPageContext(),
        language: askLanguage,
      });
    } finally {
      setIsStreaming(false);
    }
  }, [messages, ask, config.siteId, config.channel, config.previewMode, resolveInput]);

  // 稳定引用:C/nudge 动作在 handleSend 定义前就需要触发真实发送
  const handleSendRef = useRef<((text: string, attachmentIds: string[]) => Promise<void>) | null>(
    null,
  );
  useEffect(() => {
    handleSendRef.current = handleSend;
  });

  const handleFeedback = useCallback(async (_msgId: string, feedback: "up" | "down") => {
    if (!conversationId) return;
    await fetch(`${config.apiUrl}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, feedback }),
    });
  }, [conversationId, config.apiUrl]);

  const showNudge =
    !isOpen && !miniOpen && nudgeVisible && appearancePhase !== "unresolved" && !conversationStarted;

  return (
    <div
      className="ask-ai-root"
      data-entry-mode={entryMode}
      style={chatTheme.tokens as React.CSSProperties}
    >
      {/* I-UX-001 入口呈现:legacy/pill/nudge-dismissed/移动 C → launcher 或 pill;
          桌面 mini_entry → launcher(点击展开 C,同一表面生长叙事) */}
      {!isOpen && !miniOpen && appearancePhase !== "unresolved" && (
        <>
          {entryMode !== "pill" && (
            <Launcher
              icon={launcherIcon}
              shape={launcherShape}
              theme={launcherTheme}
              label={strings.launcherOpen}
              onOpen={entryMode === "mini_entry" && !mobile ? expandMini : openPanel}
              motion={launcherMotion}
              size={launcherSize}
              brandStyle={launcherBrandStyle}
            />
          )}
          {(entryMode === "pill" || (entryMode === "nudge" && !nudgeVisible)) && (
            <div className="ask-ai-entry-slot">
              <EntryPill label={strings.pillLabel} onOpen={openPanel} />
            </div>
          )}
        </>
      )}
      {showNudge && (
        <ContextualNudge
          greeting={engagement.greeting}
          dismissLabel={strings.notNow}
          onOpen={openPanel}
          onDismiss={dismissNudge}
        />
      )}
      {!isOpen && miniOpen && appearancePhase !== "unresolved" && (
        <MiniConversationEntry
          identity={siteConfig?.display_name || "Ask AI"}
          greeting={engagement.greeting}
          actions={miniActions}
          placeholder={strings.placeholder}
          sendLabel={strings.send}
          notNowLabel={strings.notNow}
          minimizeLabel={strings.minimize}
          actionsLabel={strings.trustedActions}
          onAction={(action) => handleColdAction(action)}
          onSubmit={(text) => startConversation(text)}
          onMinimize={dismissMini}
        />
      )}
      {isOpen && (
        <ChatPanel
          config={config}
          strings={strings}
          messages={messages}
          isStreaming={isStreaming}
          conversationId={conversationId}
          suggestedQuestions={starters}
          welcome={welcome}
          themeStyle={chatTheme.tokens}
          character={chatTheme.character}
          chatSize={resolveChatSize(config, siteConfig)}
          coldActions={chatColdActions}
          onColdAction={(query) => {
            openPanel();
            void handleSendRef.current?.(query, []);
          }}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          onFeedback={handleFeedback}
          onUpload={uploadFiles}
        />
      )}
    </div>
  );
}

// 预览/无窗口环境的确定性安全消解(避免在模块顶层引用 window)

function readableOn(hex: string): string {
  try {
    const n = hex.replace("#", "");
    const r = parseInt(n.slice(0, 2), 16);
    const g = parseInt(n.slice(2, 4), 16);
    const b = parseInt(n.slice(4, 6), 16);
    return 0.2126 * lum(r) + 0.7152 * lum(g) + 0.0722 * lum(b) > 0.35 ? "#1a1a1a" : "#ffffff";
  } catch {
    return "#ffffff";
  }
}

function lum(v: number): number {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
