import { type ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Menu } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

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
            <span className="truncate text-sm text-muted-foreground">
              欢迎，{user?.name || user?.email}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="rounded bg-muted px-2 py-0.5 text-xs">{user?.role}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { logout(); navigate("/login"); }}
            >
              退出
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
