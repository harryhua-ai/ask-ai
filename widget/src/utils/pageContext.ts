// 宿主页面上下文自动收集(MSW;非信任语义提示,后端消毒后仅作软加分/背景段)。
// 结构化字段(page_type/product/…)由宿主经 window.AskAIConfig.pageContext 可选
// 提供;自动收集的 url/title/language 不被宿主提供值覆盖(防基本字段伪造)。
import type { PageContextPayload } from "../types";

export function collectPageContext(win: Window = window): PageContextPayload {
  const auto: PageContextPayload = {
    url: win.location?.href || undefined,
    title: win.document?.title || undefined,
    language: win.navigator?.language || undefined,
  };
  const hostExtra = (
    win as Window & { AskAIConfig?: { pageContext?: PageContextPayload } }
  ).AskAIConfig?.pageContext;
  if (!hostExtra) return auto;
  // auto 在后:结构化字段保留自 hostExtra,url/title/language 以自动收集为准
  return { ...hostExtra, ...auto };
}
