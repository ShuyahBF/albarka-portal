/*
  PaieBulletins — lot 8 : onglets « Bulletins » et « Livre de paie ».

  Bulletins : employeur + mois →
    - « Préparer / recalculer le mois » : un bulletin par salarié (les
      brouillons sont recalculés avec la fiche et les paramètres actuels ; les
      bulletins validés ne bougent plus) ;
    - pour chaque bulletin : éléments du mois (primes imposables, acomptes,
      prêts, autres retenues, ancienneté saisie, observations), rubriques
      calculées, Valider / Rouvrir, PDF ; « Tout imprimer » en un seul PDF.
  Livre de paie : tableau du mois (brut, CNSS, IUTS, soutien patriotique,
  retenues, net à payer, charges patronales, coût total), détail des charges
  patronales, PDF et Excel.
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { RefreshCw, Printer, FileText, Lock, Unlock, Plus, Trash2, X, FileSpreadsheet } from "lucide-react";
import { EmployerSelect, MonthInput, useEmployers, fcfa, previousMonth, GREEN } from "@/components/paie/paieCommon";

const openPdf = async (url, params) => {
  try {
    const { data } = await apiClient.get(url, { params, responseType: "blob" });
    window.open(URL.createObjectURL(data), "_blank");
  } catch (e) { toast.error(extractError(e)); }
};

// Lignes « libellé / montant » (primes ou retenues du mois)
function ItemsEditor({ items, onChange, placeholder, disabled, testId }) {
  return (
    <div className="space-y-1" data-testid={testId}>
      {items.map((it, i) => (
        <div key={i} className="flex gap-2">
          <input value={it.label} disabled={disabled} placeholder={placeholder} onChange={(e) => onChange(items.map((x, k) => (k === i ? { ...x, label: e.target.value } : x)))}
            className="h-8 flex-1 rounded border border-slate-300 px-2 text-sm" />
          <input type="number" value={it.amount} disabled={disabled} onChange={(e) => onChange(items.map((x, k) => (k === i ? { ...x, amount: e.target.value } : x)))}
            className="h-8 w-28 rounded border border-slate-300 px-2 text-sm text-right" />
          {!disabled && <button type="button" onClick={() => onChange(items.filter((_, k) => k !== i))} className="p-1 text-slate-400 hover:text-rose-600"><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      ))}
      {!disabled && <button type="button" onClick={() => onChange([...items, { label: "", amount: "" }])} className="inline-flex items-center gap-1 text-xs font-medium" style={{ color: GREEN }}><Plus className="h-3 w-3" /> Ajouter</button>}
    </div>
  );
}

function BulletinDrawer({ id, onClose, onChanged }) {
  const [b, setB] = useState(null);
  const [vars, setVars] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const { data } = await apiClient.get(`/hr/paie/bulletins/${id}`);
    setB(data);
    const v = data.variables || {};
    setVars({ extras: v.extras || [], deductions: v.deductions || [], seniority_amount: v.seniority_amount ?? "", notes: v.notes || "" });
  }, [id]);
  useEffect(() => { load().catch((e) => toast.error(extractError(e))); }, [load]);
  if (!b || !vars) return null;
  const locked = b.status === "validated";
  const r = b.result || {};

  const save = async () => {
    setBusy(true);
    try {
      await apiClient.put(`/hr/paie/bulletins/${id}`, { ...vars, seniority_amount: vars.seniority_amount === "" ? null : Number(vars.seniority_amount),
        extras: vars.extras.map((x) => ({ ...x, amount: Number(x.amount) || 0 })), deductions: vars.deductions.map((x) => ({ ...x, amount: Number(x.amount) || 0 })) });
      toast.success("Bulletin recalculé"); await load(); onChanged();
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };
  const toggle = async () => {
    try { await apiClient.post(`/hr/paie/bulletins/${id}/${locked ? "reopen" : "validate"}`); await load(); onChanged(); toast.success(locked ? "Bulletin rouvert" : "Bulletin validé"); }
    catch (e) { toast.error(extractError(e)); }
  };
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="h-full w-full max-w-2xl overflow-auto bg-white p-5 shadow-2xl space-y-4" data-testid="bulletin-drawer">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-500">Bulletin {b.period_month} · {locked ? "validé" : "brouillon"}</p>
            <h3 className="font-display text-xl">{b.employee?.full_name}</h3>
            <p className="text-xs text-slate-500">{b.employer?.name} · modèle « {b.template_name} »{b.customized ? " (personnalisé)" : ""}</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-slate-100" aria-label="Fermer"><X className="h-5 w-5" /></button>
        </div>
        <table className="w-full text-sm" data-testid="bulletin-lines">
          <thead className="text-[11px] uppercase text-slate-500"><tr><th className="text-left">Rubrique</th><th className="text-right">Base</th><th className="text-right">Taux</th><th className="text-right">Gains</th><th className="text-right">Retenues</th></tr></thead>
          <tbody>
            {/* Même ordre que le PDF : gains, brut, CNSS et IUTS, net, puis soutien patriotique et retenues */}
            {(() => {
              const isAfter = (ln) => ln.code === "patriotic" || ln.code.startsWith("ded_");
              const row = (ln, i) => (
                <tr key={`${ln.code}-${i}`} className="border-t border-slate-100">
                  <td className="py-1">{ln.label}</td><td className="text-right tabular-nums text-slate-500">{ln.base ? fcfa(ln.base) : ""}</td>
                  <td className="text-right text-slate-500">{ln.rate ? `${String(ln.rate).replace(".", ",")} %` : ""}</td>
                  <td className="text-right tabular-nums">{ln.kind === "gain" ? fcfa(ln.amount) : ""}</td>
                  <td className="text-right tabular-nums">{ln.kind === "deduction" ? fcfa(ln.amount) : ""}</td>
                </tr>
              );
              const lines = r.lines || [];
              const gains = lines.filter((ln) => ln.kind === "gain");
              const taxes = lines.filter((ln) => ln.kind === "deduction" && !isAfter(ln));
              const after = lines.filter(isAfter);
              return (
                <>
                  {gains.map(row)}
                  <tr className="border-t font-semibold"><td className="py-1">Salaire brut</td><td /><td /><td className="text-right">{fcfa(r.gross)}</td><td /></tr>
                  {taxes.map(row)}
                  <tr className="font-semibold"><td className="py-1">IUTS net</td><td /><td /><td /><td className="text-right">{fcfa(r.iuts)}</td></tr>
                  <tr className="border-t font-semibold"><td className="py-1">Salaire net</td><td /><td /><td className="text-right">{fcfa(r.net)}</td><td /></tr>
                  {after.map(row)}
                  <tr className="border-t font-bold text-lg" style={{ color: GREEN }}><td className="py-1">Net à payer</td><td /><td /><td className="text-right" data-testid="bulletin-net-to-pay">{fcfa(r.net_to_pay)}</td><td /></tr>
                </>
              );
            })()}
          </tbody>
        </table>
        <p className="text-[11px] text-slate-500">Base IUTS {fcfa(r.iuts_base)} · exonérations {fcfa(r.exemptions_total)} · abattement forfaitaire {fcfa(r.flat_abatement)} · charges patronales {fcfa(r.employer_total)}</p>
        <div className="rounded-xl bg-slate-50 p-3 space-y-3 text-sm">
          <p className="font-semibold">Éléments du mois</p>
          <div><p className="text-xs text-slate-600 mb-1">Primes (imposables)</p><ItemsEditor items={vars.extras} disabled={locked} placeholder="Prime de rendement…" onChange={(extras) => setVars({ ...vars, extras })} testId="bulletin-extras" /></div>
          <div><p className="text-xs text-slate-600 mb-1">Retenues (acomptes, prêts, autres)</p><ItemsEditor items={vars.deductions} disabled={locked} placeholder="Acompte…" onChange={(deductions) => setVars({ ...vars, deductions })} testId="bulletin-deductions" /></div>
          <label className="block text-xs text-slate-600">Prime d'ancienneté saisie (vide = calculée : {fcfa(r.seniority)})
            <input type="number" value={vars.seniority_amount} disabled={locked} onChange={(e) => setVars({ ...vars, seniority_amount: e.target.value })} className="mt-1 block h-8 w-40 rounded border border-slate-300 px-2 text-sm" /></label>
          <label className="block text-xs text-slate-600">Observations
            <input value={vars.notes} disabled={locked} onChange={(e) => setVars({ ...vars, notes: e.target.value })} className="mt-1 block h-8 w-full rounded border border-slate-300 px-2 text-sm" /></label>
          {!locked && <button type="button" onClick={save} disabled={busy} className="rounded-lg px-3 py-2 text-sm font-medium text-white disabled:opacity-50" style={{ background: GREEN }} data-testid="bulletin-save">Enregistrer et recalculer</button>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={toggle} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="bulletin-toggle">
            {locked ? <><Unlock className="h-4 w-4" /> Rouvrir</> : <><Lock className="h-4 w-4" /> Valider le bulletin</>}</button>
          <button type="button" onClick={() => openPdf(`/hr/paie/bulletins/${id}/pdf`)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="bulletin-pdf"><FileText className="h-4 w-4" /> PDF</button>
        </div>
      </div>
    </div>
  );
}

export function PaieBulletins() {
  const employers = useEmployers();
  const [eid, setEid] = useState("");
  const [month, setMonth] = useState(previousMonth());
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (!eid || !month) { setData(null); return; }
    const { data: d } = await apiClient.get("/hr/paie/bulletins", { params: { employer_id: eid, period_month: month } });
    setData(d);
  }, [eid, month]);
  useEffect(() => { load().catch((e) => toast.error(extractError(e))); }, [load]);

  const prepare = async () => {
    setBusy(true);
    try {
      const { data: r } = await apiClient.post("/hr/paie/bulletins/prepare", { employer_id: eid, period_month: month });
      toast.success(`${r.created} bulletin(s) créé(s), ${r.updated} recalculé(s)`); await load();
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };
  const t = data?.totals || {};
  return (
    <div className="space-y-3" data-testid="paie-bulletins">
      <div className="flex flex-wrap items-center gap-3">
        <EmployerSelect value={eid} onChange={setEid} employers={employers} testId="bulletins-employer" />
        <MonthInput value={month} onChange={setMonth} testId="bulletins-month" />
        {eid && <>
          <button type="button" onClick={prepare} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-white disabled:opacity-50" style={{ background: GREEN }} data-testid="bulletins-prepare">
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /> Préparer / recalculer le mois</button>
          {data?.items?.length > 0 && <button type="button" onClick={() => openPdf("/hr/paie/bulletins-pdf", { employer_id: eid, period_month: month })} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><Printer className="h-4 w-4" /> Tout imprimer</button>}
        </>}
      </div>
      {data && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Salarié</th><th className="text-right">Brut</th><th className="text-right">CNSS</th><th className="text-right">IUTS</th>
                <th className="text-right">Net</th><th className="text-right">Net à payer</th><th className="text-left px-3">État</th></tr>
            </thead>
            <tbody>
              {data.items.map((b) => (
                <tr key={b.id} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => setOpen(b.id)} data-testid={`bulletin-row-${b.id}`}>
                  <td className="px-3 py-2 font-medium">{b.employee?.full_name}</td>
                  <td className="text-right tabular-nums">{fcfa(b.result?.gross)}</td><td className="text-right tabular-nums">{fcfa(b.result?.cnss)}</td>
                  <td className="text-right tabular-nums">{fcfa(b.result?.iuts)}</td><td className="text-right tabular-nums">{fcfa(b.result?.net)}</td>
                  <td className="text-right tabular-nums font-semibold">{fcfa(b.result?.net_to_pay)}</td>
                  <td className="px-3">{b.status === "validated" ? <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-800">validé</span> : <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-800">brouillon</span>}</td>
                </tr>
              ))}
              {!data.items.length && <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-500">Aucun bulletin : cliquez sur « Préparer / recalculer le mois ».</td></tr>}
              {data.items.length > 0 && (
                <tr className="border-t-2 font-semibold bg-slate-50"><td className="px-3 py-2">TOTAL ({t.count})</td><td className="text-right">{fcfa(t.gross)}</td><td className="text-right">{fcfa(t.cnss)}</td>
                  <td className="text-right">{fcfa(t.iuts)}</td><td /><td className="text-right">{fcfa(t.net_to_pay)}</td><td /></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {open && <BulletinDrawer id={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}

export function PaieLivre() {
  const employers = useEmployers();
  const [eid, setEid] = useState("");
  const [month, setMonth] = useState(previousMonth());
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!eid || !month) { setData(null); return; }
    apiClient.get("/hr/paie/livre", { params: { employer_id: eid, period_month: month } }).then(({ data: d }) => setData(d)).catch((e) => toast.error(extractError(e)));
  }, [eid, month]);
  const downloadCsv = async () => {
    try {
      const { data: blob } = await apiClient.get("/hr/paie/livre/csv", { params: { employer_id: eid, period_month: month }, responseType: "blob" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `livre_de_paie_${month}.csv`; a.click();
    } catch (e) { toast.error(extractError(e)); }
  };
  return (
    <div className="space-y-3" data-testid="paie-livre">
      <div className="flex flex-wrap items-center gap-3">
        <EmployerSelect value={eid} onChange={setEid} employers={employers} testId="livre-employer" />
        <MonthInput value={month} onChange={setMonth} testId="livre-month" />
        {data?.rows?.length > 0 && <>
          <button type="button" onClick={() => openPdf("/hr/paie/livre/pdf", { employer_id: eid, period_month: month })} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><FileText className="h-4 w-4" /> PDF</button>
          <button type="button" onClick={downloadCsv} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><FileSpreadsheet className="h-4 w-4" /> Excel</button>
        </>}
      </div>
      {data && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white overflow-auto">
            <table className="w-full text-sm" data-testid="livre-table">
              <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
                <tr><th className="px-3 py-2 text-left">Salarié</th>{data.columns.map((c) => <th key={c.key} className="text-right px-2">{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100"><td className="px-3 py-1.5 font-medium">{r.full_name}</td>
                    {data.columns.map((c) => <td key={c.key} className="text-right tabular-nums px-2">{fcfa(r[c.key])}</td>)}</tr>
                ))}
                {!data.rows.length && <tr><td colSpan={data.columns.length + 1} className="px-3 py-6 text-center text-slate-500">Aucun bulletin pour ce mois.</td></tr>}
                {data.rows.length > 0 && (
                  <tr className="border-t-2 font-semibold bg-slate-50"><td className="px-3 py-2">TOTAL</td>{data.columns.map((c) => <td key={c.key} className="text-right tabular-nums px-2">{fcfa(data.totals[c.key])}</td>)}</tr>
                )}
              </tbody>
            </table>
          </div>
          {data.rows.length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white p-3 max-w-md" data-testid="livre-employer-charges">
              <p className="font-semibold text-sm mb-1">Charges patronales du mois</p>
              <table className="w-full text-sm"><tbody>
                {data.totals.employer_detail.map((x) => <tr key={x.label}><td className="text-slate-600">{x.label}</td><td className="text-right tabular-nums">{fcfa(x.amount)}</td></tr>)}
                <tr className="border-t font-semibold"><td>Total</td><td className="text-right tabular-nums">{fcfa(data.totals.employer_total)}</td></tr>
              </tbody></table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
