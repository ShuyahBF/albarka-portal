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
  if (err?.response?.data?.message) return err.response.data.message;
  // Lot 11 : erreur du serveur sans explication (500, 502…) — plutôt que
  // « Request failed with status code 500 », un message en français
  const status = err?.response?.status;
  if (status >= 500) {
    return `Erreur du serveur (code ${status}) : l'opération n'a pas abouti. Réessayez ; si le problème persiste, `
      + "signalez-le à l'administrateur en indiquant l'heure.";
  }
  if (!err?.response && err?.message === "Network Error") {
    return "Serveur injoignable : vérifiez la connexion Internet puis réessayez.";
  }
  return err?.message || fallback;
}
