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
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`/api/admin${path}`, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    // BrowserRouter basename="/admin",登录路由为 /admin/login。
    window.location.href = "/admin/login";
    throw new ApiError(401, "未登录或登录已过期");
  }
  if (!resp.ok) {
    let detail = "请求失败";
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch { /* ignore parse error */ }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}
