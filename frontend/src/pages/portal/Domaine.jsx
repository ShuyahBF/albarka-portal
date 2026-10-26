/*
  Lot 72 — Pages « Comptabilité », « Fiscalité » et « Ressources humaines » de l'espace client.
  Pour son domaine, le client voit : ses missions, ses échéances et les documents que le cabinet lui a envoyés (rangement : lib/domainesClient.js),
  et un bouton pour faire une demande de service. Le serveur ne renvoie que SES éléments (même règle que les autres pages de l'espace).
*/
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, MessageCircle } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ListeDocumentsClient from "@/components/ListeDocumentsClient";
import { DOMAINES, STATUTS_ECHEANCE, STATUTS_MISSION, elementsDuDomaine } from "@/lib/domainesClient";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");

export default function Domaine({ domaine }) {
  const d = DOMAINES[domaine];
  const [donnees, setDonnees] = useState(null);

  // Trois lectures indépendantes, en parallèle : une qui échoue (module fermé par le cabinet…) n'empêche pas les autres
  const charger = useCallback(async () => {
    const [m, e, s] = await Promise.allSettled([apiClient.get("/missions"), apiClient.get("/echeances"), apiClient.get("/me/space")]);
    const echecs = [m, e, s].filter((r) => r.status === "rejected");
    if (echecs.length === 3) toast.error(extractError(echecs[0].reason));
    setDonnees({
      missions: m.status === "fulfilled" ? m.value.data || [] : [],
      echeances: e.status === "fulfilled" ? e.value.data || [] : [],
      documents: s.status === "fulfilled" ? s.value.data?.items || [] : [],
    });
  }, []);
  useEffect(() => { setDonnees(null); charger(); }, [charger, domaine]);

  const el = donnees ? elementsDuDomaine(domaine, donnees) : null;
  const total = el ? el.missions.length + el.echeances.length + el.documents.length : 0;

  return (
    <div className="space-y-6" data-testid={`page-domaine-${domaine}`}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[220px]">
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
          <h1 className="font-display text-3xl">{d.titre}</h1>
          <p className="text-muted-foreground mt-1">Vos missions, échéances et documents de ce domaine.</p>
        </div>
        <Link to="/portal/demandes"><Button size="sm" variant="outline"><MessageCircle className="w-4 h-4 mr-1" /> Demander un service</Button></Link>
      </div>
      {el === null ? (
        <p className="text-sm text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Chargement…</p>
      ) : total === 0 ? (
        <div className="albarka-card p-10 text-center text-muted-foreground" data-testid="domaine-vide">{d.vide}</div>
      ) : (
        <>
          {el.missions.length > 0 && (
            <section className="space-y-2" data-testid="domaine-missions">
              <h2 className="font-display text-xl">Missions</h2>
              {el.missions.map((m) => (
                <div key={m.id} className="albarka-card p-4 flex flex-wrap items-center gap-3">
                  <div className="flex-1 min-w-[220px]"><div className="font-medium">{m.title}</div>
                    {m.due_date && <div className="text-xs text-muted-foreground">Échéance : {fmtDate(m.due_date)}</div>}</div>
                  <span className="albarka-chip text-xs">{STATUTS_MISSION[m.status] || m.status}</span>
                </div>
              ))}
            </section>
          )}
          {el.echeances.length > 0 && (
            <section className="space-y-2" data-testid="domaine-echeances">
              <h2 className="font-display text-xl">Échéances</h2>
              {el.echeances.map((e) => (
                <div key={e.id} className="albarka-card p-4 flex flex-wrap items-center gap-3">
                  <div className="flex-1 min-w-[220px]"><div className="font-medium">{e.title}</div>
                    <div className="text-xs text-muted-foreground">À rendre le {fmtDate(e.due_date)}{e.period ? ` · ${e.period}` : ""}</div></div>
                  <span className={`albarka-chip text-xs ${e.status === "en_retard" ? "bg-rose-100 text-rose-800" : ""}`}>{STATUTS_ECHEANCE[e.status] || e.status}</span>
                </div>
              ))}
            </section>
          )}
          {el.documents.length > 0 && (
            <section className="space-y-2" data-testid="domaine-documents">
              <h2 className="font-display text-xl">Documents</h2>
              <ListeDocumentsClient items={el.documents} apres={charger} testid="domaine-liste-docs" />
            </section>
          )}
        </>
      )}
    </div>
  );
}
