import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, FileSignature, Pencil } from "lucide-react";
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
import EntitySelect from "@/components/EntitySelect";

const STATUSES = [
  { value: "en_cours", label: "En cours" },
  { value: "suspendu", label: "Suspendu" },
  { value: "termine", label: "Terminé" },
  { value: "annule", label: "Annulé" },
];

const STATUS_TONE = {
  en_cours: "bg-emerald-100 text-emerald-800",
  suspendu: "bg-amber-100 text-amber-800",
  termine: "bg-slate-100 text-slate-500",
  annule: "bg-red-100 text-red-700",
};

const emptyForm = () => ({
  tenant_id: "", numero_contrat: "", title: "", start_date: "", end_date: "",
  amount: "", currency: "XOF", status: "en_cours",
  date_dernier_paiement: "", notes: "",
});

export default function AdminContracts() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());

  const clientNames = React.useMemo(
    () => Object.fromEntries(clients.map((c) => [c.id, `${c.full_name}${c.company ? ` — ${c.company}` : ""}`])),
    [clients],
  );

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: contracts }, { data: cls }] = await Promise.all([
        apiClient.get("/client-contracts"),
        apiClient.get("/clients"),
      ]);
      setItems(contracts);
      setClients(cls);
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing(null); setForm(emptyForm()); setOpen(true); };
  const openEdit = (c) => {
    setEditing(c);
    setForm({
      tenant_id: c.tenant_id,
      numero_contrat: c.numero_contrat || "",
      title: c.title || "",
      start_date: c.start_date || "",
      end_date: c.end_date || "",
      amount: c.amount || "",
      currency: c.currency || "XOF",
      status: c.status || "en_cours",
      date_dernier_paiement: c.date_dernier_paiement || "",
      notes: c.notes || "",
    });
    setOpen(true);
  };

  const submit = async () => {
    if (editing) {
      try {
        const payload = { ...form };
        if (payload.amount === "" || payload.amount === null) delete payload.amount;
        else payload.amount = Number(payload.amount);
        if (!payload.end_date) delete payload.end_date;
        delete payload.tenant_id;
        await apiClient.patch(`/client-contracts/${editing.id}`, payload);
        toast.success("Contrat mis à jour");
      } catch (err) { toast.error(extractError(err)); return; }
    } else {
      if (!form.tenant_id || !form.title || !form.start_date) {
        toast.error("Client, titre et date de début requis"); return;
      }
      try {
        const payload = { ...form };
        if (payload.amount === "") delete payload.amount;
        else payload.amount = Number(payload.amount);
        if (!payload.end_date) delete payload.end_date;
        await apiClient.post("/client-contracts", payload);
        toast.success("Contrat créé");
      } catch (err) { toast.error(extractError(err)); return; }
    }
    setOpen(false);
    setEditing(null);
    setForm(emptyForm());
    await load();
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer le contrat "${c.title}" ?`)) return;
    try {
      await apiClient.delete(`/client-contracts/${c.id}`);
      toast.success("Contrat supprimé");
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-contracts-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Contrats clients</h1>
          <p className="text-muted-foreground mt-1 max-w-2xl">
            Un contrat actif est <strong>obligatoire</strong> pour qu'un client puisse se connecter au portail.
          </p>
        </div>
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setEditing(null); }}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-contract-btn" onClick={openNew}>
              <Plus className="w-4 h-4 mr-2" />Nouveau contrat
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="contract-dialog">
            <DialogHeader>
              <DialogTitle>{editing ? "Modifier le contrat" : "Nouveau contrat"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              {!editing && (
                <div>
                  <Label>Client</Label>
                  <EntitySelect
                    value={form.tenant_id}
                    onChange={(v) => setForm({ ...form, tenant_id: v })}
                    testId="contract-tenant-input"
                  />
                </div>
              )}
              <div><Label>Titre</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="contract-title-input" /></div>
              <div><Label>Numéro de contrat <span className="text-[10px] text-muted-foreground">(auto-généré si vide)</span></Label><Input value={form.numero_contrat} onChange={(e) => setForm({ ...form, numero_contrat: e.target.value })} placeholder="CTR-2026-0001" data-testid="contract-numero-input" /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Début</Label><Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} data-testid="contract-start-input" /></div>
                <div><Label>Fin (optionnel)</Label><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} data-testid="contract-end-input" /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Montant</Label><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="contract-amount-input" /></div>
                <div><Label>Dernier paiement</Label><Input type="date" value={form.date_dernier_paiement} onChange={(e) => setForm({ ...form, date_dernier_paiement: e.target.value })} data-testid="contract-dernier-paiement-input" /></div>
              </div>
              <div>
                <Label>Statut</Label>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                  <SelectTrigger data-testid="contract-status-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Notes</Label><Textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="contract-notes-input" /></div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="contract-submit-btn">
                {editing ? "Enregistrer" : "Créer"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>N° / Titre</TableHead>
              <TableHead>Client</TableHead>
              <TableHead>Début</TableHead>
              <TableHead>Fin</TableHead>
              <TableHead className="text-right">Montant</TableHead>
              <TableHead>Dernier paiement</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={8} className="text-center py-10 text-muted-foreground">Aucun contrat.</TableCell></TableRow>}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <FileSignature className="w-4 h-4 text-[#0F6B4A]" />
                    <div>
                      <div className="font-mono text-xs text-muted-foreground">{c.numero_contrat || "—"}</div>
                      <div className="text-sm">{c.title}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-xs">
                  <div className="font-medium text-foreground text-sm">{clientNames[c.tenant_id] || "Client inconnu"}</div>
                  <div className="font-mono text-muted-foreground">{c.tenant_id.slice(0, 10)}…</div>
                </TableCell>
                <TableCell className="text-sm">{c.start_date}</TableCell>
                <TableCell className="text-sm">{c.end_date || "—"}</TableCell>
                <TableCell className="text-sm font-mono text-right">{c.amount ? `${Number(c.amount).toLocaleString()} ${c.currency || "XOF"}` : "—"}</TableCell>
                <TableCell className="text-sm">{c.date_dernier_paiement || "—"}</TableCell>
                <TableCell>
                  <span className={`albarka-chip ${STATUS_TONE[c.status] || "bg-slate-100 text-slate-700"}`}>
                    {STATUSES.find((s) => s.value === c.status)?.label || c.status}
                  </span>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => openEdit(c)} data-testid={`edit-contract-${c.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => remove(c)} data-testid={`delete-contract-${c.id}`}>
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
