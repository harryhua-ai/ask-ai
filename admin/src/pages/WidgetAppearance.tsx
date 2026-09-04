// Issue #24:Widget 外观管理(per-site launcher 风格/主题;最小配置面)。
//
// 实时预览 = iframe 加载真实生产 widget 产物(/widget/widget.js + css,
// 与站点嵌入同一构建物),经 data-launcher-style/theme 覆写即时反映未保存
// 选择 —— 不存在第二套渲染实现(A7);iframe pointer-events:none +
// sandbox(仅 allow-scripts):预览不可交互,不产生 /ask 流量、不创建会话、
// 不触碰站点授权(G5);未保存前不发起任何写请求(A4)。

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

/** 语义风格身份(与后端 LAUNCHER_STYLES / widget 注册表同一冻结集合)。 */
const LAUNCHER_STYLES = [
  { id: "current", label: "经典(默认)", hint: "当前线上外观,升级零变化" },
  { id: "assistant-spark", label: "智能火花", hint: "品牌渐变 + 火花,现代 AI 助手" },
  { id: "chat-bubble", label: "对话气泡", hint: "会话中心,一眼即懂" },
  { id: "orbit-neural", label: "轨道神经", hint: "细线轨道节点,技术智能感" },
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
  launcher_style: string;
  launcher_theme: string;
}

function styleLabel(id: string): string {
  return LAUNCHER_STYLES.find((s) => s.id === id)?.label ?? id;
}

function themeLabel(id: string): string {
  return LAUNCHER_THEMES.find((t) => t.id === id)?.label ?? id;
}

export default function WidgetAppearance() {
  const [sites, setSites] = useState<SiteAppearance[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(null);
  // 草稿(未保存的预览选择);与已保存值分离(A4:未保存不落库)
  const [draftStyle, setDraftStyle] = useState<string>("current");
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
    setDraftStyle(site?.launcher_style ?? "current");
    setDraftTheme(site?.launcher_theme ?? "auto");
  };

  const dirty =
    !!selected &&
    (draftStyle !== selected.launcher_style || draftTheme !== selected.launcher_theme);

  const save = async () => {
    if (!selectedSiteId) return;
    setSaving(true);
    try {
      const updated = await apiFetch<SiteAppearance>(
        `/widget-appearance/${encodeURIComponent(selectedSiteId)}`,
        { method: "PUT", body: JSON.stringify({ launcher_style: draftStyle, launcher_theme: draftTheme }) },
      );
      setSites((prev) => prev.map((s) => (s.site_id === updated.site_id ? updated : s)));
      toast.success(`已保存:${updated.display_name} → ${styleLabel(updated.launcher_style)} / ${themeLabel(updated.launcher_theme)}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  // 实时预览文档:真实 widget 产物 + data-* 覆写(未保存草稿即时可见)。
  // 预览页与站点嵌入同构(css+js 成对),但完全不可交互(无 /ask 流量)。
  const previewDoc = useMemo(() => {
    const bg = hostBg === "dark" ? "#14161a" : "#f6f7f9";
    return [
      "<!doctype html><html><head><meta charset=\"utf-8\">",
      `<link rel=\"stylesheet\" href=\"/widget/ask-ai-widget.css\">`,
      `<style>html,body{margin:0;min-height:100%;background:${bg}}</style>`,
      "</head><body>",
      `<script src=\"/widget/widget.js\" data-launcher-style=\"${draftStyle}\" data-launcher-theme=\"${draftTheme}\"></script>`,
      "</body></html>",
    ].join("");
  }, [draftStyle, draftTheme, hostBg]);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Widget 外观</h1>
      <p className="text-sm text-muted-foreground">
        为每个站点体验选择启动器风格与主题;保存后该站点 Widget 下一次加载即生效。
        未配置的站点保持「经典」默认外观。
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
                    {styleLabel(s.launcher_style)} · {themeLabel(s.launcher_theme)}
                    {!s.enabled && <span className="ml-1">(已禁用)</span>}
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>

          {selected && (
            <div className="space-y-4">
              <Card aria-label="启动器风格">
                <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-2">
                  <CardTitle className="text-sm">启动器风格</CardTitle>
                  {dirty ? (
                    <Badge variant="warning">未保存</Badge>
                  ) : (
                    <Badge variant="success">已保存</Badge>
                  )}
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {LAUNCHER_STYLES.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        aria-pressed={draftStyle === s.id}
                        onClick={() => setDraftStyle(s.id)}
                        className={`rounded-md border p-3 text-left text-sm ${
                          draftStyle === s.id ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                        }`}
                      >
                        <span className="font-medium">{s.label}</span>
                        {s.id === "current" && (
                          <span className="ml-1 rounded bg-muted px-1 text-xs">默认</span>
                        )}
                        <div className="mt-0.5 text-xs text-muted-foreground">{s.hint}</div>
                      </button>
                    ))}
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
                      srcDoc={previewDoc}
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
                    保存后该站点 Widget 下一次加载生效;「自动」跟随访问者系统深浅色偏好,
                    无法检测时使用浅色。
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
