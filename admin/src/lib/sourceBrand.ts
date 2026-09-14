/**
 * v1.6.3 Track C(U-6 / DS-P2-02):source-type/品牌权威内建映射。
 *
 * 冻结语义:品牌呈现使用**内建映射**(类型→色块/字形),不得引入任意
 * 远程 logo_url 作为产品真值(零远程资产、零运行时图片拉取)。
 * WooCommerce 参考呈现 = 紫(品牌紫 #7F54B3)底白字「W」;其余类型按
 * 运营类型内建字形/色块;未知类型回退产品名首字母(与参考字母块同构)。
 */

export interface SourceBrand {
  /** 品牌块背景色(内建;远程 URL 一律禁止)。 */
  bg: string;
  /** 品牌块前景色。 */
  fg: string;
  /** 品牌字形(字母或字符;不使用远程图片)。 */
  glyph: string;
  /** 无障碍名称(品牌/类型语义)。 */
  label: string;
}

const BRAND_MAP: Record<string, SourceBrand> = {
  woocommerce: { bg: "#7F54B3", fg: "#FFFFFF", glyph: "W", label: "WooCommerce" },
  github: { bg: "#24292F", fg: "#FFFFFF", glyph: "G", label: "GitHub" },
  web_crawl: { bg: "#2563EB", fg: "#FFFFFF", glyph: "◉", label: "网站" },
  filesystem: { bg: "#B45309", fg: "#FFFFFF", glyph: "▤", label: "文件系统" },
  local_git: { bg: "#0F766E", fg: "#FFFFFF", glyph: "▤", label: "Wiki" },
};

/** source-type 内建品牌映射;未知类型回退产品名首字母字母块(零远程资产)。 */
export function sourceBrandOf(type: string, product: string): SourceBrand {
  const known = BRAND_MAP[type];
  if (known) return known;
  return {
    bg: "rgb(4 59 178 / 0.10)",
    fg: "var(--acc, #1d4ed8)",
    glyph: (product || "?").slice(0, 1).toUpperCase(),
    label: product || type,
  };
}
