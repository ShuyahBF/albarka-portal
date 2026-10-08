// BandeauContrat.jsx — Lot 21 : bandeau du CONTRAT SAWALI en haut des pages du cabinet, pour le DG.
// Orange autour de l'échéance (de J-5 à J+4), rouge au-delà (J+5) : « renouvelez, sinon certains services pourraient
// être suspendus ». Le serveur décide de l'affichage (rôle DG, état du contrat lu dans SAWALI) ; relu toutes les 30 min.
// Lot 22 : seulement à ± 5 jours de l'échéance — orange de J-5 au jour J, rouge de J+1 à J+5 (avec les services qui
// seront suspendus et la date) ; en dehors de cette fenêtre, aucun bandeau.
import React, { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function BandeauContrat() {
  const [bandeau, setBandeau] = useState(null);
  useEffect(() => {
    let fini = false;
    const lire = () => apiClient.get("/contrat-plateforme").then((r) => { if (!fini) setBandeau(r.data); }).catch(() => {});
    lire();
    const minuterie = setInterval(lire, 5 * 60 * 1000);   // lot 22.1 : relu toutes les 5 min
    return () => { fini = true; clearInterval(minuterie); };
  }, []);
  if (!bandeau?.visible) return null;
  // Barème (lot 22.3) : orange J-5..J ; rouge adouci J+1..J+5 ; rouge vif quand des services sont suspendus
  const couleurs = {
    orange: "bg-amber-400 text-[#3b2a00]",
    rouge: "bg-red-200 text-red-900 border-b border-red-300",
    rouge_vif: "bg-red-600 text-white",
  };
  return (
    <div role="alert" data-testid={`bandeau-contrat-${bandeau.couleur}`}
      className={`flex w-full items-center justify-center gap-3 px-5 py-3 text-center text-sm md:text-base font-semibold shadow-sm ${couleurs[bandeau.couleur] || couleurs.orange}`}>
      {/* Lot 22.1 : bandeau en travers de toute la zone de droite, en haut de l'en-tête fixe */}
      <AlertTriangle className="h-5 w-5 shrink-0" />
      <span>{bandeau.message}</span>
    </div>
  );
}
