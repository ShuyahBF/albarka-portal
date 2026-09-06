import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
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
      await apiClient.post("/missions", form);
      toast.success("Mission créée");
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
          <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v) setForm(defaultMissionForm(tenantIdOverride)); }}>
            <DialogTrigger asChild>
              <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-mission-btn">
                <Plus className="w-4 h-4 mr-2" />Nouvelle mission
              </Button>
            </DialogTrigger>
            <DialogContent data-testid="mission-dialog">
              <DialogHeader>
                <DialogTitle>Nouvelle mission</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {!tenantIdOverride && (
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
                  <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} data-testid="mission-desc-input" />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
                <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="mission-submit-btn">Créer</Button>
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
                  {m.description && <div className="text-xs text-muted-foreground max-w-md truncate">{m.description}</div>}
                </TableCell>
                <TableCell className="text-sm">{TYPES.find((t) => t.value === m.type)?.label || m.type}</TableCell>
                <TableCell className="text-sm">{m.due_date || "—"}</TableCell>
                <TableCell>
                  <span className={`albarka-chip ${STATUS_TONE[m.status] || "bg-slate-100 text-slate-700"}`}>
                    {STATUSES.find((s) => s.value === m.status)?.label || m.status}
                  </span>
                </TableCell>
                {canCreate && (
                  <TableCell>
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
