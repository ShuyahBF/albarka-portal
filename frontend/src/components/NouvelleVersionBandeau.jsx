import React, { useEffect, useRef, useState } from "react";
import { empreinteChargee, empreinteHtml, nouvelleVersionDisponible } from "@/lib/versionSite";

/*
  Lot 63 — Bandeau « Une nouvelle version de ALBARKA est disponible ».
  Toutes les 5 minutes (et quand l'onglet redevient visible), on télécharge la page d'accueil sans cache
  et on compare ses fichiers principaux à ceux de la page ouverte. S'ils diffèrent, un bandeau propose
  d'actualiser.
  Toujours actif (aucun réglage). Aucun effet en développement. La vérification est en arrière-plan : elle ne bloque jamais l'écran.
*/
const INTERVALLE_MS = 5 * 60 * 1000;

export default function NouvelleVersionBandeau() {
  const [dispo, setDispo] = useState(false);
  const [masque, setMasque] = useState(false);
  const actif = useRef(true);   // toujours actif
  const chargee = useRef("");

  useEffect(() => {
    let vivant = true;
    chargee.current = empreinteChargee(document);
    if (!chargee.current) return undefined;   // développement : rien à surveiller

    // Compare la page ouverte à la page d'accueil actuellement en ligne.
    const verifier = () => {
      if (!actif.current || document.hidden) return;
      fetch("/", { cache: "no-store" })
        .then((r) => r.text())
        .then((html) => {
          if (vivant && nouvelleVersionDisponible(chargee.current, empreinteHtml(html))) setDispo(true);
        })
        .catch(() => {});
    };
    const id = setInterval(verifier, INTERVALLE_MS);
    document.addEventListener("visibilitychange", verifier);
    return () => { vivant = false; clearInterval(id); document.removeEventListener("visibilitychange", verifier); };
  }, []);

  if (!dispo || masque) return null;
  return (
    <div
      role="status"
      data-testid="bandeau-nouvelle-version"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-3 rounded-xl bg-slate-900 text-white shadow-lg px-4 py-3 text-sm max-w-[92vw]"
    >
      <span>Une nouvelle version de ALBARKA est disponible.</span>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded-lg bg-sky-500 hover:bg-sky-400 px-3 py-1 font-semibold"
        data-testid="bandeau-nouvelle-version-actualiser"
      >
        Actualiser
      </button>
      <button type="button" onClick={() => setMasque(true)} className="text-slate-300 hover:text-white">
        Plus tard
      </button>
    </div>
  );
}
