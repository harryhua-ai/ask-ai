import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoginChat } from "@/components/LoginChat";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted p-4">
      <div className="flex w-full max-w-5xl flex-col items-center gap-8 md:flex-row md:items-start md:justify-center">
        {/* 登录表单 */}
        <div className="w-full max-w-md rounded-lg border bg-card p-8 shadow-lg">
          <h1 className="mb-6 text-2xl font-bold">Ask AI 管理后台</h1>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "登录中..." : "登录"}
            </Button>
          </form>
        </div>

        {/* 聊天窗口(免登录测试,共享 widget ChatPanel) */}
        <div className="flex w-full max-w-md flex-col">
          <p className="mb-2 text-center text-sm text-muted-foreground">
            免登录试用(直接提问)
          </p>
          {/* login-chat-wrapper 内嵌 ChatPanel;scoped 样式见 index.css */}
          <LoginChat />
        </div>
      </div>
    </div>
  );
}
