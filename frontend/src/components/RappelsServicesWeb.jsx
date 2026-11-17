/*
  Lot 90 — Fenêtre de rappel des services web, montrée au DG SEUL (monté par PortalLayout). Lot 120.7 : elle rappelle aussi les RELIQUATS (services à montant unique partiellement payés).
  S'ouvre quand un rappel est dû (7 jours, 3 jours, jour même, retard) et n'a pas encore été acquitté.
  FERMETURE : uniquement par le bouton « J'ai compris ». Ni clic à l'extérieur, ni touche Échap, ni bouton de fermeture (×).
  API : GET /me/services-web/rappels, POST /me/services-web/rappels/ack
*/
import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Globe, CheckCircle2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { EtatService } from "@/pages/admin/MesServicesWeb";

// Lot 120.6 : un rappel de RETARD revient à chaque connexion ; dans la même session (onglet / application ouverte) il n'est pas remontré après « J'ai compris » (rechargement de page compris)
const CLE_VUS = "rappels_sw_retard_vus";
const lireVus = () => { try { return JSON.parse(sessionStorage.getItem(CLE_VUS) || "[]"); } catch { return []; } };
const noterVus = (cles) => { try { sessionStorage.setItem(CLE_VUS, JSON.stringify([...new Set([...lireVus(), ...cles])])); } catch { /* stockage indisponible */ } };
const COULEUR_TEXTE = "#0277B5";   // bleu clair lisible (règle 16 : contraste ≥ 4,5:1)
const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR");

/** `onFini` : appelée quand il n'y a plus (ou pas) de rappel à montrer, pour que la fenêtre suivante (« Du nouveau chez SAWALI ») puisse s'ouvrir À SA SUITE. */
export default function RappelsServicesWeb({ onFini }) {
  const [rappels, setRappels] = useState([]);
  const [envoi, setEnvoi] = useState(false);

  // Au chargement du portail : y a-t-il des rappels à acquitter ?
  // Lot 120.8 : ROBUSTE aux coupures. Si le serveur est indisponible au moment de la connexion (redéploiement en cours, réseau instable), on RÉESSAIE (4 fois, toutes les 5 s)
  // au lieu d'abandonner en silence ; la fenêtre suivante ne s'ouvre qu'après la réponse définitive.
  useEffect(() => {
    let vivant = true; let minuterie; let essais = 0;
    const lire = () => apiClient.get("/me/services-web/rappels").then(({ data }) => {
      if (!vivant) return;
      const vus = lireVus();
      const a = (data.rappels || []).filter((r) => !(String(r.cle).includes(":retard") && vus.includes(r.cle)));
      setRappels(a); if (!a.length) onFini?.();
    }).catch(() => {
      if (!vivant) return;
      essais += 1;
      if (essais < 4) minuterie = setTimeout(lire, 5000); else onFini?.();
    });
    lire();
    return () => { vivant = false; clearTimeout(minuterie); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Échap ne ferme rien : on neutralise la touche tant que la fenêtre est ouverte
  useEffect(() => {
    if (rappels.length === 0) return undefined;
    const bloquer = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); } };
    document.addEventListener("keydown", bloquer, true);
    return () => document.removeEventListener("keydown", bloquer, true);
  }, [rappels.length]);

  if (rappels.length === 0) return null;

  // « J'ai compris » : acquitte les rappels affichés puis ferme (le seul moyen de fermer)
  const jAiCompris = async () => {
    setEnvoi(true);
    try {
      await apiClient.post("/me/services-web/rappels/ack", { cles: rappels.map((r) => r.cle) });
    } catch { /* en cas d'échec réseau, la fenêtre se fermera mais reviendra au prochain chargement */ }
    noterVus(rappels.map((r) => r.cle));
    setRappels([]);
    setEnvoi(false);
    onFini?.();                                                    // la fenêtre suivante peut s'ouvrir
  };

  // Aucun gestionnaire de clic sur le fond : cliquer à l'extérieur ne fait rien
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4" data-testid="rappels-services-web">
      <div role="alertdialog" aria-modal="true" aria-labelledby="rappel-titre" className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[85dvh] overflow-y-auto p-5 space-y-4">
        <h2 id="rappel-titre" className="text-lg font-semibold flex items-center gap-2"><Globe className="w-5 h-5 text-[#0F6B4A]" /> Rappel — services web à payer</h2>
        {/* Lot 120.7 : une PUCE NOIRE par service, texte en BLEU CLAIR (#0277B5, contraste 4,9:1), MONTANTS en gras, rouge, alignés à DROITE */}
        <ul className="space-y-3" data-testid="liste-rappels">
          {rappels.map((r) => {
            const reliquat = r.palier === "reliquat";
            return (
              <li key={r.cle} className="border rounded-lg p-3 text-sm" data-testid={`rappel-${r.id}`}>
                <div className="flex items-start gap-2">
                  <span aria-hidden="true" className="text-black leading-5" data-testid="puce-noire">●</span>
                  <div className="flex-1 min-w-0" style={{ color: COULEUR_TEXTE }}>
                    <div className="font-medium">{r.service}</div>
                    {reliquat ? (
                      <div>Reliquat à payer — payé {Number(r.total_paye || 0).toLocaleString("fr-FR")} sur {Number(r.montant).toLocaleString("fr-FR")} {r.devise}</div>
                    ) : (
                      <div>Payable avant le {fmtDate(r.payable_avant)}</div>
                    )}
                    <div className="mt-1"><EtatService s={r} /></div>
                  </div>
                  <div className="ml-auto text-right font-bold text-red-700 tabular-nums whitespace-nowrap" data-testid="montant-rappel">
                    {Number(reliquat ? r.reste_a_payer : r.montant).toLocaleString("fr-FR")} {r.devise}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <Button className="w-full bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={jAiCompris} disabled={envoi} data-testid="btn-jai-compris">
          <CheckCircle2 className="w-4 h-4 mr-1" /> J'ai compris
        </Button>
      </div>
    </div>,
    document.body,
  );
}
