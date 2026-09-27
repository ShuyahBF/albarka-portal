/*
  PaieParamsEditor — lot 8 : édition d'un jeu complet de paramètres de paie.

  Utilisé pour un MODÈLE de configuration et pour la PERSONNALISATION d'un
  employeur. Tout est modifiable :
    - barème IUTS (tranches et taux), CNSS salariale (taux, plafond, limite
      fiscale de 8 % du salaire de base), CNSS patronale par branche, taxes
      patronales (TPA…) ;
    - rubriques d'indemnités et leurs règles d'exonération (taux, plafond) ;
    - abattement forfaitaire : taux unique OU taux selon la catégorie ;
    - charges de famille : lignes « nombre de charges → taux » (ajout /
      suppression ; la dernière ligne vaut au-delà) ;
    - prime d'ancienneté (à partir de 3 ans par défaut), soutien patriotique ;
    - arrondis (pas : franc, 5, 10, 25, 50, 100… ; au plus proche / inférieur / supérieur).
  À droite : APERÇU du calcul en direct sur un salarié d'exemple (bulletin du
  fichier du cabinet), modifiable.

  Props : value (params), onChange(params)
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { fcfa, GREEN } from "@/components/paie/paieCommon";

const STEPS = [[0, "Aucun (décimales)"], [1, "Au franc"], [5, "5 F"], [10, "10 F"], [25, "25 F"], [50, "50 F"], [100, "Centaine"], [1000, "Millier"]];
const MODES = [["nearest", "Au plus proche"], ["down", "Inférieur"], ["up", "Supérieur"]];
const ROUNDING_LABELS = { amounts: "Montants (CNSS, IUTS, primes…)", iuts_base: "Base IUTS", net: "Salaire net" };

// Clé unique pour une nouvelle ligne (évite les doublons après suppression)
const newKey = (prefix) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
// Champ numérique : vide autorisé pendant la saisie (sinon impossible d'effacer le 0)
const numOrEmpty = (e) => (e.target.value === "" ? "" : Number(e.target.value));
const num = "w-24 h-8 rounded border border-slate-300 px-2 text-sm text-right";
const txt = "h-8 rounded border border-slate-300 px-2 text-sm";

// Section repliable
function Section({ title, hint, children, open: defaultOpen = false, testId }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-slate-200 bg-white" data-testid={testId}>
      <button type="button" onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-4 py-2.5 text-left">
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <span className="font-semibold text-sm text-slate-800">{title}</span>
        {hint && <span className="text-xs text-slate-500 truncate">— {hint}</span>}
      </button>
      {open && <div className="border-t border-slate-100 px-4 py-3 space-y-2 text-sm">{children}</div>}
    </div>
  );
}

// Tableau de lignes éditables (ajout / suppression)
function Rows({ rows, onChange, columns, newRow, addLabel = "Ajouter une ligne", testId }) {
  const set = (i, patch) => onChange(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-1" data-testid={testId}>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          {columns.map((c) => (
            <label key={c.key} className="flex items-center gap-1 text-xs text-slate-600">
              {c.label}
              {c.render ? c.render(r, (v) => set(i, { [c.key]: v }), i) : (
                <input type={c.type || "number"} value={r[c.key] ?? ""} placeholder={c.placeholder}
                  onChange={(e) => set(i, { [c.key]: c.type === "text" ? e.target.value : (e.target.value === "" ? "" : Number(e.target.value)) })}
                  className={c.type === "text" ? `${txt} ${c.width || "w-48"}` : num} />
              )}
              {c.suffix}
            </label>
          ))}
          <button type="button" onClick={() => onChange(rows.filter((_, k) => k !== i))} className="p-1 text-slate-400 hover:text-rose-600" title="Supprimer">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...rows, newRow(rows)])} className="inline-flex items-center gap-1 text-xs font-medium" style={{ color: GREEN }}>
        <Plus className="h-3 w-3" /> {addLabel}
      </button>
    </div>
  );
}

// Salarié d'exemple de l'aperçu (bulletin du fichier Excel du cabinet)
const SAMPLE = { base_salary: 231672, dependents: 1, category: "", hire_date: "", allowances: { housing: 50000, transport: 30000, function: 30000 } };

function Preview({ params }) {
  const [emp, setEmp] = useState(SAMPLE);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      apiClient.post("/hr/paie/simulate", { params, employee: emp, period_month: new Date().toISOString().slice(0, 7) })
        .then(({ data }) => { setRes(data); setErr(""); })
        .catch((e) => setErr(e?.response?.data?.detail || "Paramètres invalides"));
    }, 350);                                   // attend la fin de la saisie
    return () => clearTimeout(t);
  }, [params, emp]);
  const setAllow = (k, v) => setEmp({ ...emp, allowances: { ...emp.allowances, [k]: Number(v) || 0 } });
  const cats = params?.flat_abatement?.mode === "by_category" ? params.flat_abatement.categories : [];
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3 text-sm space-y-2" data-testid="paie-preview">
      <p className="font-semibold text-emerald-900">Aperçu du calcul</p>
      <div className="grid grid-cols-2 gap-1.5 text-xs">
        <label>Salaire de base<input type="number" value={emp.base_salary} onChange={(e) => setEmp({ ...emp, base_salary: Number(e.target.value) || 0 })} className={`${txt} w-full`} /></label>
        <label>Charges de famille<input type="number" value={emp.dependents} onChange={(e) => setEmp({ ...emp, dependents: Number(e.target.value) || 0 })} className={`${txt} w-full`} /></label>
        {(params?.allowances || []).slice(0, 4).map((a) => (
          <label key={a.key}>{a.label.replace("Indemnité de ", "Ind. ")}<input type="number" value={emp.allowances[a.key] || 0} onChange={(e) => setAllow(a.key, e.target.value)} className={`${txt} w-full`} /></label>
        ))}
        <label>Date d'embauche<input type="date" value={emp.hire_date} onChange={(e) => setEmp({ ...emp, hire_date: e.target.value })} className={`${txt} w-full`} /></label>
        {cats.length > 0 && (
          <label>Catégorie<select value={emp.category} onChange={(e) => setEmp({ ...emp, category: e.target.value })} className={`${txt} w-full`}>
            {cats.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
        )}
      </div>
      {err ? <p className="text-xs text-rose-600">{err}</p> : res && (
        <table className="w-full text-xs" data-testid="paie-preview-result">
          <tbody>
            {[["Prime d'ancienneté", res.seniority], ["Salaire brut", res.gross, true], ["CNSS", res.cnss], ["Imposable IUTS", res.taxable],
              ["Exonérations", res.exemptions_total], [`Abattement forfaitaire (${res.flat_abatement_rate} %)`, res.flat_abatement],
              ["Base IUTS", res.iuts_base], ["IUTS brut", res.iuts_gross], [`Abattement famille (${res.family_rate} %)`, res.family_abatement],
              ["IUTS net", res.iuts], ["Salaire net", res.net, true], ["Soutien patriotique", res.patriotic_support],
              ["Net à payer", res.net_to_pay, true], ["Charges patronales", res.employer_total]].map(([l, v, b]) => (
              <tr key={l} className={b ? "font-semibold" : ""}><td className="py-0.5 text-slate-600">{l}</td><td className="text-right tabular-nums">{fcfa(v)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function PaieParamsEditor({ value, onChange }) {
  const p = value;
  if (!p) return null;
  const set = (patch) => onChange({ ...p, ...patch });
  const setIn = (key, patch) => onChange({ ...p, [key]: { ...p[key], ...patch } });
  const exKeys = (p.exemptions || []).map((e) => e.key);
  return (
    <div className="grid xl:grid-cols-[1fr_320px] gap-4" data-testid="paie-params-editor">
      <div className="space-y-2">
        <Section title="Barème IUTS" hint="tranches et taux marginaux" open testId="sec-iuts">
          <Rows testId="rows-iuts" rows={p.iuts_brackets} onChange={(rows) => set({ iuts_brackets: rows })}
            newRow={(rows) => ({ up_to: null, rate: rows.length ? rows[rows.length - 1].rate : 0 })} addLabel="Ajouter une tranche"
            columns={[
              { key: "up_to", label: "Jusqu'à", render: (r, v, i) => (
                <input type="number" value={r.up_to ?? ""} placeholder={i === p.iuts_brackets.length - 1 ? "au-delà" : ""}
                  onChange={(e) => v(e.target.value === "" ? null : Number(e.target.value))} className={num} />) },
              { key: "rate", label: "taux", suffix: "%" },
            ]} />
          <p className="text-[11px] text-slate-500">Laissez vide la borne de la dernière tranche (« au-delà »).</p>
        </Section>

        <Section title="CNSS" hint={`${p.cnss.employee_rate} % plafonnée à ${fcfa(p.cnss.ceiling)}`} testId="sec-cnss">
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1">Part salariale <input type="number" value={p.cnss.employee_rate} onChange={(e) => setIn("cnss", { employee_rate: numOrEmpty(e) })} className={num} /> %</label>
            <label className="flex items-center gap-1">Plafond du brut <input type="number" value={p.cnss.ceiling} onChange={(e) => setIn("cnss", { ceiling: numOrEmpty(e) })} className={num} /></label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={p.cnss.fiscal_cap_enabled} onChange={(e) => setIn("cnss", { fiscal_cap_enabled: e.target.checked })} />
              CNSS déductible de l'IUTS limitée à <input type="number" value={p.cnss.fiscal_cap_rate} onChange={(e) => setIn("cnss", { fiscal_cap_rate: numOrEmpty(e) })} className={num} /> % du salaire de base</label>
          </div>
          <p className="text-xs font-semibold text-slate-700 pt-2">CNSS patronale (livre de paie)</p>
          <label className="flex items-center gap-1 text-xs">Plafond <input type="number" value={p.cnss.employer_ceiling} onChange={(e) => setIn("cnss", { employer_ceiling: numOrEmpty(e) })} className={num} /></label>
          <Rows rows={p.cnss.employer_lines} onChange={(rows) => setIn("cnss", { employer_lines: rows })} newRow={() => ({ label: "", rate: 0 })}
            columns={[{ key: "label", label: "Branche", type: "text" }, { key: "rate", label: "taux", suffix: "%" }]} />
        </Section>

        <Section title="Taxes patronales" hint="sur le brut, non plafonnées (livre de paie)" testId="sec-taxes">
          <Rows rows={p.employer_taxes} onChange={(rows) => set({ employer_taxes: rows })} newRow={() => ({ label: "", rate: 0 })}
            columns={[{ key: "label", label: "Taxe", type: "text", width: "w-72" }, { key: "rate", label: "taux", suffix: "%" }]} />
        </Section>

        <Section title="Exonérations" hint="min(montant versé, taux × imposable, plafond)" testId="sec-exemptions">
          <Rows rows={p.exemptions} onChange={(rows) => set({ exemptions: rows })}
            newRow={(rows) => ({ key: newKey("ex"), label: "", rate: 0, cap: 0 })}
            columns={[{ key: "label", label: "Nom", type: "text", width: "w-32" }, { key: "rate", label: "taux", suffix: "% de l'imposable" },
              { key: "cap", label: "plafond (0 = sans plafond)" }]} />
        </Section>

        <Section title="Indemnités" hint="rubriques de la fiche salarié" testId="sec-allowances">
          <Rows rows={p.allowances} onChange={(rows) => set({ allowances: rows })}
            newRow={(rows) => ({ key: newKey("ind"), label: "", exemption: null })} addLabel="Ajouter une indemnité"
            columns={[{ key: "label", label: "Libellé", type: "text", width: "w-56" },
              { key: "exemption", label: "exonération", render: (r, v) => (
                <select value={r.exemption || ""} onChange={(e) => v(e.target.value || null)} className={txt}>
                  <option value="">Aucune (imposable)</option>
                  {(p.exemptions || []).map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
                </select>) }]} />
          {p.allowances.some((a) => a.exemption && !exKeys.includes(a.exemption)) && <p className="text-xs text-rose-600">Une indemnité pointe vers une exonération supprimée.</p>}
        </Section>

        <Section title="Abattement forfaitaire" hint={p.flat_abatement.mode === "single" ? `${p.flat_abatement.rate} % pour tous` : "selon la catégorie"} testId="sec-flat">
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1"><input type="radio" checked={p.flat_abatement.mode === "single"} onChange={() => setIn("flat_abatement", { mode: "single" })} data-testid="flat-single" />
              Taux unique <input type="number" value={p.flat_abatement.rate} onChange={(e) => setIn("flat_abatement", { rate: numOrEmpty(e) })} className={num} /> % du salaire de base</label>
            <label className="flex items-center gap-1"><input type="radio" checked={p.flat_abatement.mode === "by_category"} onChange={() => setIn("flat_abatement", { mode: "by_category" })} data-testid="flat-category" />
              Selon la catégorie du salarié</label>
          </div>
          {p.flat_abatement.mode === "by_category" && (
            <Rows rows={p.flat_abatement.categories} onChange={(rows) => setIn("flat_abatement", { categories: rows })}
              newRow={(rows) => ({ key: newKey("cat"), label: "", rate: 25 })} addLabel="Ajouter une catégorie"
              columns={[{ key: "label", label: "Catégorie", type: "text", width: "w-40" }, { key: "rate", label: "taux", suffix: "%" }]} />
          )}
          {p.flat_abatement.mode === "by_category" && (
            // Un salarié sans catégorie (ou dont la catégorie a été supprimée) garde le taux unique
            <p className="text-[11px] text-slate-500">Salarié sans catégorie : taux unique ci-dessus ({p.flat_abatement.rate} %).</p>
          )}
        </Section>

        <Section title="Charges de famille" hint="abattement sur l'IUTS" testId="sec-family">
          <Rows testId="rows-family" rows={p.family_abatement} onChange={(rows) => set({ family_abatement: rows })}
            newRow={(rows) => ({ charges: (rows[rows.length - 1]?.charges || 0) + 1, rate: rows[rows.length - 1]?.rate || 0 })} addLabel="Ajouter un nombre de charges"
            columns={[{ key: "charges", label: "Charges" }, { key: "rate", label: "taux", suffix: "% de l'IUTS" }]} />
          <p className="text-[11px] text-slate-500">Au-delà de la dernière ligne, son taux s'applique.</p>
        </Section>

        <Section title="Prime d'ancienneté" hint={p.seniority.enabled ? `à partir de ${p.seniority.start_years} ans` : "désactivée"} testId="sec-seniority">
          <label className="flex items-center gap-1"><input type="checkbox" checked={p.seniority.enabled} onChange={(e) => setIn("seniority", { enabled: e.target.checked })} /> Calculer la prime d'ancienneté</label>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1">À partir de <input type="number" value={p.seniority.start_years} onChange={(e) => setIn("seniority", { start_years: numOrEmpty(e) })} className={num} /> ans</label>
            <label className="flex items-center gap-1">taux <input type="number" value={p.seniority.start_rate} onChange={(e) => setIn("seniority", { start_rate: numOrEmpty(e) })} className={num} /> %</label>
            <label className="flex items-center gap-1">puis + <input type="number" value={p.seniority.step_rate} onChange={(e) => setIn("seniority", { step_rate: numOrEmpty(e) })} className={num} /> point(s) par an</label>
            <label className="flex items-center gap-1">plafond <input type="number" value={p.seniority.max_rate} onChange={(e) => setIn("seniority", { max_rate: numOrEmpty(e) })} className={num} /> %</label>
          </div>
          <p className="text-[11px] text-slate-500">Calculée sur le salaire de base, d'après la date d'embauche (années complètes à la fin du mois).</p>
        </Section>

        <Section title="Soutien patriotique" hint={p.patriotic_support.enabled ? `${p.patriotic_support.rate} % du net` : "désactivé"} testId="sec-patriotic">
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1"><input type="checkbox" checked={p.patriotic_support.enabled} onChange={(e) => setIn("patriotic_support", { enabled: e.target.checked })} /> Appliquer</label>
            <label className="flex items-center gap-1">Taux <input type="number" value={p.patriotic_support.rate} onChange={(e) => setIn("patriotic_support", { rate: numOrEmpty(e) })} className={num} /> % du salaire net</label>
            <label className="flex items-center gap-1">Libellé <input value={p.patriotic_support.label} onChange={(e) => setIn("patriotic_support", { label: e.target.value })} className={`${txt} w-56`} /></label>
          </div>
        </Section>

        <Section title="Arrondis" hint="pas de décimales ; centaine par défaut pour la base IUTS et le net" testId="sec-rounding">
          {Object.entries(ROUNDING_LABELS).map(([k, l]) => (
            <div key={k} className="flex flex-wrap items-center gap-2">
              <span className="w-56 text-slate-700">{l}</span>
              <select value={p.rounding[k]?.step ?? 1} onChange={(e) => set({ rounding: { ...p.rounding, [k]: { ...p.rounding[k], step: Number(e.target.value) } } })} className={txt} data-testid={`round-step-${k}`}>
                {STEPS.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}
              </select>
              <select value={p.rounding[k]?.mode || "nearest"} onChange={(e) => set({ rounding: { ...p.rounding, [k]: { ...p.rounding[k], mode: e.target.value } } })} className={txt}>
                {MODES.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}
              </select>
            </div>
          ))}
        </Section>
      </div>
      <div className="xl:sticky xl:top-4 self-start"><Preview params={p} /></div>
    </div>
  );
}
