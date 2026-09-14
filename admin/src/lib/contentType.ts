/**
 * v1.6.3 Track C(U-7 / DS-P2-16/20):逐文档内容类型呈现映射。
 *
 * 冻结语义:content_type 是**结构化后端真值**(connector/ingestion 所有);
 * 本模块只做词表→运营词的呈现映射,**禁止从文件名/文本推断**。
 * null = 后端无类型(存量行不可用),必须诚实呈现「—」,不得猜测。
 */

export const CONTENT_TYPE_LABELS: Record<string, string> = {
  product: "商品",
  page: "页面",
  document: "文档",
};

/** 后端 content_type → 运营词;null/未知 → null(UI 呈现「—」+title 不可用)。 */
export function contentTypeLabel(contentType: string | null | undefined): string | null {
  if (!contentType) return null;
  return CONTENT_TYPE_LABELS[contentType] ?? null;
}
