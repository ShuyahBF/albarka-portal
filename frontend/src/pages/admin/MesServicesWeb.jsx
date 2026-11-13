/*
  Lot 90 — « Mes Services Web » : écran du DG (lecture seule).
  Liste les frais des services web configurés par le super-admin : service, montant, payable avant le, état (à jour / dans N jours /
  en retard) et dernier paiement (date et heure, montant, référence de la transaction).
  API : GET /me/services-web (albarka_services_web.py) — refusé à tout autre rôle que le DG.
*/
import React, { useEffect, useState } from "react";
import { Globe, AlertTriangle, CheckCircle2, Clock } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";

const fmtDate = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const fmtHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Aucun paiement enregistré");
const fmtMontant = (m, dev) => `${Number(m || 0).toLocaleString("fr-FR")} ${dev || "FCFA"}`;

// Pastille d'état : retard en rouge, échéance proche en orange, payé / à jour en vert
export function EtatService({ s }) {
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
          Frais des services web du cabinet. Vous êtes rappelé 7 jours avant, 3 jours avant et le jour même de l'échéance.
        </p>
      </div>
      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead>
            <tr className="text-left border-b">
              <th className="p-3">Service</th>
              <th className="p-3 text-right">Montant</th>
              <th className="p-3">Payable avant le</th>
              <th className="p-3">État</th>
              <th className="p-3">Dernier paiement</th>
              <th className="p-3 text-right">Montant payé</th>
              <th className="p-3">Référence</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.id} className="border-b last:border-0" data-testid={`service-${s.id}`}>
                <td className="p-3 font-medium">{s.service}</td>
                <td className="p-3 text-right tabular-nums">{fmtMontant(s.montant, s.devise)}</td>
                <td className="p-3">{fmtDate(s.payable_avant)}</td>
                <td className="p-3"><EtatService s={s} /></td>
                <td className="p-3">{fmtHeure(s.dernier_paiement_le)}</td>
                <td className="p-3 text-right tabular-nums">{s.dernier_paiement_le ? fmtMontant(s.dernier_paiement_montant, s.devise) : "—"}</td>
                <td className="p-3 font-mono text-xs">{s.dernier_paiement_reference || "—"}</td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">Aucun service configuré par le super-admin.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
