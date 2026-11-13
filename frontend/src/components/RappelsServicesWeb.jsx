/*
  Lot 90 — Fenêtre de rappel des services web, montrée au DG SEUL (monté par PortalLayout).
  S'ouvre quand un rappel est dû (7 jours, 3 jours, jour même, retard) et n'a pas encore été acquitté.
  FERMETURE : uniquement par le bouton « J'ai compris ». Ni clic à l'extérieur, ni touche Échap, ni bouton de fermeture (×).
  API : GET /me/services-web/rappels, POST /me/services-web/rappels/ack
*/
import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Globe } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { EtatService } from "@/pages/admin/MesServicesWeb";

const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR");

export default function RappelsServicesWeb() {
  const [rappels, setRappels] = useState([]);
  const [envoi, setEnvoi] = useState(false);

  // Au chargement du portail : y a-t-il des rappels à acquitter ?
  useEffect(() => {
    apiClient.get("/me/services-web/rappels").then(({ data }) => setRappels(data.rappels || [])).catch(() => {});
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
    setRappels([]);
    setEnvoi(false);
  };

  // Aucun gestionnaire de clic sur le fond : cliquer à l'extérieur ne fait rien
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4" data-testid="rappels-services-web">
      <div role="alertdialog" aria-modal="true" aria-labelledby="rappel-titre" className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[85dvh] overflow-y-auto p-5 space-y-4">
        <h2 id="rappel-titre" className="text-lg font-semibold flex items-center gap-2"><Globe className="w-5 h-5 text-[#0F6B4A]" /> Rappel — services web à payer</h2>
        <ul className="space-y-3">
          {rappels.map((r) => (
            <li key={r.cle} className="border rounded-lg p-3 text-sm" data-testid={`rappel-${r.id}`}>
              <div className="font-medium">{r.service}</div>
              <div className="tabular-nums">{Number(r.montant).toLocaleString("fr-FR")} {r.devise}</div>
              <div className="text-muted-foreground">Payable avant le {fmtDate(r.payable_avant)}</div>
              <div className="mt-1"><EtatService s={r} /></div>
            </li>
          ))}
        </ul>
        <Button className="w-full bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={jAiCompris} disabled={envoi} data-testid="btn-jai-compris">
          J'ai compris
        </Button>
      </div>
    </div>,
    document.body,
  );
}
