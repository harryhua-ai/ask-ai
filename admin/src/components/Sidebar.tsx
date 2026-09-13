import { NavLink } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Database,
  LayoutGrid,
  Palette,
  Sparkles,
  Cpu,
  MessageSquare,
  Users,
  LayoutDashboard,
  CheckSquare,
  BarChart3,
  Target,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

/**
 * Ownership: Track A — Wave 1(共享 chrome):
 * - DEF-A1(SH-06):新增「系统」分组,用户管理/系统信息移入;运营/配置 既有
 *   分组语义与成员保留(对照 PNG2);
 * - U-4(SH-12):收起/展开为纯 Admin shell 交互(零后端语义、零产品语义副作用);
 *   状态持久于前端(localStorage,由 Layout 持有);收起态 = icon-only rail;
 * - UADC-4(SH-10/11):帮助中心入口推迟至存在权威目的地 —— 本侧栏不实现;
 * - U-1(SH-16):LIGHT 侧栏=权威方向,既有浅色实现零动作。
 */

interface NavItem {
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  roles: string[];
}

const OPS_ITEMS: NavItem[] = [
  { to: "/", icon: LayoutDashboard, label: "业务概览", roles: ["admin", "editor", "viewer"] },
  { to: "/leads", icon: Target, label: "销售线索", roles: ["admin", "editor", "viewer"] },
  { to: "/conversations", icon: MessageSquare, label: "对话审查", roles: ["admin", "editor", "viewer"] },
  { to: "/analytics", icon: BarChart3, label: "技术洞察", roles: ["admin", "editor", "viewer"] },
];

const CONFIG_ITEMS: NavItem[] = [
  { to: "/data-sources", icon: Database, label: "数据源", roles: ["admin", "editor", "viewer"] },
  { to: "/customizations", icon: Palette, label: "对话接入", roles: ["admin", "editor", "viewer"] },
  { to: "/llm-providers", icon: Cpu, label: "模型配置", roles: ["admin", "editor", "viewer"] },
  { to: "/answer-overrides", icon: CheckSquare, label: "答案覆盖", roles: ["admin", "editor", "viewer"] },
  { to: "/widget", icon: Sparkles, label: "Widget", roles: ["admin", "editor"] },
];

const SYSTEM_ITEMS: NavItem[] = [
  { to: "/users", icon: Users, label: "用户管理", roles: ["admin"] },
  { to: "/system", icon: Info, label: "系统信息", roles: ["admin", "editor", "viewer"] },
];

// lucide-react 无 Target 具名导出情况下的兜底不适用——Target 为既有导入(保持不动)。
function renderNavLinks(
  items: NavItem[],
  onNavigate: (() => void) | undefined,
  collapsed: boolean,
) {
  return items.map(({ to, icon: Icon, label }) => (
    <NavLink
      key={to}
      to={to}
      end={to === "/"}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          collapsed && "justify-center px-0",
          isActive
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && label}
    </NavLink>
  ));
}

export function Sidebar({
  onNavigate,
  collapsed = false,
  onToggleCollapse,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const { user } = useAuth();
  if (!user) return null;
  const ops = OPS_ITEMS.filter((item) => item.roles.includes(user.role));
  const config = CONFIG_ITEMS.filter((item) => item.roles.includes(user.role));
  const system = SYSTEM_ITEMS.filter((item) => item.roles.includes(user.role));

  return (
    <aside
      data-sidebar
      data-collapsed={collapsed ? "true" : "false"}
      className={cn(
        "flex flex-col border-r bg-card transition-[width] duration-150",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <div className={cn("flex h-14 items-center gap-2.5 border-b px-4", collapsed && "justify-center px-0")}>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <LayoutGrid className="h-4 w-4" />
        </span>
        {!collapsed && <span className="text-lg font-bold tracking-tight">ASK-AI</span>}
      </div>
      <nav className={cn("flex-1 space-y-4 p-3", collapsed && "px-2")}>
        <div className="space-y-1">
          {!collapsed && (
            <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
              运营
            </div>
          )}
          {renderNavLinks(ops, onNavigate, collapsed)}
        </div>
        <div className="space-y-1">
          {!collapsed && (
            <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
              配置
            </div>
          )}
          {renderNavLinks(config, onNavigate, collapsed)}
        </div>
        <div className="space-y-1">
          {!collapsed && (
            <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
              系统
            </div>
          )}
          {renderNavLinks(system, onNavigate, collapsed)}
        </div>
      </nav>
      {onToggleCollapse && (
        <div className={cn("border-t p-2", collapsed && "flex justify-center px-1")}>
          {collapsed ? (
            <button
              type="button"
              data-sidebar-toggle
              aria-label="展开菜单"
              title="展开菜单"
              onClick={onToggleCollapse}
              className="flex w-full items-center justify-center rounded-md px-2 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              data-sidebar-toggle
              onClick={onToggleCollapse}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" />
              收起菜单
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
