import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Pencil, FileSignature, ChevronDown, ChevronRight } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import RichTextEditor from "@/components/RichTextEditor";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/contexts/AuthContext";
import EntitySelect from "@/components/EntitySelect";

const TYPES = [
  { value: "tenue_comptable", label: "Tenue comptable" },
  { value: "declaration_fiscale", label: "Déclaration fiscale" },
  { value: "paie_rh", label: "Paie / RH" },
  { value: "audit", label: "Audit" },
  { value: "conseil", label: "Conseil" },
  { value: "creation_entreprise", label: "Création d'entreprise" },
  { value: "autre", label: "Autre" },
];

const STATUSES = [
  { value: "en_attente", label: "En attente" },
  { value: "en_cours", label: "En cours" },
  { value: "en_revue", label: "En revue" },
  { value: "terminee", label: "Terminée" },
  { value: "archivee", label: "Archivée" },
];

const STATUS_TONE = {
  en_attente: "bg-slate-100 text-slate-700",
  en_cours: "bg-[#0F6B4A]/10 text-[#0F6B4A]",
  en_revue: "bg-blue-100 text-blue-700",
  terminee: "bg-emerald-100 text-emerald-800",
  archivee: "bg-slate-100 text-slate-500",
};

const defaultMissionForm = (tenantIdOverride) => ({
  tenant_id: tenantIdOverride || "",
  title: "",
  type: "tenue_comptable",
  description: "",
  // Lot 7 : description mise en forme (éditeur « comme Word »)
  description_html: "",
  due_date: "",
  status: "en_attente",
});

export default function Missions({ tenantIdOverride = null, staffMode = false }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(defaultMissionForm(tenantIdOverride));
  const { isClient } = useAuth();
  const canCreate = staffMode || !isClient;
  const navigate = useNavigate();
  const [editingId, setEditingId] = useState(null);   // mission modifiée (null = création)
  const [expanded, setExpanded] = useState(null);     // mission dont la description est dépliée

  const load = async () => {
    setLoading(true);
    try {
      const params = tenantIdOverride ? { tenant_id: tenantIdOverride } : {};
      const { data } = await apiClient.get("/missions", { params });
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tenantIdOverride]);

  const submit = async () => {
    if (!form.title || !form.tenant_id) {
      toast.error("Titre et client requis");
      return;
    }
    try {
      if (editingId) {
        // Modification : titre, type, échéance et description mise en forme
        const { title, type, due_date, description_html } = form;
        await apiClient.patch(`/missions/${editingId}`, { title, type, due_date: due_date || null, description_html });
        toast.success("Mission modifiée");
      } else {
        await apiClient.post("/missions", form);
        toast.success("Mission créée");
      }
      setEditingId(null);
      setOpen(false);
      setForm(defaultMissionForm(tenantIdOverride));
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const updateStatus = async (id, status) => {
    try {
      await apiClient.patch(`/missions/${id}`, { status });
      toast.success("Statut mis à jour");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-6" data-testid="missions-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Missions</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">
            {isClient ? "Mes missions" : "Missions en cours"}
          </h1>
          <p className="text-muted-foreground mt-1">Suivi des dossiers ouverts, en revue et terminés.</p>
        </div>
        {canCreate && (
          <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v && !editingId) setForm(defaultMissionForm(tenantIdOverride)); if (!v) setEditingId(null); }}>
            <DialogTrigger asChild>
              <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-mission-btn" onClick={() => setEditingId(null)}>
                <Plus className="w-4 h-4 mr-2" />Nouvelle mission
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto" data-testid="mission-dialog">
              <DialogHeader>
                <DialogTitle>{editingId ? "Modifier la mission" : "Nouvelle mission"}</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {!tenantIdOverride && !editingId && (
                  <div>
                    <Label>Client</Label>
                    <EntitySelect
                      value={form.tenant_id}
                      onChange={(v) => setForm({ ...form, tenant_id: v })}
                      testId="mission-tenant-input"
                    />
                  </div>
                )}
                <div>
                  <Label>Titre</Label>
                  <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="mission-title-input" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Type</Label>
                    <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                      <SelectTrigger data-testid="mission-type-select"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Échéance</Label>
                    <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} data-testid="mission-duedate-input" />
                  </div>
                </div>
                <div>
                  <Label>Description</Label>
                  {/* Éditeur « comme Word » : gras, listes, retraits, tableaux, images… */}
                  <div className="mt-1">
                    <RichTextEditor value={form.description_html} onChange={(html) => setForm((f) => ({ ...f, description_html: html }))}
                      minHeight={220} testId="mission-desc" placeholder="Décrivez la mission…" />
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
                <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="mission-submit-btn">{editingId ? "Enregistrer" : "Créer"}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Titre</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Échéance</TableHead>
              <TableHead>Statut</TableHead>
              {canCreate && <TableHead>Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-10 text-muted-foreground">Aucune mission.</TableCell></TableRow>}
            {items.map((m) => (
              <TableRow key={m.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell>
                  <div className="font-medium">{m.title}</div>
                  {m.description && (
                    // Clic : déplie la description mise en forme (HTML déjà nettoyé par le serveur)
                    <button type="button" onClick={() => setExpanded(expanded === m.id ? null : m.id)} className="flex items-start gap-1 text-left text-xs text-muted-foreground max-w-md" data-testid={`mission-desc-toggle-${m.id}`}>
                      {expanded === m.id ? <ChevronDown className="h-3.5 w-3.5 shrink-0 mt-0.5" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 mt-0.5" />}
                      <span className={expanded === m.id ? "" : "truncate"}>{expanded === m.id ? "Masquer la description" : m.description}</span>
                    </button>
                  )}
                  {expanded === m.id && (
                    m.description_html
                      ? <div className="mission-desc-html mt-2 rounded-lg border border-slate-200 bg-white p-3 text-sm" dangerouslySetInnerHTML={{ __html: m.description_html }} />
                      : <div className="mt-2 whitespace-pre-line text-sm">{m.description}</div>
                  )}
                </TableCell>
                <TableCell className="text-sm">{TYPES.find((t) => t.value === m.type)?.label || m.type}</TableCell>
                <TableCell className="text-sm">{m.due_date || "—"}</TableCell>
                <TableCell>
                  <span className={`albarka-chip ${STATUS_TONE[m.status] || "bg-slate-100 text-slate-700"}`}>
                    {STATUSES.find((s) => s.value === m.status)?.label || m.status}
                  </span>
                </TableCell>
                {canCreate && (
                  <TableCell className="space-y-1.5">
                    <div className="flex gap-1">
                      {/* Modifier la mission (description mise en forme comprise) */}
                      <button type="button" title="Modifier" data-testid={`mission-edit-${m.id}`}
                        onClick={() => { setEditingId(m.id); setForm({ ...defaultMissionForm(m.tenant_id), ...m, due_date: m.due_date || "", description_html: m.description_html || (m.description || "").replace(/\n/g, "<br>") }); setOpen(true); }}
                        className="inline-flex h-7 w-7 items-center justify-center rounded bg-slate-900 text-white hover:bg-slate-800"><Pencil className="h-3.5 w-3.5" /></button>
                      {/* Générer un ordre / avis de mission à partir d'un modèle */}
                      <button type="button" title="Générer un document (ordre, avis de mission…)" data-testid={`mission-doc-${m.id}`}
                        onClick={() => navigate(`/admin/modeles?mission=${m.id}&tenant=${m.tenant_id}`)}
                        className="inline-flex h-7 items-center gap-1 rounded bg-sky-600 px-2 text-[11px] text-white hover:bg-sky-700"><FileSignature className="h-3.5 w-3.5" /> Document</button>
                    </div>
                    <Select value={m.status} onValueChange={(v) => updateStatus(m.id, v)}>
                      <SelectTrigger className="w-36 h-8" data-testid={`mission-status-${m.id}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
