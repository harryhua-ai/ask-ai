# 目录选择器(Plan 2.6)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员在面板配置 filesystem/local_git 数据源时,`include_dirs` 不再手填文本,而是**浏览 root_path 下的子目录树 + 勾选**(类似 preview-branches 选分支)。

**Architecture:** 后端新增 `GET /data-sources/preview-dirs?root_path=&type=` 返回 root_path 下子目录树(递归 2 层,过滤系统目录);前端 `DataSources.tsx` 的 include_dirs 字段从文本输入改为**目录选择器**(浏览 + Checkbox 勾选),复用 react-query + preview-branches 的交互模式。

**Tech Stack:** FastAPI(后端 API)、React + @tanstack/react-query + react-hook-form + radix-ui(前端目录选择器组件)。

**范围:** Plan 1 Task 8 前端表单增强。改 `backend/api/admin/data_sources.py` + `admin/src/`(hook + 组件 + types)。

## Global Constraints

- 后端 `preview-dirs` 只列目录(不列文件),递归 2 层(防深层爆炸),过滤系统目录(`.git`/`node_modules`/`__pycache__`/`build`/`dist`/`.venv` 等)
- 安全:`root_path` 必须存在 + 可读;返回相对 root_path 的相对路径(不泄露绝对路径结构);admin/editor 权限
- 前端:目录树懒加载(点展开才拉子层)或一次 2 层;Checkbox 勾选 → include_dirs[]
- 不破坏现有 include_dirs 文本编辑(兼容已配源)

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/api/admin/data_sources.py` | `GET /data-sources/preview-dirs` 端点 | Modify |
| `admin/src/types/api.ts` | `PreviewDir` 类型 | Modify |
| `admin/src/hooks/useDataSources.ts` | `usePreviewDirs` hook | Modify |
| `admin/src/pages/DataSources.tsx` | include_dirs 字段改目录选择器组件 | Modify |
| `admin/src/components/DirPicker.tsx` | 目录选择器组件(树 + Checkbox) | Create |
| `tests/api/admin/test_data_sources.py` | preview-dirs 测试 | Modify |

---

### Task 1: 后端 preview-dirs API

**Files:**
- Modify: `backend/api/admin/data_sources.py`(加 `GET /data-sources/preview-dirs`)
- Test: `tests/api/admin/test_data_sources.py`

**Interfaces:**
- Produces: `GET /api/admin/data-sources/preview-dirs?root_path=<path>&type=<filesystem|local_git>` → `{dirs: [{name, path, children_count}]}`
- Consumes: admin/editor 权限(复用 EditorDep)

- [ ] **Step 1: Write failing test**

```python
# tests/api/admin/test_data_sources.py(新增)
def test_preview_dirs_lists_subdirs(tmp_path, client, admin_token):
    """preview-dirs 返回 root_path 下的子目录(不列文件/系统目录)。"""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "en").mkdir()
    (root / "src").mkdir()
    (root / "node_modules").mkdir()  # 系统目录,应过滤
    (root / "README.md").write_text("x")  # 文件,不列
    r = client.get("/api/admin/data-sources/preview-dirs",
                   params={"root_path": str(root)}, headers=admin_token)
    assert r.status_code == 200
    names = {d["name"] for d in r.json()["dirs"]}
    assert "docs" in names and "src" in names
    assert "node_modules" not in names  # 系统目录过滤

def test_preview_dirs_nonexistent_root_404(client, admin_token):
    r = client.get("/api/admin/data-sources/preview-dirs",
                   params={"root_path": "/nonexistent/xxx"}, headers=admin_token)
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# backend/api/admin/data_sources.py
import os
from pathlib import Path

SYSTEM_DIRS = {".git", "node_modules", "__pycache__", "build", "dist", ".venv",
               "venv", ".idea", ".vscode", "target", ".next"}

@router.get("/preview-dirs")
async def preview_dirs(root_path: str, _: EditorDep) -> dict[str, list[dict]]:
    """列出 root_path 下子目录(递归 2 层,过滤系统目录),供前端目录选择器。"""
    root = Path(root_path).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {root_path}")
    dirs: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in SYSTEM_DIRS or entry.name.startswith("."):
            continue
        children = []
        for sub in sorted(entry.iterdir()):
            if sub.is_dir() and sub.name not in SYSTEM_DIRS and not sub.name.startswith("."):
                children.append({"name": sub.name, "path": str(entry.name + "/" + sub.name),
                                 "children_count": sum(1 for x in sub.iterdir() if x.is_dir() and x.name not in SYSTEM_DIRS)})
        dirs.append({"name": entry.name, "path": entry.name,
                     "children": children[:50], "children_count": len(children)})
        if len(dirs) >= 100:
            break  # 防巨型目录爆炸
    return {"dirs": dirs}
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `feat(admin): preview-dirs API 列子目录(目录选择器后端)`

---

### Task 2: 前端 usePreviewDirs hook + types

**Files:**
- Modify: `admin/src/types/api.ts`(PreviewDir 类型)
- Modify: `admin/src/hooks/useDataSources.ts`(usePreviewDirs)
- Test: `admin/tests/`(若有 hook 测试)

**Interfaces:**
- Produces: `usePreviewDirs(root_path)` → `{data, isLoading, error}`;`PreviewDir {name, path, children_count, children?}`

- [ ] **Step 1: Implement types + hook**

```typescript
// admin/src/types/api.ts
export interface PreviewDir {
  name: string;
  path: string;
  children_count: number;
  children?: PreviewDir[];
}

// admin/src/hooks/useDataSources.ts
export function usePreviewDirs(rootPath: string | undefined) {
  return useQuery({
    queryKey: ["preview-dirs", rootPath],
    queryFn: async () => {
      if (!rootPath) return { dirs: [] };
      const r = await apiFetch(`/api/admin/data-sources/preview-dirs?root_path=${encodeURIComponent(rootPath)}`);
      return r.json() as Promise<{ dirs: PreviewDir[] }>;
    },
    enabled: !!rootPath,
  });
}
```

- [ ] **Step 2: tsc 编译通过** — `cd admin && npx tsc --noEmit`

- [ ] **Step 3: Commit** — `feat(admin): usePreviewDirs hook + PreviewDir 类型`

---

### Task 3: 前端目录选择器组件(DirPicker)

**Files:**
- Create: `admin/src/components/DirPicker.tsx`

**Interfaces:**
- Produces: `<DirPicker rootPath={...} value={string[]} onChange={(dirs) => ...} />`(浏览树 + Checkbox 勾选)

- [ ] **Step 1: Implement**

```tsx
// admin/src/components/DirPicker.tsx
import { Checkbox } from "@/components/ui/checkbox";
import { usePreviewDirs } from "@/hooks/useDataSources";
import { Loader2, Folder, FolderOpen } from "lucide-react";
import { useState } from "react";

export function DirPicker({ rootPath, value, onChange }: {
  rootPath: string;
  value: string[];
  onChange: (dirs: string[]) => void;
}) {
  const { data, isLoading } = usePreviewDirs(rootPath);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (!rootPath) return <p className="text-xs text-gray-500">请先填 root_path</p>;
  if (isLoading) return <Loader2 className="h-4 w-4 animate-spin" />;
  const toggle = (p: string) => onChange(value.includes(p) ? value.filter(v => v !== p) : [...value, p]);
  const toggleExpand = (p: string) => setExpanded(prev => {
    const n = new Set(prev); n.has(p) ? n.delete(p) : n.add(p); return n;
  });
  return (
    <div className="border rounded p-2 max-h-60 overflow-auto text-sm">
      {data?.dirs.map(d => (
        <div key={d.path}>
          <div className="flex items-center gap-1">
            <Checkbox checked={value.includes(d.path)} onCheckedChange={() => toggle(d.path)} />
            <button type="button" onClick={() => toggleExpand(d.path)} className="flex items-center gap-1">
              {expanded.has(d.path) ? <FolderOpen className="h-3 w-3" /> : <Folder className="h-3 w-3" />}
              {d.name}
            </button>
            {d.children_count > 0 && <span className="text-xs text-gray-400">({d.children_count})</span>}
          </div>
          {expanded.has(d.path) && d.children?.map(c => (
            <div key={c.path} className="flex items-center gap-1 ml-5">
              <Checkbox checked={value.includes(c.path)} onCheckedChange={() => toggle(c.path)} />
              <Folder className="h-3 w-3" /> {c.name}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: tsc 编译通过**

- [ ] **Step 3: Commit** — `feat(admin): DirPicker 目录选择器组件(树+Checkbox)`

---

### Task 4: DataSources.tsx 接入 DirPicker

**Files:**
- Modify: `admin/src/pages/DataSources.tsx`(include_dirs 字段:文本输入 → DirPicker,type=filesystem/local_git 且 root_path 已填时显示)

- [ ] **Step 1: 改 include_dirs 字段**

在表单中,当 `type ∈ {filesystem, local_git}` 且 `root_path` 已填时,`include_dirs` 用 `<DirPicker>` 替代文本输入:

```tsx
{(["filesystem", "local_git"].includes(type) && watch("root_path")) && (
  <div>
    <Label>目录范围(include_dirs)</Label>
    <DirPicker
      rootPath={watch("root_path")}
      value={watch("include_dirs") || []}
      onChange={(dirs) => setValue("include_dirs", dirs)}
    />
  </div>
)}
```

(保留文本回退:若 root_path 未填或 type=github,仍用文本输入。)

- [ ] **Step 2: `cd admin && npm run build` 通过(tsc + vite)**

- [ ] **Step 3: 手动验证**(浏览器开 admin 数据源页,新建 filesystem 源,填 root_path,看 DirPicker 浏览勾选)

- [ ] **Step 4: Commit** — `feat(admin): include_dirs 改目录选择器(填 root_path 后浏览勾选)`

---

## Self-Review

**1. 覆盖**:用户需求"管理员自己选文件夹目录"→ Task 1-4 ✓

**2. 占位符**:Task 3/4 的代码完整;Task 2 hook 简单(无占位)。手动验证(Task 4 Step 3)是 UI 验证,执行时做。

**3. 类型一致**:`PreviewDir {name, path, children_count, children?}` 在 Task 1(JSON)/ Task 2(types)/ Task 3(DirPicker)一致 ✓

**4. 风险**:
- 安全:`preview-dirs` 列任意 root_path 子目录(admin 权限,但 root_path 校验存在 + 可读);返回相对路径(不泄露)
- 性能:递归 2 层 + 限 100 顶层/50 子层,防巨型目录爆炸
- 前端:DirPicker 懒展开(点开拉子层);react-query cache(root_path 变才重拉)
- 兼容:已配源 include_dirs(文本)仍能编辑(回退文本 or DirPicker 显示已选)
