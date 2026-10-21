/*
  Lot 67 — « Mon contrat » (espace client) : le client voit SES contrats avec le cabinet (numéro, période, montant, statut)
  et peut ouvrir ou télécharger le document du contrat attaché par le cabinet (Word, PDF ou image).
  API : GET /me/contracts, GET /me/contracts/{id}/document[?download=true] (backend/albarka_contracts.py, me_router).
  Lecture seule : le client ne modifie rien.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Eye, FileSignature, Paperclip } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";

const STATUTS = {
  en_cours: ["En cours", "bg-emerald-100 text-emerald-800"],
  suspendu: ["Suspendu", "bg-amber-100 text-amber-800"],
  termine: ["Terminé", "bg-slate-100 text-slate-500"],
  annule: ["Annulé", "bg-red-100 text-red-700"],
};
const tailleLisible = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} Mo` : `${Math.max(1, Math.round((n || 0) / 1024))} Ko`);
const dateFr = (d) => (d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : "—");

export default function MonContrat() {
  const [items, setItems] = useState([]);
  const [chargement, setChargement] = useState(true);

  useEffect(() => {
    apiClient.get("/me/contracts")
      .then((r) => setItems(r.data.items || []))
      .catch((err) => toast.error(extractError(err)))
      .finally(() => setChargement(false));
  }, []);

  // Ouvre le document dans un nouvel onglet, ou le télécharge (le jeton de connexion est joint à la demande)
  const ouvrir = async (c, telecharger) => {
    try {
      const res = await apiClient.get(`/me/contracts/${c.id}/document`, { responseType: "blob", params: telecharger ? { download: true } : {} });
      const url = window.URL.createObjectURL(res.data);
      if (telecharger) { const a = document.createElement("a"); a.href = url; a.download = c.document?.filename || "contrat"; a.click(); }
      else window.open(url, "_blank");
    } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
  };

  return (
    <div className="space-y-6" data-testid="client-contrat-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Mon contrat</h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">Vos contrats avec le cabinet. Quand le cabinet a joint le document signé, vous pouvez l'ouvrir ou le télécharger ici.</p>
      </div>
      {chargement && <p className="text-muted-foreground">Chargement…</p>}
      {!chargement && items.length === 0 && <div className="albarka-card p-8 text-center text-muted-foreground">Aucun contrat enregistré pour le moment.</div>}
      <div className="grid gap-4">
        {items.map((c) => {
          const [libelle, tonalite] = STATUTS[c.status] || [c.status, "bg-slate-100 text-slate-700"];
          return (
            <div key={c.id} className="albarka-card p-5" data-testid={`client-contrat-${c.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <FileSignature className="w-6 h-6 text-[#0F6B4A] mt-0.5" />
                  <div>
                    <div className="font-mono text-xs text-muted-foreground">{c.numero_contrat || "—"}</div>
                    <div className="text-lg font-medium">{c.title}</div>
                  </div>
                </div>
                <span className={`albarka-chip ${tonalite}`}>{libelle}</span>
              </div>
              <dl className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div><dt className="text-muted-foreground text-xs">Début</dt><dd>{dateFr(c.start_date)}</dd></div>
                <div><dt className="text-muted-foreground text-xs">Fin</dt><dd>{c.end_date ? dateFr(c.end_date) : "Sans date de fin"}</dd></div>
                <div><dt className="text-muted-foreground text-xs">Montant</dt><dd className="font-mono">{c.amount ? `${Number(c.amount).toLocaleString("fr-FR")} ${c.currency || "XOF"}` : "—"}</dd></div>
                <div><dt className="text-muted-foreground text-xs">Dernier paiement</dt><dd>{dateFr(c.date_dernier_paiement)}</dd></div>
              </dl>
              <div className="mt-4 rounded-lg border border-dashed border-[#0F6B4A]/40 p-3 flex flex-wrap items-center gap-3 text-sm">
                <Paperclip className="w-4 h-4 text-[#0F6B4A]" />
                {c.document ? (
                  <>
                    <span className="font-medium">{c.document.filename}</span>
                    <span className="text-xs text-muted-foreground">{tailleLisible(c.document.size)}</span>
                    <Button size="sm" variant="outline" onClick={() => ouvrir(c, false)} data-testid={`client-contrat-ouvrir-${c.id}`}><Eye className="w-4 h-4 mr-1" />Ouvrir</Button>
                    <Button size="sm" className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={() => ouvrir(c, true)} data-testid={`client-contrat-telecharger-${c.id}`}><Download className="w-4 h-4 mr-1" />Télécharger</Button>
                  </>
                ) : <span className="text-muted-foreground">Le document du contrat n'a pas encore été joint par le cabinet.</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
