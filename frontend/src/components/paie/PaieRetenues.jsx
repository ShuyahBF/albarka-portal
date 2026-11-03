/*
  Lot 85 — Paie : DÉCLARATION des retenues SND, SFED et CENAMU (onglet « Retenues » de Paie & RH).
  État par rubrique et par période (mois ou trimestre), établi depuis les bulletins VALIDÉS de l'employeur choisi :
  un salarié par ligne (base, calcul, montant retenu) et total de la rubrique. Les agents exonérés d'une rubrique n'y figurent pas.
  Boutons : PDF (ouvert dans un nouvel onglet) et export CSV (Excel). Lecture seule.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { FileSpreadsheet, FileText, TriangleAlert } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { EmployerSelect, fcfa, useEmployers } from "@/components/paie/paieCommon";

const MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
const TRIMESTRES = ["1er trimestre (janv. – mars)", "2e trimestre (avr. – juin)", "3e trimestre (juil. – sept.)", "4e trimestre (oct. – déc.)"];
const BASES = { gross: "du salaire brut", base: "du salaire de base", net: "du salaire net" };
const champ = "h-10 rounded-md border border-input bg-white px-3 text-sm";
const bouton = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";

// Mois précédent : période proposée par défaut
const moisPrecedent = () => { const d = new Date(); return d.getMonth() === 0 ? { annee: d.getFullYear() - 1, numero: 12 } : { annee: d.getFullYear(), numero: d.getMonth() }; };

export default function PaieRetenues() {
  const employers = useEmployers();
  const [eid, setEid] = useState("");
  const [periodicite, setPeriodicite] = useState("mensuelle");
  const [{ annee, numero }, setPeriode] = useState(moisPrecedent());
  const [brouillons, setBrouillons] = useState(false);
  const [rubrique, setRubrique] = useState("");
  const [data, setData] = useState(null);
  const params = { employer_id: eid, annee, numero, periodicite, inclure_brouillons: brouillons, ...(rubrique ? { rubrique } : {}) };

  useEffect(() => {
    if (!eid) { setData(null); return; }
    apiClient.get("/hr/paie/retenues/declaration", { params }).then(({ data: d }) => setData(d)).catch((e) => { setData(null); toast.error(extractError(e)); });
    // eslint-disable-next-line
  }, [eid, annee, numero, periodicite, brouillons, rubrique]);

  // Changement de périodicité : le numéro doit rester dans la liste (1 à 12 ou 1 à 4)
  const changerPeriodicite = (p) => { setPeriodicite(p); setPeriode((x) => ({ ...x, numero: Math.min(x.numero, p === "mensuelle" ? 12 : 4) })); };

  const pdf = async () => {
    const attente = toast.loading("Patientez…");
    try { const { data: f } = await apiClient.get("/hr/paie/retenues/pdf", { params, responseType: "blob" }); window.open(URL.createObjectURL(f), "_blank"); }
    catch (e) { toast.error(extractError(e)); } finally { toast.dismiss(attente); }
  };
  const csv = async () => {
    const attente = toast.loading("Patientez…");
    try {
      const { data: f } = await apiClient.get("/hr/paie/retenues/csv", { params, responseType: "blob" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(f); a.download = `retenues_${annee}_${periodicite}_${numero}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { toast.error(extractError(e)); } finally { toast.dismiss(attente); }
  };

  return (
    <div className="space-y-4" data-testid="paie-retenues">
      <div className="flex flex-wrap items-end gap-3">
        <EmployerSelect value={eid} onChange={setEid} employers={employers} testId="ret-employer" />
        <label className="text-xs text-slate-600">Périodicité<select value={periodicite} onChange={(e) => changerPeriodicite(e.target.value)} className={`${champ} block`} data-testid="ret-periodicite">
          <option value="mensuelle">Mensuelle</option><option value="trimestrielle">Trimestrielle</option></select></label>
        <label className="text-xs text-slate-600">{periodicite === "mensuelle" ? "Mois" : "Trimestre"}
          <select value={numero} onChange={(e) => setPeriode((x) => ({ ...x, numero: Number(e.target.value) }))} className={`${champ} block`} data-testid="ret-numero">
            {(periodicite === "mensuelle" ? MOIS : TRIMESTRES).map((l, i) => <option key={l} value={i + 1}>{l}</option>)}</select></label>
        <label className="text-xs text-slate-600">Année<input type="number" value={annee} onChange={(e) => setPeriode((x) => ({ ...x, annee: Number(e.target.value) || x.annee }))} className={`${champ} block w-24`} /></label>
        <label className="text-xs text-slate-600">Rubrique<select value={rubrique} onChange={(e) => setRubrique(e.target.value)} className={`${champ} block`}>
          <option value="">Toutes</option><option value="snd">SND</option><option value="sfed">SFED</option><option value="cenamu">CENAMU</option></select></label>
        <label className="flex items-center gap-1 pb-2 text-sm text-slate-700"><input type="checkbox" checked={brouillons} onChange={(e) => setBrouillons(e.target.checked)} /> Inclure les brouillons</label>
        <div className="flex gap-2 pb-0.5">
          <button type="button" onClick={pdf} disabled={!eid} className={bouton} data-testid="ret-pdf"><FileText className="h-4 w-4" /> PDF</button>
          <button type="button" onClick={csv} disabled={!eid} className={bouton} data-testid="ret-csv"><FileSpreadsheet className="h-4 w-4" /> Excel (CSV)</button>
        </div>
      </div>
      {!eid && <p className="text-sm text-slate-500">Choisissez l'employeur pour afficher les retenues SND, SFED et CENAMU de la période.</p>}
      {(data?.alertes || []).map((a) => <p key={a} className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />{a}</p>)}
      {data && data.rubriques.map((rub) => (
        <div key={rub.key} className="overflow-auto rounded-xl border border-slate-200 bg-white" data-testid={`ret-rub-${rub.key}`}>
          <p className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-800">{rub.label} — {rub.effectif} salarié(s) · {data.libelle_periode}</p>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-500"><tr><th className="px-3 py-2 text-left">Salarié</th><th className="text-left">Matricule</th><th className="text-left">Calcul</th>
              <th className="text-right">Base</th><th className="px-3 text-right">Montant retenu</th></tr></thead>
            <tbody>
              {rub.lignes.map((l) => (
                <tr key={l.n} className="border-t border-slate-100"><td className="px-3 py-2 font-medium">{l.full_name}</td><td className="text-slate-600">{l.matricule || "—"}</td>
                  <td className="text-slate-600">{l.mode === "percent" ? `${l.valeur} % ${BASES[l.base_calcul] || ""}` : "Valeur fixe"}</td>
                  <td className="text-right tabular-nums">{l.base != null ? fcfa(l.base) : ""}</td><td className="px-3 text-right tabular-nums">{fcfa(l.montant)}</td></tr>
              ))}
              <tr className="border-t-2 bg-slate-50 font-semibold"><td className="px-3 py-2" colSpan={4}>TOTAL {rub.label}</td><td className="px-3 text-right tabular-nums">{fcfa(rub.total)}</td></tr>
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
