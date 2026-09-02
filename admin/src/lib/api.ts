const TOKEN_KEY = "ask-ai-admin-token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** T27:FastAPI detail 兼容格式化——422 校验错误为 [{loc,msg}] 数组,扁平化为 msg 文本;字符串原样;其余 JSON 化。 */
export function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && typeof (item as { msg?: unknown }).msg === "string"
          ? (item as { msg: string }).msg
          : String(item),
      )
      .join("; ");
  }
  if (detail == null) return "请求失败";
  return JSON.stringify(detail);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) || {}),
  };
  // FormData 交给浏览器设置 multipart 边界,不能强设 JSON
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`/api/admin${path}`, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    // BrowserRouter basename="/admin",登录路由为 /admin/login。
    window.location.href = "/admin/login";
    throw new ApiError(401, "未登录或登录已过期");
  }
  // AFP-CLOSURE-01 §6.7:403 必须传达权限语义,不降级为泛化「请求失败」,
  // 也不透出后端框架 prose(admin 面 403 = RBAC 角色不足)
  if (resp.status === 403) {
    throw new ApiError(403, "无权限执行此操作");
  }
  if (!resp.ok) {
    let detail: unknown = "请求失败";
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch { /* ignore parse error */ }
    // T27:FastAPI 校验错误(422)的 detail 是 [{loc,msg}] 数组,扁平化为可读文本
    throw new ApiError(resp.status, formatApiDetail(detail));
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}
