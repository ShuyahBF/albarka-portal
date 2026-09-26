/*
  ClientSpacePanel — côté cabinet, « Espace client » d'UN client :
    1. modules visibles par ce client dans son espace (cases à cocher) ;
    2. dépôt de documents faits hors du portail (factures, rapports…) :
       fichiers ou scan (appareil photo sur téléphone), SANS analyse OCR ;
       le client est prévenu par WhatsApp (textes réglés dans Paramètres) ;
    3. liste de tout ce qui est dans son espace (dépôts + Caisse) : visible
       ou non, dernière notification, consulté ou non par le client.
  Props : tenantId (identifiant du client)
  API : /client-space/* (albarka_client_space.py)
*/
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Upload, Camera, Eye, EyeOff, Bell, Trash2, CheckCircle2, AlertTriangle, Loader2, FileText, LayoutGrid,
} from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

// Doit rester identique à CLIENT_MANAGE_ROLES côté backend : qui peut ouvrir/fermer les modules.
const CLIENT_MANAGE_ROLES = ["administrateur", "superviseur", "dg", "direction", "secretariat"];
// Libellé du canal par lequel le client a été prévenu.
const CHANNEL_LABEL = { whatsapp: "WhatsApp", whatsapp_template: "WhatsApp (modèle)", email: "e-mail" };

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");
const fmtAmount = (n) => (n || n === 0 ? `${Math.round(Number(n)).toLocaleString("fr-FR")} FCFA` : "");

export default function ClientSpacePanel({ tenantId }) {
  const { user } = useAuth();
  const roles = user?.roles || [];
  const canManageModules = roles.includes("superviseur") || roles.some((r) => CLIENT_MANAGE_ROLES.includes(r));

  const [catalog, setCatalog] = useState(null);
  const [items, setItems] = useState(null);
  const [modules, setModules] = useState([]);
  const [savingModules, setSavingModules] = useState(false);
  // Formulaire de dépôt
  const emptyForm = { category: "facture", title: "", reference: "", amount: "", doc_date: "", visible: true, notify: true };
  const [form, setForm] = useState(emptyForm);
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);
  const cameraRef = useRef(null);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/client-space/documents", { params: { tenant_id: tenantId } });
      setItems(data.items || []);
      setModules(data.modules || []);
    } catch (err) { toast.error(extractError(err)); setItems([]); }
  };
  useEffect(() => {
    apiClient.get("/client-space/catalog").then(({ data }) => setCatalog(data)).catch(() => {});
    if (tenantId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  // --- Modules visibles -----------------------------------------------------
  const toggleModule = (key) => setModules((m) => (m.includes(key) ? m.filter((x) => x !== key) : [...m, key]));
  const saveModules = async () => {
    setSavingModules(true);
    try {
      const { data } = await apiClient.put(`/client-space/modules/${tenantId}`, { modules });
      setModules(data.modules);
      toast.success("Modules de l'espace client enregistrés");
    } catch (err) { toast.error(extractError(err)); } finally { setSavingModules(false); }
  };

  // --- Dépôt ----------------------------------------------------------------
  // Copie immédiate de la liste : le champ fichier est vidé juste après
  // (pour pouvoir re-choisir le même fichier), ce qui viderait aussi la FileList.
  const addFiles = (list) => {
    const picked = Array.from(list || []);
    setFiles((f) => [...f, ...picked].slice(0, 10));
  };
  const submit = async () => {
    if (!files.length) { toast.error("Choisissez au moins un fichier"); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("tenant_id", tenantId);
      Object.entries(form).forEach(([k, v]) => fd.append(k, typeof v === "boolean" ? String(v) : v));
      files.forEach((f) => fd.append("files", f, f.name));
      const { data } = await apiClient.post("/client-space/documents", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const n = data.notification;
      toast.success(`${data.items.length} document(s) déposé(s)${n ? (n.ok ? ` — client prévenu par ${CHANNEL_LABEL[n.channel] || n.channel}` : ` — client non prévenu : ${n.error}`) : ""}`);
      setFiles([]); setForm(emptyForm);
      await load();
    } catch (err) { toast.error(extractError(err)); } finally { setUploading(false); }
  };

  // --- Actions sur un document ------------------------------------------------
  const openFile = async (it) => {
    // Ouverture dans un nouvel onglet : dépôt → /client-space/documents/{id}/file ; Caisse → PDF de la facture
    const url = it.source === "upload" ? `/client-space/documents/${it.id}/file` : `/billing/invoices/${it.id}/pdf`;
    try {
      const res = await apiClient.get(url, { responseType: "blob" });
      window.open(window.URL.createObjectURL(res.data), "_blank");
    } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
  };
  const setVisible = async (it, visible) => {
    try {
      const { data } = it.source === "upload"
        ? await apiClient.patch(`/client-space/documents/${it.id}`, { visible, notify: true })
        : await apiClient.post(`/client-space/invoices/${it.id}/visibility`, { visible, notify: true });
      const n = data.notification;
      toast.success(visible ? `Visible par le client${n ? (n.ok ? " — client prévenu" : ` — non prévenu : ${n.error}`) : ""}` : "Masqué au client");
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };
  const renotify = async (it) => {
    try {
      const { data } = await apiClient.post(`/client-space/documents/${it.id}/notify`);
      const n = data.notification;
      if (n.ok) toast.success(`Client prévenu par ${CHANNEL_LABEL[n.channel] || n.channel}`); else toast.error(`Non envoyé : ${n.error}`);
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };
  const remove = async (it) => {
    if (!window.confirm(`Retirer « ${it.title} » de l'espace du client ?`)) return;
    try { await apiClient.delete(`/client-space/documents/${it.id}`); toast.success("Document retiré"); await load(); }
    catch (err) { toast.error(extractError(err)); }
  };

  const categories = (catalog?.categories || []).filter((c) => c.key !== "recu" || catalog?.can_issue_receipt);

  return (
    <div className="space-y-5" data-testid="client-space-panel">
      {/* 1. Modules visibles par le client */}
      {catalog && (
        <div className="albarka-card p-4">
          <div className="flex items-center gap-2 font-semibold mb-2"><LayoutGrid className="w-4 h-4 text-[#0F6B4A]" /> Modules visibles dans l'espace client</div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {catalog.modules.map((m) => (
              <label key={m.key} className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={modules.includes(m.key)} disabled={!canManageModules} onChange={() => toggleModule(m.key)} data-testid={`module-${m.key}`} />
                {m.label}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-2">Tableau de bord et Mon compte restent toujours visibles.</p>
          {canManageModules && (
            <Button size="sm" className="mt-3 bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={saveModules} disabled={savingModules} data-testid="modules-save">Enregistrer les modules</Button>
          )}
        </div>
      )}

      {/* 2. Dépôt de documents faits hors du portail */}
      <div className="albarka-card p-4 space-y-3" data-testid="client-space-upload">
        <div className="flex items-center gap-2 font-semibold"><Upload className="w-4 h-4 text-[#0F6B4A]" /> Déposer dans l'espace du client</div>
        <p className="text-xs text-muted-foreground">Facture, rapport, attestation… faits dans un autre logiciel : téléversez le fichier ou scannez-le. Aucune analyse OCR.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Catégorie</Label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="mt-1 w-full h-10 rounded-md border px-2 text-sm bg-white" data-testid="cs-category">
              {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div><Label className="text-xs">Titre (facultatif)</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="ex. Honoraires septembre" data-testid="cs-title" /></div>
          <div><Label className="text-xs">Référence / n° (facultatif)</Label><Input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} data-testid="cs-reference" /></div>
          <div><Label className="text-xs">Montant FCFA (facultatif)</Label><Input inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="cs-amount" /></div>
          <div><Label className="text-xs">Date du document</Label><Input type="date" value={form.doc_date} onChange={(e) => setForm({ ...form, doc_date: e.target.value })} data-testid="cs-date" /></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Fichiers (plusieurs possibles) */}
          <input ref={fileRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.txt,.csv" className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} data-testid="cs-files" />
          {/* Scan : appareil photo du téléphone / tablette */}
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
          <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={form.visible} onChange={(e) => setForm({ ...form, visible: e.target.checked })} data-testid="cs-visible" /> Visible par le client</label>
          <label className={`flex items-center gap-2 cursor-pointer ${form.visible ? "" : "opacity-40"}`}><input type="checkbox" disabled={!form.visible} checked={form.visible && form.notify} onChange={(e) => setForm({ ...form, notify: e.target.checked })} data-testid="cs-notify" /> Prévenir le client (WhatsApp)</label>
          <Button onClick={submit} disabled={uploading || !files.length} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white ml-auto" data-testid="cs-submit">
            {uploading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Upload className="w-4 h-4 mr-1" />} Déposer {files.length ? `(${files.length})` : ""}
          </Button>
        </div>
      </div>

      {/* 3. Contenu de l'espace client */}
      <div className="albarka-card overflow-x-auto" data-testid="client-space-list">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-muted-foreground border-b">
            <th className="p-3">Document</th><th className="p-3">Origine</th><th className="p-3">Date</th>
            <th className="p-3">Client</th><th className="p-3">Notification</th><th className="p-3 text-right">Actions</th>
          </tr></thead>
          <tbody>
            {items === null && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline" /> Chargement…</td></tr>}
            {items && items.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground">Rien dans l'espace de ce client pour l'instant.</td></tr>}
            {(items || []).map((it) => (
              <tr key={`${it.source}-${it.id}`} className="border-b last:border-0" data-testid={`cs-row-${it.id}`}>
                <td className="p-3">
                  <div className="font-medium flex items-center gap-1.5"><FileText className="w-4 h-4 text-slate-400" />{it.title}</div>
                  <div className="text-xs text-muted-foreground">{it.category_label}{it.reference ? ` · ${it.reference}` : ""}{it.amount ? ` · ${fmtAmount(it.amount)}` : ""}</div>
                </td>
                <td className="p-3 text-xs">{it.source === "upload" ? `Déposé${it.uploaded_by_name ? ` par ${it.uploaded_by_name}` : ""}` : "Caisse"}</td>
                <td className="p-3 text-xs">{fmtDate(it.date)}</td>
                <td className="p-3 text-xs">
                  {it.visible
                    ? <span className="albarka-chip bg-[#0F6B4A]/10 text-[#0F6B4A]">{it.viewed_at ? `Consulté le ${fmtDate(it.viewed_at)}` : "Visible, non consulté"}</span>
                    : <span className="albarka-chip bg-slate-100 text-slate-600">Masqué</span>}
                </td>
                <td className="p-3 text-xs">
                  {it.last_notification
                    ? (it.last_notification.ok
                      ? <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 className="w-3.5 h-3.5" /> {CHANNEL_LABEL[it.last_notification.channel] || it.last_notification.channel}</span>
                      : <span className="inline-flex items-center gap-1 text-amber-700" title={it.last_notification.error}><AlertTriangle className="w-3.5 h-3.5" /> Non prévenu</span>)
                    : "—"}
                </td>
                <td className="p-3">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" className="px-2" title="Ouvrir" onClick={() => openFile(it)}><Eye className="w-4 h-4" /></Button>
                    <Button size="sm" variant="ghost" className="px-2" title={it.visible ? "Masquer au client" : "Rendre visible (le client est prévenu)"} onClick={() => setVisible(it, !it.visible)} data-testid={`cs-toggle-${it.id}`}>
                      {it.visible ? <EyeOff className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4 text-[#0F6B4A]" />}
                    </Button>
                    {it.source === "upload" && it.visible && <Button size="sm" variant="ghost" className="px-2" title="Prévenir à nouveau le client" onClick={() => renotify(it)}><Bell className="w-4 h-4" /></Button>}
                    {it.source === "upload" && <Button size="sm" variant="ghost" className="px-2 text-rose-600" title="Retirer" onClick={() => remove(it)}><Trash2 className="w-4 h-4" /></Button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
