// I-UX-001:Trusted Action 语义目录 + 确定性选取(冻结 §2.13-§2.15)。
//
// - 语义身份(type)独立于展示 label;label 由站点下发(本地化展示词);
// - 资格:仅站点下发的 verified/published 动作(服务端已过滤)∩ 页面上下文
//   适用性(确定性谓词,零 LLM);
// - 数量上限(冻结):C 最多 2;空聊天窗最多 3;
// - 查询绑定:动作 query 可含 {product}/{page_title} 占位符,点击时按当前
//   参与上下文确定性替换;绑定缺失(如无产品上下文的 {product})→ 该动作
//   本次不选(错误的具体不如正确的通用);
// - PRICING/COMPARE_PRODUCTS 的「不默认发布」由服务端生命周期保证:没有
//   published 动作就绝不会出现;Widget 侧不做目录级默认发布。

import type { TrustedActionRef } from "../types";
import type { EngagementContext, PageType } from "./greeting";

/** 语义动作 → 页面上下文适用性谓词(确定性;与后端目录同集合)。 */
const APPLICABILITY: Record<string, (ctx: EngagementContext) => boolean> = {
  PRODUCT_SPECIFICATIONS: (ctx) => !!ctx.product || ctx.pageType === "product",
  SETUP_GUIDE: (ctx) => !!ctx.product || ctx.pageType === "product" || ctx.pageType === "documentation",
  EXPLAIN_PAGE: (ctx) => !!ctx.pageTitle || ctx.pageType === "documentation",
  TROUBLESHOOT: (ctx) => ctx.pageType === "documentation" || ctx.pageType === "support" || !!ctx.pageTitle,
  FIND_DOCUMENTATION: (ctx) => !!ctx.product || ctx.pageType !== "unknown",
  COMPARE_PRODUCTS: (ctx) => !!ctx.product || ctx.pageType === "product" || ctx.pageType === "comparison",
  COMPATIBILITY: (ctx) => !!ctx.product || ctx.pageType === "product",
  PRICING: (ctx) => !!ctx.product || ctx.pageType === "product" || ctx.pageType === "pricing",
};

/**
 * 从站点已发布动作中选取当前上下文适用的动作(保序;确定性)。
 * 谓词未定义的语义类型按「不适用」处理(fail-closed:未经核对的语义不主动)。
 */
export function selectTrustedActions(
  actions: TrustedActionRef[] | undefined,
  ctx: EngagementContext,
  max: number,
): TrustedActionRef[] {
  if (!Array.isArray(actions) || actions.length === 0) return [];
  const picked: TrustedActionRef[] = [];
  for (const action of actions) {
    if (picked.length >= max) break;
    const predicate = APPLICABILITY[action.type];
    if (predicate && predicate(ctx)) picked.push(action);
  }
  return picked;
}

/** 绑定动作查询:{product}/{page_title} 占位符按参与上下文确定性替换。 */
export function buildActionQuery(action: TrustedActionRef, ctx: EngagementContext): string | null {
  // 上下文缺失 → 占位符无法绑定 → 空洞问题,不发送(宁缺毋滥)
  if (action.query.includes("{product}") && !ctx.product) return null;
  if (action.query.includes("{page_title}") && !ctx.pageTitle) return null;
  const bound = action.query
    .replace(/\{product\}/g, ctx.product ?? "")
    .replace(/\{page_title\}/g, ctx.pageTitle ?? "");
  if (!bound.trim()) return null;
  return bound.trim();
}

/** 页面类型 → 推荐语义默认(产品契约 §2.13 初始推荐;仅供 Admin 建动作参考)。 */
export const RECOMMENDED_ACTION_TYPES: Record<PageType, string[]> = {
  product: ["PRODUCT_SPECIFICATIONS", "SETUP_GUIDE"],
  documentation: ["EXPLAIN_PAGE", "TROUBLESHOOT"],
  integration: ["FIND_DOCUMENTATION", "EXPLAIN_PAGE"],
  support: ["TROUBLESHOOT", "FIND_DOCUMENTATION"],
  pricing: ["PRICING"],
  comparison: ["COMPARE_PRODUCTS"],
  unknown: ["PRODUCT_SPECIFICATIONS", "SETUP_GUIDE"],
};
