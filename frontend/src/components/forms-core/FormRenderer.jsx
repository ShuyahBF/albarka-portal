/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormRenderer : affiche un formulaire et recueille les réponses. UN SEUL
  moteur pour tous les usages (aperçu du constructeur, page publique, espace
  client) : tous les types de champs y sont gérés, y compris fichier et
  signature, et l'affichage conditionnel (show_if).

  Props :
    form        { title, description, pages }
    value       réponses {id_du_champ: valeur}      onChange(nouvellesRéponses)
    errors      {id_du_champ: message} (renvoyées par le serveur)
    uploadFile  async (fieldId, fichier|blob, nom) => {file_id, filename, size, content_type}
    onSubmit    () => void   (absent = mode aperçu, bouton désactivé)
    submitting, submitLabel, header (contenu affiché en haut de la 1re page)
*/
import React, { useEffect, useRef, useState } from "react";
import { Star, Paperclip, X, Loader2, ChevronLeft, ChevronRight, Eraser, Plus, Trash2 } from "lucide-react";
import { isVisible, isEmpty } from "./fieldTypes";
import { ui, cx } from "./ui";

// Champ de saisie du répondant (design SAWALI, couleur du site)
const inputCls = ui.input;

// --- Signature dessinée au doigt ou à la souris (sans bibliothèque externe)
function SignaturePad({ value, onUpload, disabled }) {
  const canvasRef = useRef(null);
  const drawing = useRef(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.strokeStyle = "#0f172a";
  }, []);

  const pos = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    const p = e.touches ? e.touches[0] : e;
    return { x: ((p.clientX - r.left) * canvasRef.current.width) / r.width, y: ((p.clientY - r.top) * canvasRef.current.height) / r.height };
  };
  const start = (e) => { if (disabled) return; drawing.current = true; const { x, y } = pos(e); const ctx = canvasRef.current.getContext("2d"); ctx.beginPath(); ctx.moveTo(x, y); };
  const move = (e) => { if (!drawing.current) return; e.preventDefault(); const { x, y } = pos(e); const ctx = canvasRef.current.getContext("2d"); ctx.lineTo(x, y); ctx.stroke(); setDirty(true); };
  const end = () => { drawing.current = false; };
  const clear = () => { const c = canvasRef.current; c.getContext("2d").clearRect(0, 0, c.width, c.height); setDirty(false); };
  const save = () => {
    setBusy(true);
    canvasRef.current.toBlob(async (blob) => {
      try { await onUpload(blob, "signature.png"); clear(); } finally { setBusy(false); }
    }, "image/png");
  };

  if (value?.file_id) {
    return (
      <div className="flex items-center gap-2 text-sm text-emerald-700">
        ✔ Signature enregistrée
        {!disabled && <button type="button" onClick={() => onUpload(null)} className="text-xs text-slate-500 underline">Signer à nouveau</button>}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <canvas ref={canvasRef} width={600} height={180}
        className="w-full h-40 bg-white rounded-lg ring-1 ring-slate-300 cursor-crosshair touch-none"
        onMouseDown={start} onMouseMove={move} onMouseUp={end} onMouseLeave={end}
        onTouchStart={start} onTouchMove={move} onTouchEnd={end} />
      <div className="flex gap-2">
        <button type="button" onClick={clear} disabled={!dirty || disabled} className={ui.act.slate}><Eraser className="h-3 w-3" /> Effacer</button>
        <button type="button" onClick={save} disabled={!dirty || busy || disabled}
          className={ui.act.primary}>
          {busy && <Loader2 className="h-3 w-3 animate-spin" />} Valider la signature
        </button>
      </div>
    </div>
  );
}

// --- Un champ
function Field({ field, value, onChange, error, uploadFile, disabled }) {
  const [uploading, setUploading] = useState(false);
  const t = field.type;
  const upload = async (file, name) => {
    if (!file) { onChange(null); return; }
    if (!uploadFile) return;
    setUploading(true);
    try { onChange(await uploadFile(field.id, file, name || file.name)); } finally { setUploading(false); }
  };
  const common = { disabled, id: `ff-${field.id}` };

  if (t === "section") {
    return (
      <div className="pt-2">
        <h3 className="font-display font-bold text-slate-900 text-base border-b border-slate-100 pb-1">{field.label}</h3>
        {field.help && <p className="text-sm text-slate-600 mt-1 whitespace-pre-line">{field.help}</p>}
      </div>
    );
  }

  let control;
  if (["text", "email", "tel", "url"].includes(t)) {
    control = <input {...common} type={t === "text" ? "text" : t} value={value ?? ""} placeholder={field.placeholder || ""} onChange={(e) => onChange(e.target.value)} className={inputCls} />;
  } else if (t === "textarea") {
    control = <textarea {...common} rows={4} value={value ?? ""} placeholder={field.placeholder || ""} onChange={(e) => onChange(e.target.value)} className={inputCls} />;
  } else if (t === "number") {
    control = <input {...common} type="number" value={value ?? ""} min={field.min ?? undefined} max={field.max ?? undefined} onChange={(e) => onChange(e.target.value === "" ? "" : e.target.value)} className={inputCls} />;
  } else if (t === "date") {
    control = <input {...common} type="date" value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={inputCls} />;
  } else if (t === "datetime") {
    control = <input {...common} type="datetime-local" value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={inputCls} />;
  } else if (t === "select") {
    control = (
      <select {...common} value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={inputCls}>
        <option value="">— Choisir —</option>
        {(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  } else if (t === "radio") {
    control = (
      <div className="space-y-1.5">
        {(field.options || []).map((o) => (
          <label key={o} className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="radio" name={field.id} checked={value === o} disabled={disabled} onChange={() => onChange(o)} className={ui.check} /> {o}
          </label>
        ))}
      </div>
    );
  } else if (t === "checkbox" || t === "multiselect") {
    const arr = Array.isArray(value) ? value : [];
    const toggle = (o) => onChange(arr.includes(o) ? arr.filter((x) => x !== o) : [...arr, o]);
    control = (
      <div className={t === "multiselect" ? "flex flex-wrap gap-1.5" : "space-y-1.5"}>
        {(field.options || []).map((o) => t === "multiselect" ? (
          <button key={o} type="button" disabled={disabled} onClick={() => toggle(o)}
            className={ui.chip(arr.includes(o))}>{o}</button>
        ) : (
          <label key={o} className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={arr.includes(o)} disabled={disabled} onChange={() => toggle(o)} className={ui.check} /> {o}
          </label>
        ))}
      </div>
    );
  } else if (t === "boolean") {
    control = (
      <div className="flex gap-2">
        {[["Oui", true], ["Non", false]].map(([label, v]) => (
          <button key={label} type="button" disabled={disabled} onClick={() => onChange(value === v ? null : v)}
            className={cx("px-5 py-1.5 rounded-lg ring-1 text-sm transition", value === v ? "bg-primary text-primary-foreground ring-primary" : "bg-white ring-slate-300 text-slate-700 hover:ring-primary/50")}>{label}</button>
        ))}
      </div>
    );
  } else if (t === "rating") {
    const max = field.max || 5;
    control = (
      <div className="flex gap-1">
        {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
          <button key={n} type="button" disabled={disabled} onClick={() => onChange(value === n ? null : n)} aria-label={`${n} sur ${max}`}>
            <Star className={`h-7 w-7 ${Number(value) >= n ? "fill-amber-400 text-amber-400" : "text-slate-300"}`} />
          </button>
        ))}
      </div>
    );
  } else if (t === "scale") {
    control = (
      <div className="flex flex-wrap gap-1">
        {Array.from({ length: 11 }, (_, i) => i).map((n) => (
          <button key={n} type="button" disabled={disabled} onClick={() => onChange(value === n ? null : n)}
            className={cx("h-9 w-9 rounded-lg ring-1 text-sm tabular-nums transition", Number(value) === n && value !== null && value !== "" ? "bg-primary text-primary-foreground ring-primary" : "bg-white ring-slate-300 text-slate-700 hover:ring-primary/50")}>{n}</button>
        ))}
      </div>
    );
  } else if (t === "table") {
    const cols = field.columns || [];
    const rows = Array.isArray(value) && value.length ? value : [{}];
    const setCell = (i, k, v) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
    control = (
      <div className="overflow-x-auto">
        <table className="w-full text-sm rounded-lg ring-1 ring-slate-200 overflow-hidden">
          <thead className={ui.thead}><tr>{cols.map((c) => <th key={c.key} className={ui.th}>{c.label}</th>)}<th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100">
                {cols.map((c) => (
                  <td key={c.key} className="p-1">
                    <input type={c.type === "number" ? "number" : c.type === "date" ? "date" : "text"} value={r[c.key] ?? ""} disabled={disabled}
                      onChange={(e) => setCell(i, c.key, e.target.value)} className={ui.inputSm} />
                  </td>
                ))}
                <td className="p-1 w-8">
                  {rows.length > 1 && !disabled && <button type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))} className="text-slate-400 hover:text-rose-600"><Trash2 className="h-4 w-4" /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!disabled && <button type="button" onClick={() => onChange([...rows, {}])} className={cx(ui.btnTool, "mt-2")}><Plus className="h-3 w-3" /> Ajouter une ligne</button>}
      </div>
    );
  } else if (t === "file") {
    control = value?.file_id ? (
      <div className="flex items-center gap-2 text-sm rounded-lg ring-1 ring-slate-200 bg-slate-50 px-3 py-2">
        <Paperclip className="h-4 w-4 text-primary" /> <span className="truncate">{value.filename}</span>
        {!disabled && <button type="button" onClick={() => onChange(null)} className="text-slate-400 hover:text-rose-600"><X className="h-4 w-4" /></button>}
      </div>
    ) : (
      <label className={cx("flex items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-300 bg-slate-50/60 px-3 py-4 text-sm text-slate-600", disabled ? "opacity-50" : "cursor-pointer hover:border-primary hover:text-primary")}>
        {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
        {uploading ? "Envoi…" : "Joindre un fichier"}
        <input type="file" className="hidden" disabled={disabled || uploading} accept={field.accept || undefined}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
      </label>
    );
  } else if (t === "signature") {
    control = <SignaturePad value={value} onUpload={upload} disabled={disabled} />;
  }

  return (
    <div>
      <label htmlFor={`ff-${field.id}`} className="block text-sm font-semibold text-slate-800 mb-1">
        {field.label}{field.required && <span className="text-rose-600"> *</span>}
      </label>
      {field.help && <p className="text-xs text-slate-500 mb-1.5 whitespace-pre-line">{field.help}</p>}
      {control}
      {error && <p className={ui.error} data-testid={`field-error-${field.id}`}>{error}</p>}
    </div>
  );
}

export default function FormRenderer({ form, value = {}, onChange, errors = {}, uploadFile, onSubmit, submitting = false,
  submitLabel = "Envoyer", header = null, disabled = false }) {
  const pages = form?.pages?.length ? form.pages : [{ id: "p", title: "", fields: [] }];
  const [pageIdx, setPageIdx] = useState(0);
  const [localErrors, setLocalErrors] = useState({});
  const page = pages[Math.min(pageIdx, pages.length - 1)];
  const allErrors = { ...localErrors, ...errors };

  // Si le serveur signale une erreur, on affiche la première page qui en contient.
  useEffect(() => {
    const ids = Object.keys(errors || {});
    if (!ids.length) return;
    const idx = pages.findIndex((p) => p.fields.some((f) => ids.includes(f.id)));
    if (idx >= 0) setPageIdx(idx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errors]);

  const set = (id, v) => { onChange({ ...value, [id]: v }); if (localErrors[id]) setLocalErrors((e) => ({ ...e, [id]: undefined })); };

  // Contrôle des champs obligatoires visibles de la page (le serveur recontrôle tout).
  const checkPage = () => {
    const errs = {};
    page.fields.forEach((f) => {
      if (f.type !== "section" && f.required && isVisible(f, value) && isEmpty(value[f.id])) errs[f.id] = "Ce champ est obligatoire.";
    });
    setLocalErrors(errs);
    return Object.keys(errs).length === 0;
  };
  const next = () => { if (checkPage()) { setPageIdx((i) => i + 1); window.scrollTo?.({ top: 0, behavior: "smooth" }); } };
  const submit = () => { if (checkPage() && onSubmit) onSubmit(); };
  const last = pageIdx >= pages.length - 1;

  return (
    <div className="space-y-5" data-testid="form-renderer">
      {pages.length > 1 && (
        <div>
          <div className="flex justify-between text-xs text-slate-500 mb-1"><span>{page.title}</span><span>Étape {pageIdx + 1} / {pages.length}</span></div>
          <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden"><div className="h-full bg-primary transition-all" style={{ width: `${((pageIdx + 1) * 100) / pages.length}%` }} /></div>
        </div>
      )}
      {pageIdx === 0 && header}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-5">
        {page.fields.filter((f) => isVisible(f, value)).map((f) => (
          <div key={f.id} className={f.width === "half" && f.type !== "section" ? "md:col-span-1" : "md:col-span-2"} data-testid={`field-${f.id}`}>
            <Field field={f} value={value[f.id]} onChange={(v) => set(f.id, v)} error={allErrors[f.id]} uploadFile={uploadFile} disabled={disabled} />
          </div>
        ))}
        {page.fields.length === 0 && <p className="md:col-span-2 text-sm text-slate-400 italic">Aucune question sur cette page.</p>}
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <button type="button" onClick={() => setPageIdx((i) => Math.max(0, i - 1))} disabled={pageIdx === 0}
          className={cx(ui.btnSecondary, "disabled:invisible")}><ChevronLeft className="h-4 w-4" /> Précédent</button>
        {last ? (
          <button type="button" onClick={submit} disabled={!onSubmit || submitting || disabled} data-testid="form-submit"
            className={cx(ui.btnPrimary, "px-5")}>
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />} {onSubmit ? submitLabel : "Aperçu — envoi désactivé"}
          </button>
        ) : (
          <button type="button" onClick={next} data-testid="form-next"
            className={ui.btnPrimary}>Suivant <ChevronRight className="h-4 w-4" /></button>
        )}
      </div>
    </div>
  );
}
