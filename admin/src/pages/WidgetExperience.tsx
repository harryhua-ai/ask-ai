// I-UX-001:Admin Widget Experience(入口/主动展开/启动器/聊天窗/参与 + 实时预览)。
//
// - 分组冻结于产品契约 §2.16;未配置值 = NULL → Widget 侧 legacy/默认语义
//   (既有站点不变;新站点 seed 已默认 mini_entry);
// - 实时预览复用**真实 Widget 渲染路径**(/widget/widget.js,同一视觉实现,
//   无第二套渲染):iframe + data-* 覆写 + previewMode(不产生真实 /ask 流量);
// - Trusted Action 生命周期:新建(draft)→ Test(真实 ASK-AI 管道,结果
//   原样展示)→ Verify(人工验收)→ Publish;语义编辑(query/type)自动
//   失效回落 draft;纯 label 编辑不失效;
// - 无任意 CSS 编辑器/动画设计器(契约 §21 非目标)。

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

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

const LAUNCHER_ICONS = [
  { id: "current", label: "经典(默认)" },
  { id: "bot-sparkle", label: "机器人 + 星光" },
  { id: "bubble-sparkle-fill", label: "气泡星光 · 填充" },
  { id: "robot-smile", label: "机器人笑脸" },
  { id: "bubble-sparkle-outline", label: "气泡星光 · 描边" },
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

interface SiteExperience {
  site_id: string;
  display_name: string;
  enabled: boolean;
  launcher_icon: string | null;
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
  trusted_actions: TrustedAction[];
}

const STATE_BADGES: Record<string, { label: string; variant: "default" | "warning" | "success" }> = {
  draft: { label: "草稿", variant: "default" },
  verified: { label: "已验证", variant: "warning" },
  published: { label: "已发布", variant: "success" },
};

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

/** 实时预览文档:真实 Widget 产物 + data-* 覆写 + previewActions 注入。 */
function previewDoc(cfg: {
  entryMode: string;
  proactive: string;
  launcherIcon: string;
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
    `data-launcher-icon="${cfg.launcherIcon}"`,
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

export default function WidgetExperience() {
  const [sites, setSites] = useState<SiteExperience[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<SiteExperience>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  // 预览上下文
  const [previewDevice, setPreviewDevice] = useState<"desktop" | "mobile">("desktop");
  const [previewPageType, setPreviewPageType] = useState("product");
  const [previewProduct, setPreviewProduct] = useState("NE503");
  const [previewLanguage, setPreviewLanguage] = useState("en");
  const [previewNonce, setPreviewNonce] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await apiFetch<SiteExperience[]>("/widget-experience");
      setSites(list);
      setSelectedSiteId((prev) => prev ?? list[0]?.site_id ?? null);
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

  const draftValue = <K extends keyof SiteExperience>(key: K, fallback: SiteExperience[K]): SiteExperience[K] =>
    (draft[key] as SiteExperience[K] | undefined) ?? selected?.[key] ?? fallback;

  const selectSite = (siteId: string) => {
    setSelectedSiteId(siteId);
    setDraft({});
  };

  const dirty = useMemo(
    () =>
      !!selected &&
      Object.keys(draft).some((k) => {
        const key = k as keyof SiteExperience;
        return draft[key] !== undefined && draft[key] !== selected[key];
      }),
    [draft, selected],
  );

  const saveExperience = async () => {
    if (!selectedSiteId) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {};
      for (const k of Object.keys(draft)) {
        const key = k as keyof SiteExperience;
        if (draft[key] === undefined) continue;
        body[k] = draft[key];
        if (draft[key] === null && key === "greeting_override") body.clear_greeting_override = true;
        if (draft[key] === null && key === "launcher_color") body.clear_launcher_color = true;
        if (draft[key] === null && key === "chat_accent_color") body.clear_chat_accent_color = true;
      }
      await apiFetch(`/widget-experience/${encodeURIComponent(selectedSiteId)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      toast.success("体验配置已保存(Widget 下一次加载生效)");
      await load();
      setDraft({});
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  // ---------------- Trusted Actions ----------------
  const reloadSite = async () => {
    await load();
  };

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
      await reloadSite();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "新建失败");
    }
  };

  const patchAction = async (id: string, body: Record<string, unknown>, note: string) => {
    try {
      await apiFetch(`/widget-experience/actions/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      toast.success(note);
      await reloadSite();
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
      await reloadSite();
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
      await reloadSite();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const previewSrc = useMemo(
    () =>
      previewDoc({
        entryMode: (draft.entry_mode ?? selected?.entry_mode ?? "mini_entry") as string,
        proactive: (draft.proactive_timing ?? selected?.proactive_timing ?? "balanced") as string,
        launcherIcon: "current",
        launcherMotion: (draft.launcher_motion ?? selected?.launcher_motion ?? "subtle_glow") as string,
        launcherSize: (draft.launcher_size ?? selected?.launcher_size ?? "medium") as string,
        launcherBrand: (draft.launcher_brand ?? selected?.launcher_brand ?? "askai") as string,
        launcherColor: (draft.launcher_color ?? selected?.launcher_color ?? "") as string,
        chatTheme: (draft.chat_theme ?? selected?.chat_theme ?? "match") as string,
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
    [draft, selected, previewPageType, previewProduct, previewLanguage],
  );

  if (loading) return <p className="text-sm text-muted-foreground">加载中…</p>;
  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (!sites.length) return <p className="text-sm text-muted-foreground">尚无站点体验。</p>;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Widget 体验</h1>
      <p className="text-sm text-muted-foreground">
        入口呈现、主动展开、启动器与聊天窗、上下文问候与可信动作;未配置的既有站点保持现状,
        新站点默认 C(Mini Conversation Entry)。预览复用真实 Widget 渲染(预览内发送不产生真实请求)。
      </p>

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
                  入口:{ENTRY_MODES.find((m) => m.id === (s.entry_mode ?? "legacy"))?.label}
                  {!s.enabled && <span className="ml-1">(已禁用)</span>}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        {selected && (
          <div className="space-y-4">
            {/* ---------- 入口 ---------- */}
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
              </CardContent>
            </Card>

            {/* ---------- 启动器 ---------- */}
            <Card aria-label="启动器">
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm">启动器</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                <div className="flex flex-wrap gap-1">
                  {LAUNCHER_ICONS.map((t) => (
                    <Chip
                      key={t.id}
                      active={draftValue("launcher_icon", null as string | null) === t.id}
                      onClick={() => setDraft((d) => ({ ...d, launcher_icon: t.id }))}
                    >
                      {t.label}
                    </Chip>
                  ))}
                </div>
                <div>
                  <span className="text-xs font-medium text-muted-foreground">动效(注意力提示,非装饰动画;跟随系统「减少动态」设置)</span>
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
                  <span className="text-xs font-medium text-muted-foreground">尺寸</span>
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
                  <span className="text-xs font-medium text-muted-foreground">品牌(独立于聊天窗主题)</span>
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

            {/* ---------- 聊天窗 ---------- */}
            <Card aria-label="聊天窗">
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm">聊天窗</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">
                    主题(「跟随网站」只读取安全品牌信号,派生 Ask AI 自有配色;不继承站点 CSS)
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
                <div>
                  <span className="text-xs font-medium text-muted-foreground">窗口尺寸</span>
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
              </CardContent>
            </Card>

            {/* ---------- 参与 ---------- */}
            <Card aria-label="参与">
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm">参与(问候与可信动作)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">
                    问候覆写(留空 = 按页面上下文确定性解析;优先级:覆写 → 页面上下文 → 页面类型模板 → 通用)
                  </span>
                  <input
                    className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
                    placeholder="如:Questions about NE503?"
                    value={(draft.greeting_override as string | undefined) ?? selected.greeting_override ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, greeting_override: e.target.value || null }))}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">
                      可信动作(仅「已验证/已发布」对访客可见;C 最多 2 个,空聊天最多 3 个)
                    </span>
                    <Button type="button" size="sm" variant="outline" onClick={addAction}>
                      新建动作
                    </Button>
                  </div>
                  {(selected.trusted_actions ?? []).length === 0 && (
                    <p className="text-xs text-muted-foreground">尚无动作;新建后编辑问题 → Test → Verify → Publish。</p>
                  )}
                  <div className="space-y-2">
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
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="flex items-center gap-2">
              <Button type="button" onClick={saveExperience} disabled={!dirty || saving}>
                {saving ? "保存中…" : "保存体验配置"}
              </Button>
              {dirty && <Badge variant="warning">未保存</Badge>}
            </div>

            {/* ---------- 实时预览 ---------- */}
            <Card aria-label="实时预览">
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm">实时预览(真实 Widget 渲染)</CardTitle>
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
                <p className="text-xs text-muted-foreground">
                  预览内可点击/展开/输入(engagement preview);发送只产生确定性预览回显,不创建会话、不产生 /ask 流量。
                </p>
                <div
                  className="overflow-hidden rounded-md border"
                  style={{ background: "#f6f7f9" }}
                >
                  <iframe
                    key={`${previewSrc.length}-${previewNonce}`}
                    title="Widget 体验实时预览(真实 Widget 渲染)"
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
          </div>
        )}
      </div>
    </div>
  );
}
