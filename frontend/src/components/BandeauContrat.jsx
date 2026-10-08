// BandeauContrat.jsx — Lot 21 : bandeau du CONTRAT SAWALI en haut des pages du cabinet, pour le DG.
// Orange autour de l'échéance (de J-5 à J+4), rouge au-delà (J+5) : « renouvelez, sinon certains services pourraient
// être suspendus ». Le serveur décide de l'affichage (rôle DG, état du contrat lu dans SAWALI) ; relu toutes les 30 min.
import React, { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function BandeauContrat() {
  const [bandeau, setBandeau] = useState(null);
  useEffect(() => {
    let fini = false;
    const lire = () => apiClient.get("/contrat-plateforme").then((r) => { if (!fini) setBandeau(r.data); }).catch(() => {});
    lire();
    const minuterie = setInterval(lire, 30 * 60 * 1000);
    return () => { fini = true; clearInterval(minuterie); };
  }, []);
  if (!bandeau?.visible) return null;
  const rouge = bandeau.couleur === "rouge";
  return (
    <div role="alert" data-testid={`bandeau-contrat-${bandeau.couleur}`}
      className={`flex items-start gap-2 px-5 py-2 text-sm font-medium ${rouge ? "bg-red-600 text-white" : "bg-amber-400 text-[#3b2a00]"}`}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{bandeau.message}</span>
    </div>
  );
}
