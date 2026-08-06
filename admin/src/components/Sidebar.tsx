import { NavLink } from "react-router-dom";
import {
  Database, Activity, Palette, Cpu, MessageSquare, Users, LayoutDashboard, CheckSquare, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "概览", roles: ["admin", "editor", "viewer"] },
  { to: "/data-sources", icon: Database, label: "数据源", roles: ["admin", "editor", "viewer"] },
  { to: "/sync-logs", icon: Activity, label: "同步监控", roles: ["admin", "editor", "viewer"] },
  { to: "/customizations", icon: Palette, label: "Customization", roles: ["admin", "editor", "viewer"] },
  { to: "/llm-providers", icon: Cpu, label: "模型配置", roles: ["admin", "editor", "viewer"] },
  { to: "/conversations", icon: MessageSquare, label: "对话审查", roles: ["admin", "editor", "viewer"] },
  { to: "/answer-overrides", icon: CheckSquare, label: "答案覆盖", roles: ["admin", "editor", "viewer"] },
  { to: "/analytics", icon: BarChart3, label: "分析仪表盘", roles: ["admin", "editor", "viewer"] },
  { to: "/users", icon: Users, label: "用户管理", roles: ["admin"] },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  const items = NAV_ITEMS.filter((item) => user && item.roles.includes(user.role));
  return (
    <aside className="flex w-60 flex-col border-r bg-card">
      <div className="flex h-14 items-center border-b px-6">
        <span className="text-lg font-bold">Ask AI</span>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {items.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
