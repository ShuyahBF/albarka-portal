/*
  EtatServeur — état de la connexion au serveur, comme sur SAWALI
  (page de connexion et en-tête fixe du portail) :
  - pastille verte  « Connecté au serveur · 855 ms » : le serveur répond ;
  - pastille orange « Connexion lente » : réponse en plus de 2 s ;
  - pastille rouge  « Serveur injoignable » ou « Pas de réseau ».
  Test sur la route publique /api/health toutes les 30 s, et tout de suite
  quand l'appareil perd ou retrouve le réseau. Le bouton ↻ relance le test.
*/
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

const LENT_MS = 2000;          // au-delà : connexion lente (orange)
const INTERVALLE_MS = 30000;   // vérification toutes les 30 s

// Libellé et couleur de la pastille pour chaque état
const AFFICHAGE = {
  verif: { couleur: "bg-slate-400", texte: "Vérification…" },
  ok: { couleur: "bg-emerald-500", texte: "Connecté au serveur" },
  lent: { couleur: "bg-amber-500", texte: "Connexion lente" },
  injoignable: { couleur: "bg-red-500", texte: "Serveur injoignable" },
  hors_ligne: { couleur: "bg-red-500", texte: "Pas de réseau" },
};

export default function EtatServeur({ className = "" }) {
  const [etat, setEtat] = useState({ statut: "verif", ms: null });

  // Mesure du temps de réponse de /api/health (10 s maximum)
  const verifier = useCallback(async () => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setEtat({ statut: "hors_ligne", ms: null });
      return;
    }
    const debut = performance.now();
    try {
      await apiClient.get("/health", { timeout: 10000, headers: { "Cache-Control": "no-store" } });
      const ms = Math.round(performance.now() - debut);
      setEtat({ statut: ms > LENT_MS ? "lent" : "ok", ms });
    } catch {
      setEtat({ statut: "injoignable", ms: null });
    }
  }, []);

  // Premier test, puis toutes les 30 s et à chaque changement d'état du réseau
  useEffect(() => {
    verifier();
    const minuterie = setInterval(verifier, INTERVALLE_MS);
    window.addEventListener("online", verifier);
    window.addEventListener("offline", verifier);
    return () => {
      clearInterval(minuterie);
      window.removeEventListener("online", verifier);
      window.removeEventListener("offline", verifier);
    };
  }, [verifier]);

  const a = AFFICHAGE[etat.statut] || AFFICHAGE.verif;
  return (
    <div className={`flex items-center gap-1.5 text-xs text-muted-foreground ${className}`} data-testid="etat-serveur">
      <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${a.couleur} ${etat.statut === "ok" ? "animate-pulse" : ""}`} />
      <span className="font-medium" data-testid="etat-serveur-statut">{a.texte}</span>
      {etat.ms != null && <span className="opacity-70">· {etat.ms} ms</span>}
      <button type="button" onClick={verifier} className="ml-1 text-slate-400 hover:text-slate-600" title="Vérifier maintenant">↻</button>
    </div>
  );
}
