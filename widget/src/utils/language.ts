// 语言解析工具(ML Closure:CAMTHINK_V1_P1_THREE_SITE_MULTILINGUAL_BEHAVIOR_CLOSURE)。
//
// 冻结语义(接入契约 §3.4 Resolution):
//   宿主显式(data-language / AskAIConfig.language)
//     → <html lang>(发送时读取,支持页内热切换)
//     → 站点默认语言(site-config)
//     → 浏览器语言(navigator.language,仅兜底)
//     → 省略(交由服务端按提问文本检测,fallback en)
//
// UI_LANGUAGE 与 ANSWER_LANGUAGE 是两个独立轴:
//   - UI_LANGUAGE(界面文案)取解析链的 en/zh 二值;
//   - ANSWER_LANGUAGE 随 ask 发送,由服务端管线消费(归一化后)。

/** 归一化语言代码:zh* → zh,en* → en,其他取小写主子标签;无效 → null。 */
export function normalizeLanguage(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const cleaned = raw.trim().toLowerCase().replace(/_/g, "-");
  if (!cleaned) return null;
  const primary = cleaned.split("-", 1)[0];
  if (primary === "zh" || primary === "en") return primary;
  return /^[a-z]{2,3}$/.test(primary) ? primary : null;
}

/** 读取宿主页面 <html lang>(每次发送时读取,SPA 页内热切换天然生效)。 */
export function readHtmlLang(doc: Document | null | undefined): string | null {
  const lang = doc?.documentElement?.getAttribute("lang");
  return lang ? lang : null;
}

/** 浏览器语言兜底(仅当解析链上游全空时使用;不与页面语言竞争)。 */
export function readBrowserLanguage(nav?: Navigator | null): string | null {
  const langs = nav?.languages?.length ? nav.languages : nav?.language ? [nav.language] : [];
  return langs.length > 0 ? langs[0] : null;
}

export interface LanguageResolutionInput {
  /** 宿主显式配置(data-language / AskAIConfig.language) */
  configLanguage?: string | null;
  /** 宿主页面 <html lang>(发送时读取) */
  htmlLang?: string | null;
  /** 站点默认语言(site-config) */
  siteLanguage?: string | null;
  /** 浏览器语言兜底 */
  browserLanguage?: string | null;
}

/**
 * ask 语言解析(ANSWER_LANGUAGE 语境)。返回归一化语言或 undefined
 * (undefined = 全链无信号,随请求省略 language 字段,服务端按文本检测)。
 */
export function resolveAskLanguage(input: LanguageResolutionInput): string | undefined {
  return (
    normalizeLanguage(input.configLanguage) ??
    normalizeLanguage(input.htmlLang) ??
    normalizeLanguage(input.siteLanguage) ??
    normalizeLanguage(input.browserLanguage) ??
    undefined
  );
}

/** Widget UI 语言二值(界面文案只有 en/zh 变体)。 */
export type UiLanguage = "en" | "zh";

/** Widget UI 语言二值:解析链归一化后非 zh 一律 en(界面文案只有 en/zh 变体)。 */
export function resolveUiLanguage(input: LanguageResolutionInput): UiLanguage {
  return resolveAskLanguage(input) === "zh" ? "zh" : "en";
}
