/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormsLibrary : page « Formulaires » des gestionnaires.
    - vue d'ensemble (formulaires, réponses sur 30 jours, taux de réponse) ;
    - catégories (pastilles filtrantes + gestion : ajout, couleur, suppression) ;
    - recherche, formulaires actifs / archivés ;
    - une carte par formulaire : numéro, statut (ouvert, clos, lien public),
      nombre de questions, réponses, invitations et taux de réponse ;
      actions : Ouvrir, Envoyer, Réponses, Statistiques, Dupliquer, Archiver /
      Restaurer ;
    - création : titre + catégorie, puis ouverture du constructeur.

  Props : apiBase ("/forms"), basePath ("/admin/forms"), title
*/
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Search, Send, BarChart3, Inbox, Copy, Archive, RotateCcw, FileText, Globe, Settings2, X, Loader2, ClipboardList } from "lucide-react";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime } from "./fieldTypes";

const COLORS = ["#0F6B4A", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#0891b2", "#475569"];

function CategoriesManager({ apiBase, categories, onClose, onChanged }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLORS[0]);
  const add = async () => {
    try { await apiClient.post(`${apiBase}/categories`, { name, color }); setName(""); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  const del = async (c) => {
    if (!window.confirm(`Supprimer la catégorie « ${c.name} » ? Ses formulaires passent en « Sans catégorie ».`)) return;
    try { await apiClient.delete(`${apiBase}/categories/${c.id}`); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  const rename = async (c) => {
    const n = window.prompt("Nouveau nom", c.name);
    if (!n || n === c.name) return;
    try { await apiClient.put(`${apiBase}/categories/${c.id}`, { name: n }); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl space-y-3" data-testid="categories-manager">
        <div className="flex justify-between"><h3 className="font-semibold">Catégories</h3><button type="button" onClick={onClose}><X className="h-5 w-5 text-slate-400" /></button></div>
        <ul className="space-y-1">
          {categories.map((c) => (
            <li key={c.id} className="flex items-center gap-2 text-sm">
              <span className="h-3 w-3 rounded-full" style={{ background: c.color }} /> <span className="flex-1">{c.name}</span>
              <button type="button" onClick={() => rename(c)} className="text-xs text-slate-500 underline">Renommer</button>
              <button type="button" onClick={() => del(c)} className="text-xs text-rose-600 underline">Supprimer</button>
            </li>
          ))}
          {categories.length === 0 && <li className="text-xs text-slate-400">Aucune catégorie.</li>}
        </ul>
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nouvelle catégorie" className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          <button type="button" onClick={add} disabled={!name.trim()} className="rounded-lg bg-primary text-primary-foreground px-3 text-sm disabled:opacity-50">Ajouter</button>
        </div>
        <div className="flex gap-1">{COLORS.map((c) => <button key={c} type="button" onClick={() => setColor(c)} className={`h-6 w-6 rounded-full ${color === c ? "ring-2 ring-offset-1 ring-slate-500" : ""}`} style={{ background: c }} aria-label={c} />)}</div>
      </div>
    </div>
  );
}

export default function FormsLibrary({ apiBase = "/forms", basePath = "/admin/forms", title = "Formulaires" }) {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [archived, setArchived] = useState(false);
  const [categories, setCategories] = useState([]);
  const [cat, setCat] = useState("all");
  const [query, setQuery] = useState("");
  const [overview, setOverview] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newCat, setNewCat] = useState("");
  const [busy, setBusy] = useState(false);
  const [manageCats, setManageCats] = useState(false);

  const load = () => {
    apiClient.get(apiBase, { params: { archived } }).then((r) => setItems(r.data.items || [])).catch((e) => { toast.error(errorText(e)); setItems([]); });
    apiClient.get(`${apiBase}/overview`).then((r) => setOverview(r.data)).catch(() => {});
  };
  const loadCats = () => apiClient.get(`${apiBase}/categories`).then((r) => setCategories(r.data.items || [])).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [archived]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadCats(); }, []);

  const create = async () => {
    setBusy(true);
    try {
      const r = await apiClient.post(apiBase, { title: newTitle, category_id: newCat || null });
      navigate(`${basePath}/${r.data.id}`);
    } catch (e) { toast.error(errorText(e)); } finally { setBusy(false); }
  };
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast.success(okMsg); load(); } catch (e) { toast.error(errorText(e)); } };

  const catById = Object.fromEntries(categories.map((c) => [c.id, c]));
  const list = (items || []).filter((f) => (cat === "all" || (cat === "none" ? !f.category_id : f.category_id === cat))
    && (!query.trim() || `${f.title} ${f.description} ${f.number}`.toLowerCase().includes(query.trim().toLowerCase())));
  const count = (id) => (items || []).filter((f) => (id === "none" ? !f.category_id : f.category_id === id)).length;

  return (
    <div className="space-y-5" data-testid="forms-library">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-display font-semibold inline-flex items-center gap-2"><ClipboardList className="h-6 w-6 text-primary" /> {title}</h1>
        <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium" data-testid="forms-new"><Plus className="h-4 w-4" /> Nouveau formulaire</button>
      </div>

      {overview && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="forms-overview">
          {[["Formulaires actifs", overview.forms], ["Réponses (total)", overview.submissions_total], ["Réponses sur 30 jours", overview.submissions_30d],
            ["Taux de réponse des invités", `${overview.invitations?.response_pct || 0} %`]].map(([l, v]) => (
            <div key={l} className="rounded-xl border border-slate-200 bg-white px-4 py-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{l}</p><p className="text-2xl font-semibold tabular-nums">{v}</p></div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {[["all", "Tous", (items || []).length], ...categories.map((c) => [c.id, c.name, count(c.id), c.color]), ["none", "Sans catégorie", count("none")]].map(([id, l, n, color]) => (
          <button key={id} type="button" onClick={() => setCat(id)} className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs border ${cat === id ? "bg-primary text-primary-foreground border-primary" : "bg-white border-slate-300"}`}>
            {color && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}{l} ({n})
          </button>
        ))}
        <button type="button" onClick={() => setManageCats(true)} className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-400 px-2.5 py-1 text-xs"><Settings2 className="h-3 w-3" /> Catégories</button>
        <div className="relative ml-auto"><Search className="h-4 w-4 text-slate-400 absolute left-2.5 top-2" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher…" className="rounded-lg border border-slate-300 pl-8 pr-3 py-1.5 text-sm" /></div>
        <button type="button" onClick={() => setArchived(!archived)} className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs ${archived ? "bg-slate-800 text-white" : ""}`}><Archive className="h-3.5 w-3.5" /> {archived ? "Voir les actifs" : "Archivés"}</button>
      </div>

      {items === null ? <p className="text-sm text-slate-500 inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p> : list.length === 0 ? (
        <div className="text-center py-16 text-slate-400"><FileText className="h-10 w-10 mx-auto mb-2" /><p className="text-sm">{archived ? "Aucun formulaire archivé." : "Aucun formulaire. Créez le premier !"}</p></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {list.map((f) => {
            const c = catById[f.category_id];
            const inv = f.invitations || {};
            return (
              <div key={f.id} className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col gap-2" data-testid={`form-card-${f.id}`}>
                <div className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="font-mono text-slate-500">{f.number}</span>
                  <span className="flex gap-1">
                    {f.public_link_enabled && <span className="inline-flex items-center gap-0.5 rounded-full bg-sky-50 text-sky-700 px-2 py-0.5"><Globe className="h-3 w-3" /> Public</span>}
                    <span className={`rounded-full px-2 py-0.5 ${f.closed_reason ? "bg-slate-100 text-slate-600" : "bg-emerald-50 text-emerald-700"}`}>{f.closed_reason ? "Clos" : "Ouvert"}</span>
                  </span>
                </div>
                <button type="button" onClick={() => navigate(`${basePath}/${f.id}`)} className="text-left font-semibold text-slate-900 hover:text-primary">{f.title}</button>
                {c && <span className="text-[11px] inline-flex items-center gap-1 text-slate-600"><span className="h-2 w-2 rounded-full" style={{ background: c.color }} /> {c.name}</span>}
                {f.description && <p className="text-xs text-slate-500 line-clamp-2">{f.description}</p>}
                <div className="grid grid-cols-3 gap-2 text-center text-xs mt-1">
                  <div className="rounded-lg bg-slate-50 py-1.5"><p className="font-semibold text-sm">{f.fields_count}</p>questions</div>
                  <div className="rounded-lg bg-slate-50 py-1.5"><p className="font-semibold text-sm">{f.submissions_count || 0}</p>réponses</div>
                  <div className="rounded-lg bg-slate-50 py-1.5"><p className="font-semibold text-sm">{inv.sent ? `${inv.response_pct} %` : "—"}</p>{inv.sent ? `de ${inv.sent} invités` : "invités"}</div>
                </div>
                <p className="text-[11px] text-slate-400">Modifié le {formatDateTime(f.updated_at)}{f.created_by_label ? ` · créé par ${f.created_by_label}` : ""}</p>
                <div className="flex flex-wrap gap-1 mt-auto pt-2">
                  {archived ? (
                    <button type="button" onClick={() => act(() => apiClient.post(`${apiBase}/${f.id}/restore`), "Formulaire restauré.")} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs"><RotateCcw className="h-3.5 w-3.5" /> Restaurer</button>
                  ) : (
                    <>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}`)} className="rounded-lg bg-primary text-primary-foreground px-2.5 py-1 text-xs">Ouvrir</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=send`)} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs"><Send className="h-3.5 w-3.5" /> Envoyer</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=responses`)} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs"><Inbox className="h-3.5 w-3.5" /> Réponses</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=stats`)} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs"><BarChart3 className="h-3.5 w-3.5" /> Stats</button>
                      <button type="button" title="Dupliquer" onClick={() => act(() => apiClient.post(`${apiBase}/${f.id}/duplicate`), "Copie créée.")} className="rounded-lg border px-2 py-1 text-xs"><Copy className="h-3.5 w-3.5" /></button>
                      <button type="button" title="Archiver" onClick={() => { if (window.confirm(`Archiver « ${f.title} » ? Ses liens cessent de fonctionner ; les réponses sont conservées.`)) act(() => apiClient.delete(`${apiBase}/${f.id}`), "Formulaire archivé."); }} className="rounded-lg border px-2 py-1 text-xs text-rose-600"><Archive className="h-3.5 w-3.5" /></button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && setCreating(false)}>
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl space-y-3" data-testid="forms-create">
            <h3 className="font-semibold">Nouveau formulaire</h3>
            <input autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && newTitle.trim() && create()}
              placeholder="Ex. : Questionnaire de satisfaction 2026" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="forms-create-title" />
            <select value={newCat} onChange={(e) => setNewCat(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">Sans catégorie</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setCreating(false)} className="px-3 py-1.5 text-sm text-slate-600">Annuler</button>
              <button type="button" onClick={create} disabled={!newTitle.trim() || busy} className="inline-flex items-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-1.5 text-sm disabled:opacity-50" data-testid="forms-create-submit">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} Créer et construire</button>
            </div>
          </div>
        </div>
      )}
      {manageCats && <CategoriesManager apiBase={apiBase} categories={categories} onClose={() => setManageCats(false)} onChanged={loadCats} />}
    </div>
  );
}
