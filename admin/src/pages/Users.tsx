import { useState } from "react";
import { useUsers, useCreateUser, useDeleteUser } from "@/hooks/useUsers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Pagination } from "@/components/Pagination";
import { useAuth } from "@/hooks/useAuth";
import NoPermission from "@/components/NoPermission";

const PAGE_SIZE = 20;

export default function Users() {
  const { user: currentUser } = useAuth();
  // AFP-002:用户管理仅 admin;非 admin 直达 → 显式无权限态(非空表)
  if (currentUser && currentUser.role !== "admin") {
    return <NoPermission />;
  }
  const [page, setPage] = useState(1);
  const { data: users, isLoading } = useUsers(page, PAGE_SIZE);
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const [showCreate, setShowCreate] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createUser.mutateAsync({ email, password, role });
    setShowCreate(false);
    setEmail(""); setPassword(""); setRole("viewer");
  };

  // 依据当前页返回条数推断是否还有下一页
  const hasMore = (users?.length ?? 0) >= PAGE_SIZE;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">用户管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增用户</Button>
      </div>
      {showCreate && (
        <form onSubmit={handleCreate} className="flex items-end gap-3 rounded-lg border bg-card p-4">
          <div className="space-y-1">
            <Label>邮箱</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="space-y-1">
            <Label>密码</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </div>
          <div className="space-y-1">
            <Label>角色</Label>
            <select className="h-10 rounded-md border px-3" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="admin">admin</option>
              <option value="editor">editor</option>
              <option value="viewer">viewer</option>
            </select>
          </div>
          <Button type="submit" disabled={createUser.isPending}>创建</Button>
        </form>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>邮箱</TableHead>
            <TableHead>姓名</TableHead>
            <TableHead>角色</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow><TableCell colSpan={5} className="text-center">加载中...</TableCell></TableRow>
          ) : users?.map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.email}</TableCell>
              <TableCell>{u.name || "-"}</TableCell>
              <TableCell><Badge variant={u.role === "admin" ? "default" : "outline"}>{u.role}</Badge></TableCell>
              <TableCell><Badge variant={u.is_active ? "success" : "destructive"}>{u.is_active ? "启用" : "禁用"}</Badge></TableCell>
              <TableCell>
                {u.id !== currentUser?.id && (
                  <Button variant="destructive" size="sm" onClick={() => deleteUser.mutate(u.id)}>删除</Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Pagination page={page} onPageChange={setPage} hasMore={hasMore} />
    </div>
  );
}
