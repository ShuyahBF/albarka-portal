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
import { Checkbox } from "@/components/ui/checkbox";

const STAFF_ROLES = [
  { value: "superviseur", label: "Superviseur" },
  { value: "direction", label: "Direction" },
  { value: "secretariat", label: "Secrétariat" },
  { value: "fiscaliste", label: "Fiscaliste" },
  { value: "comptable", label: "Comptable" },
  { value: "aide_comptable", label: "Aide-comptable" },
  { value: "rh", label: "RH" },
];

export default function AdminStaff() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    email: "", full_name: "", phone: "", password: "", roles: ["comptable"],
  });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/clients/staff");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggleRole = (r) => {
    setForm((f) => ({
      ...f,
      roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r],
    }));
  };

  const submit = async () => {
    if (!form.email || !form.full_name || !form.password || form.roles.length === 0) {
      toast.error("Champs requis manquants"); return;
    }
    try {
      await apiClient.post("/clients/staff", form);
      toast.success("Collaborateur créé");
      setOpen(false);
      setForm({ email: "", full_name: "", phone: "", password: "", roles: ["comptable"] });
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-staff-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Collaborateurs</h1>
          <p className="text-muted-foreground mt-1">Équipe du cabinet et leurs rôles.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-staff-btn">
              <Plus className="w-4 h-4 mr-2" />Nouveau collaborateur
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="staff-dialog">
            <DialogHeader><DialogTitle>Nouveau collaborateur</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="staff-email-input" /></div>
              <div><Label>Nom complet</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="staff-name-input" /></div>
              <div><Label>Téléphone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="staff-phone-input" /></div>
              <div><Label>Mot de passe</Label><Input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="staff-password-input" /></div>
              <div>
                <Label>Rôles</Label>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {STAFF_ROLES.map((r) => (
                    <label key={r.value} className="flex items-center gap-2 text-sm cursor-pointer">
                      <Checkbox
                        checked={form.roles.includes(r.value)}
                        onCheckedChange={() => toggleRole(r.value)}
                        data-testid={`role-${r.value}`}
                      />
                      {r.label}
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="staff-submit-btn">Créer</Button>
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
              <TableHead>Rôles</TableHead>
              <TableHead>Téléphone</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">Aucun collaborateur.</TableCell></TableRow>}
            {items.map((s) => (
              <TableRow key={s.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">{s.full_name}</TableCell>
                <TableCell className="text-sm">{s.email}</TableCell>
                <TableCell className="text-xs">
                  <div className="flex flex-wrap gap-1">
                    {s.roles?.map((r) => (
                      <span key={r} className="albarka-chip bg-[#0F6B4A]/10 text-[#0F6B4A]">{r}</span>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-sm">{s.phone || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
