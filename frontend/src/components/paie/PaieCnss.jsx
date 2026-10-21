/*
  Lot 68 — Paie : déclarations CNSS. Deux onglets de « Paie & RH » (BTN et DECLARATION) partagent ce composant :
    - BTN   : Bordereau Nominatif des Travailleurs salariés (un salarié par ligne, total, taux 21,5 %, cotisations) ;
    - DECLARATION (feuille « DECL » du classeur) : Déclaration récapitulative des salaires (nombre de travailleurs, décompte par branche 14 % + 1,5 % + 6 %).
  Les deux états sont remplis automatiquement depuis les bulletins de paie VALIDÉS de l'employeur choisi.
  Règle : moins de 20 salariés → déclaration par TRIMESTRE ; 20 salariés et plus → déclaration MENSUELLE.

  Props :
    vue      : "btn" ou "recap" (l'état affiché ; « recap » = onglet DECLARATION) ;
    choix    : { eid, annee, numero, periodicite, brouillons } — choix partagé par les deux onglets (gardé dans AdminHR) ;
    setChoix : mise à jour du choix.
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { FileSpreadsheet, FileText, Printer, Save, TriangleAlert } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { EmployerSelect, fcfa, useEmployers } from "@/components/paie/paieCommon";

const MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
const TRIMESTRES = ["1er trimestre (janv. – mars)", "2e trimestre (avr. – juin)", "3e trimestre (juil. – sept.)", "4e trimestre (oct. – déc.)"];
const SEUIL = 20;                      // à partir de 20 salariés : déclaration mensuelle

// Période à proposer par défaut : le mois ou le trimestre qui vient de se terminer
export function periodeParDefaut(mode) {
  const d = new Date();
  const mois = d.getMonth();           // 0 à 11
  if (mode === "mensuelle") {
    const m = mois === 0 ? 12 : mois;
    return { annee: mois === 0 ? d.getFullYear() - 1 : d.getFullYear(), numero: m };
  }
  const t = Math.floor(mois / 3);      // trimestre en cours (0 à 3)
  return t === 0 ? { annee: d.getFullYear() - 1, numero: 4 } : { annee: d.getFullYear(), numero: t };
}

export const CHOIX_CNSS_INITIAL = { eid: "", annee: periodeParDefaut("trimestrielle").annee, numero: periodeParDefaut("trimestrielle").numero, periodicite: "auto", brouillons: false };

const dateFr = (iso) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");
const tauxFr = (t) => String(t).replace(".", ",");
const bouton = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";
const champ = "h-10 rounded-md border border-input bg-white px-3 text-sm";

// Ouvre un PDF dans un nouvel onglet (toast « Patientez… » pendant le calcul, règle du propriétaire)
async function ouvrirPdf(url, params) {
  const attente = toast.loading("Patientez…");
  try {
    const { data } = await apiClient.get(url, { params, responseType: "blob" });
    window.open(URL.createObjectURL(data), "_blank");
  } catch (e) { toast.error(extractError(e)); } finally { toast.dismiss(attente); }
}

// Télécharge le classeur Excel (feuilles BTN et DECLARATION)
async function telechargerExcel(params) {
  const attente = toast.loading("Patientez…");
  try {
    const { data, headers } = await apiClient.get("/hr/paie/cnss/excel", { params, responseType: "blob" });
    const nom = /filename="([^"]+)"/.exec(headers?.["content-disposition"] || "")?.[1] || "declaration_cnss.xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(data); a.download = nom; document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { toast.error(extractError(e)); } finally { toast.dismiss(attente); }
}

export default function PaieCnss({ vue, choix, setChoix }) {
  const employers = useEmployers();
  const [data, setData] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [declarant, setDeclarant] = useState({ nom: "", ville: "" });
  const [enregistrement, setEnregistrement] = useState(false);

  // Périodicité appliquée : celle imposée, sinon selon l'effectif de l'employeur (liste des employeurs déjà chargée)
  const employeur = employers.find((e) => e.employer_id === choix.eid);
  const mode = choix.periodicite !== "auto" ? choix.periodicite : ((employeur?.employees_count || 0) >= SEUIL ? "mensuelle" : "trimestrielle");
  const maj = (patch) => setChoix((c) => ({ ...c, ...patch }));

  // Quand la périodicité change (employeur ou choix), le numéro doit rester dans la liste (1 à 4 ou 1 à 12)
  useEffect(() => {
    const max = mode === "mensuelle" ? 12 : 4;
    if (choix.numero > max) maj(periodeParDefaut(mode));
    // eslint-disable-next-line
  }, [mode]);

  const params = useMemo(() => ({
    employer_id: choix.eid, annee: choix.annee, numero: choix.numero, periodicite: choix.periodicite, inclure_brouillons: choix.brouillons,
  }), [choix]);

  // Chargement de la déclaration à chaque changement de choix
  useEffect(() => {
    if (!choix.eid || !choix.annee) { setData(null); return; }
    let actif = true;
    setChargement(true);
    apiClient.get("/hr/paie/cnss/declaration", { params }).then(({ data: d }) => {
      if (!actif) return;
      setData(d); setDeclarant({ nom: d.declarant || "", ville: d.ville || "" });
    }).catch((e) => { if (actif) { setData(null); toast.error(extractError(e)); } }).finally(() => { if (actif) setChargement(false); });
    return () => { actif = false; };
  }, [params, choix.eid, choix.annee]);

  const enregistrerDeclarant = async () => {
    setEnregistrement(true);
    try {
      await apiClient.put(`/hr/paie/cnss/${encodeURIComponent(choix.eid)}/declarant`, declarant);
      toast.success("Nom du déclarant et ville enregistrés");
    } catch (e) { toast.error(extractError(e)); } finally { setEnregistrement(false); }
  };

  const e = data?.employer;
  return (
    <div className="space-y-4" data-testid={`paie-cnss-${vue}`}>
      {/* Choix de l'employeur et de la période */}
      <div className="flex flex-wrap items-end gap-3">
        <EmployerSelect value={choix.eid} onChange={(eid) => maj({ eid })} employers={employers} testId={`cnss-${vue}-employer`} />
        <label className="text-xs text-slate-500">Année
          <input type="number" min="2000" max="2100" value={choix.annee} onChange={(ev) => maj({ annee: Number(ev.target.value) })}
                 className={`${champ} w-24 block`} data-testid={`cnss-${vue}-annee`} />
        </label>
        <label className="text-xs text-slate-500">Périodicité
          <select value={choix.periodicite} onChange={(ev) => maj({ periodicite: ev.target.value })} className={`${champ} block`} data-testid={`cnss-${vue}-periodicite`}>
            <option value="auto">Automatique (selon l'effectif)</option>
            <option value="mensuelle">Mensuelle</option>
            <option value="trimestrielle">Trimestrielle</option>
          </select>
        </label>
        <label className="text-xs text-slate-500">{mode === "mensuelle" ? "Mois" : "Trimestre"}
          <select value={choix.numero} onChange={(ev) => maj({ numero: Number(ev.target.value) })} className={`${champ} block`} data-testid={`cnss-${vue}-numero`}>
            {(mode === "mensuelle" ? MOIS : TRIMESTRES).map((l, i) => <option key={l} value={i + 1}>{l}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm pb-2">
          <input type="checkbox" checked={choix.brouillons} onChange={(ev) => maj({ brouillons: ev.target.checked })} data-testid={`cnss-${vue}-brouillons`} />
          Inclure les brouillons
        </label>
      </div>

      {!choix.eid && <p className="text-sm text-slate-500">Choisissez l'employeur : la déclaration se remplit toute seule à partir de ses bulletins validés.</p>}
      {chargement && <p className="text-sm text-slate-500">Patientez…</p>}

      {data && (
        <>
          <p className="text-sm text-slate-600" data-testid={`cnss-${vue}-regle`}>
            {data.effectif} salarié(s) enregistré(s) : {data.periodicite_auto === "mensuelle" ? `${data.seuil} et plus → déclaration mensuelle` : `moins de ${data.seuil} → déclaration trimestrielle`}
            {data.periodicite !== data.periodicite_auto && <> (périodicité {data.periodicite} choisie à la main)</>}.
            {" "}Période : <b>{data.libelle_periode}</b> ({dateFr(data.debut)} au {dateFr(data.fin)}).
          </p>

          {data.alertes.length > 0 && (
            <ul className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 space-y-1" data-testid={`cnss-${vue}-alertes`}>
              {data.alertes.map((a) => <li key={a} className="flex gap-2"><TriangleAlert className="h-4 w-4 shrink-0 mt-0.5" />{a}</li>)}
            </ul>
          )}

          {/* Impression et export */}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={bouton} onClick={() => ouvrirPdf(`/hr/paie/cnss/${vue}/pdf`, params)} data-testid={`cnss-${vue}-pdf`}>
              <Printer className="h-4 w-4" /> Imprimer {vue === "btn" ? "le BTN" : "la DECLARATION"} (PDF)</button>
            <button type="button" className={bouton} onClick={() => ouvrirPdf("/hr/paie/cnss/pdf", params)} data-testid={`cnss-${vue}-pdf-complet`}>
              <FileText className="h-4 w-4" /> BTN + DECLARATION (PDF)</button>
            <button type="button" className={bouton} onClick={() => telechargerExcel(params)} data-testid={`cnss-${vue}-excel`}>
              <FileSpreadsheet className="h-4 w-4" /> Excel (BTN et DECLARATION)</button>
          </div>

          {/* Nom du déclarant et ville imprimés en bas des états (mémorisés par employeur) */}
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-slate-500">Nom et prénoms du déclarant
              <input value={declarant.nom} maxLength={120} onChange={(ev) => setDeclarant({ ...declarant, nom: ev.target.value })}
                     className={`${champ} block w-64`} data-testid={`cnss-${vue}-declarant`} />
            </label>
            <label className="text-xs text-slate-500">Ville
              <input value={declarant.ville} maxLength={80} onChange={(ev) => setDeclarant({ ...declarant, ville: ev.target.value })}
                     className={`${champ} block w-44`} data-testid={`cnss-${vue}-ville`} />
            </label>
            <button type="button" className={bouton} onClick={enregistrerDeclarant} disabled={enregistrement} data-testid={`cnss-${vue}-declarant-enregistrer`}>
              <Save className="h-4 w-4" /> Enregistrer</button>
          </div>

          {vue === "btn" ? <ApercuBtn d={data} e={e} /> : <ApercuRecap d={data} e={e} />}
        </>
      )}
    </div>
  );
}

// Aperçu du BTN : en-tête (période, société, n° CNSS) puis un salarié par ligne
function ApercuBtn({ d, e }) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-slate-300 bg-white p-3 grid gap-3 md:grid-cols-[1fr_2fr_1fr] text-sm" data-testid="btn-entete">
        <div><p className="font-semibold">Période de déclaration</p><p>du {dateFr(d.debut)}</p><p>au {dateFr(d.fin)}</p></div>
        <div className="text-center">
          <p className="font-semibold">Bordereau Nominatif des Travailleurs Salariés</p>
          <p className="font-semibold text-[#0F6B4A]">{(e.name || "").toUpperCase()}</p>
          <p>{[e.address, e.bp ? `BP ${e.bp}` : ""].filter(Boolean).join(" — ")}</p>
          {e.phone && <p>TEL: {e.phone}</p>}
        </div>
        <div className="md:text-right"><p className="font-semibold">NUMERO :</p><p>{e.cnss_number || "—"}</p></div>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-auto">
        <table className="w-full text-xs sm:text-sm" data-testid="btn-table">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr><th className="px-1 sm:px-2 py-2 text-left w-10">N°</th><th className="text-left px-1 sm:px-2">Nom &amp; prénoms</th><th className="text-left px-1 sm:px-2">N° CNSS<span className="hidden sm:inline"> d'immatriculation</span></th>
              <th className="text-right px-1 sm:px-2">Rémunérations<span className="hidden sm:inline"> soumises à cotisations</span></th><th className="text-center px-1 sm:px-2 hidden sm:table-cell">Période</th><th className="text-center px-1 sm:px-2 hidden sm:table-cell">Observations</th></tr>
          </thead>
          <tbody>
            {d.lignes.map((l) => (
              <tr key={l.n} className="border-t border-slate-100">
                <td className="px-1 sm:px-3 py-1.5">{l.n}</td><td className="px-1 sm:px-2 font-medium">{l.full_name}</td>
                <td className="px-1 sm:px-2">{l.cnss_number}</td><td className="text-right tabular-nums px-1 sm:px-2">{fcfa(l.remuneration)}</td>
                <td className="text-center px-1 sm:px-2 whitespace-nowrap hidden sm:table-cell">{dateFr(l.du)} au {dateFr(l.au)}</td><td className="text-center px-1 sm:px-2 hidden sm:table-cell">{l.observation}</td>
              </tr>
            ))}
            {!d.lignes.length && <tr><td colSpan={6} className="px-1 sm:px-3 py-6 text-center text-slate-500">Aucun salarié sur cette période.</td></tr>}
            <tr className="border-t-2 font-semibold bg-slate-50"><td colSpan={3} className="px-1 sm:px-3 py-2 text-right">TOTAL :</td><td className="text-right tabular-nums px-1 sm:px-2">{fcfa(d.total_remuneration)}</td><td colSpan={2} /></tr>
            <tr className="font-semibold bg-slate-50"><td colSpan={3} className="px-1 sm:px-3 py-1 text-right">TAUX :</td><td className="text-right px-1 sm:px-2">{tauxFr(d.taux_total)} %</td><td colSpan={2} /></tr>
            <tr className="font-semibold bg-slate-50"><td colSpan={3} className="px-1 sm:px-3 py-1 text-right">COTISATIONS :</td><td className="text-right tabular-nums px-1 sm:px-2">{fcfa(d.cotisations)}</td><td colSpan={2} /></tr>
          </tbody>
        </table>
      </div>
      <p className="text-sm text-slate-600">Certifié exact le {dateFr(d.date_certification)} — à {d.ville}{d.declarant ? ` — ${d.declarant}` : ""}</p>
    </div>
  );
}

// Aperçu de la DECLARATION : nombre de travailleurs et décompte des cotisations par branche
function ApercuRecap({ d, e }) {
  const N = d.travailleurs;
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-slate-300 bg-white p-3 text-sm space-y-1" data-testid="recap-entete">
        <p className="font-semibold">DÉCLARATION RÉCAPITULATIVE DES SALAIRES</p>
        <p>Période : du {dateFr(d.debut)} au {dateFr(d.fin)} — <b>{(e.name || "").toUpperCase()}</b> — Matricule de l'employeur : <b>{e.cnss_number || "—"}</b></p>
        <p>Nombre de travailleurs salariés : permanents <b>{N.permanents}</b> · temporaires <b>{N.temporaires}</b> · journaliers <b>{N.journaliers}</b> · apprentis <b>{N.apprentis}</b></p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-auto">
        <table className="w-full text-sm" data-testid="recap-table">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr><th className="px-3 py-2 text-left">Branche</th><th className="text-right px-2">Total rémunérations soumises à cotisations</th><th className="text-right px-2">Taux</th><th className="text-right px-2">Cotisations dues</th></tr>
          </thead>
          <tbody>
            {d.branches.map((b) => (
              <tr key={b.libelle} className="border-t border-slate-100">
                <td className="px-3 py-1.5 font-medium">{b.libelle}</td><td className="text-right tabular-nums px-2">{fcfa(b.remuneration)}</td>
                <td className="text-right px-2">{tauxFr(b.taux)} %</td><td className="text-right tabular-nums px-2">{fcfa(b.cotisation)}</td>
              </tr>
            ))}
            <tr className="border-t-2 font-semibold bg-slate-50"><td className="px-3 py-2" colSpan={2}>TOTAL COTISATIONS</td><td className="text-right px-2">{tauxFr(d.taux_total)} %</td><td className="text-right tabular-nums px-2">{fcfa(d.cotisations)}</td></tr>
          </tbody>
        </table>
      </div>
      <p className="text-sm text-slate-600">Certifié exact le {dateFr(d.date_certification)}{d.declarant ? ` — ${d.declarant}` : ""}</p>
    </div>
  );
}
