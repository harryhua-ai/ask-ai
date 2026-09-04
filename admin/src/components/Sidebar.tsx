import { NavLink } from "react-router-dom";
import {
  Database,
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
  { to: "/widget-appearance", icon: Sparkles, label: "Widget 外观", roles: ["admin", "editor"] },
  { to: "/users", icon: Users, label: "用户管理", roles: ["admin"] },
  { to: "/system", icon: Info, label: "系统信息", roles: ["admin", "editor", "viewer"] },
];

function renderNavLinks(items: NavItem[], onNavigate?: () => void) {
  return items.map(({ to, icon: Icon, label }) => (
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
  ));
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  if (!user) return null;
  const ops = OPS_ITEMS.filter((item) => item.roles.includes(user.role));
  const config = CONFIG_ITEMS.filter((item) => item.roles.includes(user.role));

  return (
    <aside className="flex w-60 flex-col border-r bg-card">
      <div className="flex h-14 items-center border-b px-6">
        <span className="text-lg font-bold">Ask AI</span>
      </div>
      <nav className="flex-1 space-y-4 p-3">
        <div className="space-y-1">
          <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
            运营
          </div>
          {renderNavLinks(ops, onNavigate)}
        </div>
        <div className="space-y-1">
          <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
            配置
          </div>
          {renderNavLinks(config, onNavigate)}
        </div>
      </nav>
    </aside>
  );
}
