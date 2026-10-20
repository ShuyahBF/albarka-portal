/*
  « Mes demandes » (espace client, lot 53) — le client demande un service au cabinet
  (fiscalité, RH, comptabilité, autres) par texte, note vocale et pièces jointes,
  et suit l'avancement de ses demandes.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import FormulaireDemande from "@/components/demandes/FormulaireDemande";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
export const STATUTS = { nouvelle: ["Reçue", "bg-sky-100 text-sky-800"], en_cours: ["En cours", "bg-amber-100 text-amber-800"],
  traitee: ["Traitée", "bg-emerald-100 text-emerald-800"], classee: ["Classée", "bg-slate-100 text-slate-700"] };
export const LIBELLES = { fiscalite: "Fiscalité", rh: "Ressources humaines", comptable: "Comptabilité", autres: "Autres demandes" };

export default function Demandes() {
  const [liste, setListe] = useState(null);
  const charger = () => apiClient.get("/demandes/mes").then(({ data }) => setListe(data)).catch((e) => { toast.error(extractError(e)); setListe([]); });
  useEffect(() => { charger(); }, []);

  return (
    <div className="space-y-6" data-testid="demandes-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl">Demander un service</h1>
        <p className="text-muted-foreground mt-1">Fiscalité, ressources humaines, comptabilité ou autre : écrivez, parlez ou joignez vos pièces.</p>
      </div>
      <div className="rounded-xl border bg-white p-5 max-w-2xl">
        <FormulaireDemande onEnvoyer={async (fd) => { await apiClient.post("/demandes", fd); charger(); }} />
      </div>
      <div>
        <h2 className="font-display text-xl mb-3">Mes demandes</h2>
        {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div>
          : !liste.length ? <div className="text-sm text-muted-foreground">Aucune demande pour le moment.</div>
          : (
            <div className="space-y-2">
              {liste.map((d) => (
                <div key={d.id} className="rounded-lg border bg-white p-3 text-sm" data-testid="demande-ligne">
                  <div className="flex flex-wrap items-center gap-2">
                    <b>{LIBELLES[d.service] || d.service}</b>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${STATUTS[d.status]?.[1] || ""}`}>{STATUTS[d.status]?.[0] || d.status}</span>
                    {d.urgent && <span className="px-2 py-0.5 rounded-full text-xs bg-rose-100 text-rose-800">Urgent</span>}
                    <span className="text-muted-foreground ml-auto">{fmtDate(d.created_at)}</span>
                  </div>
                  {d.description && <p className="mt-1 text-slate-700 whitespace-pre-wrap">{d.description}</p>}
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
