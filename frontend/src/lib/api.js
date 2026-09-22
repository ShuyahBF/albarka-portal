import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const apiClient = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("albarka_token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof window !== "undefined") {
      const path = window.location.pathname;
      if (!path.startsWith("/login") && !path.startsWith("/")) {
        localStorage.removeItem("albarka_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

export function extractError(err, fallback = "Une erreur est survenue") {
  const detail = err?.response?.data?.detail;
  // Erreur de validation FastAPI/Pydantic (422) : `detail` est alors un
  // tableau d'objets {type, loc, msg, ...}, jamais une chaîne — le rendre
  // tel quel (ex. dans un toast) fait planter React ("Objects are not
  // valid as a React child"), d'où une page blanche après une saisie
  // invalide (ex. mot de passe trop court) plutôt qu'un message d'erreur.
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (typeof d === "string" ? d : d?.msg)).filter(Boolean);
    if (msgs.length) return msgs.join(" · ");
  } else if (typeof detail === "string" && detail) {
    return detail;
  }
  return (
    err?.response?.data?.message ||
    err?.message ||
    fallback
  );
}
