import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";
// Règle 9 — Ctrl + Espace / double-clic : reprendre le texte par défaut (gris) d'un champ pour le modifier
import { installerValeurParDefaut } from "@/lib/valeurParDefaut";

installerValeurParDefaut();

// Application installable (Android / PWABuilder) : le service worker est enregistré dès le démarrage du site
// (page « Pas de connexion », notifications). Un échec (navigateur ancien, mode privé) est sans conséquence.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
// Garde l'invitation d'installation de Chrome pour le bouton « Installer l'application » (qui peut apparaître plus tard)
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); window.__albarkaInvite = e; window.dispatchEvent(new Event("albarka-invite")); });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
