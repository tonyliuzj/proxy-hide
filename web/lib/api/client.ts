export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const API_ROOT = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const CSRF_COOKIE = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? "proxyhide_csrf";
const CSRF_BOOTSTRAP_PATHS = new Set(["/auth/login", "/auth/setup"]);

function csrfToken() {
  if (typeof document === "undefined") return undefined;
  const prefix = `${CSRF_COOKIE}=`;
  const cookie = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : undefined;
}

export function buildQuery(params: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const csrf = !["GET", "HEAD", "OPTIONS"].includes(method) && !CSRF_BOOTSTRAP_PATHS.has(path) ? csrfToken() : undefined;
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const details = await response.json().catch(() => undefined);
    const message = typeof details === "object" && details && "error" in details && typeof details.error === "object" && details.error && "message" in details.error ? String(details.error.message) : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, details);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  health: async <T>() => {
    const response = await fetch("/health/ready", { credentials: "include", headers: { Accept: "application/json" } });
    if (!response.ok) throw new ApiError("Health check failed", response.status);
    return response.json() as Promise<T>;
  },
};
