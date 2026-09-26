/*
  MultiClientUpload — « Dépôt » en mode « Plusieurs clients » :
  le MÊME document (ex. une note des impôts) est déposé en une fois dans
  l'espace de tous les clients cochés, au lieu de recommencer client par client.
    1. liste des clients à cocher (recherche, « tout sélectionner ») ;
    2. formulaire identique au dépôt pour un client (catégorie, titre, fichiers…) ;
    3. compte rendu : clients prévenus, non prévenus (motif), module fermé.
  API : GET /clients, GET /client-space/catalog, POST /client-space/documents/multi
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Upload, Camera, Loader2, Users, CheckCircle2, AlertTriangle, Search } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Nombre maximum de clients par dépôt (identique à MAX_MULTI_CLIENTS côté serveur)
const MAX_CLIENTS = 300;

export default function MultiClientUpload() {
  const [catalog, setCatalog] = useState(null);
  const [clients, setClients] = useState(null);      // tous les clients (GET /clients)
  const [selected, setSelected] = useState([]);      // identifiants des clients cochés
  const [search, setSearch] = useState("");
  // Formulaire de dépôt (mêmes champs que pour un seul client)
  const emptyForm = { category: "autre", title: "", reference: "", amount: "", doc_date: "", visible: true, notify: true };
  const [form, setForm] = useState(emptyForm);
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [report, setReport] = useState(null);        // compte rendu du dernier dépôt
  const fileRef = useRef(null);
  const cameraRef = useRef(null);

  // Chargement du catalogue (catégories) et de la liste des clients actifs
  useEffect(() => {
    apiClient.get("/client-space/catalog").then(({ data }) => setCatalog(data)).catch(() => {});
    apiClient.get("/clients")
      .then(({ data }) => setClients((data || []).filter((c) => c.is_active !== false)))
      .catch((err) => { toast.error(extractError(err, "Impossible de charger la liste des clients")); setClients([]); });
  }, []);

  // Clients affichés : filtre de recherche sur le nom, la société et l'e-mail
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (clients || []).filter((c) => !q || `${c.full_name || ""} ${c.company || ""} ${c.email || ""}`.toLowerCase().includes(q));
  }, [clients, search]);
  const allShownSelected = shown.length > 0 && shown.every((c) => selected.includes(c.id));

  // Coche / décoche un client
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  // « Tout sélectionner » agit sur les clients affichés (donc après recherche)
  const toggleAllShown = () => {
    const ids = shown.map((c) => c.id);
    setSelected((s) => (allShownSelected ? s.filter((x) => !ids.includes(x)) : [...new Set([...s, ...ids])]));
  };

  // Copie immédiate de la liste de fichiers AVANT la mise à jour de l'état :
  // le champ est vidé juste après, ce qui viderait aussi la FileList d'origine.
  const addFiles = (list) => {
    const picked = Array.from(list || []);
    setFiles((f) => [...f, ...picked].slice(0, 10));
  };

  // Envoi : un seul appel pour tous les clients cochés
  const submit = async () => {
    if (!selected.length) { toast.error("Cochez au moins un client"); return; }
    if (selected.length > MAX_CLIENTS) { toast.error(`${MAX_CLIENTS} clients maximum par dépôt`); return; }
    if (!files.length) { toast.error("Choisissez au moins un fichier"); return; }
    if (!window.confirm(`Déposer ${files.length} fichier(s) dans l'espace de ${selected.length} client(s) ?`)) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("tenant_ids", selected.join(","));
      Object.entries(form).forEach(([k, v]) => fd.append(k, typeof v === "boolean" ? String(v) : v));
      files.forEach((f) => fd.append("files", f, f.name));
      const { data } = await apiClient.post("/client-space/documents/multi", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setReport(data);
      toast.success(`${data.documents} document(s) déposé(s) chez ${data.clients} client(s)`);
      setFiles([]); setForm(emptyForm); setSelected([]);
    } catch (err) { toast.error(extractError(err)); } finally { setUploading(false); }
  };

  const categories = (catalog?.categories || []).filter((c) => c.key !== "recu" || catalog?.can_issue_receipt);

  return (
    <div className="space-y-5" data-testid="multi-client-upload">
      {/* 1. Clients destinataires */}
      <div className="albarka-card p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 font-semibold"><Users className="w-4 h-4 text-[#0F6B4A]" /> Clients destinataires</div>
          <span className="albarka-chip bg-[#0F6B4A]/10 text-[#0F6B4A] text-xs" data-testid="mc-count">{selected.length} sélectionné(s)</span>
          <div className="relative ml-auto w-full sm:w-72">
            <Search className="w-4 h-4 absolute left-2 top-3 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher un client…" className="pl-8" data-testid="mc-search" />
          </div>
        </div>
        {clients === null ? (
          <p className="text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline" /> Chargement…</p>
        ) : (
          <>
            <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
              <input type="checkbox" checked={allShownSelected} onChange={toggleAllShown} data-testid="mc-select-all" />
              Tout sélectionner {search ? "(résultats de la recherche)" : ""} — {shown.length} client(s)
            </label>
            <div className="max-h-72 overflow-y-auto border rounded-md divide-y">
              {shown.length === 0 && <div className="p-3 text-sm text-muted-foreground">Aucun client.</div>}
              {shown.map((c) => (
                <label key={c.id} className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-slate-50" data-testid={`mc-client-${c.id}`}>
                  <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
                  <span className="font-medium">{c.full_name}</span>
                  <span className="text-muted-foreground truncate">{c.company || c.email || ""}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </div>

      {/* 2. Document(s) à déposer chez tous les clients cochés */}
      <div className="albarka-card p-4 space-y-3">
        <div className="flex items-center gap-2 font-semibold"><Upload className="w-4 h-4 text-[#0F6B4A]" /> Document commun</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Catégorie</Label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="mt-1 w-full h-10 rounded-md border px-2 text-sm bg-white" data-testid="mc-category">
              {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div><Label className="text-xs">Titre (facultatif)</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="ex. Note des impôts 2026" data-testid="mc-title" /></div>
          <div><Label className="text-xs">Référence / n° (facultatif)</Label><Input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></div>
          <div><Label className="text-xs">Montant FCFA (facultatif)</Label><Input inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
          <div><Label className="text-xs">Date du document</Label><Input type="date" value={form.doc_date} onChange={(e) => setForm({ ...form, doc_date: e.target.value })} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Fichiers (plusieurs possibles) et scan par l'appareil photo */}
          <input ref={fileRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.txt,.csv" className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} data-testid="mc-files" />
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}><Upload className="w-4 h-4 mr-1" /> Choisir des fichiers</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => cameraRef.current?.click()}><Camera className="w-4 h-4 mr-1" /> Scanner</Button>
          {files.map((f, i) => (
            <span key={i} className="albarka-chip bg-slate-100 text-slate-700 text-xs">
              {f.name} <button type="button" className="ml-1 text-slate-400 hover:text-rose-600" onClick={() => setFiles(files.filter((_, j) => j !== i))}>×</button>
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-5 text-sm">
          <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={form.visible} onChange={(e) => setForm({ ...form, visible: e.target.checked })} /> Visible par les clients</label>
          <label className={`flex items-center gap-2 cursor-pointer ${form.visible ? "" : "opacity-40"}`}><input type="checkbox" disabled={!form.visible} checked={form.visible && form.notify} onChange={(e) => setForm({ ...form, notify: e.target.checked })} /> Prévenir chaque client (push, WhatsApp ou e-mail)</label>
          <Button onClick={submit} disabled={uploading || !files.length || !selected.length} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white ml-auto" data-testid="mc-submit">
            {uploading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Upload className="w-4 h-4 mr-1" />} Déposer chez {selected.length} client(s)
          </Button>
        </div>
      </div>

      {/* 3. Compte rendu du dernier dépôt groupé */}
      {report && (
        <div className="albarka-card p-4 space-y-2 text-sm" data-testid="mc-report">
          <div className="flex items-center gap-2 font-semibold text-emerald-700"><CheckCircle2 className="w-4 h-4" /> {report.documents} document(s) déposé(s) chez {report.clients} client(s) — {report.notified} prévenu(s)</div>
          {report.not_notified?.length > 0 && (
            <div className="text-amber-800">
              <div className="flex items-center gap-2 font-medium"><AlertTriangle className="w-4 h-4" /> Non prévenus ({report.not_notified.length})</div>
              <ul className="list-disc ml-6">{report.not_notified.map((n, i) => <li key={i}>{n.name} : {n.error || "motif inconnu"}</li>)}</ul>
            </div>
          )}
          {report.module_closed?.length > 0 && (
            <div className="text-slate-600">
              Module « Factures & documents » fermé (le document est déposé mais le client ne le voit pas tant que le module est fermé) : {report.module_closed.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
