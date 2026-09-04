// Issue #24 REV1:Widget 外观管理(per-site launcher icon × shape × theme)。
//
// 统一语义 = 图标(Icon Style)× 形状(Button Shape)× 主题(Theme);
// 选择卡片与实时预览共用真实 Widget 产物(/widget/widget.js + css)作为
// 唯一渲染真相 —— 不在 Admin 复刻 SVG/CSS,不存在第二套视觉实现;
// iframe pointer-events:none + sandbox(仅 allow-scripts):预览不可交互,
// 不产生 /ask 流量、不创建会话、不触碰站点授权;未保存前零写请求。
// UI 只呈现人类可读标签,不暴露语义 id 之外的实现细节(无 SVG 文件名)。

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

/** 内置图标(与后端 LAUNCHER_ICONS / widget 注册表同一冻结集合;current 恒为兼容默认)。 */
const LAUNCHER_ICONS = [
  { id: "current", label: "经典(默认)", hint: "当前线上外观,升级零变化" },
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

interface SiteAppearance {
  site_id: string;
  display_name: string;
  enabled: boolean;
  launcher_icon: string;
  launcher_shape: string;
  launcher_theme: string;
  /** REV0 遗留风格选择(已退役);存在且非 current 时 UI 提示重新选择 */
  legacy_launcher_style?: string | null;
}

function iconLabel(id: string): string {
  return LAUNCHER_ICONS.find((s) => s.id === id)?.label ?? id;
}

function shapeLabel(id: string): string {
  return LAUNCHER_SHAPES.find((s) => s.id === id)?.label ?? id;
}

function themeLabel(id: string): string {
  return LAUNCHER_THEMES.find((t) => t.id === id)?.label ?? id;
}

/** 预览文档:真实 Widget 产物 + data-launcher-* 覆写(未保存草稿即时可见)。 */
function previewDoc(icon: string, shape: string, theme: string, bg: "light" | "dark"): string {
  const background = bg === "dark" ? "#14161a" : "#f6f7f9";
  return [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    `<link rel=\"stylesheet\" href=\"/widget/ask-ai-widget.css\">`,
    `<style>html,body{margin:0;min-height:100%;background:${background}}</style>`,
    "</head><body>",
    `<script src=\"/widget/widget.js\" data-launcher-icon=\"${icon}\" data-launcher-shape=\"${shape}\" data-launcher-theme=\"${theme}\"></script>`,
    "</body></html>",
  ].join("");
}

export default function WidgetAppearance() {
  const [sites, setSites] = useState<SiteAppearance[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  // 草稿(未保存的预览选择);与已保存值分离(未保存不落库)
  const [draftIcon, setDraftIcon] = useState<string>("current");
  const [draftShape, setDraftShape] = useState<string>("rounded-square");
  const [draftTheme, setDraftTheme] = useState<string>("auto");
  const [hostBg, setHostBg] = useState<"light" | "dark">("light");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await apiFetch<SiteAppearance[]>("/widget-appearance");
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

  const selectSite = (siteId: string) => {
    setSelectedSiteId(siteId);
    const site = sites.find((s) => s.site_id === siteId);
    // 切站点 = 草稿回滚到该站点已保存值(未保存的选择不跨站点携带)
    setDraftIcon(site?.launcher_icon ?? "current");
    setDraftShape(site?.launcher_shape ?? "rounded-square");
    setDraftTheme(site?.launcher_theme ?? "auto");
  };

  const dirty =
    !!selected &&
    (draftIcon !== selected.launcher_icon ||
      draftShape !== selected.launcher_shape ||
      draftTheme !== selected.launcher_theme);

  const save = async () => {
    if (!selectedSiteId) return;
    setSaving(true);
    try {
      const updated = await apiFetch<SiteAppearance>(
        `/widget-appearance/${encodeURIComponent(selectedSiteId)}`,
        {
          method: "PUT",
          body: JSON.stringify({
            launcher_icon: draftIcon,
            launcher_shape: draftShape,
            launcher_theme: draftTheme,
          }),
        },
      );
      setSites((prev) => prev.map((s) => (s.site_id === updated.site_id ? updated : s)));
      toast.success(
        `已保存:${updated.display_name} → ${iconLabel(updated.launcher_icon)} / ${shapeLabel(updated.launcher_shape)} / ${themeLabel(updated.launcher_theme)}`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const mainPreview = useMemo(
    () => previewDoc(draftIcon, draftShape, draftTheme, hostBg),
    [draftIcon, draftShape, draftTheme, hostBg],
  );

  const showLegacyNote =
    !!selected?.legacy_launcher_style && selected.legacy_launcher_style !== "current";

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Widget 外观</h1>
      <p className="text-sm text-muted-foreground">
        为每个站点体验选择启动器图标、形状与主题;保存后该站点 Widget 下一次加载即生效,
        无需修改客户网页嵌入代码。未配置的站点保持「经典」默认外观。
      </p>

      {loading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      {!loading && !loadError && sites.length === 0 && (
        <p className="text-sm text-muted-foreground">尚无站点体验(外观按站点配置)。</p>
      )}

      {sites.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
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
                    {iconLabel(s.launcher_icon)} · {shapeLabel(s.launcher_shape)} ·{" "}
                    {themeLabel(s.launcher_theme)}
                    {!s.enabled && <span className="ml-1">(已禁用)</span>}
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>

          {selected && (
            <div className="space-y-4">
              <Card aria-label="启动器外观">
                <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-2">
                  <CardTitle className="text-sm">启动器外观</CardTitle>
                  {dirty ? (
                    <Badge variant="warning">未保存</Badge>
                  ) : (
                    <Badge variant="success">已保存</Badge>
                  )}
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0">
                  {showLegacyNote && (
                    <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
                      该站点此前的风格选择「{selected.legacy_launcher_style}」已随新图标体系退役,
                      当前显示「经典」外观。选择新图标并保存以完成替换。
                    </p>
                  )}

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">图标样式</span>
                    <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
                      {LAUNCHER_ICONS.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          aria-pressed={draftIcon === s.id}
                          aria-label={`图标样式:${s.label}`}
                          onClick={() => setDraftIcon(s.id)}
                          className={`rounded-md border p-2 text-left text-sm ${
                            draftIcon === s.id ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                          }`}
                        >
                          {/* 选择卡片 = canonical 渲染器 mini 预览(真实 Widget 产物) */}
                          <iframe
                            title={`图标预览:${s.label}`}
                            srcDoc={previewDoc(s.id, draftShape, draftTheme, "light")}
                            sandbox="allow-scripts"
                            className="h-[88px] w-full"
                            style={{ pointerEvents: "none", border: "none" }}
                          />
                          <span className="mt-1 block font-medium">{s.label}</span>
                          {s.id === "current" && (
                            <span className="ml-1 rounded bg-muted px-1 text-xs">默认</span>
                          )}
                          <span className="mt-0.5 block text-xs text-muted-foreground">{s.hint}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">按钮形状</span>
                    <div className="flex flex-wrap gap-1">
                      {LAUNCHER_SHAPES.map((sh) => (
                        <button
                          key={sh.id}
                          type="button"
                          aria-pressed={draftShape === sh.id}
                          onClick={() => setDraftShape(sh.id)}
                          className={`rounded-md border px-3 py-1.5 text-sm ${
                            draftShape === sh.id ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                          }`}
                        >
                          {sh.label}
                        </button>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      形状对「经典」图标不生效(保持原外观);对以上四个新图标生效。
                    </p>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">主题</span>
                    <div className="flex flex-wrap gap-1">
                      {LAUNCHER_THEMES.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          aria-pressed={draftTheme === t.id}
                          onClick={() => setDraftTheme(t.id)}
                          className={`rounded-md border px-3 py-1.5 text-sm ${
                            draftTheme === t.id ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                          }`}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">预览页面背景</span>
                    <div className="flex gap-1">
                      {(["light", "dark"] as const).map((bg) => (
                        <button
                          key={bg}
                          type="button"
                          aria-pressed={hostBg === bg}
                          onClick={() => setHostBg(bg)}
                          className={`rounded-md border px-3 py-1.5 text-sm ${
                            hostBg === bg ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                          }`}
                        >
                          {bg === "light" ? "浅色页面" : "深色页面"}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div
                    className="relative overflow-hidden rounded-md border"
                    style={{ background: hostBg === "dark" ? "#14161a" : "#f6f7f9" }}
                  >
                    <iframe
                      title="启动器实时预览(真实 Widget 渲染)"
                      srcDoc={mainPreview}
                      sandbox="allow-scripts"
                      className="h-56 w-full"
                      style={{ pointerEvents: "none", border: "none" }}
                    />
                    <span className="pointer-events-none absolute bottom-1 left-2 text-[10px] text-muted-foreground">
                      实时预览 = 真实 Widget 渲染(不可交互)
                    </span>
                  </div>

                  <Button type="button" size="sm" onClick={save} disabled={!dirty || saving}>
                    {saving ? "保存中…" : "保存外观"}
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    保存后该站点 Widget 下一次加载生效,客户网页嵌入代码无需改动;「自动」跟随访问者
                    系统深浅色偏好,无法检测时使用浅色。
                  </p>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
