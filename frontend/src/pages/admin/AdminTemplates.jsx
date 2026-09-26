/*
  « Documents & modèles » (lot 7) — ordres / avis de mission, courriers,
  attestations… rédigés dans un éditeur « comme Word ».

  Onglet « Modèles » : une carte par modèle (catégorie, numérotation, auteur,
  cadenas) avec Générer · Éditer · Dupliquer · Verrouiller/Déverrouiller ·
  Supprimer.
  Éditeur de modèle : nom, catégorie, papier à en-tête, format du numéro
  (ex. {n}/GESP/DG/{annee}), prochain numéro, titre des documents, VARIABLES
  (commune = même valeur pour tous ; par destinataire = une valeur par client)
  et le texte mis en forme où l'on place les variables.
  Génération : destinataires cochés, valeurs communes, tableau des valeurs par
  destinataire, date, papier, dépôt dans l'espace client → autant de documents
  (PDF avec QR code), impression groupée.
  Onglet « Documents générés » : PDF, Word, suppression.

  Adresse : /admin/modeles (?generate=<modèle>&tenant=<client>&mission=<mission>)
*/
import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  FileSignature, Plus, Edit, Copy, Lock, Unlock, Trash2, Wand2, Loader2, ArrowLeft, Save, Eye, Printer, FileText,
  Download, Search, Users, X,
} from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { openServerFile } from "@/lib/docfiles";
import RichTextEditor from "@/components/RichTextEditor";
import DocSettingsPanel from "@/pages/admin/DocSettingsPanel";
import { ui, cx } from "@/components/forms-core/ui";

const today = () => new Date().toISOString().slice(0, 10);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");
const emptyTemplate = { name: "", category: "courrier", body_html: "", variables: [], number_format: "{n}/{annee}", next_number: 1, letterhead_id: "", title_pattern: "" };

// ---------------------------------------------------------------- éditeur de modèle
function TemplateEditor({ initial, catalog, letterheads, onClose, onSaved }) {
  const [tpl, setTpl] = useState({ ...emptyTemplate, ...initial });
  const [saving, setSaving] = useState(false);
  const locked = Boolean(initial?.locked);

  // Liste du menu « Variable » : automatiques + variables du modèle
  const varList = useMemo(() => [
    ...Object.entries(catalog?.system_variables || {}).map(([key, label]) => ({
      key, label, group: key.startsWith("client.") ? "Client" : key.startsWith("mission.") ? "Mission" : "Document",
    })),
    ...tpl.variables.filter((v) => v.key).map((v) => ({ key: v.key, label: v.label || v.key, group: "Variables du modèle" })),
  ], [catalog, tpl.variables]);

  const setVar = (i, patch) => setTpl({ ...tpl, variables: tpl.variables.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  const addVar = () => setTpl({ ...tpl, variables: [...tpl.variables, { key: "", label: "", scope: "recipient", default: "" }] });

  // Enregistrement (création ou modification)
  const save = async () => {
    if (!tpl.name.trim()) { toast.error("Donnez un nom au modèle"); return; }
    setSaving(true);
    try {
      const body = { ...tpl, letterhead_id: tpl.letterhead_id || null, next_number: Number(tpl.next_number) || 1,
        variables: tpl.variables.filter((v) => v.key.trim()).map((v) => ({ ...v, label: v.label || v.key })) };
      const { data } = tpl.id ? await apiClient.put(`/letters/templates/${tpl.id}`, body) : await apiClient.post("/letters/templates", body);
      toast.success("Modèle enregistré");
      onSaved(data);
    } catch (e) { toast.error(extractError(e)); } finally { setSaving(false); }
  };

  return (
    <div className="space-y-4" data-testid="template-editor">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onClose} className={ui.btnGhost}><ArrowLeft className="h-4 w-4" /> Modèles</button>
        <div className="flex gap-2">
          {locked && <span className={ui.badge.amber}><Lock className="h-3 w-3" /> Verrouillé — lecture seule</span>}
          <button type="button" onClick={save} disabled={saving || locked} className={ui.btnPrimary} data-testid="template-save">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer le modèle
          </button>
        </div>
      </div>
      <div className={cx(ui.card, "grid grid-cols-1 md:grid-cols-3 gap-3")}>
        <label className="block md:col-span-2"><span className={ui.label}>Nom du modèle</span>
          <input value={tpl.name} onChange={(e) => setTpl({ ...tpl, name: e.target.value })} className={ui.input} placeholder="ex. Ordre de mission" data-testid="template-name" /></label>
        <label className="block"><span className={ui.label}>Catégorie</span>
          <select value={tpl.category} onChange={(e) => setTpl({ ...tpl, category: e.target.value })} className={ui.select}>
            {Object.entries(catalog?.categories || {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
        <label className="block"><span className={ui.label}>Format du numéro</span>
          <input value={tpl.number_format} onChange={(e) => setTpl({ ...tpl, number_format: e.target.value })} className={ui.input} placeholder="{n}/GESP/DG/{annee}" />
          <span className={ui.help}>{"{n}"} = numéro, {"{annee}"}, {"{mois}"}, {"{n:03}"} = sur 3 chiffres</span></label>
        <label className="block"><span className={ui.label}>Prochain numéro</span>
          <input type="number" min="1" value={tpl.next_number} onChange={(e) => setTpl({ ...tpl, next_number: e.target.value })} className={ui.input} data-testid="template-next" /></label>
        <label className="block"><span className={ui.label}>Papier à en-tête</span>
          <select value={tpl.letterhead_id || ""} onChange={(e) => setTpl({ ...tpl, letterhead_id: e.target.value })} className={ui.select}>
            <option value="">Papier par défaut</option>
            <option value="none">Aucun en-tête</option>
            {letterheads.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select></label>
        <label className="block md:col-span-3"><span className={ui.label}>Titre des documents produits (facultatif)</span>
          <input value={tpl.title_pattern} onChange={(e) => setTpl({ ...tpl, title_pattern: e.target.value })} className={ui.input} placeholder="ex. Avis de mission — {{client.nom}}" /></label>
      </div>

      {/* Variables propres au modèle */}
      <div className={ui.panel}>
        <div className="flex items-center justify-between">
          <p className={ui.panelTitle}><Wand2 className={ui.panelIcon} /> Variables du modèle</p>
          <button type="button" onClick={addVar} className={ui.act.sky} data-testid="template-add-var"><Plus className="h-3.5 w-3.5" /> Ajouter une variable</button>
        </div>
        <p className="text-xs text-slate-500">Les variables automatiques (client, date, numéro, signataire, mission) sont déjà disponibles dans le menu « Variable » de l'éditeur. Ajoutez ici les éléments qui changent d'un document à l'autre : <b>commune</b> = même valeur pour tous les destinataires, <b>par destinataire</b> = une valeur par client.</p>
        {tpl.variables.length === 0 && <p className={ui.empty}>Aucune variable propre à ce modèle.</p>}
        {tpl.variables.map((v, i) => (
          <div key={i} className="grid grid-cols-1 md:grid-cols-12 gap-2 items-end" data-testid={`template-var-${i}`}>
            <label className="md:col-span-3"><span className={ui.label}>Libellé</span>
              <input value={v.label} onChange={(e) => setVar(i, { label: e.target.value, key: v.key || e.target.value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) })} className={ui.input} placeholder="ex. Période de la mission" /></label>
            <label className="md:col-span-3"><span className={ui.label}>Code</span>
              <input value={v.key} onChange={(e) => setVar(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} className={cx(ui.input, "font-mono")} placeholder="periode_mission" /></label>
            <label className="md:col-span-2"><span className={ui.label}>Valeur</span>
              <select value={v.scope} onChange={(e) => setVar(i, { scope: e.target.value })} className={ui.select}>
                <option value="recipient">Par destinataire</option><option value="common">Commune</option>
              </select></label>
            <label className="md:col-span-3"><span className={ui.label}>Valeur par défaut</span>
              <input value={v.default} onChange={(e) => setVar(i, { default: e.target.value })} className={ui.input} /></label>
            <button type="button" onClick={() => setTpl({ ...tpl, variables: tpl.variables.filter((_, j) => j !== i) })} className={cx(ui.act.iconDanger, "md:col-span-1 mb-1")} title="Retirer"><X className="h-3.5 w-3.5" /></button>
          </div>
        ))}
      </div>

      {/* Texte du modèle, avec la barre de mise en forme */}
      <RichTextEditor value={tpl.body_html} onChange={(html) => setTpl((t) => ({ ...t, body_html: html }))} variables={varList} minHeight={520} testId="template-body" />
    </div>
  );
}

// ---------------------------------------------------------------- génération
function GenerateWizard({ template, letterheads, preset, onClose, onDone }) {
  const [full, setFull] = useState(null);
  const [clients, setClients] = useState([]);
  const [selected, setSelected] = useState(preset?.tenant ? [preset.tenant] : []);
  const [search, setSearch] = useState("");
  const [common, setCommon] = useState({});
  const [perClient, setPerClient] = useState({});
  const [docDate, setDocDate] = useState(today());
  const [letterheadId, setLetterheadId] = useState("");
  const [deposit, setDeposit] = useState(false);
  const [notify, setNotify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  // Modèle complet (variables) + liste des clients actifs
  useEffect(() => {
    apiClient.get(`/letters/templates/${template.id}`).then(({ data }) => {
      setFull(data);
      setCommon(Object.fromEntries(data.variables.filter((v) => v.scope === "common").map((v) => [v.key, v.default || ""])));
    }).catch((e) => toast.error(extractError(e)));
    apiClient.get("/clients").then(({ data }) => setClients((data || []).filter((c) => c.is_active !== false))).catch(() => setClients([]));
  }, [template.id]);

  const recipientVars = (full?.variables || []).filter((v) => v.scope === "recipient");
  const commonVars = (full?.variables || []).filter((v) => v.scope === "common");
  const shown = clients.filter((c) => !search || `${c.full_name} ${c.company || ""} ${c.email || ""}`.toLowerCase().includes(search.toLowerCase()));
  const nameOf = (id) => { const c = clients.find((x) => x.id === id); return c ? (c.company || c.full_name) : id; };
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const cellValue = (tid, v) => perClient[tid]?.[v.key] ?? v.default ?? "";
  const setCell = (tid, key, val) => setPerClient((p) => ({ ...p, [tid]: { ...(p[tid] || {}), [key]: val } }));

  const payload = () => ({
    tenant_ids: selected, common_values: common, doc_date: docDate, letterhead_id: letterheadId || null,
    mission_id: preset?.mission || null, deposit, notify: deposit && notify,
    recipient_values: Object.fromEntries(selected.map((tid) => [tid, Object.fromEntries(recipientVars.map((v) => [v.key, cellValue(tid, v)]))])),
  });

  const previewPdf = () => {
    if (!selected.length) { toast.error("Cochez au moins un destinataire"); return; }
    openServerFile(`/letters/templates/${template.id}/preview`, { method: "post", data: payload() });
  };
  const generate = async () => {
    if (!selected.length) { toast.error("Cochez au moins un destinataire"); return; }
    if (!window.confirm(`Générer ${selected.length} document(s) « ${template.name} » ?`)) return;
    setBusy(true);
    try {
      const { data } = await apiClient.post(`/letters/templates/${template.id}/generate`, payload());
      setResult(data);
      toast.success(`${data.count} document(s) générés`);
      onDone?.();
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };

  if (!full) return <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline" /> Chargement…</p>;

  return (
    <div className="space-y-4" data-testid="generate-wizard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onClose} className={ui.btnGhost}><ArrowLeft className="h-4 w-4" /> Modèles</button>
        <h2 className={ui.panelTitle}><Wand2 className={ui.panelIcon} /> Générer : {template.name}</h2>
      </div>
      {preset?.mission && <p className={cx(ui.badge.violet, "text-xs")}>Depuis une mission : les variables « Mission » sont remplies automatiquement.</p>}

      {result ? (
        // Compte rendu : liste des documents produits
        <div className={ui.panel} data-testid="generate-result">
          <p className="font-semibold text-emerald-700">{result.count} document(s) produits.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => openServerFile("/letters/documents/merged-pdf", { method: "post", data: { batch_id: result.batch_id } })} className={ui.act.dark} data-testid="generate-print-all"><Printer className="h-3.5 w-3.5" /> Tout imprimer (un seul PDF)</button>
            <button type="button" onClick={() => { setResult(null); setSelected([]); }} className={ui.act.sky}><Plus className="h-3.5 w-3.5" /> Nouvelle génération</button>
          </div>
          <table className={ui.table}><thead className={ui.thead}><tr><th className={ui.th}>N°</th><th className={ui.th}>Destinataire</th><th className={ui.th}>Espace client</th><th className={ui.th}></th></tr></thead>
            <tbody>{result.items.map((d) => (
              <tr key={d.id} className={ui.tr}><td className={cx(ui.td, "font-mono text-xs")}>{d.number}</td><td className={ui.td}>{d.recipient_name}</td>
                <td className={ui.td}>{d.client_document_id ? <span className={ui.badge.green}>Déposé</span> : "—"}</td>
                <td className={cx(ui.td, "text-right space-x-1")}>
                  <button type="button" onClick={() => openServerFile(`/letters/documents/${d.id}/pdf`)} className={ui.act.primary}><FileText className="h-3.5 w-3.5" /> PDF</button>
                  <button type="button" onClick={() => openServerFile(`/letters/documents/${d.id}/word`, { download: true, filename: `${d.number.replace(/\//g, "-")}.doc` })} className={ui.act.sky}><Download className="h-3.5 w-3.5" /> Word</button>
                </td></tr>))}</tbody></table>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* 1. Destinataires */}
            <div className={ui.panel}>
              <div className="flex items-center justify-between gap-2">
                <p className={ui.panelTitle}><Users className={ui.panelIcon} /> Destinataires <span className={ui.badge.sky}>{selected.length}</span></p>
                <div className="relative w-48"><Search className="absolute left-2 top-2.5 h-3.5 w-3.5 text-slate-400" />
                  <input value={search} onChange={(e) => setSearch(e.target.value)} className={cx(ui.inputSm, "pl-7")} placeholder="Rechercher…" data-testid="generate-search" /></div>
              </div>
              <label className={ui.checkLabel}><input type="checkbox" className={ui.check} checked={shown.length > 0 && shown.every((c) => selected.includes(c.id))}
                onChange={(e) => setSelected(e.target.checked ? [...new Set([...selected, ...shown.map((c) => c.id)])] : selected.filter((id) => !shown.some((c) => c.id === id)))} /> Tout sélectionner ({shown.length})</label>
              <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-100">
                {shown.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-slate-50" data-testid={`generate-client-${c.id}`}>
                    <input type="checkbox" className={ui.check} checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
                    <span className="font-medium">{c.company || c.full_name}</span><span className="text-xs text-slate-400 truncate">{c.company ? c.full_name : c.email}</span>
                  </label>
                ))}
              </div>
            </div>
            {/* 2. Réglages communs */}
            <div className={ui.panel}>
              <p className={ui.panelTitle}><FileSignature className={ui.panelIcon} /> Valeurs communes</p>
              <div className="grid grid-cols-2 gap-3">
                <label className="block"><span className={ui.label}>Date du document</span><input type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className={ui.input} /></label>
                <label className="block"><span className={ui.label}>Papier à en-tête</span>
                  <select value={letterheadId} onChange={(e) => setLetterheadId(e.target.value)} className={ui.select}>
                    <option value="">Celui du modèle</option><option value="none">Aucun en-tête</option>
                    {letterheads.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                  </select></label>
              </div>
              {commonVars.map((v) => (
                <label key={v.key} className="block"><span className={ui.label}>{v.label}</span>
                  <input value={common[v.key] ?? ""} onChange={(e) => setCommon({ ...common, [v.key]: e.target.value })} className={ui.input} data-testid={`generate-common-${v.key}`} /></label>
              ))}
              <div className="space-y-1 pt-1">
                <label className={ui.checkLabel}><input type="checkbox" className={ui.check} checked={deposit} onChange={(e) => setDeposit(e.target.checked)} data-testid="generate-deposit" /> Déposer chaque document dans l'espace du client (Courrier)</label>
                <label className={cx(ui.checkLabel, !deposit && "opacity-40")}><input type="checkbox" className={ui.check} disabled={!deposit} checked={deposit && notify} onChange={(e) => setNotify(e.target.checked)} /> et prévenir le client (WhatsApp ou e-mail)</label>
              </div>
            </div>
          </div>

          {/* 3. Valeurs par destinataire */}
          {recipientVars.length > 0 && selected.length > 0 && (
            <div className={cx(ui.card, "overflow-x-auto")} data-testid="generate-grid">
              <p className={cx(ui.panelTitle, "mb-2")}>Valeurs par destinataire</p>
              <table className={ui.table}>
                <thead className={ui.thead}><tr><th className={ui.th}>Destinataire</th>{recipientVars.map((v) => <th key={v.key} className={ui.th}>{v.label}</th>)}</tr></thead>
                <tbody>{selected.map((tid) => (
                  <tr key={tid} className={ui.tr}><td className={cx(ui.td, "font-medium whitespace-nowrap")}>{nameOf(tid)}</td>
                    {recipientVars.map((v) => <td key={v.key} className={ui.td}><input value={cellValue(tid, v)} onChange={(e) => setCell(tid, v.key, e.target.value)} className={ui.inputSm} /></td>)}
                  </tr>))}</tbody>
              </table>
            </div>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={previewPdf} className={ui.btnSecondary} data-testid="generate-preview"><Eye className="h-4 w-4" /> Aperçu (1er destinataire)</button>
            <button type="button" onClick={generate} disabled={busy || !selected.length} className={ui.btnPrimary} data-testid="generate-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />} Générer {selected.length} document(s)
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- page
export default function AdminTemplates() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState("templates");
  const [catalog, setCatalog] = useState(null);
  const [templates, setTemplates] = useState(null);
  const [docs, setDocs] = useState(null);
  const [letterheads, setLetterheads] = useState([]);
  const [editing, setEditing] = useState(null);       // modèle ouvert dans l'éditeur
  const [generating, setGenerating] = useState(null); // modèle en cours de génération
  const [cat, setCat] = useState("all");
  const preset = { tenant: params.get("tenant") || "", mission: params.get("mission") || "" };

  const load = () => {
    apiClient.get("/letters/templates").then(({ data }) => setTemplates(data)).catch((e) => toast.error(extractError(e)));
    apiClient.get("/letters/documents").then(({ data }) => setDocs(data)).catch(() => setDocs([]));
  };
  useEffect(() => {
    load();
    apiClient.get("/letters/catalog").then(({ data }) => setCatalog(data)).catch(() => {});
    apiClient.get("/admin/letterheads").then(({ data }) => setLetterheads(data)).catch(() => {});
  }, []);

  // Arrivée depuis une mission : ouvre directement la génération du modèle demandé
  useEffect(() => {
    const want = params.get("generate");
    if (want && templates) {
      const t = templates.find((x) => x.id === want) || templates.find((x) => x.category === want);
      if (t) setGenerating(t);
    }
  }, [params, templates]);

  const openEditor = async (t) => {
    if (!t) { setEditing({ ...emptyTemplate }); return; }
    try { const { data } = await apiClient.get(`/letters/templates/${t.id}`); setEditing(data); } catch (e) { toast.error(extractError(e)); }
  };
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast.success(okMsg); load(); } catch (e) { toast.error(extractError(e)); } };

  if (editing) return <TemplateEditor initial={editing} catalog={catalog} letterheads={letterheads} onClose={() => setEditing(null)} onSaved={(d) => { setEditing(d); load(); }} />;
  if (generating) return <GenerateWizard template={generating} letterheads={letterheads} preset={preset} onDone={load}
    onClose={() => { setGenerating(null); if (params.get("generate")) setParams({}); }} />;

  const shownTemplates = (templates || []).filter((t) => cat === "all" || t.category === cat);
  return (
    <div className="space-y-6" data-testid="admin-templates-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className={ui.eyebrow}>Cabinet</p>
          <h1 className={ui.h1}><FileSignature className={ui.h1Icon} /> Documents & modèles</h1>
          <p className={ui.subtitle}>Ordres et avis de mission, courriers, attestations : rédigez-les comme dans Word, enregistrez-les comme modèles à variables, puis générez un document par client en une fois.</p>
        </div>
        <button type="button" onClick={() => openEditor(null)} className={ui.btnPrimary} data-testid="template-new"><Plus className="h-4 w-4" /> Nouveau modèle</button>
      </div>
      {preset.mission && <p className={ui.badge.violet}>Choisissez le modèle à générer pour la mission sélectionnée (bouton « Générer »).</p>}

      <div className={ui.tabs}>
        <button type="button" onClick={() => setTab("templates")} className={ui.tab(tab === "templates")} data-testid="tab-templates"><FileSignature className="h-3.5 w-3.5" /> Modèles ({(templates || []).length})</button>
        <button type="button" onClick={() => setTab("docs")} className={ui.tab(tab === "docs")} data-testid="tab-docs"><FileText className="h-3.5 w-3.5" /> Documents générés ({(docs || []).length})</button>
        <button type="button" onClick={() => setTab("paper")} className={ui.tab(tab === "paper")} data-testid="tab-paper"><Printer className="h-3.5 w-3.5" /> Papiers à en-tête & signataire</button>
      </div>

      {tab === "paper" ? <DocSettingsPanel /> : tab === "templates" ? (
        <>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setCat("all")} className={ui.chip(cat === "all")}>Tous</button>
            {Object.entries(catalog?.categories || {}).map(([k, l]) => <button key={k} type="button" onClick={() => setCat(k)} className={ui.chip(cat === k)}>{l}</button>)}
          </div>
          {templates === null ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline" /> Chargement…</p> : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {shownTemplates.length === 0 && <p className={ui.empty}>Aucun modèle.</p>}
              {shownTemplates.map((t) => (
                <div key={t.id} className={cx(ui.card, "flex flex-col gap-2")} data-testid={`template-card-${t.id}`}>
                  <div className="flex items-start justify-between gap-2">
                    <span className={ui.badge.violet}>{t.category_label}</span>
                    {t.locked ? <span className={ui.badge.amber} title={`Verrouillé par ${t.locked_by_name || ""}`}><Lock className="h-3 w-3" /> Verrouillé</span> : <span className={ui.badge.green}>Modifiable</span>}
                  </div>
                  <p className="font-display font-bold text-slate-900">{t.name}</p>
                  <p className="text-xs text-slate-500 line-clamp-3">{t.excerpt || "—"}</p>
                  <p className="text-[11px] text-slate-400">N° suivant : <code className={ui.code}>{t.number_format?.replace("{n}", t.next_number).replace("{annee}", new Date().getFullYear())}</code> · {t.generated_count || 0} document(s) · {t.variables?.length || 0} variable(s)</p>
                  <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                    <button type="button" onClick={() => setGenerating(t)} className={ui.act.primary} data-testid={`template-generate-${t.id}`}><Wand2 className="h-3.5 w-3.5" /> Générer</button>
                    <button type="button" onClick={() => openEditor(t)} className={ui.act.dark} data-testid={`template-edit-${t.id}`}><Edit className="h-3.5 w-3.5" /> {t.locked ? "Voir" : "Éditer"}</button>
                    <button type="button" onClick={() => act(() => apiClient.post(`/letters/templates/${t.id}/duplicate`), "Modèle dupliqué")} className={ui.act.sky}><Copy className="h-3.5 w-3.5" /> Dupliquer</button>
                    {t.locked
                      ? <button type="button" onClick={() => act(() => apiClient.post(`/letters/templates/${t.id}/unlock`), "Modèle déverrouillé")} className={ui.act.amber} data-testid={`template-unlock-${t.id}`}><Unlock className="h-3.5 w-3.5" /> Déverrouiller</button>
                      : <button type="button" onClick={() => act(() => apiClient.post(`/letters/templates/${t.id}/lock`), "Modèle verrouillé")} className={ui.act.amber} data-testid={`template-lock-${t.id}`}><Lock className="h-3.5 w-3.5" /> Verrouiller</button>}
                    <button type="button" disabled={t.locked} title={t.locked ? "Déverrouillez d'abord" : "Supprimer"}
                      onClick={() => window.confirm(`Supprimer le modèle « ${t.name} » ? Les documents déjà générés sont conservés.`) && act(() => apiClient.delete(`/letters/templates/${t.id}`), "Modèle supprimé")}
                      className={ui.act.danger}><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className={cx(ui.card, "overflow-x-auto p-0")} data-testid="generated-docs">
          <table className={ui.table}>
            <thead className={ui.thead}><tr><th className={ui.th}>N°</th><th className={ui.th}>Document</th><th className={ui.th}>Destinataire</th><th className={ui.th}>Date</th><th className={ui.th}>Par</th><th className={ui.th}></th></tr></thead>
            <tbody>
              {(docs || []).length === 0 && <tr><td colSpan={6} className={ui.empty}>Aucun document généré.</td></tr>}
              {(docs || []).map((d) => (
                <tr key={d.id} className={ui.tr}>
                  <td className={cx(ui.td, "font-mono text-xs")}>{d.number}</td>
                  <td className={ui.td}><span className={ui.badge.violet}>{d.category_label}</span> <span className="text-xs text-slate-500">{d.template_name}</span></td>
                  <td className={ui.td}>{d.recipient_name}{d.client_document_id && <span className={cx(ui.badge.green, "ml-1")}>Espace client</span>}</td>
                  <td className={cx(ui.td, "text-xs")}>{fmtDate(d.doc_date || d.created_at)}</td>
                  <td className={cx(ui.td, "text-xs text-slate-500")}>{d.created_by_name}</td>
                  <td className={cx(ui.td, "text-right whitespace-nowrap space-x-1")}>
                    <button type="button" onClick={() => openServerFile(`/letters/documents/${d.id}/pdf`)} className={ui.act.primary}><FileText className="h-3.5 w-3.5" /> PDF</button>
                    <button type="button" onClick={() => openServerFile(`/letters/documents/${d.id}/word`, { download: true, filename: `${(d.number || "document").replace(/\//g, "-")}.doc` })} className={ui.act.sky}><Download className="h-3.5 w-3.5" /> Word</button>
                    <button type="button" onClick={() => window.confirm("Supprimer ce document ?") && act(() => apiClient.delete(`/letters/documents/${d.id}`), "Document supprimé")} className={ui.act.iconDanger}><Trash2 className="h-3.5 w-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
