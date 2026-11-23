const TOKEN_KEY = "datagent.access_token";

// Development sign-in only: the token lives in sessionStorage so it dies with the tab.
// Real SSO will move this to an HttpOnly session cookie.
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

let unauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function describeError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { code, message } = detail as { code?: string; message?: string };
    return new ApiError(status, message ?? `请求失败（HTTP ${status}）`, code ?? null);
  }
  if (typeof detail === "string") return new ApiError(status, detail);
  if (status === 422) return new ApiError(status, "请求参数不合法", "validation_error");
  return new ApiError(status, `请求失败（HTTP ${status}）`);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "无法连接后端服务，请确认服务已启动", "network");
  }

  const payload: unknown = await response.json().catch(() => null);
  if (response.ok) return payload as T;
  if (response.status === 401 && token) unauthorizedHandler?.();
  throw describeError(response.status, payload);
}

export function jsonBody(value: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(value) };
}
