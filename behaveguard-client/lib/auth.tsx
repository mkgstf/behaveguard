"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type UserRole = "user" | "org_admin" | "platform_admin";

export interface AuthUser {
  id: string;
  email: string;
  role: UserRole;
  org_id: string | null;
  status: string;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
}

const ACCESS_KEY = "bg_access_token";
const REFRESH_KEY = "bg_refresh_token";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

// Module-level (not React state) so lib/api.ts's plain `request()` function
// can read/refresh the current token without needing to be a hook itself.
// Persisted to localStorage so a page reload doesn't force a re-login;
// the access token is short-lived (15 min) and the refresh token rotates on
// every use, which bounds the damage of it sitting in storage. A stronger
// (but heavier) alternative is an httpOnly cookie set by the backend — worth
// revisiting if this ever needs to defend against a stored-XSS threat model.
let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

function persist(tokens: { access_token: string; refresh_token: string }) {
  accessToken = tokens.access_token;
  refreshToken = tokens.refresh_token;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
    window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  }
}

function clearTokens() {
  accessToken = null;
  refreshToken = null;
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  }
}

function hydrateFromStorage() {
  if (typeof window === "undefined") return;
  accessToken = window.localStorage.getItem(ACCESS_KEY);
  refreshToken = window.localStorage.getItem(REFRESH_KEY);
}

async function parseErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

/** Single-flight refresh: concurrent 401s from several in-flight requests
 * should trigger exactly one /auth/refresh call, not one per request. */
export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshToken) return null;
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearTokens();
        return null;
      }
      const data: TokenPair = await response.json();
      persist(data);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export async function loginWithPassword(email: string, password: string): Promise<AuthUser> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await parseErrorDetail(response, "Login failed"));
  const data: TokenPair = await response.json();
  persist(data);
  return data.user;
}

export async function registerWithPassword(email: string, password: string): Promise<AuthUser> {
  const response = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await parseErrorDetail(response, "Registration failed"));
  const data: TokenPair = await response.json();
  persist(data);
  return data.user;
}

export async function logout(): Promise<void> {
  if (refreshToken) {
    try {
      await fetch(`${API_URL}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // best-effort — clear local tokens regardless of network outcome
    }
  }
  clearTokens();
}

/** Full URL for the "Sign in with Google" button — a plain navigation
 * (`window.location.href = googleLoginUrl()`), not a fetch, since the
 * backend redirects the browser through Google's consent screen. */
export function googleLoginUrl(): string {
  return `${API_URL}/auth/google/login`;
}

async function fetchMe(token: string): Promise<AuthUser | null> {
  const response = await fetch(`${API_URL}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  return response.ok ? response.json() : null;
}

async function resolveCurrentUser(): Promise<AuthUser | null> {
  if (!accessToken) return null;
  const me = await fetchMe(accessToken);
  if (me) return me;
  const refreshed = await refreshAccessToken();
  return refreshed ? fetchMe(refreshed) : null;
}

/** Reads Google OAuth callback tokens out of the URL fragment
 * (`#access_token=...&refresh_token=...`) and strips them from the address
 * bar — see api.py's /auth/google/callback for why they arrive as a
 * fragment rather than a query string or response body. */
function consumeGoogleCallbackFragment(): boolean {
  if (typeof window === "undefined") return false;
  if (!window.location.hash.includes("access_token")) return false;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const at = params.get("access_token");
  const rt = params.get("refresh_token");
  if (!at || !rt) return false;
  persist({ access_token: at, refresh_token: rt });
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return true;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  registerWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    hydrateFromStorage();
    consumeGoogleCallbackFragment();
    resolveCurrentUser()
      .then(setUser)
      .finally(() => setLoading(false));
  }, []);

  const doLogin = useCallback(async (email: string, password: string) => {
    setUser(await loginWithPassword(email, password));
  }, []);

  const doRegister = useCallback(async (email: string, password: string) => {
    setUser(await registerWithPassword(email, password));
  }, []);

  const doSignOut = useCallback(async () => {
    await logout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, loginWithPassword: doLogin, registerWithPassword: doRegister, signOut: doSignOut }),
    [user, loading, doLogin, doRegister, doSignOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}
