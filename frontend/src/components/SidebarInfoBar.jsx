/*
  SidebarInfoBar — barre jaune tout en haut de la sidebar (cabinet et client) :
    - à gauche : date et heure en temps réel (mise à jour chaque seconde) ;
    - à droite : numéro de version du portail (APP_VERSION dans src/version.js).
*/
import React, { useEffect, useState } from "react";
import { APP_VERSION } from "@/version";

export default function SidebarInfoBar() {
  const [now, setNow] = useState(() => new Date());
  // Horloge : rafraîchit l'affichage toutes les secondes, arrêtée au démontage
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  // Format français : 26/09/2026 14:05:09
  const date = now.toLocaleDateString("fr-FR");
  const time = now.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return (
    <div className="shrink-0 bg-[#FACC15] text-[#0B1912] px-3 py-1 flex items-center justify-between text-xs font-semibold tabular-nums" data-testid="sidebar-info-bar">
      <span data-testid="sidebar-clock">{date} {time}</span>
      <span data-testid="sidebar-version">{APP_VERSION}</span>
    </div>
  );
}
