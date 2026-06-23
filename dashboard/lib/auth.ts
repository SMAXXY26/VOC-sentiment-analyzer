// Dashboard auth — bearer token stored client-side, attached to API calls.
// NOTE: token lives in localStorage (XSS-accessible); acceptable for this simple
// operator login. The token is short-lived (server TTL) and HMAC-signed.

const TOKEN_KEY = "cx_auth_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function login(username: string, password: string): Promise<{ username: string; role: string }> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Login failed (${res.status})`);
  }
  const data = await res.json();
  setToken(data.token);
  return { username: data.username, role: data.role };
}

export function logout(): void {
  clearToken();
  if (typeof window !== "undefined") window.location.href = "/login";
}
