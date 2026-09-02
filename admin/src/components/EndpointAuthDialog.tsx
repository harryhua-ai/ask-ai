import { useState } from "react";
import { ShieldCheck, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import {
  useAllowedHosts,
  useAuthorizeHost,
  useRevokeHost,
  type LLMAllowedHost,
} from "@/hooks/useLLMProviders";

interface Props {
  onClose: () => void;
}

function TierBadge({ item }: { item: LLMAllowedHost }) {
  return item.allow_private ? (
    <Badge variant="outline" className="text-[10px] text-amber-700">
      内网
    </Badge>
  ) : (
    <Badge variant="secondary" className="text-[10px]">
      公网
    </Badge>
  );
}

/** 端点授权管理:与「供应商配置」分离的信任面(P1 契约 LLM-02/LLM-03)。

 * 写操作仅 admin;editor/viewer 只读并提示需管理员操作。
 */
export function EndpointAuthDialog({ onClose }: Props) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data: hosts, isLoading } = useAllowedHosts();
  const authorize = useAuthorizeHost();
  const revoke = useRevokeHost();
  const [hostInput, setHostInput] = useState("");
  const [noteInput, setNoteInput] = useState("");

  const handleAuthorize = async () => {
    if (!hostInput.trim()) return;
    try {
      const created = await authorize.mutateAsync({
        host: hostInput.trim(),
        note: noteInput.trim(),
      });
      toast.success(
        `已授权 ${created.host}${created.allow_private ? "(内网级)" : "(公网级)"}`,
      );
      setHostInput("");
      setNoteInput("");
    } catch (err) {
      toast.error(`授权失败:${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  const handleRevoke = async (host: string) => {
    try {
      await revoke.mutateAsync(host);
      toast.success(`已撤销 ${host} 的授权,点「应用变更」后运行时生效`);
    } catch (err) {
      toast.error(`撤销失败:${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            端点授权
          </DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          自定义 LLM API 地址默认拒绝。管理员在此显式授权后,对应主机方可用于供应商
          API Base。内网/私有地址(如 10.x、192.168.x、Tailscale 100.x)授权为内网级。
          授权记录持久化在数据库,可随时撤销审查。
        </p>

        {isAdmin && (
          <div className="space-y-2 rounded-md border p-3">
            <div className="space-y-1.5">
              <Label htmlFor="auth-host">主机或完整 URL</Label>
              <Input
                id="auth-host"
                placeholder="如 api.together.xyz 或 10.0.0.5"
                value={hostInput}
                onChange={(e) => setHostInput(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="auth-note">用途备注(可选)</Label>
              <Input
                id="auth-note"
                placeholder="如 自建 vLLM 网关"
                value={noteInput}
                onChange={(e) => setNoteInput(e.target.value)}
              />
            </div>
            <Button size="sm" onClick={handleAuthorize} disabled={authorize.isPending}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              {authorize.isPending ? "授权中..." : "授权"}
            </Button>
          </div>
        )}

        <div className="space-y-1.5">
          {isLoading && <p className="text-xs text-muted-foreground">加载中...</p>}
          {(hosts ?? []).map((item) => (
            <div
              key={item.host}
              className="flex items-center gap-2 rounded-md border px-2.5 py-1.5"
            >
              <span className="flex-1 font-mono text-xs">{item.host}</span>
              <TierBadge item={item} />
              {item.note && (
                <span className="max-w-32 truncate text-[10px] text-muted-foreground">
                  {item.note}
                </span>
              )}
              {isAdmin && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title="撤销授权"
                  onClick={() => handleRevoke(item.host)}
                  disabled={revoke.isPending}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
            </div>
          ))}
          {!isLoading && (hosts ?? []).length === 0 && (
            <p className="text-xs text-muted-foreground">暂无自定义端点授权</p>
          )}
        </div>

        {!isAdmin && (
          <p className="text-xs text-amber-700">
            授权与撤销需管理员操作;当前账号为 {user?.role ?? "未知"} 角色,仅可查看。
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
