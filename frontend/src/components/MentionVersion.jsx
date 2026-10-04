/*
  MentionVersion — Lot 13 (règle permanente du propriétaire) : version et lot
  toujours affichés, au format « Version 1.N · Lot L (commit) ».
  Source unique : backend/lot.py, lue par GET /api/version (1.N = compteur de
  déploiements). Lecture faite une seule fois par page (mémorisée) ; en cas
  d'échec (serveur injoignable), repli sur APP_VERSION de src/version.js.
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { APP_VERSION } from "@/version";

// Promesse partagée : la barre du portail et la page de connexion ne font qu'un appel
let promesseVersion = null;
function chargerVersion() {
  if (!promesseVersion) {
    promesseVersion = apiClient.get("/version").then((r) => r.data).catch(() => null);
  }
  return promesseVersion;
}

export default function MentionVersion({ className = "", testId = "app-version" }) {
  const [infos, setInfos] = useState(null);
  useEffect(() => {
    let actif = true;
    chargerVersion().then((d) => { if (actif) setInfos(d); });
    return () => { actif = false; };
  }, []);
  // Texte affiché : version + lot + commit, sinon l'ancienne mention de version
  const texte = infos
    ? `Version ${infos.version} · Lot ${infos.lot}${infos.git_sha ? ` (${infos.git_sha})` : ""}`
    : APP_VERSION;
  return (
    <span className={className} data-testid={testId} title={infos?.lot_libelle || undefined}>
      {texte}
    </span>
  );
}
