/*
  Lot 90 — « Mes Services Web » : écran du DG (lecture seule).
  Liste les frais des services web configurés par le super-admin : service, montant, payable avant le, état (à jour / dans N jours /
  en retard) et dernier paiement (date et heure, montant, référence de la transaction).
  API : GET /me/services-web (albarka_services_web.py) — refusé à tout autre rôle que le DG.
*/
import React, { useEffect, useState } from "react";
import { Globe, AlertTriangle, CheckCircle2, Clock, Printer } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { imprimerRecu } from "@/lib/recuServiceWeb";

const fmtDate = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const fmtHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Aucun paiement enregistré");
const fmtMontant = (m, dev) => `${Number(m || 0).toLocaleString("fr-FR")} ${dev || "FCFA"}`;

// Pastille d'état : retard en rouge, échéance proche en orange, payé / à jour en vert
export function EtatService({ s }) {
  if (s.etat === "partiel") return <span className="inline-flex items-center gap-1 text-orange-700 font-semibold"><Clock className="w-4 h-4" /> Partiellement payé</span>;
  if (s.etat === "impaye") return <span className="inline-flex items-center gap-1 text-red-700"><AlertTriangle className="w-4 h-4" /> Rien payé</span>;
  if (s.etat === "paye") return <span className="inline-flex items-center gap-1 text-green-700"><CheckCircle2 className="w-4 h-4" /> Payé</span>;
  if (s.etat === "en_retard") return <span className="inline-flex items-center gap-1 text-red-700 font-semibold"><AlertTriangle className="w-4 h-4" /> En retard de {Math.abs(s.jours_restants)} j</span>;
  if (s.etat === "aujourdhui") return <span className="inline-flex items-center gap-1 text-orange-700 font-semibold"><Clock className="w-4 h-4" /> À payer aujourd'hui</span>;
  if (s.etat === "bientot") return <span className="inline-flex items-center gap-1 text-orange-700"><Clock className="w-4 h-4" /> Dans {s.jours_restants} j</span>;
  return <span className="text-muted-foreground">Dans {s.jours_restants} j</span>;
}

export default function MesServicesWeb() {
  const [services, setServices] = useState(null);
  const [erreur, setErreur] = useState("");

  useEffect(() => {
    apiClient.get("/me/services-web").then(({ data }) => setServices(data.services)).catch((e) => setErreur(extractError(e, "Accès refusé")));
  }, []);

  if (erreur) return <div className="p-6 text-sm text-red-700">{erreur}</div>;
  if (!services) return <div className="p-6 text-sm text-muted-foreground">Chargement…</div>;

  return (
    <div className="space-y-5" data-testid="mes-services-web">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Globe className="w-6 h-6 text-[#0F6B4A]" /> Mes Services Web</h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
          Frais des services web du cabinet. Paiements mensuels : vous êtes rappelé 7 jours avant, 3 jours avant et le jour même de l'échéance, chaque mois. Montant unique : le payé et le reste à payer sont affichés, sans rappel mensuel.
        </p>
      </div>
      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead>
            <tr className="text-left border-b">
              <th className="p-3">Service</th>
              <th className="p-3 text-right">Montant</th>
              <th className="p-3">Payable le</th>
              <th className="p-3">État</th>
              <th className="p-3">Dernier paiement</th>
              <th className="p-3 text-right">Montant payé</th>
              <th className="p-3">Référence</th>
              <th className="p-3 text-right">Reste à payer</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.id} className="border-b last:border-0" data-testid={`service-${s.id}`}>
                <td className="p-3 font-medium whitespace-pre-line">{s.service}</td>
                <td className="p-3 text-right tabular-nums">{fmtMontant(s.montant, s.devise)}</td>
                <td className="p-3">{s.mode === "unique" ? <>Montant unique<div className="text-xs text-muted-foreground">réglé en une ou plusieurs fois</div></> : <>Le {s.jour_du_mois} de chaque mois<div className="text-xs text-muted-foreground">Prochaine échéance : {fmtDate(s.payable_avant)}</div></>}</td>
                <td className="p-3"><EtatService s={s} /></td>
                <td className="p-3">{fmtHeure(s.dernier_paiement_le)}</td>
                <td className="p-3 text-right tabular-nums">{s.dernier_paiement_le ? fmtMontant(s.dernier_paiement_montant, s.devise) : "—"}</td>
                <td className="p-3 font-mono text-xs">{s.dernier_paiement_reference || "—"}</td>
                <td className="p-3 text-right tabular-nums">
                  {s.mode === "unique" ? (<><span className={s.reste_a_payer > 0 ? "font-semibold text-red-700" : "text-green-700"}>{fmtMontant(s.reste_a_payer, s.devise)}</span>
                    <div className="text-xs text-muted-foreground">payé {fmtMontant(s.total_paye, s.devise)}</div></>) : "—"}
                  {(s.paiements || []).length > 0 && (
                    <details className="text-left text-xs mt-1"><summary className="cursor-pointer text-muted-foreground">{s.paiements.length} paiement(s) — imprimer un reçu</summary>
                      <ul className="mt-1 space-y-0.5">{s.paiements.map((p) => (<li key={p.id} className="flex flex-wrap items-center gap-2">{new Date(p.paye_le).toLocaleDateString("fr-FR")} · {fmtMontant(p.montant, s.devise)} · {p.reference}
                        <button type="button" className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5" onClick={() => imprimerRecu(`/me/services-web/${s.id}/paiements/${p.id}/recu`).catch((e) => window.alert(extractError(e)))} title="Imprimer le reçu de ce paiement" aria-label="Imprimer le reçu de ce paiement"><Printer className="w-3 h-3" /> Imprimer le reçu</button></li>))}</ul></details>
                  )}
                </td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-muted-foreground">Aucun service configuré par le super-admin.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
