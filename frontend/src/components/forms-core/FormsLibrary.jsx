/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormsLibrary : page « Formulaires » des gestionnaires.
    - vue d'ensemble GRAPHIQUE (1.2.0) : indicateurs colorés à chiffres animés,
      courbe des réponses des 30 derniers jours, classement des formulaires
      les plus remplis (un clic ouvre leurs statistiques) ;
    - catégories (pastilles filtrantes + gestion : ajout, couleur, suppression) ;
    - recherche, formulaires actifs / archivés ;
    - une carte par formulaire : numéro, statut (ouvert, clos, lien public),
      nombre de questions, réponses, invitations et taux de réponse ;
      actions (boutons pleins colorés, design SAWALI) : Envoyer, Éditer,
      Données (réponses), Stats, Dupliquer, Archiver / Restaurer ;
    - création : titre + catégorie, puis ouverture du constructeur.

  Props : apiBase ("/forms"), basePath ("/admin/forms"), title
*/
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Search, Send, BarChart3, Inbox, Copy, Archive, RotateCcw, FileText, Globe, Settings2, X, Loader2, Folder, Edit, Trash2, Database, Lock } from "lucide-react";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime } from "./fieldTypes";
import { ui, cx } from "./ui";
import { ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell } from "recharts";
import { PALETTE, ChartStyles, KpiCard, ChartCard, ChartTip } from "./charts";

const COLORS = ["#0F6B4A", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#0891b2", "#475569"];

function CategoriesManager({ apiBase, categories, onClose, onChanged }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLORS[0]);
  // Ajout d'une catégorie (nom + couleur choisie)
  const add = async () => {
    try { await apiClient.post(`${apiBase}/categories`, { name, color }); setName(""); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  const del = async (c) => {
    if (!window.confirm(`Supprimer la catégorie « ${c.name} » ? Ses formulaires passent en « Sans catégorie ».`)) return;
    try { await apiClient.delete(`${apiBase}/categories/${c.id}`); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  const rename = async (c) => {
    const n = window.prompt(`Renommer « ${c.name} » :`, c.name);
    if (!n || n === c.name) return;
    try { await apiClient.put(`${apiBase}/categories/${c.id}`, { name: n }); onChanged(); } catch (e) { toast.error(errorText(e)); }
  };
  return (
    <div className={ui.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={ui.modal} data-testid="categories-manager">
        <div className="flex items-center justify-between">
          <h2 className={ui.modalTitle}><Folder className={ui.modalIcon} /> Catégories ({categories.length})</h2>
          <button type="button" onClick={onClose} className={ui.close} aria-label="Fermer"><X className="h-4 w-4" /></button>
        </div>
        <p className={ui.modalText}>Les catégories rangent vos formulaires. Supprimer une catégorie ne supprime pas ses formulaires.</p>
        {/* Liste des catégories existantes */}
        <div className="space-y-2 max-h-72 overflow-y-auto">
          {categories.length === 0 && <p className="text-xs text-slate-400 italic">Aucune catégorie pour l'instant.</p>}
          {categories.map((c) => (
            <div key={c.id} className="flex items-center gap-2 px-2 py-1.5 ring-1 ring-slate-200 rounded-lg">
              <span className="h-3 w-3 rounded-full" style={{ background: c.color }} />
              <span className="flex-1 text-sm">{c.name}</span>
              <button type="button" onClick={() => rename(c)} className="text-slate-500 hover:text-slate-800 p-1" title="Renommer"><Edit className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => del(c)} className="text-rose-500 hover:bg-rose-50 rounded p-1" title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
        {/* Nouvelle catégorie : nom + couleur */}
        <div className="border-t border-slate-100 pt-3 space-y-2">
          <label className={ui.label}>Nouvelle catégorie</label>
          <div className="flex gap-2">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex. : Fiscalité" className={ui.input} />
            <button type="button" onClick={add} disabled={!name.trim()} className={ui.btnPrimary}><Plus className="h-4 w-4" /> Ajouter</button>
          </div>
          <div className="flex gap-1.5">{COLORS.map((c) => <button key={c} type="button" onClick={() => setColor(c)} className={cx("h-6 w-6 rounded-full transition", color === c && "ring-2 ring-offset-2 ring-slate-500")} style={{ background: c }} aria-label={c} />)}</div>
        </div>
      </div>
    </div>
  );
}

// Vue d'ensemble graphique de tous les formulaires actifs
function OverviewCharts({ overview, onOpenStats }) {
  const inv = overview.invitations || {};
  const series = overview.series_30d || [];
  const top = (overview.top_forms || []).filter((f) => f.submissions > 0);
  const shortDay = (d) => (d || "").slice(5).split("-").reverse().join("/");
  return (
    <div className="space-y-4" data-testid="forms-overview">
      <ChartStyles />
      {/* Indicateurs colorés à chiffres animés */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard label="Formulaires actifs" value={overview.forms} icon={FileText} theme="indigo" delay={0} />
        <KpiCard label="Réponses (total)" value={overview.submissions_total} icon={Database} theme="emerald" delay={60} />
        <KpiCard label="Réponses sur 30 jours" value={overview.submissions_30d} icon={Inbox} theme="sky" delay={120} />
        <KpiCard label="Taux de réponse des invités" value={inv.response_pct || 0} decimals={(inv.response_pct || 0) % 1 ? 1 : 0} suffix=" %" icon={BarChart3} theme="rose" delay={180}
          hint={`${inv.answered || 0} réponse(s) sur ${inv.sent || 0} invitation(s)`} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Courbe des réponses des 30 derniers jours, tous formulaires confondus */}
        <ChartCard title="Réponses des 30 derniers jours" subtitle="Tous formulaires confondus." icon={Inbox} color="#6366F1" className="lg:col-span-2" delay={100} testId="forms-overview-30d">
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ left: -22, right: 6, top: 6 }}>
                <defs>
                  <linearGradient id="fcOverviewGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366F1" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748B" }} tickFormatter={shortDay} minTickGap={18} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#64748B" }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTip labelFormatter={(d) => new Date(d).toLocaleDateString("fr-FR")} />} />
                <Area type="monotone" dataKey="count" name="Réponses" stroke="#6366F1" strokeWidth={2.5} fill="url(#fcOverviewGrad)" animationDuration={1100} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
        {/* Formulaires les plus remplis : un clic sur une barre ouvre ses statistiques */}
        <ChartCard title="Les plus remplis" subtitle="Cliquez pour voir les statistiques." icon={BarChart3} color="#10B981" delay={160} testId="forms-overview-top">
          {top.length === 0 ? <p className={ui.empty}>Aucune réponse pour l'instant.</p> : (
            <div style={{ height: Math.max(120, top.length * 34) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={top} layout="vertical" margin={{ left: 0, right: 30 }}>
                  <XAxis type="number" hide allowDecimals={false} />
                  <YAxis type="category" dataKey="title" width={110} tick={{ fontSize: 10, fill: "#475569" }} axisLine={false} tickLine={false}
                    tickFormatter={(t) => (t && t.length > 18 ? `${t.slice(0, 17)}…` : t)} />
                  <Tooltip cursor={{ fill: "#F1F5F9" }} content={<ChartTip />} />
                  <Bar dataKey="submissions" name="Réponses" radius={[0, 6, 6, 0]} barSize={16} animationDuration={900} className="cursor-pointer"
                    label={{ position: "right", fontSize: 11, fill: "#334155" }} onClick={(d) => { const id = d?.id || d?.payload?.id; if (id) onOpenStats(id); }}>
                    {top.map((f, i) => <Cell key={f.id} fill={PALETTE[i % PALETTE.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
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

  // Création : titre + catégorie, puis ouverture du constructeur
  const create = async () => {
    setBusy(true);
    try {
      const r = await apiClient.post(apiBase, { title: newTitle, category_id: newCat || null });
      navigate(`${basePath}/${r.data.id}`);
    } catch (e) { toast.error(errorText(e)); } finally { setBusy(false); }
  };
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast.success(okMsg); load(); } catch (e) { toast.error(errorText(e)); } };

  // Titre déjà utilisé : signalé dans la fenêtre de création (comme SAWALI)
  const titleConflict = (() => {
    const t = newTitle.trim().toLowerCase();
    return t ? (items || []).find((f) => (f.title || "").trim().toLowerCase() === t) || null : null;
  })();

  const catById = Object.fromEntries(categories.map((c) => [c.id, c]));
  const list = (items || []).filter((f) => (cat === "all" || (cat === "none" ? !f.category_id : f.category_id === cat))
    && (!query.trim() || `${f.title} ${f.description} ${f.number}`.toLowerCase().includes(query.trim().toLowerCase())));
  const count = (id) => (items || []).filter((f) => (id === "none" ? !f.category_id : f.category_id === id)).length;

  return (
    <div className="space-y-6" data-testid="forms-library">
      {/* En-tête : petite ligne, titre avec icône, bouton de création */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className={ui.eyebrow}>Formulaires</p>
          <h1 className={ui.h1}><FileText className={ui.h1Icon} /> {title === "Formulaires" ? "Bibliothèque de formulaires" : title}</h1>
        </div>
        <button type="button" onClick={() => setCreating(true)} className={ui.btnPrimary} data-testid="forms-new"><Plus className="h-4 w-4" /> Nouveau formulaire</button>
      </div>

      {/* Vue d'ensemble graphique (indicateurs + courbe 30 jours + top formulaires) */}
      {overview && <OverviewCharts overview={overview} onOpenStats={(id) => navigate(`${basePath}/${id}?tab=stats`)} />}

      {/* Onglets soulignés : formulaires actifs / archivés */}
      <div className={ui.tabs}>
        {[[false, "Mes formulaires"], [true, "Archivés"]].map(([k, l]) => (
          <button key={l} type="button" onClick={() => setArchived(k)} className={ui.tab(archived === k)} data-testid={`forms-tab-${k ? "archived" : "active"}`}>
            {k ? <Archive className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />} {l}
          </button>
        ))}
      </div>

      {/* Pastilles de catégories (remplies de leur couleur quand choisies) + recherche */}
      <div className="flex flex-wrap items-center gap-2" data-testid="forms-category-bar">
        <button type="button" onClick={() => setCat("all")} className={ui.chip(cat === "all")}>Tous ({(items || []).length})</button>
        {categories.map((c) => {
          const active = cat === c.id;
          return (
            <button key={c.id} type="button" onClick={() => setCat(c.id)} style={active ? { background: c.color } : {}}
              className={cx("text-xs px-3 py-1.5 rounded-full ring-1 transition inline-flex items-center gap-1", active ? "text-white ring-transparent" : "bg-white text-slate-700 ring-slate-200 hover:ring-slate-400")}>
              <Folder className="h-3 w-3" /> {c.name} <span className="opacity-70">({count(c.id)})</span>
            </button>
          );
        })}
        <button type="button" onClick={() => setCat("none")} className={cx("text-xs px-3 py-1.5 rounded-full ring-1 transition", cat === "none" ? "bg-slate-600 text-white ring-slate-600" : "bg-white text-slate-700 ring-slate-200 hover:ring-slate-400")}>
          Sans catégorie ({count("none")})
        </button>
        <button type="button" onClick={() => setManageCats(true)} className={cx(ui.btnTool, "ml-auto")} data-testid="forms-manage-cats"><Settings2 className="h-3 w-3" /> Gérer ({categories.length})</button>
        <div className={ui.searchWrap}>
          <Search className={ui.searchIcon} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Recherche (titre, description, n°)…" className={ui.searchInput} data-testid="forms-search" />
        </div>
      </div>

      {/* Cartes des formulaires */}
      {items === null ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p> : list.length === 0 ? (
        <div className={ui.empty}><FileText className="h-10 w-10 mx-auto mb-2 opacity-40" />{archived ? "Aucun formulaire archivé." : "Aucun formulaire. Créez le premier !"}</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="forms-grid">
          {list.map((f) => {
            const c = catById[f.category_id];
            const inv = f.invitations || {};
            return (
              <div key={f.id} className={cx(ui.card, "flex flex-col")} data-testid={`form-card-${f.id}`}>
                {/* Numéro + état (ouvert / clos / public) */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <code className={ui.code}>{f.number}</code>
                  <span className="flex gap-1">
                    {f.public_link_enabled && <span className={ui.badge.sky}><Globe className="h-3 w-3" /> Public</span>}
                    {f.closed_reason ? <span className={ui.badge.grey}><Lock className="h-3 w-3" /> Clos</span> : <span className={ui.badge.green}>Ouvert</span>}
                  </span>
                </div>
                <h3 className="text-sm font-display font-bold mb-1 line-clamp-2 text-slate-900">{f.title}</h3>
                {c && <span className="text-[11px] inline-flex items-center gap-1 text-slate-600 mb-1"><span className="h-2 w-2 rounded-full" style={{ background: c.color }} /> {c.name}</span>}
                <p className="text-[11px] text-slate-500 line-clamp-2 mb-2">{f.description || "—"}</p>
                {/* Chiffres clés : réponses, questions, invitations */}
                <p className="text-[10px] text-slate-400 mb-3">
                  <span className={cx(ui.badge.sky, "mb-1")} data-testid={`form-submissions-count-${f.id}`}><Database className="h-3 w-3" /> {f.submissions_count || 0} réponse(s) reçue(s)</span>
                  <span className="ml-1 text-slate-500">{f.fields_count} question(s){inv.sent ? ` · ${inv.response_pct} % de ${inv.sent} invité(s)` : ""}</span>
                  <br />Modifié le {formatDateTime(f.updated_at)}
                  {f.created_by_label && <><br />Par <strong>{f.created_by_label}</strong></>}
                </p>
                {/* Actions : boutons pleins colorés */}
                <div className="mt-auto flex gap-1 flex-wrap">
                  {archived ? (
                    <button type="button" onClick={() => act(() => apiClient.post(`${apiBase}/${f.id}/restore`), "Formulaire restauré.")} className={ui.act.emerald}><RotateCcw className="h-3.5 w-3.5" /> Restaurer</button>
                  ) : (
                    <>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=send`)} className={ui.act.primary} data-testid={`form-send-${f.id}`}><Send className="h-3.5 w-3.5" /> Envoyer</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}`)} className={ui.act.dark} data-testid={`form-edit-${f.id}`}><Edit className="h-3.5 w-3.5" /> Éditer</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=responses`)} className={ui.act.sky} title="Voir les réponses reçues"><Database className="h-3.5 w-3.5" /> Données</button>
                      <button type="button" onClick={() => navigate(`${basePath}/${f.id}?tab=stats`)} className={ui.act.indigo} title="Statistiques du formulaire"><BarChart3 className="h-3.5 w-3.5" /> Stats</button>
                      <button type="button" title="Dupliquer" onClick={() => act(() => apiClient.post(`${apiBase}/${f.id}/duplicate`), "Copie créée.")} className={ui.act.slate}><Copy className="h-3.5 w-3.5" /></button>
                      <button type="button" title="Archiver" onClick={() => { if (window.confirm(`Archiver « ${f.title} » ? Ses liens cessent de fonctionner ; les réponses sont conservées.`)) act(() => apiClient.delete(`${apiBase}/${f.id}`), "Formulaire archivé."); }} className={ui.act.danger} data-testid={`form-archive-${f.id}`}><Archive className="h-3.5 w-3.5" /></button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Fenêtre « Nouveau formulaire » */}
      {creating && (
        <div className={ui.overlay} onClick={(e) => e.target === e.currentTarget && !busy && setCreating(false)}>
          <div className={ui.modal} data-testid="forms-create">
            <h2 className={ui.modalTitle}><FileText className={ui.modalIcon} /> Nouveau formulaire</h2>
            <p className={ui.modalText}>Donnez un titre unique au formulaire, choisissez sa catégorie, puis construisez les questions.</p>
            <div>
              <label className={ui.label}>Titre du formulaire</label>
              <input autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && newTitle.trim() && !titleConflict && create()}
                placeholder="Ex. : Questionnaire de satisfaction 2026" className={titleConflict ? ui.inputError : ui.input} data-testid="forms-create-title" />
              {titleConflict && <p className={ui.error} data-testid="forms-title-conflict">Un formulaire porte déjà ce titre : <strong>{titleConflict.number}</strong></p>}
            </div>
            <div>
              <label className={ui.label}>Catégorie</label>
              <select value={newCat} onChange={(e) => setNewCat(e.target.value)} className={ui.select}>
                <option value="">Sans catégorie</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            </div>
            <div className={ui.modalFooter}>
              <button type="button" onClick={() => setCreating(false)} disabled={busy} className={ui.btnSecondary}>Annuler</button>
              <button type="button" onClick={create} disabled={!newTitle.trim() || busy || !!titleConflict} className={ui.btnPrimary} data-testid="forms-create-submit">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Créer et construire</button>
            </div>
          </div>
        </div>
      )}
      {manageCats && <CategoriesManager apiBase={apiBase} categories={categories} onClose={() => setManageCats(false)} onChanged={loadCats} />}
    </div>
  );
}
