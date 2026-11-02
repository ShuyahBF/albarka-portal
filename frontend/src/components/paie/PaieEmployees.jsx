/*
  PaieEmployees — lot 8 : onglet « Salariés ».

  Pour l'employeur choisi (personnel du cabinet ou un client) :
    - liste des salariés, avec brut et net calculés ;
    - fiche paie (création / modification) : identité, matricule, n° CNSS,
      catégorie (si l'abattement dépend de la catégorie), charges de famille,
      date d'embauche (prime d'ancienneté), indemnités (rubriques du modèle) et
      « non exonérée » par indemnité, mode « brut → net » ou « net négocié → brut » ;
    - calcul en direct avec les paramètres de l'employeur ;
    - lot 26 : avantage en nature mensuel (logement, véhicule… : dans le brut
      et l'IUTS, hors CNSS, retiré du net car non versé en argent) ; libellé
      « FSP » (Prélèvement pour effort de paix) au lieu de « Soutien patriotique » ;
    - lot 84 : case « Exonéré de la cotisation CNSS » (le bulletin n'applique alors aucune CNSS, part salariale comme patronale) ;
      rubriques de retenue SND, SFED et CENAMU : en pourcentage du brut, du salaire de base ou du net, ou en valeur fixe
      (laisser vide = réglage du modèle de l'employeur, onglet Paramètres).
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { EmployerSelect, useEmployers, fcfa, GREEN } from "@/components/paie/paieCommon";

const empty = { full_name: "", role: "", matricule: "", cnss_number: "", category: "", grade: "", echelon: "", dependents: 0, hire_date: "",
  pay_mode: "gross", base_salary: "", net_target: "", allowances: {}, non_exempt: [], in_kind: "", cnss_exempt: false, special_deductions: {}, email: "", phone: "" };
const inp = "mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm";
// Lot 84 : libellés des listes finies des rubriques SND / SFED / CENAMU (règle : liste finie = liste déroulante)
const MODES_RUBRIQUE = [["percent", "% du…"], ["amount", "Valeur (FCFA)"]];
const BASES_RUBRIQUE = [["gross", "salaire brut"], ["base", "salaire de base"], ["net", "salaire net"]];
// Réglage du modèle de l'employeur affiché en indication (« 1 % du salaire brut » ou « 2 000 FCFA »)
const texteReglage = (r) => (!Number(r.value) ? "non réglée" : r.mode === "amount" ? `${fcfa(r.value)} FCFA` : `${r.value} % du ${(BASES_RUBRIQUE.find(([k]) => k === r.base) || ["", "brut"])[1]}`);

function EmployeeDialog({ employerId, params, officine, initial, onClose, onSaved }) {
  const [f, setF] = useState({ ...empty, ...initial, hire_date: initial?.hire_date || "", allowances: initial?.allowances || {}, special_deductions: initial?.special_deductions || {} });
  const [calc, setCalc] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (patch) => setF((x) => ({ ...x, ...patch }));
  const cats = params?.flat_abatement?.mode === "by_category" ? params.flat_abatement.categories : [];
  // Lot 84 : modifie une rubrique SND / SFED / CENAMU de CETTE fiche (le mode, la base et la valeur se règlent ensemble)
  const setRubrique = (key, patch) => setF((x) => ({ ...x, special_deductions: { ...x.special_deductions, [key]: { ...(x.special_deductions[key] || {}), ...patch } } }));
  // Corps envoyé au serveur : seules les rubriques dont une valeur est saisie (vide = le modèle de l'employeur s'applique)
  const rubriquesEnvoyees = () => Object.fromEntries(Object.entries(f.special_deductions || {})
    .filter(([, v]) => v && v.value !== "" && v.value != null).map(([k, v]) => [k, { mode: v.mode || "percent", base: v.base || "gross", value: Number(v.value) || 0 }]));

  // Calcul en direct (paramètres de l'employeur)
  useEffect(() => {
    const t = setTimeout(() => {
      apiClient.post("/hr/paie/simulate", { employer_id: employerId, period_month: new Date().toISOString().slice(0, 7),
        employee: { ...f, base_salary: Number(f.base_salary) || 0, net_target: Number(f.net_target) || null, in_kind: Number(f.in_kind) || 0, special_deductions: rubriquesEnvoyees() } })
        .then(({ data }) => setCalc(data)).catch(() => setCalc(null));
    }, 350);
    return () => clearTimeout(t);
  }, [f, employerId]);

  const save = async () => {
    if (!f.full_name.trim()) { toast.error("Nom du salarié requis"); return; }
    setBusy(true);
    const body = { ...f, tenant_id: employerId, base_salary: Number(f.base_salary) || 0, net_target: f.pay_mode === "net" ? Number(f.net_target) || null : null,
      dependents: Number(f.dependents) || 0, hire_date: f.hire_date || null, category: f.category || null, in_kind: Number(f.in_kind) || 0,
      cnss_exempt: !!f.cnss_exempt, special_deductions: rubriquesEnvoyees() };
    try {
      if (initial?.id) await apiClient.put(`/hr/paie/employees/${initial.id}`, body);
      else await apiClient.post("/hr/paie/employees", body);
      toast.success("Fiche paie enregistrée"); onSaved();
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-4xl max-h-[92vh] overflow-auto rounded-2xl bg-white p-5 shadow-2xl space-y-4" data-testid="paie-employee-dialog">
        <div className="flex items-start justify-between">
          <h3 className="font-display text-xl">{initial?.id ? "Fiche paie du salarié" : "Nouveau salarié"}</h3>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-slate-100" aria-label="Fermer"><X className="h-5 w-5" /></button>
        </div>
        <div className="grid lg:grid-cols-[1fr_280px] gap-4">
          <div className="space-y-3 text-xs text-slate-600">
            <div className="grid sm:grid-cols-3 gap-3">
              <label className="sm:col-span-2">Nom et prénoms<input value={f.full_name} onChange={(e) => set({ full_name: e.target.value })} className={inp} data-testid="emp-name" /></label>
              <label>Fonction<input value={f.role || ""} onChange={(e) => set({ role: e.target.value })} className={inp} /></label>
              <label>Matricule<input value={f.matricule || ""} onChange={(e) => set({ matricule: e.target.value })} className={inp} /></label>
              <label>N° CNSS<input value={f.cnss_number || ""} onChange={(e) => set({ cnss_number: e.target.value })} className={inp} /></label>
              <label>Date d'embauche<input type="date" value={f.hire_date || ""} onChange={(e) => set({ hire_date: e.target.value })} className={inp} data-testid="emp-hire" /></label>
              <label>Charges de famille<input type="number" min="0" value={f.dependents} onChange={(e) => set({ dependents: e.target.value })} className={inp} data-testid="emp-dependents" /></label>
              {/* Lot 27.7 : classement professionnel affiché sur le bulletin */}
              <label>Catégorie professionnelle<input value={f.grade || ""} placeholder="ex. 5 ou C3" onChange={(e) => set({ grade: e.target.value })} className={inp} data-testid="emp-grade" /></label>
              <label>Échelon<input value={f.echelon || ""} placeholder="ex. B ou 2" onChange={(e) => set({ echelon: e.target.value })} className={inp} data-testid="emp-echelon" /></label>
              {cats.length > 0 && (
                <label>Statut (cadre / non cadre)<select value={f.category || ""} onChange={(e) => set({ category: e.target.value })} className={inp} data-testid="emp-category">
                  <option value="">—</option>{cats.map((c) => <option key={c.key} value={c.key}>{c.label} ({c.rate} %)</option>)}</select></label>
              )}
            </div>
            {/* Mode de calcul */}
            <div className="rounded-lg bg-slate-50 p-3 space-y-2">
              <div className="flex flex-wrap gap-4 text-sm text-slate-700">
                <label className="flex items-center gap-1"><input type="radio" checked={f.pay_mode === "gross"} onChange={() => set({ pay_mode: "gross" })} data-testid="emp-mode-gross" /> Brut → net (salaire de base saisi)</label>
                <label className="flex items-center gap-1"><input type="radio" checked={f.pay_mode === "net"} onChange={() => set({ pay_mode: "net" })} data-testid="emp-mode-net" /> Net négocié → brut</label>
              </div>
              {f.pay_mode === "gross" ? (
                <label className="block max-w-xs">Salaire de base<input type="number" value={f.base_salary} onChange={(e) => set({ base_salary: e.target.value })} className={inp} data-testid="emp-base" /></label>
              ) : (
                <label className="block max-w-xs">Salaire net négocié (avant FSP)
                  <input type="number" value={f.net_target || ""} onChange={(e) => set({ net_target: e.target.value })} className={inp} data-testid="emp-net-target" /></label>
              )}
            </div>
            {/* Indemnités du modèle */}
            <div>
              <p className="font-semibold text-slate-700 mb-1">Indemnités mensuelles</p>
              <div className="grid sm:grid-cols-2 gap-2">
                {(params?.allowances || []).filter((a) => a.sector !== "officine" || officine || Number(f.allowances[a.key]) > 0).map((a) => (
                  <div key={a.key} className="flex items-end gap-2">
                    <label className="flex-1">{a.label}
                      <input type="number" value={f.allowances[a.key] || ""} data-testid={`emp-allow-${a.key}`}
                        onChange={(e) => set({ allowances: { ...f.allowances, [a.key]: Number(e.target.value) || 0 } })} className={inp} /></label>
                    {a.exemption && (
                      <label className="flex items-center gap-1 pb-2 whitespace-nowrap" title="Ne pas appliquer l'exonération à ce salarié">
                        <input type="checkbox" checked={f.non_exempt.includes(a.key)}
                          onChange={(e) => set({ non_exempt: e.target.checked ? [...f.non_exempt, a.key] : f.non_exempt.filter((k) => k !== a.key) })} />
                        non exonérée</label>
                    )}
                  </div>
                ))}
              </div>
              {/* Lot 26 : avantage en nature (non versé en argent) */}
              <label className="mt-2 block max-w-xs" title="Imposable à l'IUTS, hors base CNSS, retiré du salaire net">
                {params?.in_kind?.label || "Avantage en nature"} (valeur mensuelle)
                <input type="number" min="0" value={f.in_kind || ""} onChange={(e) => set({ in_kind: e.target.value })} className={inp} data-testid="emp-in-kind" /></label>
              {/* Lot 84 : exonération de la cotisation CNSS (prise en compte immédiate dans le calcul des bulletins) */}
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-slate-700" data-testid="emp-cnss-exempt-label">
                <input type="checkbox" className="mt-0.5" checked={!!f.cnss_exempt} onChange={(e) => set({ cnss_exempt: e.target.checked })} data-testid="emp-cnss-exempt" />
                <span><b>Exonéré de la cotisation CNSS</b><br /><span className="text-slate-500">Aucune CNSS n'est retenue sur ses bulletins ni comptée à la charge de l'employeur
                  (il n'apparaît plus dans la déclaration CNSS). La taxe patronale reste due.</span></span>
              </label>
              {/* Lot 84 : rubriques de retenue SND / SFED / CENAMU (pourcentage du brut, de la base ou du net, ou valeur) */}
              {(params?.special_deductions || []).length > 0 && (
                <div className="mt-3" data-testid="emp-rubriques">
                  <p className="font-semibold text-slate-700 mb-1">Retenues {(params.special_deductions).map((r) => r.label).join(" / ")}</p>
                  <div className="space-y-2">
                    {params.special_deductions.map((r) => {
                      const v = f.special_deductions[r.key] || {};
                      const mode = v.mode || r.mode;
                      return (
                        <div key={r.key} className="grid grid-cols-[5rem_1fr_1fr_1fr] items-end gap-2" data-testid={`emp-rub-${r.key}`}>
                          <span className="pb-2 font-medium text-slate-700" title={`Réglage du modèle : ${texteReglage(r)}`}>{r.label}</span>
                          <label>Mode<select value={mode} onChange={(e) => setRubrique(r.key, { mode: e.target.value })} className={inp}>
                            {MODES_RUBRIQUE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
                          <label>{mode === "percent" ? "Base" : " "}
                            {mode === "percent" ? (
                              <select value={v.base || r.base} onChange={(e) => setRubrique(r.key, { base: e.target.value })} className={inp}>
                                {BASES_RUBRIQUE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
                            ) : <span className="mt-1 block h-9" />}</label>
                          <label>{mode === "percent" ? "Taux (%)" : "Valeur"}
                            <input type="number" min="0" step="any" value={v.value ?? ""} placeholder={texteReglage(r)}
                              onChange={(e) => setRubrique(r.key, { value: e.target.value, mode, base: v.base || r.base })} className={inp} data-testid={`emp-rub-${r.key}-valeur`} /></label>
                        </div>
                      );
                    })}
                  </div>
                  <p className="mt-1 text-slate-500">Champ vide : le réglage du modèle de l'employeur s'applique (indiqué en grisé).</p>
                </div>
              )}
              {/* Indemnités qui ne sont plus dans le modèle : visibles et supprimables */}
              {Object.keys(f.allowances || {}).filter((k) => !(params?.allowances || []).some((a) => a.key === k)).map((k) => (
                <div key={k} className="mt-2 flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-800">
                  <span className="flex-1">Indemnité retirée du modèle (« {k} ») : {fcfa(f.allowances[k])}</span>
                  <button type="button" title="Retirer de la fiche" className="p-1 rounded hover:bg-amber-100"
                    onClick={() => { const a = { ...f.allowances }; delete a[k]; set({ allowances: a, non_exempt: f.non_exempt.filter((x) => x !== k) }); }}>
                    <Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          </div>
          {/* Calcul en direct */}
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3 text-xs self-start" data-testid="emp-calc">
            <p className="font-semibold text-emerald-900 mb-1">Calcul du mois en cours</p>
            {calc ? (
              <table className="w-full"><tbody>
                {[["Salaire de base", calc.base_salary], [`Ancienneté (${calc.years_of_service} an(s), ${calc.seniority_rate} %)`, calc.seniority],
                  ["Salaire brut", calc.gross, true], [calc.cnss_exempt ? "CNSS (exonéré)" : "CNSS", calc.cnss], ["Base IUTS", calc.iuts_base], ["IUTS net", calc.iuts], ["Salaire net", calc.net, true],
                  ["FSP (effort de paix)", calc.patriotic_support],
                  ...(calc.special_deductions || []).map((r) => [r.label, r.amount]),
                  ["Net à payer", calc.net_to_pay, true], ["Masse salariale", calc.employer_cost]].map(([l, v, b]) => (
                  <tr key={l} className={b ? "font-semibold" : ""}><td className="py-0.5 text-slate-600">{l}</td><td className="text-right tabular-nums">{fcfa(v)}</td></tr>
                ))}
              </tbody></table>
            ) : <p className="text-slate-500">Saisissez le salaire…</p>}
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">Annuler</button>
          <button type="button" onClick={save} disabled={busy} className="rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" style={{ background: GREEN }} data-testid="emp-save">Enregistrer</button>
        </div>
      </div>
    </div>
  );
}

export default function PaieEmployees() {
  const [reload, setReload] = useState(0);
  const employers = useEmployers(reload);
  const [eid, setEid] = useState("");
  const [list, setList] = useState([]);
  const [params, setParams] = useState(null);
  const [officine, setOfficine] = useState(false);   // lot 27.7 : employeur officine → primes hivernale et para
  const [dialog, setDialog] = useState(null);     // null | {} (nouveau) | salarié

  const load = async () => {
    if (!eid) { setList([]); return; }
    const [{ data: e }, { data: c }] = await Promise.all([apiClient.get("/hr/paie/employees", { params: { employer_id: eid } }), apiClient.get(`/hr/paie/employeurs/${eid}`)]);
    setList(e.items || []); setParams(c.params); setOfficine(!!c.officine);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load().catch((err) => toast.error(extractError(err))); }, [eid]);

  const remove = async (e) => {
    if (!window.confirm(`Supprimer ${e.full_name} ?`)) return;
    try { await apiClient.delete(`/hr/paie/employees/${e.id}`); load(); setReload((k) => k + 1); } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-3" data-testid="paie-employees">
      <div className="flex flex-wrap items-center gap-3">
        <EmployerSelect value={eid} onChange={setEid} employers={employers} />
        {eid && <button type="button" onClick={() => setDialog({})} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-white" style={{ background: GREEN }} data-testid="emp-new">
          <Plus className="h-4 w-4" /> Nouveau salarié</button>}
      </div>
      {eid && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Nom</th><th className="text-left">Fonction</th><th className="text-left">Catégorie / échelon</th><th className="text-right">Charges</th>
                <th className="text-left">Embauche</th><th className="text-right">Salaire de base / net négocié</th><th className="px-3" /></tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{e.full_name}</td>
                  <td className="text-slate-600">{e.role || "—"}</td>
                  <td className="text-slate-600">{[e.grade, e.echelon].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="text-right">{e.dependents || 0}</td>
                  <td className="text-slate-600">{e.hire_date ? new Date(e.hire_date).toLocaleDateString("fr-FR") : "—"}</td>
                  <td className="text-right tabular-nums">{e.pay_mode === "net" ? <>net {fcfa(e.net_target)}</> : fcfa(e.base_salary)}</td>
                  <td className="px-3 text-right whitespace-nowrap">
                    <button type="button" onClick={() => setDialog(e)} className="p-1.5 rounded hover:bg-slate-100" title="Modifier" data-testid={`emp-edit-${e.id}`}><Pencil className="h-4 w-4" /></button>
                    <button type="button" onClick={() => remove(e)} className="p-1.5 rounded hover:bg-rose-50 text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>
              ))}
              {!list.length && <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-500">Aucun salarié pour cet employeur.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {dialog && <EmployeeDialog employerId={eid} params={params} officine={officine} initial={dialog.id ? dialog : null}
        onClose={() => setDialog(null)} onSaved={() => { setDialog(null); load(); setReload((k) => k + 1); }} />}
    </div>
  );
}
