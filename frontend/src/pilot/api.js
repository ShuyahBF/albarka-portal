// Client HTTP dédié au pilote ALBARKA.
// Ajoute automatiquement le token JWT (stocké en localStorage) sur chaque
// requête, et pointe vers l'API backend (/api) définie par
// REACT_APP_BACKEND_URL.
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API_BASE = `${BACKEND_URL}/api`;

export const TOKEN_KEY = "albarka_token";

export const apiClient = axios.create({ baseURL: API_BASE });

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
