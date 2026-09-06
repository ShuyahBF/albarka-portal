import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Copy, Pencil, ShieldCheck } from "lucide-react";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

// Doivent rester identiques aux listes équivalentes côté backend (albarka_models.py).
const CLIENT_MANAGE_ROLES = ["administrateur", "superviseur", "dg", "direction", "secretariat"];
const VERIFY_PHONE_ROLES = ["administrateur", "superviseur", "dg", "direction"];

const emptyForm = () => ({
  email: "", full_name: "", company: "", phone: "", password: "",
  can_receive_notifications: true, is_active: true,
});

export default function AdminClients() {
  const { user } = useAuth();
  const myRoles = user?.roles || [];
  const canManage = myRoles.some((r) => CLIENT_MANAGE_ROLES.includes(r));
  const canVerifyPhone = myRoles.some((r) => VERIFY_PHONE_ROLES.includes(r));
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // null = create mode
  const [form, setForm] = useState(emptyForm());

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/clients");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setOpen(true);
  };

  const openEdit = (c) => {
    setEditing(c);
    setForm({
      email: c.email || "",
      full_name: c.full_name || "",
      company: c.company || "",
      phone: c.phone || "",
      password: "",
      can_receive_notifications: c.can_receive_notifications !== false,
      is_active: c.is_active !== false,
    });
    setOpen(true);
  };

  const submit = async () => {
    if (editing) {
      if (!form.full_name) {
        toast.error("Nom requis"); return;
      }
      try {
        await apiClient.patch(`/clients/${editing.id}`, {
          full_name: form.full_name,
          company: form.company || null,
          phone: form.phone || null,
          can_receive_notifications: form.can_receive_notifications,
          is_active: form.is_active,
        });
        toast.success("Client mis à jour");
        setOpen(false);
        setEditing(null);
        setForm(emptyForm());
        await load();
      } catch (err) {
        toast.error(extractError(err));
      }
      return;
    }
    if (!form.email || !form.full_name || !form.password) {
      toast.error("Email, nom et mot de passe requis"); return;
    }
    try {
      await apiClient.post("/clients", form);
      toast.success("Client créé");
      setOpen(false);
      setForm(emptyForm());
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const copyId = (id) => {
    navigator.clipboard.writeText(id);
    toast.success("ID copié");
  };

  const toggleVerified = async (c) => {
    try {
      await apiClient.patch(`/clients/${c.id}/verify-phone`, { verified: !c.phone_verified });
      toast.success(c.phone_verified ? "Numéro marqué non vérifié" : "Numéro attesté vérifié");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-clients-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Clients</h1>
          <p className="text-muted-foreground mt-1">Gérez les comptes des entreprises accompagnées.</p>
        </div>
        {canManage && (
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setEditing(null); }}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-client-btn" onClick={openNew}>
              <Plus className="w-4 h-4 mr-2" />Nouveau client
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="client-dialog">
            <DialogHeader>
              <DialogTitle>{editing ? "Modifier le client" : "Nouveau client"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>Email {editing && <span className="text-[10px] text-muted-foreground">(non modifiable)</span>}</Label>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  readOnly={!!editing}
                  data-testid="client-email-input"
                />
              </div>
              <div><Label>Nom complet</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="client-name-input" /></div>
              <div><Label>Entreprise</Label><Input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} data-testid="client-company-input" /></div>
              <div><Label>Téléphone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="client-phone-input" /></div>
              {!editing && (
                <div><Label>Mot de passe (temp)</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="client-password-input" /></div>
              )}
              <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
                <Checkbox
                  checked={form.can_receive_notifications}
                  onCheckedChange={(v) => setForm({ ...form, can_receive_notifications: !!v })}
                  data-testid="client-notif-checkbox"
                />
                <span>Autoriser la réception des notifications (rappels échéances, rapports…)</span>
              </label>
              {editing && (
                <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
                  <Checkbox
                    checked={form.is_active}
                    onCheckedChange={(v) => setForm({ ...form, is_active: !!v })}
                    data-testid="client-active-checkbox"
                  />
                  <span>Compte actif</span>
                </label>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="client-submit-btn">
                {editing ? "Enregistrer" : "Créer"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        )}
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Entreprise</TableHead>
              <TableHead>Téléphone</TableHead>
              {canVerifyPhone && <TableHead>Vérifié</TableHead>}
              <TableHead>Statut</TableHead>
              <TableHead>ID (tenant)</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={canVerifyPhone ? 8 : 7} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={canVerifyPhone ? 8 : 7} className="text-center py-10 text-muted-foreground">Aucun client.</TableCell></TableRow>}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">{c.full_name}</TableCell>
                <TableCell className="text-sm">{c.email}</TableCell>
                <TableCell className="text-sm">{c.company || "—"}</TableCell>
                <TableCell className="text-sm">{c.phone || "—"}</TableCell>
                {canVerifyPhone && (
                  <TableCell>
                    <button
                      onClick={() => toggleVerified(c)}
                      className={`flex items-center gap-1 text-xs ${c.phone_verified ? "text-emerald-700" : "text-muted-foreground"}`}
                      title={c.phone_verified ? "Numéro attesté vérifié — cliquer pour révoquer" : "Attester que ce numéro est vérifié"}
                      data-testid={`verify-phone-${c.id}`}
                    >
                      <ShieldCheck className={`w-4 h-4 ${c.phone_verified ? "fill-emerald-100" : ""}`} />
                      {c.phone_verified ? "Vérifié" : "Non vérifié"}
                    </button>
                  </TableCell>
                )}
                <TableCell>
                  {c.is_active === false
                    ? <span className="albarka-chip bg-slate-100 text-slate-500">Inactif</span>
                    : <span className="albarka-chip bg-emerald-100 text-emerald-800">Actif</span>}
                </TableCell>
                <TableCell>
                  <button onClick={() => copyId(c.id)} className="text-xs font-mono flex items-center gap-1 hover:text-[#0F6B4A]" data-testid={`copy-tenant-${c.id}`}>
                    {c.id.slice(0, 10)}… <Copy className="w-3 h-3" />
                  </button>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {canManage && (
                    <Button variant="ghost" size="sm" onClick={() => openEdit(c)} title="Modifier" data-testid={`edit-client-${c.id}`}>
                      <Pencil className="w-4 h-4" />
                    </Button>
                  )}
                  <Link to={`/admin/clients/${c.id}`}>
                    <Button variant="outline" size="sm" data-testid={`view-client-${c.id}`}>Ouvrir</Button>
                  </Link>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
