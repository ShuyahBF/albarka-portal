/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormBuilder : constructeur de formulaire.
    - palette des 19 types de champs : clic pour ajouter, ou glisser-déposer
      sur la page ;
    - pages (étapes) : ajout, renommage, suppression ;
    - questions réordonnables par glisser-déposer (ou flèches), dupliquer,
      supprimer, déplacer vers une autre page ;
    - panneau de propriétés : libellé, aide, obligatoire, largeur, options,
      bornes, colonnes de tableau, types de fichiers acceptés, et AFFICHAGE
      CONDITIONNEL (« afficher seulement si … ») ;
    - onglet Réglages : ouverture aux réponses, date limite, message de
      confirmation, identité du répondant, modification autorisée, e-mails
      prévenus à chaque réponse ;
    - aperçu en direct (même moteur que le formulaire réel).

  Props : form, categories [{id,name}], onSave(async patch), saving
*/
import React, { useEffect, useMemo, useState } from "react";
import { GripVertical, ArrowUp, ArrowDown, Copy, Trash2, Plus, Eye, Save, X, Settings2, ListOrdered, Loader2 } from "lucide-react";
import FormRenderer from "./FormRenderer";
import { FIELD_TYPES, TYPE_BY_KEY, CHOICE_TYPES, newField, newPage } from "./fieldTypes";

const inputCls = "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40";
const clone = (x) => JSON.parse(JSON.stringify(x));

function Properties({ field, pages, pageIdx, update, moveToPage }) {
  // Champs placés AVANT celui-ci : seuls candidats pour une condition d'affichage.
  const earlier = [];
  for (let p = 0; p < pages.length; p += 1) {
    for (const f of pages[p].fields) {
      if (f.id === field.id) { p = pages.length; break; }
      if (f.type !== "section") earlier.push(f);
    }
  }
  const condTarget = earlier.find((f) => f.id === field.show_if?.field);
  const set = (patch) => update({ ...field, ...patch });

  return (
    <div className="space-y-3 text-sm" data-testid="field-properties">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        {React.createElement(TYPE_BY_KEY[field.type]?.icon || ListOrdered, { className: "h-4 w-4" })} {TYPE_BY_KEY[field.type]?.label}
      </div>
      <label className="block"><span className="text-xs font-medium text-slate-600">{field.type === "section" ? "Titre" : "Question"}</span>
        <input value={field.label} onChange={(e) => set({ label: e.target.value })} className={inputCls} data-testid="prop-label" /></label>
      <label className="block"><span className="text-xs font-medium text-slate-600">{field.type === "section" ? "Texte" : "Aide (sous la question)"}</span>
        <textarea rows={2} value={field.help || ""} onChange={(e) => set({ help: e.target.value })} className={inputCls} /></label>
      {field.type !== "section" && (
        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={!!field.required} onChange={(e) => set({ required: e.target.checked })} data-testid="prop-required" /> Obligatoire</label>
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={field.width === "half"} onChange={(e) => set({ width: e.target.checked ? "half" : "full" })} /> Demi-largeur</label>
        </div>
      )}
      {["text", "textarea", "email", "tel", "url", "number"].includes(field.type) && (
        <label className="block"><span className="text-xs font-medium text-slate-600">Texte indicatif</span>
          <input value={field.placeholder || ""} onChange={(e) => set({ placeholder: e.target.value })} className={inputCls} /></label>
      )}
      {CHOICE_TYPES.includes(field.type) && (
        <label className="block"><span className="text-xs font-medium text-slate-600">Options (une par ligne)</span>
          <textarea rows={5} value={(field.options || []).join("\n")} data-testid="prop-options"
            onChange={(e) => set({ options: e.target.value.split("\n") })}
            onBlur={(e) => set({ options: e.target.value.split("\n").map((o) => o.trim()).filter(Boolean) })} className={inputCls} /></label>
      )}
      {["number", "text", "textarea"].includes(field.type) && (
        <div className="grid grid-cols-2 gap-2">
          <label><span className="text-xs text-slate-600">{field.type === "number" ? "Minimum" : "Longueur min."}</span>
            <input type="number" value={field.min ?? ""} onChange={(e) => set({ min: e.target.value === "" ? null : Number(e.target.value) })} className={inputCls} /></label>
          <label><span className="text-xs text-slate-600">{field.type === "number" ? "Maximum" : "Longueur max."}</span>
            <input type="number" value={field.max ?? ""} onChange={(e) => set({ max: e.target.value === "" ? null : Number(e.target.value) })} className={inputCls} /></label>
        </div>
      )}
      {field.type === "rating" && (
        <label className="block"><span className="text-xs text-slate-600">Nombre d'étoiles</span>
          <select value={field.max || 5} onChange={(e) => set({ max: Number(e.target.value) })} className={inputCls}>{[3, 4, 5, 6, 7, 8, 9, 10].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
      )}
      {field.type === "table" && (
        <div className="space-y-1">
          <span className="text-xs font-medium text-slate-600">Colonnes</span>
          {(field.columns || []).map((c, i) => (
            <div key={c.key} className="flex gap-1">
              <input value={c.label} onChange={(e) => set({ columns: field.columns.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} className={inputCls} />
              <select value={c.type} onChange={(e) => set({ columns: field.columns.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)) })} className="rounded border border-slate-300 text-xs px-1">
                <option value="text">Texte</option><option value="number">Nombre</option><option value="date">Date</option></select>
              <button type="button" onClick={() => set({ columns: field.columns.filter((_, j) => j !== i) })} className="text-slate-400 hover:text-rose-600"><X className="h-4 w-4" /></button>
            </div>
          ))}
          <button type="button" onClick={() => set({ columns: [...(field.columns || []), { key: `c${Date.now().toString(36)}`, label: "Colonne", type: "text" }] })}
            className="text-xs text-primary inline-flex items-center gap-1"><Plus className="h-3 w-3" /> Colonne</button>
        </div>
      )}
      {field.type === "file" && (
        <label className="block"><span className="text-xs text-slate-600">Types acceptés (vide = tous), ex. <code>.pdf,image/*</code></span>
          <input value={field.accept || ""} onChange={(e) => set({ accept: e.target.value })} className={inputCls} /></label>
      )}
      {/* Affichage conditionnel */}
      <div className="rounded-lg bg-slate-50 p-2 space-y-1.5">
        <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-700">
          <input type="checkbox" checked={!!field.show_if} disabled={!earlier.length} data-testid="prop-condition"
            onChange={(e) => set({ show_if: e.target.checked ? { field: earlier[earlier.length - 1]?.id, equals: "" } : null })} />
          Afficher seulement si…
        </label>
        {!earlier.length && <p className="text-[11px] text-slate-400">Possible à partir de la 2ᵉ question.</p>}
        {field.show_if && (
          <div className="space-y-1">
            <select value={field.show_if.field} onChange={(e) => set({ show_if: { field: e.target.value, equals: "" } })} className={inputCls}>
              {earlier.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
            {condTarget && (CHOICE_TYPES.includes(condTarget.type) || condTarget.type === "boolean") ? (
              <select value={field.show_if.equals ?? ""} onChange={(e) => set({ show_if: { ...field.show_if, equals: e.target.value } })} className={inputCls}>
                <option value="">— valeur —</option>
                {(condTarget.type === "boolean" ? ["Oui", "Non"] : condTarget.options || []).map((o) => <option key={o} value={o}>{`= ${o}`}</option>)}
              </select>
            ) : (
              <input value={field.show_if.equals ?? ""} placeholder="valeur attendue" onChange={(e) => set({ show_if: { ...field.show_if, equals: e.target.value } })} className={inputCls} />
            )}
          </div>
        )}
      </div>
      {pages.length > 1 && (
        <label className="block"><span className="text-xs text-slate-600">Page</span>
          <select value={pageIdx} onChange={(e) => moveToPage(Number(e.target.value))} className={inputCls}>
            {pages.map((p, i) => <option key={p.id} value={i}>{p.title}</option>)}</select></label>
      )}
    </div>
  );
}

function SettingsTab({ settings, set }) {
  const s = settings || {};
  return (
    <div className="max-w-2xl space-y-4 text-sm" data-testid="form-settings">
      <label className="flex items-center gap-2"><input type="checkbox" checked={s.accepting_responses !== false} onChange={(e) => set({ accepting_responses: e.target.checked })} />
        <span><strong>Accepter les réponses</strong> — décocher pour fermer le formulaire.</span></label>
      <label className="block"><span className="font-medium">Date limite de réponse</span> <span className="text-xs text-slate-500">(facultatif)</span>
        <input type="datetime-local" value={(s.close_at || "").slice(0, 16)} onChange={(e) => set({ close_at: e.target.value || null })} className={`${inputCls} max-w-xs`} /></label>
      <label className="block"><span className="font-medium">Message affiché après l'envoi</span>
        <textarea rows={2} value={s.confirmation_message || ""} onChange={(e) => set({ confirmation_message: e.target.value })} className={inputCls} /></label>
      <fieldset className="space-y-1">
        <legend className="font-medium">Identité du répondant (lien public)</legend>
        {[["none", "Ne pas demander (réponses anonymes)"], ["optional", "Nom et e-mail facultatifs"], ["required", "Nom et e-mail obligatoires"]].map(([v, l]) => (
          <label key={v} className="flex items-center gap-2"><input type="radio" name="resp" checked={(s.respondent_info || "optional") === v} onChange={() => set({ respondent_info: v })} /> {l}</label>
        ))}
        <p className="text-xs text-slate-500">Pour un client invité, le nom et l'e-mail sont connus : rien ne lui est demandé.</p>
      </fieldset>
      <label className="flex items-center gap-2"><input type="checkbox" checked={!!s.allow_edit} onChange={(e) => set({ allow_edit: e.target.checked })} />
        Un client invité peut modifier sa réponse (sinon une seule réponse)</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={s.public_multiple !== false} onChange={(e) => set({ public_multiple: e.target.checked })} />
        Lien public : plusieurs réponses possibles avec la même adresse e-mail</label>
      <label className="block"><span className="font-medium">Prévenir par e-mail à chaque réponse</span> <span className="text-xs text-slate-500">(adresses séparées par des virgules)</span>
        <input value={(s.notify_emails || []).join(", ")} onChange={(e) => set({ notify_emails: e.target.value.split(/[,;\s]+/).filter(Boolean) })} className={inputCls} placeholder="secretariat@cabinet.bf" /></label>
    </div>
  );
}

export default function FormBuilder({ form, categories = [], onSave, saving = false }) {
  const [draft, setDraft] = useState(() => clone(form));
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("questions");
  const [pageIdx, setPageIdx] = useState(0);
  const [selected, setSelected] = useState(null);
  const [preview, setPreview] = useState(false);
  const [previewData, setPreviewData] = useState({});
  const [dragInfo, setDragInfo] = useState(null); // {kind:"new", type} | {kind:"move", index}
  const [dropIndex, setDropIndex] = useState(null);

  useEffect(() => { setDraft(clone(form)); setDirty(false); }, [form]);
  // Alerte avant de quitter la page avec des modifications non enregistrées.
  useEffect(() => {
    const h = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const pages = draft.pages?.length ? draft.pages : [newPage(1)];
  const page = pages[Math.min(pageIdx, pages.length - 1)];
  const change = (patch) => { setDraft((d) => ({ ...d, ...patch })); setDirty(true); };
  const setPages = (fn) => change({ pages: fn(clone(pages)) });
  const selField = useMemo(() => page.fields.find((f) => f.id === selected), [page, selected]);

  const insertField = (type, at) => {
    const f = newField(type);
    setPages((ps) => { const fs = ps[pageIdx].fields; fs.splice(at ?? fs.length, 0, f); return ps; });
    setSelected(f.id);
  };
  const addAfterSelected = (type) => {
    const idx = page.fields.findIndex((f) => f.id === selected);
    insertField(type, idx >= 0 ? idx + 1 : page.fields.length);
  };
  const updateField = (nf) => setPages((ps) => { ps[pageIdx].fields = ps[pageIdx].fields.map((f) => (f.id === nf.id ? nf : f)); return ps; });
  const moveField = (from, to) => setPages((ps) => { const fs = ps[pageIdx].fields; if (to < 0 || to >= fs.length) return ps; const [x] = fs.splice(from, 1); fs.splice(to, 0, x); return ps; });
  const dupField = (i) => setPages((ps) => { const c = { ...clone(ps[pageIdx].fields[i]), id: newField("text").id }; ps[pageIdx].fields.splice(i + 1, 0, c); return ps; });
  const delField = (i) => { setPages((ps) => { ps[pageIdx].fields.splice(i, 1); return ps; }); setSelected(null); };
  const moveToPage = (target) => {
    if (target === pageIdx || !selField) return;
    setPages((ps) => { ps[pageIdx].fields = ps[pageIdx].fields.filter((f) => f.id !== selField.id); ps[target].fields.push(selField); return ps; });
    setPageIdx(target);
  };

  // Glisser-déposer (HTML5 natif) : depuis la palette ou pour réordonner.
  const onDrop = (e, at) => {
    e.preventDefault();
    if (dragInfo?.kind === "new") insertField(dragInfo.type, at);
    else if (dragInfo?.kind === "move") moveField(dragInfo.index, at > dragInfo.index ? at - 1 : at);
    setDragInfo(null); setDropIndex(null);
  };

  const save = async () => {
    await onSave({ title: draft.title, description: draft.description, category_id: draft.category_id || null, pages, settings: draft.settings });
    setDirty(false);
  };

  return (
    <div className="space-y-4" data-testid="form-builder">
      {/* En-tête : titre, description, catégorie, actions */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-2">
        <div className="flex flex-wrap items-start gap-3">
          <input value={draft.title || ""} onChange={(e) => change({ title: e.target.value })} className="flex-1 min-w-[240px] text-lg font-semibold border-0 border-b border-transparent focus:border-primary focus:outline-none" placeholder="Titre du formulaire" data-testid="builder-title" />
          <select value={draft.category_id || ""} onChange={(e) => change({ category_id: e.target.value || null })} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
            <option value="">Sans catégorie</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <button type="button" onClick={() => { setPreviewData({}); setPreview(true); }} className="inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm"><Eye className="h-4 w-4" /> Aperçu</button>
          <button type="button" onClick={save} disabled={saving || !dirty} data-testid="builder-save"
            className="inline-flex items-center gap-1 rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium disabled:opacity-50">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} {dirty ? "Enregistrer" : "Enregistré"}
          </button>
        </div>
        <textarea rows={1} value={draft.description || ""} onChange={(e) => change({ description: e.target.value })} className="w-full text-sm text-slate-600 border-0 focus:outline-none resize-none" placeholder="Description (affichée en haut du formulaire)" />
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        {[["questions", "Questions", ListOrdered], ["settings", "Réglages", Settings2]].map(([k, l, I]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`inline-flex items-center gap-1 px-3 py-2 text-sm -mb-px border-b-2 ${tab === k ? "border-primary text-primary font-medium" : "border-transparent text-slate-500"}`}><I className="h-4 w-4" /> {l}</button>
        ))}
      </div>

      {tab === "settings" ? (
        <SettingsTab settings={draft.settings} set={(p) => change({ settings: { ...(draft.settings || {}), ...p } })} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[190px_1fr_280px] gap-4">
          {/* Palette */}
          <div className="space-y-1" data-testid="builder-palette">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Ajouter</p>
            <div className="grid grid-cols-2 lg:grid-cols-1 gap-1">
              {FIELD_TYPES.map((t) => (
                <button key={t.type} type="button" draggable onDragStart={() => setDragInfo({ kind: "new", type: t.type })} onDragEnd={() => setDragInfo(null)}
                  onClick={() => addAfterSelected(t.type)} data-testid={`palette-${t.type}`}
                  className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 hover:border-primary hover:text-primary cursor-grab">
                  <t.icon className="h-3.5 w-3.5" /> {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* Canevas : pages + questions */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1">
              {pages.map((p, i) => (
                <button key={p.id} type="button" onClick={() => { setPageIdx(i); setSelected(null); }}
                  className={`rounded-full px-3 py-1 text-xs border ${i === pageIdx ? "bg-primary text-primary-foreground border-primary" : "bg-white border-slate-300"}`}>{p.title} ({p.fields.length})</button>
              ))}
              <button type="button" onClick={() => { setPages((ps) => [...ps, newPage(ps.length + 1)]); setPageIdx(pages.length); }} className="rounded-full px-2 py-1 text-xs border border-dashed border-slate-400 inline-flex items-center gap-1"><Plus className="h-3 w-3" /> Page</button>
            </div>
            <div className="flex items-center gap-2">
              <input value={page.title} onChange={(e) => setPages((ps) => { ps[pageIdx].title = e.target.value; return ps; })} className={`${inputCls} max-w-xs`} aria-label="Titre de la page" />
              {pages.length > 1 && (
                <button type="button" onClick={() => { if (!page.fields.length || window.confirm(`Supprimer « ${page.title} » et ses ${page.fields.length} question(s) ?`)) { setPages((ps) => ps.filter((_, i) => i !== pageIdx)); setPageIdx(0); } }}
                  className="text-xs text-rose-600 inline-flex items-center gap-1"><Trash2 className="h-3 w-3" /> Supprimer la page</button>
              )}
            </div>
            <div className="rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/60 p-2 space-y-1.5 min-h-[200px]" data-testid="builder-canvas"
              onDragOver={(e) => { e.preventDefault(); if (dropIndex === null) setDropIndex(page.fields.length); }} onDrop={(e) => onDrop(e, dropIndex ?? page.fields.length)}>
              {page.fields.length === 0 && <p className="text-sm text-slate-400 text-center py-10">Cliquez ou glissez un type de champ depuis la palette.</p>}
              {page.fields.map((f, i) => {
                const T = TYPE_BY_KEY[f.type];
                return (
                  <div key={f.id}>
                    {dropIndex === i && dragInfo && <div className="h-1 rounded bg-primary/60 my-1" />}
                    <div draggable onDragStart={() => setDragInfo({ kind: "move", index: i })} onDragEnd={() => { setDragInfo(null); setDropIndex(null); }}
                      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); setDropIndex(e.clientY < r.top + r.height / 2 ? i : i + 1); }}
                      onClick={() => setSelected(f.id)} data-testid={`canvas-field-${i}`}
                      className={`group flex items-center gap-2 rounded-lg border bg-white px-2 py-2 cursor-pointer ${selected === f.id ? "border-primary ring-2 ring-primary/20" : "border-slate-200"}`}>
                      <GripVertical className="h-4 w-4 text-slate-300 cursor-grab shrink-0" />
                      {T && <T.icon className="h-4 w-4 text-slate-500 shrink-0" />}
                      <div className="min-w-0 flex-1">
                        <p className={`text-sm truncate ${f.type === "section" ? "font-semibold" : ""}`}>{f.label}{f.required && <span className="text-rose-600"> *</span>}</p>
                        <p className="text-[11px] text-slate-400">{T?.label}{f.width === "half" ? " · demi-largeur" : ""}{f.show_if ? " · conditionnel" : ""}</p>
                      </div>
                      <div className="flex items-center gap-0.5 opacity-60 group-hover:opacity-100">
                        <button type="button" title="Monter" onClick={(e) => { e.stopPropagation(); moveField(i, i - 1); }} className="p-1 hover:text-primary"><ArrowUp className="h-3.5 w-3.5" /></button>
                        <button type="button" title="Descendre" onClick={(e) => { e.stopPropagation(); moveField(i, i + 1); }} className="p-1 hover:text-primary"><ArrowDown className="h-3.5 w-3.5" /></button>
                        <button type="button" title="Dupliquer" onClick={(e) => { e.stopPropagation(); dupField(i); }} className="p-1 hover:text-primary"><Copy className="h-3.5 w-3.5" /></button>
                        <button type="button" title="Supprimer" onClick={(e) => { e.stopPropagation(); delField(i); }} className="p-1 hover:text-rose-600" data-testid={`canvas-delete-${i}`}><Trash2 className="h-3.5 w-3.5" /></button>
                      </div>
                    </div>
                  </div>
                );
              })}
              {dropIndex === page.fields.length && dragInfo && page.fields.length > 0 && <div className="h-1 rounded bg-primary/60 my-1" />}
            </div>
          </div>

          {/* Propriétés */}
          <div className="rounded-xl border border-slate-200 bg-white p-3 h-fit lg:sticky lg:top-4">
            {selField ? <Properties field={selField} pages={pages} pageIdx={pageIdx} update={updateField} moveToPage={moveToPage} />
              : <p className="text-sm text-slate-400">Sélectionnez une question pour la configurer.</p>}
          </div>
        </div>
      )}

      {/* Aperçu en direct */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={(e) => e.target === e.currentTarget && setPreview(false)}>
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl" data-testid="builder-preview">
            <div className="flex items-start justify-between mb-4">
              <div><p className="text-xs uppercase tracking-wide text-slate-400">Aperçu</p><h2 className="text-xl font-semibold">{draft.title}</h2>
                {draft.description && <p className="text-sm text-slate-600 mt-1 whitespace-pre-line">{draft.description}</p>}</div>
              <button type="button" onClick={() => setPreview(false)} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
            </div>
            <FormRenderer form={{ ...draft, pages }} value={previewData} onChange={setPreviewData} />
          </div>
        </div>
      )}
    </div>
  );
}
