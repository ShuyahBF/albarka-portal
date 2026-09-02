import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Users2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

/** Manage contact groups for a given (scope, tenantId). */
export function ContactGroupsPanel({ scope = "client", tenantId }) {
  const [items, setItems] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", contact_ids: [] });

  const load = async () => {
    setLoading(true);
    try {
      const params = { scope };
      if (scope === "client" && tenantId) params.tenant_id = tenantId;
      const [{ data: g }, { data: c }] = await Promise.all([
        apiClient.get("/contact-groups", { params }),
        apiClient.get("/contacts", { params }),
      ]);
      setItems(g);
      setContacts(c);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [scope, tenantId]);

  const openNew = () => {
    setEditing(null);
    setForm({ name: "", description: "", contact_ids: [] });
    setOpen(true);
  };

  const openEdit = (g) => {
    setEditing(g);
    setForm({
      name: g.name || "",
      description: g.description || "",
      contact_ids: g.contact_ids || [],
    });
    setOpen(true);
  };

  const toggleContact = (id) => {
    setForm((f) => ({
      ...f,
      contact_ids: f.contact_ids.includes(id)
        ? f.contact_ids.filter((x) => x !== id)
        : [...f.contact_ids, id],
    }));
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Le nom du groupe est requis"); return; }
    try {
      if (editing) {
        await apiClient.patch(`/contact-groups/${editing.id}`, form);
        toast.success("Groupe mis à jour");
      } else {
        const payload = { ...form, scope };
        if (scope === "client") payload.tenant_id = tenantId;
        await apiClient.post("/contact-groups", payload);
        toast.success("Groupe créé");
      }
      setOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const remove = async (g) => {
    if (!window.confirm(`Supprimer le groupe "${g.name}" ?`)) return;
    try {
      await apiClient.delete(`/contact-groups/${g.id}`);
      toast.success("Groupe supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid={`groups-panel-${scope}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">
            {scope === "client" ? "Groupes du client" : "Groupes du cabinet"}
          </div>
          <div className="text-xs text-muted-foreground">
            Un groupe rassemble plusieurs contacts et peut recevoir un rapport en un clic.
          </div>
        </div>
        <Button
          onClick={openNew}
          className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
          data-testid={`add-group-${scope}-btn`}
        >
          <Plus className="w-4 h-4 mr-2" />Nouveau groupe
        </Button>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Description</TableHead>
              <TableHead className="text-center">Membres</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">Aucun groupe.</TableCell></TableRow>}
            {items.map((g) => (
              <TableRow key={g.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium flex items-center gap-2">
                  <Users2 className="w-4 h-4 text-[#0F6B4A]" />
                  {g.name}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{g.description || "—"}</TableCell>
                <TableCell className="text-center">
                  <span className="albarka-chip bg-emerald-100 text-emerald-800">{(g.contact_ids || []).length}</span>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => openEdit(g)} title="Éditer" data-testid={`edit-group-${g.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => remove(g)} title="Supprimer" data-testid={`delete-group-${g.id}`}>
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="group-dialog">
          <DialogHeader><DialogTitle>{editing ? "Modifier" : "Créer"} un groupe de contacts</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nom</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="group-name-input" /></div>
            <div><Label>Description (optionnel)</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="group-desc-input" /></div>
            <div>
              <Label>Membres ({form.contact_ids.length})</Label>
              <div className="max-h-64 overflow-y-auto border rounded-md p-2 mt-1 space-y-1">
                {contacts.length === 0 && <div className="text-xs text-muted-foreground py-2 text-center">Aucun contact disponible dans ce périmètre.</div>}
                {contacts.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm cursor-pointer p-1.5 rounded hover:bg-[#0F6B4A]/5">
                    <Checkbox
                      checked={form.contact_ids.includes(c.id)}
                      onCheckedChange={() => toggleContact(c.id)}
                      data-testid={`group-contact-${c.id}`}
                    />
                    <span className="font-medium">{c.full_name}</span>
                    <span className="text-xs text-muted-foreground">{c.email || c.phone || "—"}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button onClick={save} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="group-submit-btn">
              {editing ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
