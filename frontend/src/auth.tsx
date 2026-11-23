import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, onUnauthorized, tokenStore } from "./api/client";
import { devLogin, fetchMe } from "./api/query";
import type { Me } from "./api/types";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthState {
  status: Status;
  me: Me | null;
  error: string | null;
  login: (subject: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(tokenStore.get() ? "loading" : "anonymous");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const logout = useCallback(() => {
    tokenStore.clear();
    setMe(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    onUnauthorized(() => {
      setError("登录已过期，请重新登录");
      logout();
    });
    return () => onUnauthorized(null);
  }, [logout]);

  useEffect(() => {
    if (!tokenStore.get()) return;
    let cancelled = false;
    fetchMe()
      .then((result) => {
        if (cancelled) return;
        setMe(result);
        setStatus("authenticated");
      })
      .catch(() => {
        if (cancelled) return;
        tokenStore.clear();
        setStatus("anonymous");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (subject: string) => {
    setError(null);
    try {
      const { access_token } = await devLogin(subject);
      tokenStore.set(access_token);
      setMe(await fetchMe());
      setStatus("authenticated");
    } catch (failure) {
      tokenStore.clear();
      setError(failure instanceof ApiError ? failure.message : "登录失败");
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo(
    () => ({ status, me, error, login, logout }),
    [status, me, error, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
