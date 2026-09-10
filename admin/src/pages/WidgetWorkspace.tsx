// I-UX-001 矫正(#36/#37/#38/#6):统一 Widget 工作区。
//
// 冻结契约(I-UX-001-POST-PRODUCTION-CORRECTIVE §3.1/§3.10/§3.11):
// - 顶层 Widget 体验 / Widget 外观 两个入口合并为一个顶层 Widget 工作区,
//   内部四区:Entry & Engagement / Appearance / Authorized Websites /
//   Preview & Test;其余 Admin 导航零触碰;
// - 状态模型:配置编辑 = 生产配置草稿;预览/测试控件 = 临时模拟态;
//   预览覆写绝不因生产 Save 被持久化;只有显式 Save 改站点配置;
// - Live Preview 复用真实 Widget 渲染路径(iframe + /widget/widget.js,
//   previewMode 零真实 /ask 流量);预览 launcher 外观来自**草稿解析值**,
//   不得硬编码旧版图标(#36 根因修复);
// - Authorized Websites = 唯一授权概念:精确 origin 列表 / 新增 / 移除,
//   canonical(scheme+host[:port])校验;移除最后一个 origin 前给出后果警示;
// - Greeting:Automatic(默认,推荐)/ Custom template(受控变量
//   {product_name}/{page_title}/{page_type});模板与解析预览分离展示。

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

type SectionId = "entry" | "appearance" | "websites" | "preview";

const SECTIONS: { id: SectionId; label: string; hint: string }[] = [
  { id: "entry", label: "入口与参与", hint: "Entry & Engagement" },
  { id: "appearance", label: "外观", hint: "Appearance" },
  { id: "websites", label: "授权网站", hint: "Authorized Websites" },
  { id: "preview", label: "预览与测试", hint: "Preview & Test" },
];

const ENTRY_MODES = [
  { id: "legacy", label: "保持现状(未配置)", hint: "既有站点缺省:仅启动器,无主动展开" },
  { id: "pill", label: "A · Minimal Pill", hint: "最小「问 AI」文字入口" },
  { id: "nudge", label: "B · Contextual Nudge", hint: "页 aware 轻量气泡,可「暂不需要」" },
  { id: "mini_entry", label: "C · Mini Conversation Entry", hint: "问候 + ≤2 可信动作 + 直接输入(新站点默认)" },
] as const;

const PROACTIVE_TIMINGS = [
  { id: "off", label: "关闭" },
  { id: "fast", label: "快速 ≈3s" },
  { id: "balanced", label: "均衡 ≈6s(默认)" },
  { id: "gentle", label: "舒缓 ≈10s" },
] as const;

const LAUNCHER_MOTIONS = [
  { id: "static", label: "静止" },
  { id: "subtle_glow", label: "微光(默认)" },
  { id: "soft_pulse", label: "轻呼吸" },
  { id: "sparkle", label: "星点" },
] as const;

const LAUNCHER_PRESENTATIONS = [
  { id: "pill", label: "品牌胶囊(新站点默认)", hint: "「✦ Ask AI」紧凑胶囊" },
  { id: "icon", label: "紧凑图标", hint: "既有启动器外观" },
] as const;

const LAUNCHER_ICONS = [
  { id: "current", label: "经典", hint: "既有线上外观(仅图标呈现)" },
  { id: "bot-sparkle", label: "机器人 + 星光", hint: "描边机器人与火花,AI 助手气质" },
  { id: "bubble-sparkle-fill", label: "气泡 + 星光 · 填充", hint: "实心对话气泡,会话中心" },
  { id: "robot-smile", label: "机器人笑脸", hint: "亲和的笑脸机器人" },
  { id: "bubble-sparkle-outline", label: "气泡 + 星光 · 描边", hint: "线性对话气泡,轻盈现代" },
] as const;

const LAUNCHER_SHAPES = [
  { id: "round", label: "圆形" },
  { id: "rounded-square", label: "圆角方形" },
] as const;

const LAUNCHER_THEMES = [
  { id: "auto", label: "自动(跟随系统)" },
  { id: "light", label: "浅色" },
  { id: "dark", label: "深色" },
] as const;

const LAUNCHER_SIZES = [
  { id: "small", label: "小" },
  { id: "medium", label: "中(默认)" },
  { id: "large", label: "大" },
] as const;

const LAUNCHER_BRANDS = [
  { id: "askai", label: "Ask AI 品牌(默认)" },
  { id: "match", label: "跟随站点" },
  { id: "custom", label: "自定义颜色" },
] as const;

const CHAT_THEMES = [
  { id: "match", label: "跟随网站(默认)" },
  { id: "light", label: "浅色" },
  { id: "dark", label: "深色" },
  { id: "custom", label: "自定义强调色" },
] as const;

const CHAT_SIZES = [
  { id: "default", label: "标准(默认)" },
  { id: "large", label: "大" },
] as const;

const ACTION_TYPES = [
  { id: "PRODUCT_SPECIFICATIONS", label: "产品规格", hint: "产品页推荐" },
  { id: "SETUP_GUIDE", label: "安装指南", hint: "产品页推荐" },
  { id: "EXPLAIN_PAGE", label: "解读本页", hint: "文档页推荐" },
  { id: "TROUBLESHOOT", label: "故障排查", hint: "文档页推荐" },
  { id: "FIND_DOCUMENTATION", label: "查找文档" },
  { id: "COMPARE_PRODUCTS", label: "产品对比", hint: "对比行为可靠后再发布" },
  { id: "COMPATIBILITY", label: "兼容性" },
  { id: "PRICING", label: "价格", hint: "须有权威价格真相才发布" },
] as const;

const PAGE_TYPES = [
  { id: "", label: "未知页" },
  { id: "product", label: "产品页" },
  { id: "documentation", label: "文档页" },
  { id: "integration", label: "集成页" },
  { id: "support", label: "支持页" },
  { id: "pricing", label: "价格页" },
  { id: "comparison", label: "对比页" },
] as const;

/** #37:预览主题模拟(临时;Use Site Config = 默认;绝非生产配置)。 */
const PREVIEW_THEMES = [
  { id: "site", label: "使用站点配置(默认)" },
  { id: "match", label: "跟随网站" },
  { id: "light", label: "浅色" },
  { id: "dark", label: "深色" },
] as const;

const GREETING_VARIABLES_HINT = "可用变量:{product_name} {page_title} {page_type}";

interface TrustedAction {
  id: string;
  site_id: string;
  action_type: string;
  label: string;
  query: string;
  state: string;
  sort_order: number;
  last_tested_at: string | null;
  last_verified_at: string | null;
  last_test_result: { answer?: string; sources?: { url: string; title?: string }[]; is_answered?: boolean } | null;
}

/** 工作区合并视图模型:/widget-experience + /widget-appearance 同 site_id 合并。 */
interface SiteRow {
  site_id: string;
  display_name: string;
  enabled: boolean;
  // experience 域
  entry_mode: string | null;
  proactive_timing: string | null;
  launcher_motion: string | null;
  launcher_size: string | null;
  launcher_brand: string | null;
  launcher_color: string | null;
  chat_theme: string | null;
  chat_accent_color: string | null;
  chat_size: string | null;
  greeting_override: string | null;
  launcher_presentation: string | null;
  // appearance 域(统一外观;服务端已归一化)
  launcher_icon: string;
  launcher_shape: string;
  launcher_theme: string;
  legacy_launcher_style?: string | null;
  // trusted actions
  trusted_actions: TrustedAction[];
  // authorized websites 域
  allowed_origins: string[];
}

const STATE_BADGES: Record<string, { label: string; variant: "default" | "warning" | "success" }> = {
  draft: { label: "草稿", variant: "default" },
  verified: { label: "已验证", variant: "warning" },
  published: { label: "已发布", variant: "success" },
};

const EXPERIENCE_FIELDS = [
  "entry_mode",
  "proactive_timing",
  "launcher_motion",
  "launcher_size",
  "launcher_brand",
  "launcher_color",
  "chat_theme",
  "chat_accent_color",
  "chat_size",
  "greeting_override",
  "launcher_presentation",
] as const;

const APPEARANCE_FIELDS = ["launcher_icon", "launcher_shape", "launcher_theme"] as const;

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-md border px-3 py-1.5 text-sm ${
        active ? "border-primary bg-primary/5" : "hover:bg-muted/40"
      }`}
    >
      {children}
    </button>
  );
}

/**
 * Greeting 模板解析预览(与 Widget 侧 resolveGreetingTemplate 同语义;
 * Admin 侧独立实现,消费预览上下文)。任一引用变量缺失 → 明示回落自动问候,
 * 绝不展示残留占位符。
 */
export function resolveGreetingPreview(
  template: string,
  vars: { product: string; pageTitle: string; pageType: string },
): string {
  const hasVariable = /\{(?:product_name|product|page_title|page_type)\}/.test(template);
  if (!hasVariable) return template;
  const product = vars.product.trim();
  const pageTitle = vars.pageTitle.trim();
  const pageType = vars.pageType.trim();
  if (/\{(?:product_name|product)\}/.test(template) && !product) return "";
  if (template.includes("{page_title}") && !pageTitle) return "";
  if (template.includes("{page_type}") && !pageType) return "";
  return template
    .replace(/\{product_name\}/g, product)
    .replace(/\{product\}/g, product)
    .replace(/\{page_title\}/g, pageTitle)
    .replace(/\{page_type\}/g, pageType)
    .trim();
}

/** 实时预览文档:真实 Widget 产物 + 草稿解析外观 + 预览上下文/临时覆写。 */
export function previewDoc(cfg: {
  entryMode: string;
  proactive: string;
  launcherPresentation: string;
  launcherIcon: string;
  launcherShape: string;
  launcherTheme: string;
  launcherMotion: string;
  launcherSize: string;
  launcherBrand: string;
  launcherColor: string;
  chatTheme: string;
  chatAccent: string;
  pageType: string;
  product: string;
  language: string;
  actions: { type: string; label: string; query: string }[];
}): string {
  const attrs = [
    `data-entry-mode="${cfg.entryMode}"`,
    `data-proactive="${cfg.proactive}"`,
    `data-launcher-presentation="${cfg.launcherPresentation}"`,
    `data-launcher-icon="${cfg.launcherIcon}"`,
    `data-launcher-shape="${cfg.launcherShape}"`,
    `data-launcher-theme="${cfg.launcherTheme}"`,
    `data-launcher-motion="${cfg.launcherMotion}"`,
    `data-launcher-size="${cfg.launcherSize}"`,
    `data-launcher-brand="${cfg.launcherBrand}"`,
    cfg.launcherColor ? `data-launcher-color="${cfg.launcherColor}"` : "",
    `data-chat-theme="${cfg.chatTheme}"`,
    cfg.chatAccent ? `data-chat-accent="${cfg.chatAccent}"` : "",
    `data-preview-mode="true"`,
    `data-preview-page-type="${cfg.pageType}"`,
    `data-preview-product="${cfg.product}"`,
    `data-language="${cfg.language}"`,
  ]
    .filter(Boolean)
    .join(" ");
  return [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    `<meta name="viewport" content="width=device-width, initial-scale=1.0">`,
    `<link rel="stylesheet" href="/widget/ask-ai-widget.css">`,
    "<style>html,body{margin:0;min-height:100%;background:#f6f7f9}</style>",
    "</head><body>",
    "<script>",
    `window.AskAIConfig = { apiUrl: "", language: ${JSON.stringify(cfg.language)}, previewMode: true, previewPageType: ${JSON.stringify(cfg.pageType)}, previewProduct: ${JSON.stringify(cfg.product)}, previewActions: ${JSON.stringify(cfg.actions)} };`,
    "</script>",
    `<script src="/widget/widget.js" ${attrs}></script>`,
    "</body></html>",
  ].join("");
}

/** 外观选择卡片 mini 预览(真实 Widget 产物;不可交互)。 */
function appearanceCardDoc(icon: string, shape: string, theme: string): string {
  return [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    `<link rel=\"stylesheet\" href=\"/widget/ask-ai-widget.css\">`,
    "<style>html,body{margin:0;min-height:100%;background:#f6f7f9}</style>",
    "</head><body>",
    `<script src=\"/widget/widget.js\" data-preview-mode=\"true\" data-launcher-presentation=\"icon\" data-launcher-icon=\"${icon}\" data-launcher-shape=\"${shape}\" data-launcher-theme=\"${theme}\"></script>`,
    "</body></html>",
  ].join("");
}

export default function WidgetWorkspace() {
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<SiteRow>>({});
  const [section, setSection] = useState<SectionId>("entry");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  // Authorized Websites 局部状态(即时生效,无草稿)
  const [originInput, setOriginInput] = useState("");
  const [originBusy, setOriginBusy] = useState(false);

  // 预览模拟态(临时,绝不入 draft / 绝不随 Save 持久化)
  const [previewDevice, setPreviewDevice] = useState<"desktop" | "mobile">("desktop");
  const [previewPageType, setPreviewPageType] = useState("product");
  const [previewProduct, setPreviewProduct] = useState("NE503");
  const [previewLanguage, setPreviewLanguage] = useState("en");
  const [previewTheme, setPreviewTheme] = useState<string>("site");
  const [previewNonce, setPreviewNonce] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [experience, appearance, websites] = await Promise.all([
        apiFetch<
          (Omit<SiteRow, "launcher_icon" | "launcher_shape" | "launcher_theme" | "legacy_launcher_style" | "allowed_origins">)[]
        >("/widget-experience"),
        apiFetch<
          { site_id: string; display_name: string; enabled: boolean; launcher_icon: string; launcher_shape: string; launcher_theme: string; legacy_launcher_style?: string | null }[]
        >("/widget-appearance"),
        apiFetch<{ site_id: string; allowed_origins: string[] }[]>("/authorized-websites"),
      ]);
      const appearanceBySite = new Map(appearance.map((a) => [a.site_id, a]));
      const originsBySite = new Map(websites.map((w) => [w.site_id, w.allowed_origins]));
      const merged: SiteRow[] = experience.map((e) => {
        const app = appearanceBySite.get(e.site_id);
        return {
          ...e,
          launcher_icon: app?.launcher_icon ?? "current",
          launcher_shape: app?.launcher_shape ?? "rounded-square",
          launcher_theme: app?.launcher_theme ?? "auto",
          legacy_launcher_style: app?.legacy_launcher_style ?? null,
          allowed_origins: originsBySite.get(e.site_id) ?? [],
        };
      });
      setSites(merged);
      setSelectedSiteId((prev) => prev ?? merged[0]?.site_id ?? null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => sites.find((s) => s.site_id === selectedSiteId) ?? null,
    [sites, selectedSiteId],
  );

  const draftValue = <K extends keyof SiteRow>(key: K, fallback: SiteRow[K]): SiteRow[K] =>
    (draft[key] as SiteRow[K] | undefined) ?? selected?.[key] ?? fallback;

  const selectSite = (siteId: string) => {
    setSelectedSiteId(siteId);
    setDraft({});
    setOriginInput("");
  };

  const dirty = useMemo(
    () =>
      !!selected &&
      Object.keys(draft).some((k) => {
        const key = k as keyof SiteRow;
        return draft[key] !== undefined && draft[key] !== selected[key];
      }),
    [draft, selected],
  );

  /**
   * Greeting 模式:null = automatic(推荐,默认);字符串(含空串 = 正在输入)
   * = custom 模板。持久域无第三态:空串在语义上等同未解析变量较多时的自动
   * 行为(Widget 侧 greeting_override 空 → 自动链),但 Admin 编辑态必须能
   * 区分「清空回自动」与「自定义模板输入中」。
   */
  const overrideDraft = draft.greeting_override;
  const greetingMode =
    overrideDraft !== undefined
      ? overrideDraft === null
        ? "automatic"
        : "custom"
      : selected?.greeting_override
        ? "custom"
        : "automatic";

  const saveExperience = async () => {
    if (!selectedSiteId) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {};
      const appearanceBody: Record<string, unknown> | null = APPEARANCE_FIELDS.some(
        (f) => draft[f] !== undefined && draft[f] !== selected![f],
      )
        ? {}
        : null;
      for (const k of Object.keys(draft) as (keyof SiteRow)[]) {
        const value = draft[k];
        if (value === undefined) continue;
        if ((APPEARANCE_FIELDS as readonly string[]).includes(k)) {
          if (appearanceBody && value !== selected![k]) appearanceBody[k] = value;
          continue;
        }
        if ((EXPERIENCE_FIELDS as readonly string[]).includes(k)) {
          body[k] = value;
          if (value === null && k === "greeting_override") body.clear_greeting_override = true;
          if (value === null && k === "launcher_color") body.clear_launcher_color = true;
          if (value === null && k === "chat_accent_color") body.clear_chat_accent_color = true;
        }
      }
      const hasExperience = Object.keys(body).some((k) => !k.startsWith("clear_"));
      if (hasExperience) {
        await apiFetch(`/widget-experience/${encodeURIComponent(selectedSiteId)}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      }
      if (appearanceBody && Object.keys(appearanceBody).length > 0) {
        await apiFetch(`/widget-appearance/${encodeURIComponent(selectedSiteId)}`, {
          method: "PUT",
          body: JSON.stringify(appearanceBody),
        });
      }
      toast.success("Widget 配置已保存(访客 Widget 下一次加载生效)");
      await load();
      setDraft({});
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  // ---------------- Authorized Websites(即时生效;#6) ----------------
  const addOrigin = async () => {
    if (!selectedSiteId || !originInput.trim()) return;
    setOriginBusy(true);
    try {
      const updated = await apiFetch<SiteRow>(
        `/authorized-websites/${encodeURIComponent(selectedSiteId)}/origins`,
        { method: "POST", body: JSON.stringify({ origin: originInput.trim() }) },
      );
      setSites((prev) =>
        prev.map((s) =>
          s.site_id === updated.site_id ? { ...s, allowed_origins: updated.allowed_origins } : s,
        ),
      );
      setOriginInput("");
      toast.success(`已授权 ${updated.allowed_origins.length} 个来源;CORS 将在数秒内自动同步`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "添加失败");
    } finally {
      setOriginBusy(false);
    }
  };

  const removeOrigin = async (origin: string) => {
    if (!selectedSiteId) return;
    const origins = selected?.allowed_origins ?? [];
    if (origins.length <= 1) {
      const confirmed = window.confirm(
        `「${origin}」是该站点最后一个已授权来源。移除后,该站点所有网页上的 Widget 将立即无法访问 Ask AI(浏览器 CORS 与服务端授权同时拒绝),直到重新添加授权。确定移除吗?`,
      );
      if (!confirmed) return;
    }
    setOriginBusy(true);
    try {
      const updated = await apiFetch<SiteRow>(
        `/authorized-websites/${encodeURIComponent(selectedSiteId)}/origins`,
        { method: "DELETE", body: JSON.stringify({ origin }) },
      );
      setSites((prev) =>
        prev.map((s) =>
          s.site_id === updated.site_id ? { ...s, allowed_origins: updated.allowed_origins } : s,
        ),
      );
      toast.success("已移除授权来源");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "移除失败");
    } finally {
      setOriginBusy(false);
    }
  };

  // ---------------- Trusted Actions ----------------
  const addAction = async () => {
    if (!selectedSiteId) return;
    const type = "PRODUCT_SPECIFICATIONS";
    try {
      await apiFetch(`/widget-experience/${encodeURIComponent(selectedSiteId)}/actions`, {
        method: "POST",
        body: JSON.stringify({
          action_type: type,
          label: ACTION_TYPES.find((t) => t.id === type)?.label ?? type,
          query: "What are the specifications of {product}?",
        }),
      });
      toast.success("已新建动作(草稿);请编辑问题并执行 Test");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "新建失败");
    }
  };

  const patchAction = async (id: string, body: Record<string, unknown>, note: string) => {
    try {
      await apiFetch(`/widget-experience/actions/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      toast.success(note);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const actionOp = async (id: string, op: "test" | "verify" | "state", state?: string) => {
    setTesting(id);
    try {
      if (op === "state") {
        await apiFetch(`/widget-experience/actions/${id}/state`, {
          method: "POST",
          body: JSON.stringify({ state }),
        });
        toast.success(state === "published" ? "已发布(主动曝光生效)" : "已下架");
      } else {
        await apiFetch(`/widget-experience/actions/${id}/${op}`, { method: "POST" });
        toast.success(op === "test" ? "真实 ASK-AI 测试完成,请人工确认结果" : "已验证");
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setTesting(null);
    }
  };

  const deleteAction = async (id: string) => {
    try {
      await apiFetch(`/widget-experience/actions/${id}`, { method: "DELETE" });
      toast.success("已删除");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  // ---------------- Preview & Test ----------------
  // #36 修复:预览 launcher 外观 = 草稿解析值(绝不硬编码旧版图标);
  // #37:previewTheme 为临时模拟覆写(仅注入 iframe;不属于草稿,
  // Save 的请求体永不包含它;Reset 回「使用站点配置」)。
  const previewSrc = useMemo(
    () =>
      previewDoc({
        entryMode: (draft.entry_mode ?? selected?.entry_mode ?? "mini_entry") as string,
        proactive: (draft.proactive_timing ?? selected?.proactive_timing ?? "balanced") as string,
        launcherPresentation: (draft.launcher_presentation ??
          selected?.launcher_presentation ??
          "icon") as string,
        launcherIcon: (draft.launcher_icon ?? selected?.launcher_icon ?? "current") as string,
        launcherShape: (draft.launcher_shape ?? selected?.launcher_shape ?? "rounded-square") as string,
        launcherTheme: (draft.launcher_theme ?? selected?.launcher_theme ?? "auto") as string,
        launcherMotion: (draft.launcher_motion ?? selected?.launcher_motion ?? "subtle_glow") as string,
        launcherSize: (draft.launcher_size ?? selected?.launcher_size ?? "medium") as string,
        launcherBrand: (draft.launcher_brand ?? selected?.launcher_brand ?? "askai") as string,
        launcherColor: (draft.launcher_color ?? selected?.launcher_color ?? "") as string,
        chatTheme: previewTheme === "site" ? ((draft.chat_theme ?? selected?.chat_theme ?? "match") as string) : previewTheme,
        chatAccent: (draft.chat_accent_color ?? selected?.chat_accent_color ?? "") as string,
        pageType: previewPageType,
        product: previewProduct,
        language: previewLanguage,
        actions: (selected?.trusted_actions ?? [])
          .filter((a) => a.state === "published")
          .slice(0, 3)
          .map((a) => ({ type: a.action_type, label: a.label, query: a.query })),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 预览按草稿字段整体重算
    [draft, selected, previewPageType, previewProduct, previewLanguage, previewTheme],
  );

  const greetingTemplateForPreview =
    (draft.greeting_override as string | undefined) ?? selected?.greeting_override ?? "";
  const greetingResolvedPreview =
    greetingMode === "custom" && greetingTemplateForPreview
      ? resolveGreetingPreview(greetingTemplateForPreview, {
          product: previewProduct,
          pageTitle: "",
          pageType: previewPageType,
        })
      : "";

  if (loading) return <p className="text-sm text-muted-foreground">加载中…</p>;
  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!sites.length) return <p className="text-sm text-muted-foreground">尚无站点体验。</p>;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Widget</h1>
      <p className="text-sm text-muted-foreground">
        统一 Widget 工作区:入口与参与、外观、授权网站、预览与测试。配置编辑 = 生产草稿
        (需显式保存);预览/测试控件 = 临时模拟,绝不随保存持久化。预览复用真实 Widget 渲染。
      </p>

      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Widget 工作区分区">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={section === s.id}
            onClick={() => setSection(s.id)}
            className={`rounded-md border px-3 py-1.5 text-sm ${
              section === s.id ? "border-primary bg-primary/5 font-medium" : "hover:bg-muted/40"
            }`}
          >
            {s.label}
            <span className="ml-2 text-xs text-muted-foreground">{s.hint}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <Card aria-label="站点选择">
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">站点体验</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 p-4 pt-0">
            {sites.map((s) => (
              <button
                key={s.site_id}
                type="button"
                onClick={() => selectSite(s.site_id)}
                className={`w-full rounded-md border p-2 text-left text-sm ${
                  s.site_id === selectedSiteId ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                }`}
              >
                <span className="font-medium">{s.display_name}</span>
                <span className="ml-2 font-mono text-xs text-muted-foreground">{s.site_id}</span>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {ENTRY_MODES.find((m) => m.id === (s.entry_mode ?? "legacy"))?.label}
                  {!s.enabled && <span className="ml-1">(已禁用)</span>}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        {selected && (
          <div className="space-y-4">
            {/* ================================================================ */}
            {/* 区 1 — Entry & Engagement                                        */}
            {/* ================================================================ */}
            {section === "entry" && (
              <>
                <Card aria-label="入口呈现">
                  <CardHeader className="p-4 pb-2">
                    <CardTitle className="text-sm">入口呈现</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 p-4 pt-0">
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      {ENTRY_MODES.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          aria-pressed={draftValue("entry_mode", null as string | null) === m.id}
                          onClick={() => setDraft((d) => ({ ...d, entry_mode: m.id }))}
                          className={`rounded-md border p-2 text-left text-sm ${
                            draftValue("entry_mode", null as string | null) === m.id
                              ? "border-primary bg-primary/5"
                              : "hover:bg-muted/40"
                          }`}
                        >
                          <span className="block font-medium">{m.label}</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">{m.hint}</span>
                        </button>
                      ))}
                    </div>
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">主动展开时序(C 桌面自动展开;移动端主动呈现为 B)</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {PROACTIVE_TIMINGS.map((t) => (
                          <Chip
                            key={t.id}
                            active={draftValue("proactive_timing", null as string | null) === t.id}
                            onClick={() => setDraft((d) => ({ ...d, proactive_timing: t.id }))}
                          >
                            {t.label}
                          </Chip>
                        ))}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        主动展开每站点会话至多一次;访客关闭后本会话不再主动;SPA 切页不重触发。
                      </p>
                    </div>
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">启动器呈现方式(V2.3:品牌胶囊为新站点默认;既有未配置站点保持紧凑图标)</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {LAUNCHER_PRESENTATIONS.map((t) => (
                          <Chip
                            key={t.id}
                            active={draftValue("launcher_presentation", null as string | null) === t.id}
                            onClick={() => setDraft((d) => ({ ...d, launcher_presentation: t.id }))}
                          >
                            {t.label}
                          </Chip>
                        ))}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">启动器动效(注意力提示,非装饰动画;跟随系统「减少动态」设置)</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {LAUNCHER_MOTIONS.map((t) => (
                          <Chip
                            key={t.id}
                            active={draftValue("launcher_motion", null as string | null) === t.id}
                            onClick={() => setDraft((d) => ({ ...d, launcher_motion: t.id }))}
                          >
                            {t.label}
                          </Chip>
                        ))}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">启动器尺寸</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {LAUNCHER_SIZES.map((t) => (
                          <Chip
                            key={t.id}
                            active={draftValue("launcher_size", null as string | null) === t.id}
                            onClick={() => setDraft((d) => ({ ...d, launcher_size: t.id }))}
                          >
                            {t.label}
                          </Chip>
                        ))}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">启动器品牌(独立于聊天窗主题)</span>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {LAUNCHER_BRANDS.map((t) => (
                          <Chip
                            key={t.id}
                            active={draftValue("launcher_brand", null as string | null) === t.id}
                            onClick={() => setDraft((d) => ({ ...d, launcher_brand: t.id }))}
                          >
                            {t.label}
                          </Chip>
                        ))}
                        {draftValue("launcher_brand", null as string | null) === "custom" && (
                          <input
                            type="color"
                            aria-label="启动器自定义颜色"
                            className="h-8 w-12 cursor-pointer rounded border"
                            value={(draft.launcher_color as string) ?? selected.launcher_color ?? "#f24a00"}
                            onChange={(e) => setDraft((d) => ({ ...d, launcher_color: e.target.value }))}
                          />
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card aria-label="上下文问候">
                  <CardHeader className="p-4 pb-2">
                    <CardTitle className="text-sm">上下文问候</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 p-4 pt-0">
                    <div className="flex flex-wrap gap-1">
                      <Chip
                        active={greetingMode === "automatic"}
                        onClick={() => setDraft((d) => ({ ...d, greeting_override: null }))}
                      >
                        自动(推荐)
                      </Chip>
                      <Chip
                        active={greetingMode === "custom"}
                        onClick={() => setDraft((d) => ({ ...d, greeting_override: "" }))}
                      >
                        自定义模板
                      </Chip>
                    </div>
                    {greetingMode === "automatic" ? (
                      <p className="text-xs text-muted-foreground">
                        按页面上下文确定性解析(零 LLM):受信页面上下文 → 页面类型模板 →
                        通用兜底;错误的具体不如正确的通用。
                      </p>
                    ) : (
                      <div className="space-y-1">
                        <input
                          className="w-full rounded-md border px-3 py-2 text-sm"
                          placeholder="如:Questions about {product_name}?"
                          aria-label="自定义问候模板"
                          value={(draft.greeting_override as string | undefined) ?? ""}
                          onChange={(e) => setDraft((d) => ({ ...d, greeting_override: e.target.value }))}
                        />
                        <p className="text-xs text-muted-foreground">{GREETING_VARIABLES_HINT}</p>
                        <p className="text-xs text-muted-foreground">
                          解析预览(以当前预览上下文为例):
                          {greetingResolvedPreview ? (
                            <span className="ml-1 font-medium text-foreground">{greetingResolvedPreview}</span>
                          ) : (
                            <span className="ml-1">变量无法解析 → 访客将看到自动问候(绝不暴露占位符)</span>
                          )}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card aria-label="可信动作">
                  <CardHeader className="p-4 pb-2">
                    <CardTitle className="text-sm">可信动作(仅「已验证/已发布」对访客可见;C 最多 2 个,空聊天最多 3 个)</CardTitle>
                    <Button type="button" size="sm" variant="outline" onClick={addAction}>
                      新建动作
                    </Button>
                  </CardHeader>
                  <CardContent className="space-y-2 p-4 pt-0">
                    {(selected.trusted_actions ?? []).length === 0 && (
                      <p className="text-xs text-muted-foreground">尚无动作;新建后编辑问题 → Test → Verify → Publish。</p>
                    )}
                    {(selected.trusted_actions ?? []).map((a) => (
                      <div key={a.id} className="rounded-md border p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={STATE_BADGES[a.state]?.variant ?? "default"}>
                            {STATE_BADGES[a.state]?.label ?? a.state}
                          </Badge>
                          <select
                            aria-label={`动作语义:${a.label}`}
                            className="rounded border bg-transparent px-2 py-1 text-xs"
                            value={a.action_type}
                            onChange={(e) =>
                              patchAction(a.id, { action_type: e.target.value }, "语义已更新,原验证失效(回到草稿)")
                            }
                          >
                            {ACTION_TYPES.map((t) => (
                              <option key={t.id} value={t.id}>
                                {t.label}
                              </option>
                            ))}
                          </select>
                          <input
                            aria-label={`动作展示名:${a.label}`}
                            className="w-40 rounded border px-2 py-1 text-xs"
                            defaultValue={a.label}
                            onBlur={(e) => {
                              if (e.target.value.trim() && e.target.value !== a.label) {
                                void patchAction(a.id, { label: e.target.value.trim() }, "展示名已更新(不影响验证)");
                              }
                            }}
                          />
                          <span className="ml-auto flex gap-1">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={testing === a.id}
                              onClick={() => actionOp(a.id, "test")}
                            >
                              {testing === a.id ? "测试中…" : "Test(真实 ASK-AI)"}
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={!a.last_test_result || a.state === "verified" || a.state === "published"}
                              onClick={() => actionOp(a.id, "verify")}
                            >
                              Verify
                            </Button>
                            {a.state !== "published" ? (
                              <Button
                                type="button"
                                size="sm"
                                disabled={a.state !== "verified"}
                                onClick={() => actionOp(a.id, "state", "published")}
                              >
                                Publish
                              </Button>
                            ) : (
                              <Button type="button" size="sm" variant="outline" onClick={() => actionOp(a.id, "state", "verified")}>
                                下架
                              </Button>
                            )}
                            <Button type="button" size="sm" variant="destructive" onClick={() => deleteAction(a.id)}>
                              删除
                            </Button>
                          </span>
                        </div>
                        <div className="mt-2 flex items-center gap-2">
                          <input
                            aria-label={`动作问题:${a.label}`}
                            className="flex-1 rounded border px-2 py-1 text-xs"
                            defaultValue={a.query}
                            onBlur={(e) => {
                              if (e.target.value.trim() && e.target.value !== a.query) {
                                void patchAction(a.id, { query: e.target.value.trim() }, "问题已更新,原验证失效(回到草稿)");
                              }
                            }}
                          />
                          <span className="text-[10px] text-muted-foreground">{"占位符:{product} {page_title}"}</span>
                        </div>
                        {a.last_test_result?.answer && (
                          <details className="mt-2 rounded bg-muted/40 p-2">
                            <summary className="cursor-pointer text-xs font-medium">
                              最近测试结果(真实 ASK-AI 输出;{a.last_tested_at?.slice(0, 19).replace("T", " ") ?? ""})
                            </summary>
                            <p className="mt-1 whitespace-pre-wrap text-xs">{a.last_test_result.answer}</p>
                            {a.last_test_result.sources && a.last_test_result.sources.length > 0 && (
                              <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                                {a.last_test_result.sources.map((s, i) => (
                                  <li key={i}>
                                    <a href={s.url} target="_blank" rel="noopener noreferrer" className="underline">
                                      {s.title || s.url}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            )}
                            <p className="mt-1 text-[10px] text-muted-foreground">
                              请人工确认答案与证据无误后点击 Verify;未验证/未发布的动作不会出现在访客 Widget。
                            </p>
                          </details>
                        )}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </>
            )}

            {/* ================================================================ */}
            {/* 区 2 — Appearance                                                */}
            {/* ================================================================ */}
            {section === "appearance" && (
              <Card aria-label="启动器与聊天窗外观">
                <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-2">
                  <CardTitle className="text-sm">外观</CardTitle>
                  {dirty ? <Badge variant="warning">未保存</Badge> : <Badge variant="success">已保存</Badge>}
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0">
                  {!!selected.legacy_launcher_style && selected.legacy_launcher_style !== "current" && (
                    <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
                      该站点此前的风格选择「{selected.legacy_launcher_style}」已随新图标体系退役,
                      当前显示「经典」外观。选择新图标并保存以完成替换。
                    </p>
                  )}

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">启动器图标(仅「紧凑图标」呈现方式;品牌胶囊使用 ✦ Ask AI 品牌)</span>
                    <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
                      {LAUNCHER_ICONS.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          aria-pressed={draftValue("launcher_icon", "current") === s.id}
                          aria-label={`图标样式:${s.label}`}
                          onClick={() => setDraft((d) => ({ ...d, launcher_icon: s.id }))}
                          className={`rounded-md border p-2 text-left text-sm ${
                            draftValue("launcher_icon", "current") === s.id
                              ? "border-primary bg-primary/5"
                              : "hover:bg-muted/40"
                          }`}
                        >
                          {/* 选择卡片 = canonical 渲染器 mini 预览(真实 Widget 产物) */}
                          <iframe
                            title={`图标预览:${s.label}`}
                            srcDoc={appearanceCardDoc(
                              s.id,
                              draftValue("launcher_shape", "rounded-square"),
                              draftValue("launcher_theme", "auto"),
                            )}
                            sandbox="allow-scripts"
                            className="h-[88px] w-full"
                            style={{ pointerEvents: "none", border: "none" }}
                          />
                          <span className="mt-1 block font-medium">{s.label}</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">{s.hint}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">按钮形状(对「经典」图标不生效)</span>
                    <div className="flex flex-wrap gap-1">
                      {LAUNCHER_SHAPES.map((sh) => (
                        <Chip
                          key={sh.id}
                          active={draftValue("launcher_shape", "rounded-square") === sh.id}
                          onClick={() => setDraft((d) => ({ ...d, launcher_shape: sh.id }))}
                        >
                          {sh.label}
                        </Chip>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">启动器主题</span>
                    <div className="flex flex-wrap gap-1">
                      {LAUNCHER_THEMES.map((t) => (
                        <Chip
                          key={t.id}
                          active={draftValue("launcher_theme", "auto") === t.id}
                          onClick={() => setDraft((d) => ({ ...d, launcher_theme: t.id }))}
                        >
                          {t.label}
                        </Chip>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">
                      聊天窗主题(「跟随网站」只读取安全品牌信号,派生 Ask AI 自有配色;不继承站点 CSS;无第五种「自动」模式)
                    </span>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {CHAT_THEMES.map((t) => (
                        <Chip
                          key={t.id}
                          active={draftValue("chat_theme", null as string | null) === t.id}
                          onClick={() => setDraft((d) => ({ ...d, chat_theme: t.id }))}
                        >
                          {t.label}
                        </Chip>
                      ))}
                      {draftValue("chat_theme", null as string | null) === "custom" && (
                        <input
                          type="color"
                          aria-label="聊天窗强调色"
                          className="h-8 w-12 cursor-pointer rounded border"
                          value={(draft.chat_accent_color as string) ?? selected.chat_accent_color ?? "#f24a00"}
                          onChange={(e) => setDraft((d) => ({ ...d, chat_accent_color: e.target.value }))}
                        />
                      )}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">聊天窗尺寸</span>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {CHAT_SIZES.map((t) => (
                        <Chip
                          key={t.id}
                          active={draftValue("chat_size", null as string | null) === t.id}
                          onClick={() => setDraft((d) => ({ ...d, chat_size: t.id }))}
                        >
                          {t.label}
                        </Chip>
                      ))}
                    </div>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    保存后该站点 Widget 下一次加载生效,客户网页嵌入代码无需改动;启动器主题「自动」
                    跟随访问者系统深浅色偏好,无法检测时使用浅色。
                  </p>
                </CardContent>
              </Card>
            )}

            {/* ================================================================ */}
            {/* 区 3 — Authorized Websites(#6)                                  */}
            {/* ================================================================ */}
            {section === "websites" && (
              <Card aria-label="授权网站">
                <CardHeader className="p-4 pb-2">
                  <CardTitle className="text-sm">授权网站(Authorized Websites)</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0">
                  <p className="text-xs text-muted-foreground">
                    允许嵌入/调用该站点 Widget 的**精确来源**列表(scheme + host + 可选非默认端口;
                    http/https 视为不同来源)。变更即时生效:浏览器 CORS 与服务端授权消费同一权威,
                    数秒内自动同步,无需重新部署。禁止通配符/路径授权。
                  </p>
                  <ul className="space-y-1" aria-label="已授权来源列表">
                    {(selected.allowed_origins ?? []).length === 0 && (
                      <li className="text-xs text-destructive">
                        该站点当前没有任何已授权来源 —— 访客 Widget 将无法访问(移除前应有明确警示)。
                      </li>
                    )}
                    {(selected.allowed_origins ?? []).map((origin) => (
                      <li
                        key={origin}
                        className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                      >
                        <span className="font-mono text-xs">{origin}</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={originBusy}
                          onClick={() => removeOrigin(origin)}
                        >
                          移除
                        </Button>
                      </li>
                    ))}
                  </ul>
                  <div className="flex items-center gap-2">
                    <input
                      className="w-72 rounded-md border px-3 py-2 text-sm font-mono"
                      placeholder="https://www.example.com:8443"
                      aria-label="新增授权来源"
                      value={originInput}
                      onChange={(e) => setOriginInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void addOrigin();
                        }
                      }}
                    />
                    <Button type="button" onClick={addOrigin} disabled={originBusy || !originInput.trim()}>
                      添加授权
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* ================================================================ */}
            {/* 区 4 — Preview & Test(#36/#37)                                  */}
            {/* ================================================================ */}
            {section === "preview" && (
              <Card aria-label="预览与测试">
                <CardHeader className="p-4 pb-2">
                  <CardTitle className="text-sm">预览与测试(真实 Widget 渲染)</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip active={previewDevice === "desktop"} onClick={() => setPreviewDevice("desktop")}>
                      桌面
                    </Chip>
                    <Chip active={previewDevice === "mobile"} onClick={() => setPreviewDevice("mobile")}>
                      移动
                    </Chip>
                    <select
                      aria-label="预览页面类型"
                      className="rounded border bg-transparent px-2 py-1.5 text-sm"
                      value={previewPageType}
                      onChange={(e) => setPreviewPageType(e.target.value)}
                    >
                      {PAGE_TYPES.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="预览产品"
                      className="w-32 rounded border px-2 py-1.5 text-sm"
                      placeholder="产品名"
                      value={previewProduct}
                      onChange={(e) => setPreviewProduct(e.target.value)}
                    />
                    <select
                      aria-label="预览语言"
                      className="rounded border bg-transparent px-2 py-1.5 text-sm"
                      value={previewLanguage}
                      onChange={(e) => setPreviewLanguage(e.target.value)}
                    >
                      <option value="en">English</option>
                      <option value="zh">中文</option>
                    </select>
                    <Button type="button" size="sm" variant="outline" onClick={() => setPreviewNonce((n) => n + 1)}>
                      重载预览
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">预览主题(临时模拟;不随保存写入站点配置)</span>
                    {PREVIEW_THEMES.map((t) => (
                      <Chip key={t.id} active={previewTheme === t.id} onClick={() => setPreviewTheme(t.id)}>
                        {t.label}
                      </Chip>
                    ))}
                    {previewTheme !== "site" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setPreviewTheme("site")}
                      >
                        重置(使用站点配置)
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    预览内可点击/展开/输入(engagement preview);发送只产生确定性预览回显,不创建会话、
                    不产生 /ask 流量。Trusted Action 的真实测试请在其管理卡片执行 Test(走真实 ASK-AI 管道)。
                  </p>
                  <div
                    className="overflow-hidden rounded-md border"
                    style={{ background: "#f6f7f9" }}
                  >
                    <iframe
                      key={`${previewSrc.length}-${previewNonce}`}
                      title="Widget 实时预览(真实 Widget 渲染)"
                      srcDoc={previewSrc}
                      sandbox="allow-scripts"
                      className={
                        previewDevice === "mobile"
                          ? "mx-auto block h-[640px] w-[390px]"
                          : "block h-[560px] w-full"
                      }
                      style={{ border: "none" }}
                    />
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="flex items-center gap-2">
              <Button type="button" onClick={saveExperience} disabled={!dirty || saving}>
                {saving ? "保存中…" : "保存 Widget 配置"}
              </Button>
              {dirty && <Badge variant="warning">未保存</Badge>}
              <span className="text-xs text-muted-foreground">
                仅保存生产配置草稿;预览主题等临时模拟不会被保存。
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
