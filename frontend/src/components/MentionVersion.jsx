/*
  MentionVersion — règle permanente du propriétaire (révisée le 04/10/2026) :
  - page de connexion et portail (barre latérale) : libellé COURT
      « Version 1.N · déployée le JJ/MM/AAAA HH:MM »
  - pages d'administration / paramétrage (prop `detaille`) : libellé COMPLET
      « Version 1.N · Lot L · commit · déployée le JJ/MM/AAAA HH:MM »
  Source unique : backend/lot.py et le compteur de déploiements, lus par
  GET /api/version (version, lot, git_sha, deployed_at). Lecture faite une seule
  fois par page (mémorisée) ; en cas d'échec, repli sur APP_VERSION de src/version.js.
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { APP_VERSION } from "@/version";

// Promesse partagée : la barre du portail et la page affichée ne font qu'un appel
let promesseVersion = null;
function chargerVersion() {
  if (!promesseVersion) {
    promesseVersion = apiClient.get("/version").then((r) => r.data).catch(() => null);
  }
  return promesseVersion;
}

// Date/heure de déploiement au format français court : « 04/10/2026 21:40 »
function dateDeploiement(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

// Libellé de version : court (connexion, portail) ou complet (administration)
export function libelleVersion(infos, detaille = false) {
  if (!infos) return APP_VERSION;
  const morceaux = [`Version ${infos.version}`];
  if (detaille) {
    if (infos.lot) morceaux.push(`Lot ${infos.lot}`);
    if (infos.git_sha && infos.git_sha !== "unknown") morceaux.push(infos.git_sha);
  }
  const date = dateDeploiement(infos.deployed_at);
  if (date) morceaux.push(`déployée le ${date}`);
  return morceaux.join(" · ");
}

export default function MentionVersion({ className = "", testId = "app-version", detaille = false }) {
  const [infos, setInfos] = useState(null);
  useEffect(() => {
    let actif = true;
    chargerVersion().then((d) => { if (actif) setInfos(d); });
    return () => { actif = false; };
  }, []);
  return (
    // Au survol (administration seulement) : le libellé du lot
    <span className={className} data-testid={testId} title={detaille ? infos?.lot_libelle || undefined : undefined}>
      {libelleVersion(infos, detaille)}
    </span>
  );
}
