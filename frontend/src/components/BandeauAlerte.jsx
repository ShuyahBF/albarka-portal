/*
  Lot 44 — Bandeau d'alerte / d'incident du portail (comme sur SAWALI), publié par le super-admin.
  Affiché en haut du portail et sur la page de connexion. Une image facultative s'affiche dans le coin GAUCHE.
  Le visiteur peut le fermer ; un NOUVEAU message (date de mise à jour différente) réapparaît.
*/
import React, { useEffect, useState } from "react";
import { Info, AlertTriangle, AlertOctagon, X, ArrowRight } from "lucide-react";
import { apiClient } from "@/lib/api";

const PALETTE = {
  info: { fond: "bg-sky-600 text-white", icone: Info },
  warning: { fond: "bg-amber-500 text-slate-900", icone: AlertTriangle },
  critical: { fond: "bg-rose-600 text-white", icone: AlertOctagon },
};

export default function BandeauAlerte() {
  const [bandeau, setBandeau] = useState(null);
  const [ferme, setFerme] = useState(false);

  // Relecture toutes les 60 s (le bandeau est public : aucune connexion nécessaire)
  useEffect(() => {
    let annule = false;
    const lire = async () => {
      try {
        const { data } = await apiClient.get("/bandeau");
        if (annule) return;
        setBandeau(data?.actif ? data : null);
        const cle = `albarka_bandeau_ferme:${data?.maj_le}`;
        try { setFerme(sessionStorage.getItem(cle) === "1"); } catch { setFerme(false); }
      } catch { /* facultatif : une erreur n'affiche rien */ }
    };
    lire();
    const t = setInterval(lire, 60000);
    return () => { annule = true; clearInterval(t); };
  }, []);

  if (!bandeau || ferme) return null;
  const p = PALETTE[bandeau.severite] || PALETTE.warning;
  const Icone = p.icone;
  const fermer = () => {
    setFerme(true);
    try { sessionStorage.setItem(`albarka_bandeau_ferme:${bandeau.maj_le}`, "1"); } catch { /* sans mémoire */ }
  };

  return (
    <div className={`${p.fond} print:hidden`} role="alert" data-testid="bandeau-alerte" data-severite={bandeau.severite}>
      <div className="mx-auto max-w-7xl px-4 py-2 flex items-center gap-3">
        {/* Image dans le coin gauche du bandeau (facultative) ; à défaut, le pictogramme de gravité */}
        {bandeau.image
          ? <img src={bandeau.image} alt="" className="h-10 w-10 shrink-0 rounded-md object-cover bg-white/20" data-testid="bandeau-alerte-image" />
          : <Icone className="h-4 w-4 shrink-0" />}
        <p className="min-w-0 flex-1 text-sm font-medium leading-snug break-words" data-testid="bandeau-alerte-message">
          {bandeau.message}
          {bandeau.lien_url && (
            <a href={bandeau.lien_url} target={bandeau.lien_url.startsWith("http") ? "_blank" : undefined} rel="noreferrer"
               className="ml-2 inline-flex items-center gap-1 font-semibold underline underline-offset-2 hover:opacity-80">
              {bandeau.lien_libelle || "En savoir plus"} <ArrowRight className="h-3 w-3" />
            </a>
          )}
        </p>
        <button type="button" onClick={fermer} aria-label="Fermer" className="shrink-0 h-6 w-6 inline-flex items-center justify-center rounded-full hover:bg-black/10">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
