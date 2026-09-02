import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, CalendarClock } from "lucide-react";
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

const TYPES = [
  { value: "tva", label: "TVA" },
  { value: "is", label: "Impôt sur les sociétés (IS)" },
  { value: "irpp", label: "IRPP" },
  { value: "iuts", label: "IUTS" },
  { value: "cnss", label: "CNSS" },
  { value: "bilan_annuel", label: "Bilan annuel" },
  { value: "declaration_annuelle", label: "Déclaration annuelle" },
  { value: "autre", label: "Autre" },
];

const STATUSES = [
  { value: "a_venir", label: "À venir" },
  { value: "en_cours", label: "En cours" },
  { value: "traitee", label: "Traitée" },
  { value: "en_retard", label: "En retard" },
];

const STATUS_TONE = {
  a_venir: "bg-[#E5A24B]/15 text-[#8A5A16]",
  en_cours: "bg-blue-100 text-blue-700",
  traitee: "bg-emerald-100 text-emerald-800",
  en_retard: "bg-red-100 text-red-700",
};

export default function Echeances({ tenantIdOverride = null, staffMode = false }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    tenant_id: tenantIdOverride || "",
    title: "",
    type: "tva",
    due_date: "",
    amount: "",
    period: "",
    notes: "",
    status: "a_venir",
  });
  const { isClient } = useAuth();
  const canCreate = staffMode || !isClient;

  const load = async () => {
    setLoading(true);
    try {
      const params = tenantIdOverride ? { tenant_id: tenantIdOverride } : {};
      const { data } = await apiClient.get("/echeances", { params });
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tenantIdOverride]);

  const submit = async () => {
    if (!form.title || !form.tenant_id || !form.due_date) {
      toast.error("Titre, client et échéance requis");
      return;
    }
    const payload = { ...form };
    if (payload.amount === "") delete payload.amount;
    else payload.amount = Number(payload.amount);
    try {
      await apiClient.post("/echeances", payload);
      toast.success("Échéance ajoutée");
      setOpen(false);
      setForm({ ...form, title: "", due_date: "", amount: "", period: "", notes: "" });
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const updateStatus = async (id, status) => {
    try {
      await apiClient.patch(`/echeances/${id}`, { status });
      toast.success("Statut mis à jour");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-6" data-testid="echeances-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Calendrier fiscal</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">
            {isClient ? "Mes échéances" : "Échéances fiscales"}
          </h1>
          <p className="text-muted-foreground mt-1">TVA, IS, IRPP, CNSS, IUTS et bilans annuels.</p>
        </div>
        {canCreate && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-echeance-btn">
                <Plus className="w-4 h-4 mr-2" />Nouvelle échéance
              </Button>
            </DialogTrigger>
            <DialogContent data-testid="echeance-dialog">
              <DialogHeader>
                <DialogTitle>Nouvelle échéance</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {!tenantIdOverride && (
                  <div>
                    <Label>ID client (tenant)</Label>
                    <Input value={form.tenant_id} onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} data-testid="echeance-tenant-input" />
                  </div>
                )}
                <div>
                  <Label>Titre</Label>
                  <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="echeance-title-input" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Type</Label>
                    <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                      <SelectTrigger data-testid="echeance-type-select"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Date limite</Label>
                    <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} data-testid="echeance-duedate-input" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Montant (FCFA)</Label>
                    <Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="echeance-amount-input" />
                  </div>
                  <div>
                    <Label>Période (ex: 2026-Q1)</Label>
                    <Input value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} data-testid="echeance-period-input" />
                  </div>
                </div>
                <div>
                  <Label>Notes</Label>
                  <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} data-testid="echeance-notes-input" />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
                <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="echeance-submit-btn">Créer</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Échéance</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Date</TableHead>
              <TableHead>Période</TableHead>
              <TableHead>Montant</TableHead>
              <TableHead>Statut</TableHead>
              {canCreate && <TableHead>Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-10 text-muted-foreground">Aucune échéance.</TableCell></TableRow>}
            {items.map((e) => (
              <TableRow key={e.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell>
                  <div className="font-medium flex items-center gap-2">
                    <CalendarClock className="w-4 h-4 text-muted-foreground" />
                    {e.title}
                  </div>
                  {e.notes && <div className="text-xs text-muted-foreground max-w-md truncate">{e.notes}</div>}
                </TableCell>
                <TableCell className="text-sm">{TYPES.find((t) => t.value === e.type)?.label || e.type}</TableCell>
                <TableCell className="text-sm">{e.due_date}</TableCell>
                <TableCell className="text-sm">{e.period || "—"}</TableCell>
                <TableCell className="text-sm font-mono">{e.amount ? `${Number(e.amount).toLocaleString()} FCFA` : "—"}</TableCell>
                <TableCell>
                  <span className={`albarka-chip ${STATUS_TONE[e.status] || "bg-slate-100 text-slate-700"}`}>
                    {STATUSES.find((s) => s.value === e.status)?.label || e.status}
                  </span>
                </TableCell>
                {canCreate && (
                  <TableCell>
                    <Select value={e.status} onValueChange={(v) => updateStatus(e.id, v)}>
                      <SelectTrigger className="w-32 h-8" data-testid={`echeance-status-${e.id}`}><SelectValue /></SelectTrigger>
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
