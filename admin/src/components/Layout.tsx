import { type ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, LogOut, Menu } from "lucide-react";
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

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const displayName = user?.name || user?.email || "";

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <div className="hidden md:flex">
        <Sidebar />
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
  );
}
