import { type ReactNode, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CalendarDays, ChevronDown, LogOut, Menu } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  AnalysisWindowProvider,
  resolveAnalysisWindow,
  useAnalysisWindow,
  type AnalysisWindowSerialized,
} from "@/lib/analysisWindow";

/**
 * Ownership: Track A — Wave 1(共享 chrome 合同内 A 项):
 * - U-4(SH-12):侧栏收起状态持有于 Layout(纯 Admin shell;localStorage 持久,
 *   零后端语义、零产品语义副作用),折叠→布局重排;
 * - SH-09(GAP-SC-1 / U-2):顶栏日期范围控件(含显式起止日历,对照 PNG2)仅在
 *   技术洞察域(/analytics)呈现 —— 驱动 IF-7 单一共享分析窗状态;范围=技术洞察
 *   分析窗,非全站假全局过滤(数据源等面顶栏无此控件,对照 PNG1);
 * - 身份区/登出/移动端抽屉 = 既有实现零行为变化。
 */

const SIDEBAR_COLLAPSED_KEY = "askai.admin.sidebar.collapsed";

/** SH-09 顶栏分析窗控件:呈现当前窗(标签+起止日期)+ 快选项 + 显式起止日历。 */
function TopbarWindowControl() {
  const { value, setValue } = useAnalysisWindow();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const resolved = resolveAnalysisWindow(value);

  const quick: { value: AnalysisWindowSerialized; label: string }[] = [
    { value: "today", label: "今日" },
    { value: "7d", label: "过去 7 天" },
    { value: "30d", label: "过去 30 天" },
    { value: "all", label: "全部时间" },
  ];

  function applyExplicit() {
    if (!from || !to) return;
    setValue(`range:${from}/${to}`);
    setOpen(false);
  }

  return (
    <div className="relative" data-topbar-window>
      <button
        type="button"
        data-topbar-window-trigger
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-[13px] outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="font-medium">{resolved.label}</span>
        {resolved.kind !== "explicit" && (
          <span className="tabular-nums text-muted-foreground">
            {resolved.fromDate} → {resolved.toDate}
          </span>
        )}
        <CalendarDays className="h-4 w-4 text-muted-foreground" />
      </button>
      {open && (
        <div
          data-topbar-window-panel
          className="absolute right-0 z-40 mt-1 w-72 rounded-md border bg-popover p-3 shadow-md"
        >
          <div className="grid grid-cols-2 gap-1">
            {quick.map((q) => (
              <button
                key={q.value}
                type="button"
                data-topbar-quick={q.value}
                onClick={() => {
                  setValue(q.value);
                  setOpen(false);
                }}
                className={cn(
                  "rounded-md border px-2.5 py-1.5 text-[13px] transition-colors hover:bg-accent",
                  value === q.value && "border-primary bg-primary/10 text-primary",
                )}
              >
                {q.label}
              </button>
            ))}
          </div>
          <div className="mt-3 space-y-2 border-t pt-3">
            <div className="text-[12px] text-muted-foreground">明确起止</div>
            <input
              type="date"
              aria-label="开始日期"
              data-topbar-window-from
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="w-full rounded-md border bg-transparent px-2 py-1 text-[13px]"
            />
            <input
              type="date"
              aria-label="结束日期"
              data-topbar-window-to
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="w-full rounded-md border bg-transparent px-2 py-1 text-[13px]"
            />
            <button
              type="button"
              data-topbar-window-apply
              onClick={applyExplicit}
              disabled={!from || !to}
              className="w-full rounded-md bg-primary py-1.5 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-40"
            >
              应用
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const displayName = user?.name || user?.email || "";

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // 存储不可用(隐私模式等)仅退化为会话内状态,交互语义不变
      }
      return next;
    });
  }

  // U-2:范围控件=技术洞察分析窗(非全站),仅在 /analytics 域呈现(PNG1 数据源面顶栏无此控件)
  const isAnalyticsDomain = location.pathname === "/analytics";

  return (
    <AnalysisWindowProvider>
      <div className="flex h-screen overflow-hidden">
        {/* Desktop sidebar */}
        <div className="hidden md:flex">
          <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
        </div>

        {/* Mobile drawer */}
        {mobileNavOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/50 md:hidden"
              onClick={() => setMobileNavOpen(false)}
            />
            <div
              className={cn(
                "fixed inset-y-0 left-0 z-50 md:hidden",
                mobileNavOpen ? "translate-x-0" : "-translate-x-full",
              )}
            >
              <Sidebar onNavigate={() => setMobileNavOpen(false)} />
            </div>
          </>
        )}

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex h-14 items-center justify-between border-b bg-card px-4 md:px-6">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                className="md:hidden"
                onClick={() => setMobileNavOpen(true)}
              >
                <Menu className="h-5 w-5" />
              </Button>
              {isAnalyticsDomain && <TopbarWindowControl />}
            </div>
            {/* v1.6.3 Integration:身份区收敛为 头像+用户名+角色 身份菜单(KB-OPS-V163-002 共享 chrome 语法);
                登出沿用既有 auth 真相,语义不变。 */}
            <div className="flex shrink-0 items-center">
              <DropdownMenu>
                <DropdownMenuTrigger
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm outline-none transition-colors",
                    "hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                    {displayName.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="max-w-[16rem] truncate font-medium">{displayName}</span>
                  <span className="rounded bg-muted px-2 py-0.5 text-xs">{user?.role}</span>
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[14rem]">
                  <DropdownMenuLabel className="flex flex-col">
                    <span className="truncate">{displayName}</span>
                    {user?.email && user.email !== displayName && (
                      <span className="truncate text-xs font-normal text-muted-foreground">
                        {user.email}
                      </span>
                    )}
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => {
                      logout();
                      navigate("/login");
                    }}
                  >
                    <LogOut className="h-4 w-4" />
                    退出
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>
          <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
        </div>
      </div>
    </AnalysisWindowProvider>
  );
}
