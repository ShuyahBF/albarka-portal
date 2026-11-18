/*
  Lot 117 — Fenêtre « Du nouveau chez SAWALI », montrée au DG SEUL à son arrivée dans le portail (monté par PortalLayout, comme le rappel des services web) :
    • les NOUVEAUX PAIEMENTS reçus lus par SAWALI dans les SMS depuis la dernière lecture ;
    • les RÉPONSES de SAWALI à ses demandes (statut, commentaire, date de réalisation ou prévue).
  FERMETURE : uniquement par « J'ai compris » (qui acquitte ce qui est affiché) ou par « Voir les demandes » (qui acquitte aussi puis ouvre la page). Ni clic à l'extérieur, ni Échap.
  Le serveur lit les paiements chez SAWALI EN ARRIÈRE-PLAN : la première réponse peut être « en cours de lecture » ; on redemande quelques secondes plus tard (3 fois au plus).
  API : GET /me/infos-connexion, POST /me/infos-connexion/ack
*/
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Banknote, CheckCircle2, Send } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

const fmtJour = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : null);
const fmtHeure = (iso) => { try { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

/** Phrase de suivi d'une demande : réalisée le … / prévue le … / refusée. */
export function libelleSuivi(d) {
  if (d.statut === "realisee") return `Réalisée le ${fmtJour(d.realisee_le) || "—"}`;
  if (d.statut === "refusee") return "Refusée";
  if (d.statut === "deja_repondu") return "Déjà répondu";
  return d.prevue_le ? `Prévue le ${fmtJour(d.prevue_le)}` : "Date de réalisation à venir";
}

/** `actif` : faux tant que le rappel des services web est affiché (une seule fenêtre à la fois : l'une cachait l'autre). */
export default function InfosConnexionDG({ actif = true }) {
  const [infos, setInfos] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const navigate = useNavigate();
  const essais = useRef(0);

  // À l'arrivée : lecture, puis jusqu'à 3 relectures espacées de 6 s tant que les paiements sont « en cours de lecture » chez SAWALI
  useEffect(() => {
    if (!actif) return undefined;
    let vivant = true; let minuterie;
    const lire = () => apiClient.get("/me/infos-connexion").then(({ data }) => {
      if (!vivant) return;
      setInfos((ancien) => (ancien && (ancien.paiements.length || ancien.demandes.length) && !(data.paiements.length || data.demandes.length) ? ancien : data));
      if (data.paiements_etat === "jamais" && essais.current < 3) { essais.current += 1; minuterie = setTimeout(lire, 6000); }
    }).catch(() => {});
    lire();
    return () => { vivant = false; clearTimeout(minuterie); };
  }, [actif]);

  const ouverte = !!infos && (infos.paiements.length > 0 || infos.demandes.length > 0);

  // Échap ne ferme rien tant que la fenêtre est ouverte
  useEffect(() => {
    if (!ouverte) return undefined;
    const bloquer = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); } };
    document.addEventListener("keydown", bloquer, true);
    return () => document.removeEventListener("keydown", bloquer, true);
  }, [ouverte]);

  if (!ouverte) return null;

  // « J'ai compris » : acquitte ce qui était affiché (la date `jusqu_a` vient du serveur), puis ferme
  const acquitter = async (vers) => {
    setEnvoi(true);
    try { await apiClient.post("/me/infos-connexion/ack", { jusqu_a: infos.jusqu_a }); } catch { /* la fenêtre reviendra au prochain chargement */ }
    setInfos(null); setEnvoi(false);
    if (vers) navigate(vers);
  };

  return createPortal(
    <div className="fixed inset-0 z-[101] flex items-center justify-center bg-black/60 p-4" data-testid="infos-connexion-dg">
      <div role="alertdialog" aria-modal="true" aria-labelledby="infos-titre" className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85dvh] overflow-y-auto p-5 space-y-4">
        <h2 id="infos-titre" className="text-lg font-semibold flex items-center gap-2"><Send className="w-5 h-5 text-[#0F6B4A]" /> Du nouveau chez SAWALI</h2>

        {infos.paiements.length > 0 && (
          <section className="space-y-2" data-testid="infos-paiements">
            <h3 className="font-medium flex items-center gap-2 text-[#0F6B4A]"><Banknote className="w-4 h-4" /> {infos.paiements.length} nouveau{infos.paiements.length > 1 ? "x" : ""} paiement{infos.paiements.length > 1 ? "s" : ""} reçu{infos.paiements.length > 1 ? "s" : ""}</h3>
            <ul className="space-y-2">
              {infos.paiements.map((p) => (
                <li key={p.id || p.recu_le} className="border rounded-lg p-2 text-sm flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-semibold text-green-700 tabular-nums">{Number(p.montant).toLocaleString("fr-FR")} FCFA</span>
                  <span className="text-muted-foreground">{[p.operateur, p.tiers].filter(Boolean).join(" · ")}</span>
                  <span className="text-muted-foreground tabular-nums">{fmtHeure(p.recu_le)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {infos.demandes.length > 0 && (
          <section className="space-y-2" data-testid="infos-demandes">
            <h3 className="font-medium flex items-center gap-2 text-[#0F6B4A]"><Send className="w-4 h-4" /> {infos.demandes.length} réponse{infos.demandes.length > 1 ? "s" : ""} de SAWALI à vos demandes</h3>
            <ul className="space-y-2">
              {infos.demandes.map((d) => (
                <li key={d.id} className="border rounded-lg p-2 text-sm space-y-0.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3"><span className="font-mono text-xs text-blue-800">{d.numero_sawali || "—"}</span>
                    <span className={d.statut === "realisee" ? "text-green-700 font-medium" : d.statut === "refusee" ? "text-red-700 font-medium" : "text-orange-700 font-medium"}>{libelleSuivi(d)}</span></div>
                  <div className="line-clamp-2">{d.texte}</div>
                  {d.commentaire && <div className="text-muted-foreground">{d.commentaire}</div>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {infos.paiements_etat === "indisponible" && infos.paiements.length === 0 && <p className="text-xs text-muted-foreground">Les paiements reçus n'ont pas pu être lus chez SAWALI pour le moment.</p>}

        <div className="flex flex-wrap gap-2">
          <Button className="flex-1 bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={() => acquitter(null)} disabled={envoi} data-testid="btn-infos-compris"><CheckCircle2 className="w-4 h-4 mr-1" /> J'ai compris</Button>
          {infos.demandes.length > 0 && <Button variant="outline" onClick={() => acquitter("/admin/demandes-sawali")} disabled={envoi} data-testid="btn-infos-voir-demandes"><Send className="w-4 h-4 mr-1" /> Voir les demandes</Button>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
