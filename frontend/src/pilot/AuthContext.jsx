// Contexte d'authentification du pilote : login -> OTP -> JWT.
// Le token est conservé en localStorage ; `user` est rechargé via /auth/me
// au démarrage de l'app pour rester connecté après un rafraîchissement de page.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiClient, TOKEN_KEY } from "@/pilot/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadCurrentUser = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await apiClient.get("/auth/me");
      setUser(data);
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCurrentUser();
  }, [loadCurrentUser]);

  // Étape 1 : email + mot de passe -> déclenche l'envoi d'un code OTP.
  const login = async (email, password) => {
    const { data } = await apiClient.post("/auth/login", { email, password });
    return data; // { session_token, message, dev_otp? }
  };

  // Étape 2 : code OTP -> JWT, puis on recharge l'utilisateur courant.
  const verifyOtp = async (sessionToken, code) => {
    const { data } = await apiClient.post("/auth/verify-otp", {
      session_token: sessionToken,
      code,
    });
    localStorage.setItem(TOKEN_KEY, data.access_token);
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, verifyOtp, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth doit être utilisé dans un <AuthProvider>");
  return ctx;
}
