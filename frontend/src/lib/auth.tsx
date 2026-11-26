import {createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode} from "react";
import axios from "axios";
import {Navigate, Outlet, useNavigate} from "react-router-dom";
import {api} from "./api";
import {errorMessage} from "./api";
import type {UserProfile} from "../types";

const TOKEN_KEY = "ib_token";

interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: UserProfile;
}

interface RegistrationInput {
  email: string;
  full_name: string;
  password: string;
  password_confirmation: string;
}

interface RegistrationResponse {
  message: string;
  user: UserProfile;
}

interface AuthContextValue {
  token: string | null;
  user: UserProfile | null;
  loading: boolean;
  sessionError: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegistrationInput) => Promise<RegistrationResponse>;
  logout: () => Promise<void>;
  retrySession: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({children}: {children: ReactNode}) {
  const navigate = useNavigate();
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)));
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [verificationAttempt, setVerificationAttempt] = useState(0);

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setSessionError(null);
  }, []);

  useEffect(() => {
    const interceptorId = api.interceptors.response.use(
      response => response,
      (error: unknown) => {
        const isLoginRequest = axios.isAxiosError(error) && error.config?.url?.includes("/auth/login");
        if (
          axios.isAxiosError(error) &&
          error.response?.status === 401 &&
          localStorage.getItem(TOKEN_KEY) &&
          !isLoginRequest
        ) {
          clearSession();
          navigate("/login", {
            replace: true,
            state: {notice: "Your session expired. Please sign in again."},
          });
        }
        return Promise.reject(error);
      },
    );
    return () => api.interceptors.response.eject(interceptorId);
  }, [clearSession, navigate]);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setSessionError(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setSessionError(null);
    api.get<UserProfile>("/auth/me", {signal: controller.signal})
      .then(response => setUser(response.data))
      .catch(error => {
        if (controller.signal.aborted) return;
        if (axios.isAxiosError(error) && error.response?.status === 401) return;
        setSessionError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [token, verificationAttempt]);

  const login = useCallback(async (email: string, password: string) => {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    const response = await api.post<LoginResponse>("/auth/login", body, {
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
    });
    localStorage.setItem(TOKEN_KEY, response.data.access_token);
    setToken(response.data.access_token);
    setUser(response.data.user);
    setSessionError(null);
  }, []);

  const register = useCallback(async (input: RegistrationInput) => {
    const response = await api.post<RegistrationResponse>("/auth/register", input);
    return response.data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const retrySession = useCallback(() => {
    setVerificationAttempt(attempt => attempt + 1);
  }, []);

  const value = useMemo(
    () => ({token, user, loading, sessionError, login, register, logout, retrySession}),
    [token, user, loading, sessionError, login, register, logout, retrySession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}

export function RequireAuth() {
  const {token, user, loading, sessionError, retrySession} = useAuth();
  if (loading) {
    return <div className="session-state" role="status">Verifying your session…</div>;
  }
  if (!token) return <Navigate to="/login" replace />;
  if (sessionError) {
    return (
      <div className="session-state">
        <h1>Unable to verify your session</h1>
        <p>{sessionError}</p>
        <button className="primary-btn" onClick={retrySession}>Try again</button>
      </div>
    );
  }
  if (!user) return <div className="session-state" role="status">Loading your account…</div>;
  return <Outlet />;
}
