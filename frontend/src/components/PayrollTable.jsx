/*
  PayrollTable — onglet « Tableau de paie » de Paie & RH (lot 7).

  « Fiche de renseignement — liste actualisée du personnel permanent » d'un
  client pour un mois, saisie en grille :
    N° | Nom / prénoms | Salaire de base | Ancienneté | Indemnités (fonction,
    logement, transport, responsabilité) | Salaire brut (calculé) | Salaire net
  - un mois jamais saisi repart du mois précédent, sinon des employés du client ;
  - ajouter / retirer / monter / descendre une ligne ;
  - sorties : PDF (tableau + questionnaire RH facultatif, papier à en-tête,
    QR code) et fichier Excel (CSV).
  API : GET/PUT /hr/payroll/table, GET /hr/payroll/table/pdf, GET /hr/payroll/table/csv
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Save, FileText, FileSpreadsheet, Trash2, ArrowUp, ArrowDown, Table2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { openServerFile } from "@/lib/docfiles";
import EntitySelect from "@/components/EntitySelect";
import { ui, cx } from "@/components/forms-core/ui";

// Colonnes chiffrées saisies (dans l'ordre du document du cabinet)
const COLS = [
  ["base_salary", "Salaire de base"], ["seniority", "Ancienneté"], ["allowance_function", "Indem. fonction"],
  ["allowance_housing", "Indem. logement"], ["allowance_transport", "Indem. transport"], ["allowance_responsibility", "Indem. responsabilité"],
];
const thisMonth = () => new Date().toISOString().slice(0, 7);
const fmt = (v) => (Number(v) ? Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 0 }) : "");
const num = (v) => Number(String(v ?? "").replace(/\s/g, "").replace(",", ".")) || 0;
// Salaire brut = base + ancienneté + indemnités
const grossOf = (r) => COLS.reduce((s, [k]) => s + num(r[k]), 0);
const SOURCES = { previous_month: "repris du mois précédent", employees: "repris de la liste des employés", saved: "enregistré", empty: "nouveau" };

export default function PayrollTable() {
  const [tenantId, setTenantId] = useState("");
  const [month, setMonth] = useState(thisMonth());
  const [table, setTable] = useState(null);
  const [rows, setRows] = useState([]);
  const [legalForm, setLegalForm] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [questionnaire, setQuestionnaire] = useState(true);
  const [letterheads, setLetterheads] = useState([]);
  const [letterheadId, setLetterheadId] = useState("");

  useEffect(() => { apiClient.get("/admin/letterheads").then(({ data }) => setLetterheads(data)).catch(() => {}); }, []);

  // Chargement du tableau du client pour le mois choisi
  useEffect(() => {
    if (!tenantId || !month) return;
    setLoading(true);
    apiClient.get("/hr/payroll/table", { params: { tenant_id: tenantId, period_month: month } })
      .then(({ data }) => {
        setTable(data); setLegalForm(data.legal_form || ""); setDirty(false);
        setRows(data.rows.map((r) => ({ ...r, net: r.net ?? "" })));
      })
      .catch((e) => toast.error(extractError(e)))
      .finally(() => setLoading(false));
  }, [tenantId, month]);

  const totals = useMemo(() => {
    const t = Object.fromEntries(COLS.map(([k]) => [k, rows.reduce((s, r) => s + num(r[k]), 0)]));
    t.gross = rows.reduce((s, r) => s + grossOf(r), 0);
    t.net = rows.reduce((s, r) => s + num(r.net), 0);
    return t;
  }, [rows]);

  const setCell = (i, key, value) => { setRows(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r))); setDirty(true); };
  const addRow = () => { setRows([...rows, { full_name: "", ...Object.fromEntries(COLS.map(([k]) => [k, ""])), net: "" }]); setDirty(true); };
  const removeRow = (i) => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); };
  const move = (i, d) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const copy = [...rows]; [copy[i], copy[j]] = [copy[j], copy[i]]; setRows(copy); setDirty(true);
  };

  // Enregistrement du mois (remplace les lignes existantes)
  const save = async () => {
    if (rows.some((r) => !String(r.full_name || "").trim())) { toast.error("Chaque ligne doit avoir un nom"); return; }
    setSaving(true);
    try {
      const body = { tenant_id: tenantId, period_month: month, legal_form: legalForm,
        rows: rows.map((r) => ({ employee_id: r.employee_id || null, full_name: String(r.full_name).trim(),
          ...Object.fromEntries(COLS.map(([k]) => [k, num(r[k])])), net: r.net === "" || r.net === null ? null : num(r.net) })) };
      const { data } = await apiClient.put("/hr/payroll/table", body);
      setTable(data); setDirty(false);
      toast.success("Tableau enregistré");
    } catch (e) { toast.error(extractError(e)); } finally { setSaving(false); }
  };

  // PDF / Excel : on enregistre d'abord si des modifications sont en attente
  const exportFile = async (kind) => {
    if (dirty) { await save(); }
    const params = { tenant_id: tenantId, period_month: month };
    if (kind === "pdf") openServerFile("/hr/payroll/table/pdf", { params: { ...params, questionnaire, ...(letterheadId ? { letterhead_id: letterheadId } : {}) } });
    else openServerFile("/hr/payroll/table/csv", { params, download: true, filename: `liste-personnel-${month}.csv`, type: "text/csv" });
  };

  const cellInput = "w-full min-w-[96px] rounded border border-slate-200 bg-white px-1.5 py-1 text-right text-sm tabular-nums focus:outline-none focus:border-primary";

  return (
    <div className="space-y-4" data-testid="payroll-table">
      <div className={cx(ui.card, "flex flex-wrap items-end gap-3")}>
        <div className="w-full sm:w-72"><span className={ui.label}>Client</span><EntitySelect value={tenantId} onChange={setTenantId} placeholder="Choisir un client" testId="payroll-client" /></div>
        <label className="block"><span className={ui.label}>Mois</span><input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className={ui.inputInline} data-testid="payroll-month" /></label>
        <label className="block"><span className={ui.label}>Forme juridique</span><input value={legalForm} onChange={(e) => { setLegalForm(e.target.value); setDirty(true); }} className={ui.inputInline} placeholder="SARL" /></label>
        {table && <span className={ui.badge.grey}>{table.company} · {SOURCES[table.source] || ""}</span>}
      </div>

      {!tenantId ? <p className={ui.empty}>Choisissez un client et un mois.</p> : loading ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline" /> Chargement…</p> : (
        <>
          <div className={cx(ui.card, "p-0 overflow-x-auto")}>
            <div className="px-4 pt-3 pb-2 text-center">
              <p className="font-display font-bold text-slate-900">FICHE DE RENSEIGNEMENT</p>
              <p className="text-xs font-semibold text-slate-600">LISTE ACTUALISÉE DU PERSONNEL PERMANENT {table?.period_label} {legalForm ? `· ${legalForm.toUpperCase()}` : ""}</p>
            </div>
            <table className="w-full text-sm">
              <thead className={ui.thead}>
                <tr><th className={ui.th}>N°</th><th className={ui.th}>Nom / prénoms</th>{COLS.map(([k, l]) => <th key={k} className={cx(ui.th, "text-right")}>{l}</th>)}
                  <th className={cx(ui.th, "text-right")}>Salaire brut</th><th className={cx(ui.th, "text-right")}>Salaire net</th><th className={ui.th}></th></tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={ui.tr} data-testid={`payroll-row-${i}`}>
                    <td className={cx(ui.td, "text-slate-400")}>{i + 1}</td>
                    <td className={ui.td}><input value={r.full_name || ""} onChange={(e) => setCell(i, "full_name", e.target.value)} className={cx(cellInput, "min-w-[180px] text-left")} placeholder="Nom et prénoms" /></td>
                    {COLS.map(([k]) => <td key={k} className={ui.td}><input inputMode="numeric" value={r[k] === 0 ? "" : (r[k] ?? "")} onChange={(e) => setCell(i, k, e.target.value)} className={cellInput} data-testid={`payroll-${i}-${k}`} /></td>)}
                    <td className={cx(ui.td, "text-right font-semibold tabular-nums text-slate-900")} data-testid={`payroll-${i}-gross`}>{fmt(grossOf(r))}</td>
                    <td className={ui.td}><input inputMode="numeric" value={r.net ?? ""} onChange={(e) => setCell(i, "net", e.target.value)} className={cellInput} data-testid={`payroll-${i}-net`} /></td>
                    <td className={cx(ui.td, "whitespace-nowrap")}>
                      <button type="button" onClick={() => move(i, -1)} className={ui.act.icon} title="Monter"><ArrowUp className="h-3.5 w-3.5" /></button>
                      <button type="button" onClick={() => move(i, 1)} className={cx(ui.act.icon, "ml-1")} title="Descendre"><ArrowDown className="h-3.5 w-3.5" /></button>
                      <button type="button" onClick={() => removeRow(i)} className={cx(ui.act.iconDanger, "ml-1")} title="Retirer"><Trash2 className="h-3.5 w-3.5" /></button>
                    </td>
                  </tr>
                ))}
                {/* Ligne TOTAL */}
                <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold" data-testid="payroll-total">
                  <td className={ui.td}></td><td className={ui.td}>TOTAL</td>
                  {COLS.map(([k]) => <td key={k} className={cx(ui.td, "text-right tabular-nums")}>{fmt(totals[k])}</td>)}
                  <td className={cx(ui.td, "text-right tabular-nums")}>{fmt(totals.gross)}</td><td className={cx(ui.td, "text-right tabular-nums")}>{fmt(totals.net)}</td><td className={ui.td}></td>
                </tr>
              </tbody>
            </table>
            <div className="p-3"><button type="button" onClick={addRow} className={ui.act.sky} data-testid="payroll-add"><Plus className="h-3.5 w-3.5" /> Ajouter un employé</button></div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-3">
            <label className={ui.checkLabel}><input type="checkbox" className={ui.check} checked={questionnaire} onChange={(e) => setQuestionnaire(e.target.checked)} /> Joindre le questionnaire RH (rubrique paie, observations)</label>
            <select value={letterheadId} onChange={(e) => setLetterheadId(e.target.value)} className={ui.selectInline} title="Papier à en-tête">
              <option value="">Papier par défaut</option><option value="none">Aucun en-tête</option>
              {letterheads.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <button type="button" onClick={save} disabled={saving} className={ui.btnPrimary} data-testid="payroll-save">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer{dirty ? " *" : ""}</button>
            <button type="button" onClick={() => exportFile("pdf")} className={ui.act.dark} data-testid="payroll-pdf"><FileText className="h-3.5 w-3.5" /> PDF</button>
            <button type="button" onClick={() => exportFile("csv")} className={ui.act.emerald} data-testid="payroll-csv"><FileSpreadsheet className="h-3.5 w-3.5" /> Excel</button>
          </div>
          <p className="text-[11px] text-slate-400 text-right"><Table2 className="h-3 w-3 inline" /> Le salaire brut se calcule tout seul (base + ancienneté + indemnités). Le net est saisi.</p>
        </>
      )}
    </div>
  );
}
