import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Copy } from "lucide-react";
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
import { Link } from "react-router-dom";

export default function AdminClients() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    email: "", full_name: "", company: "", phone: "", password: "",
  });

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

  const submit = async () => {
    if (!form.email || !form.full_name || !form.password) {
      toast.error("Email, nom et mot de passe requis"); return;
    }
    try {
      await apiClient.post("/clients", form);
      toast.success("Client créé");
      setOpen(false);
      setForm({ email: "", full_name: "", company: "", phone: "", password: "" });
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const copyId = (id) => {
    navigator.clipboard.writeText(id);
    toast.success("ID copié");
  };

  return (
    <div className="space-y-6" data-testid="admin-clients-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Clients</h1>
          <p className="text-muted-foreground mt-1">Gérez les comptes des entreprises accompagnées.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-client-btn">
              <Plus className="w-4 h-4 mr-2" />Nouveau client
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="client-dialog">
            <DialogHeader><DialogTitle>Nouveau client</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="client-email-input" /></div>
              <div><Label>Nom complet</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="client-name-input" /></div>
              <div><Label>Entreprise</Label><Input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} data-testid="client-company-input" /></div>
              <div><Label>Téléphone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="client-phone-input" /></div>
              <div><Label>Mot de passe (temp)</Label><Input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="client-password-input" /></div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="client-submit-btn">Créer</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Entreprise</TableHead>
              <TableHead>Téléphone</TableHead>
              <TableHead>ID (tenant)</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-10 text-muted-foreground">Aucun client.</TableCell></TableRow>}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">{c.full_name}</TableCell>
                <TableCell className="text-sm">{c.email}</TableCell>
                <TableCell className="text-sm">{c.company || "—"}</TableCell>
                <TableCell className="text-sm">{c.phone || "—"}</TableCell>
                <TableCell>
                  <button onClick={() => copyId(c.id)} className="text-xs font-mono flex items-center gap-1 hover:text-[#0F6B4A]" data-testid={`copy-tenant-${c.id}`}>
                    {c.id.slice(0, 10)}… <Copy className="w-3 h-3" />
                  </button>
                </TableCell>
                <TableCell>
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
