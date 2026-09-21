"use client";

import { AlertTriangle, LoaderCircle, LogIn, UserPlus, UserRound, Waves } from "lucide-react";
import {
  createContext,
  type FormEvent,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import { ApiError, getCurrentUser, login, loginAsGuest, logout, register } from "@/lib/api";
import type { AuthUser } from "@/lib/types";

type AuthContextValue = {
  user: AuthUser;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser>();
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string>();
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getCurrentUser(controller.signal)
      .then((currentUser) => {
        setUser(currentUser);
        setError(undefined);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") {
          return;
        }
        if (reason instanceof ApiError && reason.status === 401) {
          setUser(undefined);
          setError(undefined);
          return;
        }
        setError(reason instanceof Error ? reason.message : "无法连接认证服务");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setChecking(false);
        }
      });
    return () => controller.abort();
  }, [retryVersion]);

  useEffect(() => {
    const handleExpiredSession = () => setUser(undefined);
    window.addEventListener("tara-auth-expired", handleExpiredSession);
    return () => window.removeEventListener("tara-auth-expired", handleExpiredSession);
  }, []);

  if (checking) {
    return <div className="auth-loading"><LoaderCircle className="spin" />正在确认登录状态…</div>;
  }

  if (error) {
    return (
      <div className="auth-loading auth-service-error">
        <AlertTriangle />
        <strong>暂时无法连接后端服务</strong>
        <span>{error}</span>
        <button
          type="button"
          onClick={() => {
            setChecking(true);
            setRetryVersion((value) => value + 1);
          }}
        >
          重新连接
        </button>
      </div>
    );
  }

  if (!user) {
    return <AuthScreen onAuthenticated={setUser} />;
  }

  async function signOut() {
    try {
      await logout();
      setUser(undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "退出登录失败");
    }
  }

  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth 必须在 AuthGate 内使用");
  }
  return value;
}

function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [loginRejected, setLoginRejected] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    setLoginRejected(false);
    try {
      const response = mode === "login"
        ? await login(email, password)
        : await register(email, displayName, password);
      onAuthenticated(response.user);
    } catch (reason) {
      setLoginRejected(
        mode === "login" && reason instanceof ApiError && reason.status === 401,
      );
      setError(reason instanceof Error ? reason.message : "认证请求失败");
    } finally {
      setBusy(false);
    }
  }

  async function enterAsGuest() {
    setBusy(true);
    setError(undefined);
    try {
      const response = await loginAsGuest();
      onAuthenticated(response.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "游客登录失败");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(nextMode: "login" | "register") {
    setMode(nextMode);
    setPassword("");
    setError(undefined);
    setLoginRejected(false);
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand-mark"><Waves size={25} /></div>
        <span className="context-label">Tara Agent</span>
        <h1>{mode === "login" ? "登录 Tara Agent" : "创建账户"}</h1>

        <div className="auth-tabs" role="tablist" aria-label="认证方式">
          <button type="button" className={mode === "login" ? "active" : undefined} onClick={() => switchMode("login")}>登录</button>
          <button type="button" className={mode === "register" ? "active" : undefined} onClick={() => switchMode("register")}>注册</button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          {mode === "register" ? (
            <label>
              <span>昵称</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                minLength={1}
                maxLength={80}
                autoComplete="name"
                required
              />
            </label>
          ) : null}
          <label>
            <span>邮箱</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              onInvalid={(event) => {
                event.currentTarget.setCustomValidity(
                  event.currentTarget.validity.valueMissing
                    ? "请输入邮箱"
                    : "请输入正确的邮箱地址",
                );
              }}
              onInput={(event) => event.currentTarget.setCustomValidity("")}
              maxLength={320}
              autoComplete="email"
              required
            />
          </label>
          <label>
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={mode === "register" ? 12 : 1}
              maxLength={128}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
            />
            {mode === "register" ? <small>至少 12 个字符</small> : null}
          </label>
          {error ? (
            <div className="auth-error">
              <AlertTriangle size={15} />
              <div>
                <span>{error}</span>
                {loginRejected ? (
                  <button type="button" onClick={() => switchMode("register")}>
                    尚未注册？前往注册
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
          <button className="auth-submit" type="submit" disabled={busy}>
            <AuthSubmitIcon busy={busy} mode={mode} />
            {busy ? "正在处理…" : mode === "login" ? "登录" : "创建并登录"}
          </button>
        </form>

        {mode === "login" ? (
          <div className="guest-entry">
            <button type="button" onClick={() => void enterAsGuest()} disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <UserRound size={17} />}
              游客进入
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function AuthSubmitIcon({ busy, mode }: { busy: boolean; mode: "login" | "register" }) {
  if (busy) return <LoaderCircle className="spin" size={17} />;
  if (mode === "login") return <LogIn size={17} />;
  return <UserPlus size={17} />;
}
