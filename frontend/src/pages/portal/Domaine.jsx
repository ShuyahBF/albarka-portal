/*
  Lot 72 — Pages « Comptabilité », « Fiscalité » et « Ressources humaines » de l'espace client.
  Pour son domaine, le client voit : ses missions, ses échéances et les documents que le cabinet lui a envoyés (rangement : lib/domainesClient.js),
  et un bouton pour faire une demande de service. Le serveur ne renvoie que SES éléments (même règle que les autres pages de l'espace).
*/
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ChevronDown, FileText, Loader2, MessageCircle } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ListeDocumentsClient from "@/components/ListeDocumentsClient";
import { ouvrirPdf } from "@/lib/ouvrirDocument";
import { DOMAINES, STATUTS_ECHEANCE, STATUTS_MISSION, elementsDuDomaine } from "@/lib/domainesClient";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");
const fmtMontant = (n) => Math.round(Number(n || 0)).toLocaleString("fr-FR");   // FCFA, sans décimales

export default function Domaine({ domaine }) {
  const d = DOMAINES[domaine];
  const [donnees, setDonnees] = useState(null);
  const [balance, setBalance] = useState(null);                // lot 74 : balance du client (page Comptabilité seulement)
  const [paie, setPaie] = useState(null);                       // lot 75 : bulletins validés et déclarations CNSS (page Ressources humaines seulement)
  const [moisOuvert, setMoisOuvert] = useState("");             // mois dont la liste des bulletins est dépliée
  const [bulletins, setBulletins] = useState([]);

  // Trois lectures indépendantes, en parallèle : une qui échoue (module fermé par le cabinet…) n'empêche pas les autres
  const charger = useCallback(async () => {
    if (domaine === "rh") apiClient.get("/me/paie").then(({ data }) => setPaie(data)).catch(() => setPaie({ mois: [], declarations: [] }));   // rubrique fermée = rien à montrer
    const [m, e, s] = await Promise.allSettled([apiClient.get("/missions"), apiClient.get("/echeances"), apiClient.get("/me/space")]);
    const echecs = [m, e, s].filter((r) => r.status === "rejected");
    if (echecs.length === 3) toast.error(extractError(echecs[0].reason));
    if (domaine === "comptabilite") apiClient.get("/me/balance").then(({ data }) => setBalance(data)).catch(() => setBalance({ rows: [] }));
    setDonnees({
      missions: m.status === "fulfilled" ? m.value.data || [] : [],
      echeances: e.status === "fulfilled" ? e.value.data || [] : [],
      documents: s.status === "fulfilled" ? s.value.data?.items || [] : [],
    });
  }, [domaine]);
  useEffect(() => { setDonnees(null); setBalance(null); setPaie(null); setMoisOuvert(""); charger(); }, [charger, domaine]);

  const el = donnees ? elementsDuDomaine(domaine, donnees) : null;
  // Lot 74 — Comptabilité : « Déclarations déposées » = documents de catégorie « Déclaration fiscale » mis à disposition par le cabinet
  const declarations = domaine === "comptabilite" && donnees ? donnees.documents.filter((x) => x.category === "declaration") : [];
  const lignesBalance = balance?.rows || [];
  const moisPaie = paie?.mois || [], declarationsCnss = paie?.declarations || [];
  const total = el ? el.missions.length + el.echeances.length + el.documents.length + declarations.length + lignesBalance.length + moisPaie.length + declarationsCnss.length : 0;

  // Déplie / replie la liste des bulletins validés d'un mois (une lecture à l'ouverture)
  const basculerMois = async (m) => {
    if (moisOuvert === m) { setMoisOuvert(""); return; }
    setMoisOuvert(m); setBulletins([]);
    try { setBulletins((await apiClient.get("/me/paie/bulletins", { params: { period_month: m } })).data?.items || []); }
    catch (err) { toast.error(extractError(err)); }
  };
  const libMois = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });

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
          {domaine === "comptabilite" && lignesBalance.length > 0 && (
            <section className="space-y-2" data-testid="domaine-balance">
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="font-display text-xl">Balance</h2>
                <span className="text-xs text-muted-foreground">arrêtée au {fmtDate(balance.arretee_au)} · écritures validées par le cabinet</span>
              </div>
              <div className="albarka-card overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-muted-foreground border-b">
                    <th className="p-3">Compte</th><th className="p-3">Libellé</th>
                    <th className="p-3 text-right">Débit</th><th className="p-3 text-right">Crédit</th>
                    <th className="p-3 text-right">Solde débiteur</th><th className="p-3 text-right">Solde créditeur</th></tr></thead>
                  <tbody>
                    {lignesBalance.map((r) => (
                      <tr key={r.code} className="border-b last:border-0">
                        <td className="p-3 font-mono">{r.code}</td><td className="p-3">{r.label}</td>
                        <td className="p-3 text-right">{fmtMontant(r.debit)}</td><td className="p-3 text-right">{fmtMontant(r.credit)}</td>
                        <td className="p-3 text-right">{r.debit_balance ? fmtMontant(r.debit_balance) : ""}</td>
                        <td className="p-3 text-right">{r.credit_balance ? fmtMontant(r.credit_balance) : ""}</td>
                      </tr>
                    ))}
                    <tr className="font-semibold bg-muted/40">
                      <td className="p-3" colSpan={2}>Totaux {balance.balanced ? "(balance équilibrée)" : "(balance non équilibrée)"}</td>
                      <td className="p-3 text-right">{fmtMontant(balance.total_debit)}</td><td className="p-3 text-right">{fmtMontant(balance.total_credit)}</td>
                      <td className="p-3" colSpan={2}></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {domaine === "rh" && moisPaie.length > 0 && (
            <section className="space-y-2" data-testid="domaine-paie">
              <h2 className="font-display text-xl">Bulletins de paie</h2>
              {moisPaie.map((m) => (
                <div key={m.period_month} className="albarka-card" data-testid={`paie-mois-${m.period_month}`}>
                  <div className="p-4 flex flex-wrap items-center gap-3">
                    <button type="button" onClick={() => basculerMois(m.period_month)} className="flex-1 min-w-[200px] text-left flex items-center gap-2" aria-expanded={moisOuvert === m.period_month}>
                      <ChevronDown className={`w-4 h-4 transition-transform ${moisOuvert === m.period_month ? "rotate-180" : ""}`} />
                      <span><span className="font-medium capitalize">{libMois(m.period_month)}</span>
                        <span className="block text-xs text-muted-foreground">{m.count} bulletin(s) · net à payer {fmtMontant(m.net_to_pay)} FCFA</span></span>
                    </button>
                    <Button size="sm" variant="outline" onClick={() => ouvrirPdf("/me/paie/bulletins-pdf", { period_month: m.period_month })}><FileText className="w-4 h-4 mr-1" /> Tous (PDF)</Button>
                  </div>
                  {moisOuvert === m.period_month && (
                    <ul className="border-t divide-y">
                      {bulletins.map((b) => (
                        <li key={b.id} className="px-4 py-2.5 flex flex-wrap items-center gap-3 text-sm">
                          <span className="flex-1 min-w-[160px] font-medium">{b.full_name}</span>
                          <span className="text-xs text-muted-foreground">Brut {fmtMontant(b.gross)} · Net {fmtMontant(b.net_to_pay)}</span>
                          <Button size="sm" variant="ghost" onClick={() => ouvrirPdf(`/me/paie/bulletins/${b.id}/pdf`)}><FileText className="w-4 h-4 mr-1" /> Bulletin</Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </section>
          )}
          {domaine === "rh" && declarationsCnss.length > 0 && (
            <section className="space-y-2" data-testid="domaine-cnss">
              <h2 className="font-display text-xl">Déclarations CNSS</h2>
              {declarationsCnss.map((d) => (
                <div key={`${d.annee}-${d.numero}`} className="albarka-card p-4 flex flex-wrap items-center gap-3">
                  <div className="flex-1 min-w-[200px]"><div className="font-medium capitalize">{d.libelle}</div>
                    <div className="text-xs text-muted-foreground">Déclaration {d.periodicite} · feuilles BTN et déclaration</div></div>
                  <Button size="sm" variant="outline" onClick={() => ouvrirPdf("/me/paie/cnss/pdf", { annee: d.annee, numero: d.numero })}><FileText className="w-4 h-4 mr-1" /> Ouvrir (PDF)</Button>
                </div>
              ))}
            </section>
          )}
          {declarations.length > 0 && (
            <section className="space-y-2" data-testid="domaine-declarations">
              <h2 className="font-display text-xl">Déclarations déposées</h2>
              <ListeDocumentsClient items={declarations} apres={charger} testid="domaine-liste-declarations" />
            </section>
          )}
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
