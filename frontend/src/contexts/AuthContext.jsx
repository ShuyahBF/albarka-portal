import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    const token = localStorage.getItem("albarka_token");
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await apiClient.get("/auth/me");
      setUser(data);
    } catch {
      localStorage.removeItem("albarka_token");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const loginStart = async (email, password, captchaToken) => {
    const { data } = await apiClient.post("/auth/login", {
      email,
      password,
      captcha_token: captchaToken || null,
    });
    return data; // { session_token, dev_otp, message }
  };

  const loginVerify = async (session_token, code) => {
    const { data } = await apiClient.post("/auth/verify-otp", { session_token, code });
    localStorage.setItem("albarka_token", data.access_token);
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("albarka_token");
    setUser(null);
  };

  const isStaff = user && !(user.roles?.length === 1 && user.roles[0] === "client");
  const isClient = user && user.roles?.includes("client");
  const isSupervisor = user && user.roles?.includes("superviseur");
  const isAdmin =
    user &&
    (user.roles?.includes("superviseur") ||
      user.roles?.includes("direction") ||
      user.roles?.includes("administrateur"));

  return (
    <AuthContext.Provider
      value={{ user, loading, loginStart, loginVerify, logout, refresh: fetchMe, isStaff, isClient, isSupervisor, isAdmin }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
