/*
  Gestion des « Outils Numériques » (lot 9) — réservée au compte admin du
  portail (admin@sawalismartsystems.com), contrôlé aussi côté serveur (403).
  Onglet « Outils » : ajout / modification / suppression, image ou icône
  prédéfinie, visibilité, public visé, ordre d'affichage.
  Onglet « Historique des téléchargements » : filtres, export CSV (Excel).
*/
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ArrowDown, ArrowUp, Download, Eye, EyeOff, FileDown, ImagePlus, Loader2, Pencil, Plus, RefreshCw, Trash2, X as XIcon,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, extractError } from "@/lib/api";
import { openServerFile } from "@/lib/docfiles";
import { downloadTool } from "@/lib/outils";
import ToolVisual, { PRESET_ICONS } from "@/components/outils/ToolVisual";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

// Même compte que ADMIN_ACCOUNT_EMAIL côté serveur (albarka_models.py)
const ADMIN_ACCOUNT_EMAIL = "admin@sawalismartsystems.com";
const AUDIENCE_LABELS = { tous: "Clients et personnel", clients: "Clients", personnel: "Personnel" };
const EMPTY_FORM = { caption: "", link: "", version: "", size_label: "", icon: "logiciel", audience: "tous", visible: true };

const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR") : "");

export default function AdminOutilsNumeriques() {
  const { user } = useAuth();
  const isSuperAdmin = (user?.email || "").toLowerCase() === ADMIN_ACCOUNT_EMAIL;

  if (!isSuperAdmin) {
    return (
      <div className="albarka-card p-10 text-center text-muted-foreground" data-testid="outils-admin-forbidden">
        Cette page est réservée à l'administrateur du portail.
      </div>
    );
  }
  return (
    <div className="space-y-6" data-testid="outils-admin-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Administration</div>
        <h1 className="font-display text-3xl md:text-4xl">Outils Numériques</h1>
        <p className="text-muted-foreground mt-1">Fichiers à télécharger par les clients et le personnel (logiciels, PDF, applications…).</p>
      </div>
      <Tabs defaultValue="outils">
        <TabsList>
          <TabsTrigger value="outils" data-testid="tab-outils">Outils</TabsTrigger>
          <TabsTrigger value="historique" data-testid="tab-historique">Historique des téléchargements</TabsTrigger>
        </TabsList>
        <TabsContent value="outils"><ToolsManager /></TabsContent>
        <TabsContent value="historique"><DownloadHistory /></TabsContent>
      </Tabs>
    </div>
  );
}

// -----------------------------------------------------------------------
// Onglet « Outils » : liste, ordre, formulaire d'ajout / modification
// -----------------------------------------------------------------------
function ToolsManager() {
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null); // null = fermé ; {} = nouvel outil ; outil = modification

  const load = () => apiClient.get("/outils-numeriques/admin/outils")
    .then(({ data }) => setItems(data.items))
    .catch((e) => { toast.error(extractError(e)); setItems([]); });
  useEffect(() => { load(); }, []);

  // Ordre d'affichage : échange avec le voisin puis envoi de la liste complète
  const move = async (index, delta) => {
    const next = [...items];
    const j = index + delta;
    if (j < 0 || j >= next.length) return;
    [next[index], next[j]] = [next[j], next[index]];
    setItems(next);
    try {
      const { data } = await apiClient.post("/outils-numeriques/admin/outils/reorder", { ids: next.map((t) => t.id) });
      setItems(data.items);
    } catch (e) { toast.error(extractError(e)); load(); }
  };

  const toggleVisible = async (t) => {
    try {
      await apiClient.put(`/outils-numeriques/admin/outils/${t.id}`, { visible: !t.visible });
      load();
    } catch (e) { toast.error(extractError(e)); }
  };

  const remove = async (t) => {
    if (!window.confirm(`Supprimer l'outil « ${t.caption} » ? L'historique de ses téléchargements est conservé.`)) return;
    try {
      await apiClient.delete(`/outils-numeriques/admin/outils/${t.id}`);
      toast.success("Outil supprimé");
      load();
    } catch (e) { toast.error(extractError(e)); }
  };

  return (
    <div className="space-y-4 mt-4">
      <div className="flex justify-end">
        <Button onClick={() => setEditing({})} className="bg-[#0F6B4A] hover:bg-[#0B5439]" data-testid="outil-add-btn">
          <Plus className="w-4 h-4 mr-2" /> Ajouter un outil
        </Button>
      </div>
      <div className="albarka-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">Ordre</TableHead>
              <TableHead>Outil</TableHead>
              <TableHead>Lien</TableHead>
              <TableHead>Public</TableHead>
              <TableHead className="text-right">Téléch.</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items === null && (
              <TableRow><TableCell colSpan={6} className="text-center py-8"><Loader2 className="w-4 h-4 animate-spin inline" /></TableCell></TableRow>
            )}
            {items?.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Aucun outil. Cliquez sur « Ajouter un outil ».</TableCell></TableRow>
            )}
            {(items || []).map((t, i) => (
              <TableRow key={t.id} data-testid={`outil-row-${t.id}`} className={t.visible ? "" : "opacity-60"}>
                <TableCell>
                  <div className="flex gap-1">
                    <Button size="icon" variant="ghost" className="h-7 w-7" disabled={i === 0} onClick={() => move(i, -1)} title="Monter"><ArrowUp className="w-3.5 h-3.5" /></Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" disabled={i === items.length - 1} onClick={() => move(i, 1)} title="Descendre"><ArrowDown className="w-3.5 h-3.5" /></Button>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <ToolVisual tool={t} size={44} />
                    <div>
                      <div className="font-medium">{t.caption}</div>
                      <div className="text-xs text-muted-foreground">
                        {[t.version && `Version ${t.version}`, t.size_label].filter(Boolean).join(" · ") || "—"}
                      </div>
                    </div>
                  </div>
                </TableCell>
                {/* Lien masqué : les identifiants FTP ne sont jamais affichés */}
                <TableCell className="text-xs font-mono max-w-[260px] truncate" title={t.link_masked}>
                  <Badge variant="outline" className="mr-1 uppercase text-[10px]">{t.protocol}</Badge>{t.link_masked}
                </TableCell>
                <TableCell className="text-xs">
                  <div>{AUDIENCE_LABELS[t.audience] || t.audience}</div>
                  <div className={t.visible ? "text-emerald-700" : "text-slate-500"}>{t.visible ? "Visible" : "Masqué"}</div>
                </TableCell>
                <TableCell className="text-right text-sm">{t.download_count || 0}</TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button size="icon" variant="ghost" title={t.visible ? "Masquer" : "Rendre visible"} onClick={() => toggleVisible(t)}>
                    {t.visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </Button>
                  <Button size="icon" variant="ghost" title="Tester le téléchargement" onClick={() => downloadTool(t)}><Download className="w-4 h-4" /></Button>
                  <Button size="icon" variant="ghost" title="Modifier" onClick={() => setEditing(t)} data-testid={`outil-edit-${t.id}`}><Pencil className="w-4 h-4" /></Button>
                  <Button size="icon" variant="ghost" title="Supprimer" onClick={() => remove(t)} className="text-rose-600"><Trash2 className="w-4 h-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {editing !== null && (
        <ToolDialog tool={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}

// Formulaire d'un outil (ajout si tool.id absent, sinon modification)
function ToolDialog({ tool, onClose, onSaved }) {
  const isNew = !tool.id;
  const [form, setForm] = useState(() => (isNew ? { ...EMPTY_FORM } : {
    caption: tool.caption, link: "", version: tool.version || "", size_label: tool.size_label || "",
    icon: tool.icon || "logiciel", audience: tool.audience || "tous", visible: !!tool.visible,
  }));
  const [current, setCurrent] = useState(tool); // outil tel qu'enregistré (image comprise)
  const [imageFile, setImageFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (!form.caption.trim()) { toast.error("Légende requise"); return; }
    if (isNew && !form.link.trim()) { toast.error("Lien de téléchargement requis"); return; }
    setSaving(true);
    try {
      // Modification : lien vide = lien actuel conservé
      const { data } = isNew
        ? await apiClient.post("/outils-numeriques/admin/outils", form)
        : await apiClient.put(`/outils-numeriques/admin/outils/${tool.id}`, form);
      // Image choisie : envoyée vers le stockage du portail
      if (imageFile) {
        const fd = new FormData();
        fd.append("file", imageFile);
        await apiClient.post(`/outils-numeriques/admin/outils/${data.id}/image`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      }
      toast.success(isNew ? "Outil ajouté" : "Outil enregistré");
      onSaved();
    } catch (e) { toast.error(extractError(e)); } finally { setSaving(false); }
  };

  // Retire l'image envoyée : l'icône prédéfinie reprend sa place
  const removeImage = async () => {
    try {
      const { data } = await apiClient.delete(`/outils-numeriques/admin/outils/${tool.id}/image`);
      setCurrent(data);
      toast.success("Image retirée");
    } catch (e) { toast.error(extractError(e)); }
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isNew ? "Ajouter un outil" : "Modifier l'outil"}</DialogTitle>
          <DialogDescription>Le téléchargement passe toujours par le portail, qui l'enregistre dans l'historique.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Légende *</Label>
            <Input value={form.caption} onChange={(e) => set("caption")(e.target.value)} placeholder="ex. Logiciel de gestion ALBARKA" data-testid="outil-caption-input" />
          </div>
          <div>
            <Label>Lien de téléchargement {isNew ? "*" : ""}</Label>
            <Input
              value={form.link}
              onChange={(e) => set("link")(e.target.value)}
              placeholder={isNew ? "ftp://utilisateur:motdepasse@hote/dossier/fichier.exe ou https://…" : `${current.link_masked} (laisser vide pour conserver)`}
              autoComplete="off"
              data-testid="outil-link-input"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              ftp://, ftps://, http:// ou https://. Les identifiants FTP restent sur le serveur et ne sont jamais affichés.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Version</Label>
              <Input value={form.version} onChange={(e) => set("version")(e.target.value)} placeholder="ex. 2.4.1" />
            </div>
            <div>
              <Label>Taille approximative</Label>
              <Input value={form.size_label} onChange={(e) => set("size_label")(e.target.value)} placeholder="ex. 120 Mo" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Public visé</Label>
              <Select value={form.audience} onValueChange={set("audience")}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(AUDIENCE_LABELS).map(([k, lbl]) => <SelectItem key={k} value={k}>{lbl}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end gap-2 pb-2">
              <Switch checked={form.visible} onCheckedChange={set("visible")} id="outil-visible" />
              <Label htmlFor="outil-visible">Visible</Label>
            </div>
          </div>
          {/* Icône prédéfinie : utilisée tant qu'aucune image n'est envoyée */}
          <div>
            <Label>Icône prédéfinie</Label>
            <div className="grid grid-cols-6 gap-2 mt-1">
              {Object.entries(PRESET_ICONS).map(([key, p]) => (
                <button
                  key={key}
                  type="button"
                  title={p.label}
                  onClick={() => set("icon")(key)}
                  className={`rounded-lg p-1 border-2 flex justify-center ${form.icon === key ? "border-[#0F6B4A]" : "border-transparent hover:border-slate-200"}`}
                >
                  <ToolVisual tool={{ icon: key, has_image: false }} size={40} />
                </button>
              ))}
            </div>
          </div>
          {/* Image représentative (PNG, JPG, WEBP ou GIF, 2 Mo max) */}
          <div>
            <Label>Image représentative (facultatif)</Label>
            <div className="flex items-center gap-3 mt-1">
              {!isNew && current.has_image && !imageFile && <ToolVisual tool={current} size={56} />}
              {imageFile && <span className="text-xs truncate max-w-[180px]">{imageFile.name}</span>}
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden"
                     onChange={(e) => setImageFile(e.target.files?.[0] || null)} />
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <ImagePlus className="w-4 h-4 mr-1" /> {current.has_image || imageFile ? "Remplacer" : "Choisir une image"}
              </Button>
              {imageFile && (
                <Button type="button" variant="ghost" size="sm" onClick={() => { setImageFile(null); if (fileRef.current) fileRef.current.value = ""; }}>
                  <XIcon className="w-4 h-4" />
                </Button>
              )}
              {!isNew && current.has_image && !imageFile && (
                <Button type="button" variant="ghost" size="sm" className="text-rose-600" onClick={removeImage}>Retirer</Button>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={saving} className="bg-[#0F6B4A] hover:bg-[#0B5439]" data-testid="outil-save-btn">
            {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />} Enregistrer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// -----------------------------------------------------------------------
// Onglet « Historique des téléchargements » (super-admin uniquement)
// -----------------------------------------------------------------------
function DownloadHistory() {
  const [tools, setTools] = useState([]);
  const [filters, setFilters] = useState({ date_from: "", date_to: "", tool_id: "all", user: "", user_type: "all" });
  const [data, setData] = useState(null);
  const setF = (k) => (v) => setFilters((f) => ({ ...f, [k]: v }));

  // Paramètres envoyés au serveur (les filtres vides sont ignorés)
  const params = () => {
    const p = {};
    if (filters.date_from) p.date_from = filters.date_from;
    if (filters.date_to) p.date_to = filters.date_to;
    if (filters.tool_id !== "all") p.tool_id = filters.tool_id;
    if (filters.user.trim()) p.user = filters.user.trim();
    if (filters.user_type !== "all") p.user_type = filters.user_type;
    return p;
  };

  const load = () => {
    setData(null);
    apiClient.get("/outils-numeriques/admin/telechargements", { params: params() })
      .then(({ data: d }) => setData(d))
      .catch((e) => { toast.error(extractError(e)); setData({ items: [], total: 0 }); });
  };
  useEffect(() => {
    apiClient.get("/outils-numeriques/admin/outils").then(({ data: d }) => setTools(d.items)).catch(() => {});
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exportCsv = () => openServerFile("/outils-numeriques/admin/telechargements/csv", {
    params: params(), download: true, filename: "telechargements-outils.csv", type: "text/csv",
  });

  return (
    <div className="space-y-4 mt-4">
      <div className="albarka-card p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3 items-end">
        <div>
          <Label>Du</Label>
          <Input type="date" value={filters.date_from} onChange={(e) => setF("date_from")(e.target.value)} />
        </div>
        <div>
          <Label>Au</Label>
          <Input type="date" value={filters.date_to} onChange={(e) => setF("date_to")(e.target.value)} />
        </div>
        <div>
          <Label>Outil</Label>
          <Select value={filters.tool_id} onValueChange={setF("tool_id")}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les outils</SelectItem>
              {tools.map((t) => <SelectItem key={t.id} value={t.id}>{t.caption}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label>Utilisateur</Label>
          <Input value={filters.user} onChange={(e) => setF("user")(e.target.value)} placeholder="Nom, e-mail, société" />
        </div>
        <div>
          <Label>Type</Label>
          <Select value={filters.user_type} onValueChange={setF("user_type")}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous</SelectItem>
              <SelectItem value="client">Clients</SelectItem>
              <SelectItem value="personnel">Personnel</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button onClick={load} className="bg-[#0F6B4A] hover:bg-[#0B5439]" data-testid="history-filter-btn"><RefreshCw className="w-4 h-4 mr-1" /> Filtrer</Button>
          <Button variant="outline" onClick={exportCsv} title="Export CSV (Excel)" data-testid="history-csv-btn"><FileDown className="w-4 h-4" /></Button>
        </div>
      </div>
      <div className="text-sm text-muted-foreground">
        {data ? `${data.total} téléchargement(s)${data.total > data.items.length ? ` — ${data.items.length} affichés (export CSV complet)` : ""}` : "Chargement…"}
      </div>
      <div className="albarka-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date / heure</TableHead>
              <TableHead>Outil</TableHead>
              <TableHead>Utilisateur</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Adresse IP</TableHead>
              <TableHead>Statut</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items?.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Aucun téléchargement.</TableCell></TableRow>
            )}
            {(data?.items || []).map((h) => (
              <TableRow key={h.id}>
                <TableCell className="text-xs whitespace-nowrap" title={`${h.created_at} (UTC)`}>{fmtDateTime(h.created_at)}</TableCell>
                <TableCell className="text-sm">{h.tool_caption}{h.tool_version ? <span className="text-xs text-muted-foreground"> · v{h.tool_version}</span> : null}</TableCell>
                <TableCell className="text-sm">
                  <div>{h.user_name}</div>
                  <div className="text-xs text-muted-foreground">{[h.user_email, h.user_company].filter(Boolean).join(" · ")}</div>
                </TableCell>
                <TableCell className="text-xs">{h.user_type === "client" ? "Client" : "Personnel"}</TableCell>
                {/* Navigateur au survol de l'adresse IP */}
                <TableCell className="text-xs font-mono whitespace-nowrap" title={h.user_agent || ""}>{h.ip || "—"}</TableCell>
                <TableCell className="text-xs">
                  {h.status === "ok"
                    ? <span className="text-emerald-700">OK ({h.protocol})</span>
                    : <span className="text-rose-600" title={h.error || ""}>Échec ({h.protocol})</span>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
