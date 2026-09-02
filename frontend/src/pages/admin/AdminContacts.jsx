import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Star, Trash2, Pencil, Users, Building } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const FUNCTIONS = [
  { value: "dg", label: "Directeur Général" },
  { value: "daf", label: "DAF" },
  { value: "dfc", label: "DFC" },
  { value: "comptable_interne", label: "Comptable interne" },
  { value: "assistant", label: "Assistant" },
  { value: "rh", label: "RH" },
  { value: "juridique", label: "Juridique" },
  { value: "banque", label: "Banque" },
  { value: "impots", label: "Impôts" },
  { value: "cnss", label: "CNSS" },
  { value: "auditeur", label: "Auditeur" },
  { value: "avocat", label: "Avocat" },
  { value: "commissaire_aux_comptes", label: "Commissaire aux comptes" },
  { value: "notaire", label: "Notaire" },
  { value: "autre", label: "Autre" },
];

const emptyForm = () => ({
  full_name: "", function: "autre", organization: "",
  email: "", phone: "",
  is_primary: false, can_receive_notifications: true,
  channels: ["email"], notes: "",
});

/** Reusable panel — contacts of a given (scope, tenantId). */
export function ContactsPanel({ scope = "client", tenantId, hideHeader = false }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());

  const load = async () => {
    setLoading(true);
    try {
      const params = { scope };
      if (scope === "client" && tenantId) params.tenant_id = tenantId;
      const { data } = await apiClient.get("/contacts", { params });
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [scope, tenantId]);

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setOpen(true);
  };

  const openEdit = (c) => {
    setEditing(c);
    setForm({
      full_name: c.full_name || "",
      function: c.function || "autre",
      organization: c.organization || "",
      email: c.email || "",
      phone: c.phone || "",
      is_primary: !!c.is_primary,
      can_receive_notifications: c.can_receive_notifications !== false,
      channels: c.channels || ["email"],
      notes: c.notes || "",
    });
    setOpen(true);
  };

  const toggleChannel = (ch) => {
    setForm((f) => ({
      ...f,
      channels: f.channels.includes(ch) ? f.channels.filter((x) => x !== ch) : [...f.channels, ch],
    }));
  };

  const save = async () => {
    if (!form.full_name.trim()) { toast.error("Le nom est requis"); return; }
    if (!form.email && !form.phone) { toast.error("Email ou téléphone requis"); return; }
    try {
      if (editing) {
        await apiClient.patch(`/contacts/${editing.id}`, form);
        toast.success("Contact mis à jour");
      } else {
        const payload = { ...form, scope };
        if (scope === "client") payload.tenant_id = tenantId;
        await apiClient.post("/contacts", payload);
        toast.success("Contact créé");
      }
      setOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer ${c.full_name} ?`)) return;
    try {
      await apiClient.delete(`/contacts/${c.id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const promote = async (c) => {
    try {
      await apiClient.patch(`/contacts/${c.id}`, { is_primary: true });
      toast.success(`${c.full_name} défini comme contact principal`);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid={`contacts-panel-${scope}`}>
      {!hideHeader && (
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-foreground">
              {scope === "client" ? "Contacts du client" : "Contacts du cabinet"}
            </div>
            <div className="text-xs text-muted-foreground">
              {scope === "client"
                ? "Personnes à qui adresser rapports et notifications côté client."
                : "Interlocuteurs externes récurrents : impôts, banques, avocats…"}
            </div>
          </div>
          <Button
            onClick={openNew}
            className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
            data-testid={`add-contact-${scope}-btn`}
          >
            <Plus className="w-4 h-4 mr-2" />Ajouter
          </Button>
        </div>
      )}

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Fonction</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Téléphone</TableHead>
              <TableHead>Canaux</TableHead>
              <TableHead>Notif.</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-10 text-muted-foreground">Aucun contact.</TableCell></TableRow>}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell>
                  <div className="flex items-center gap-2 font-medium">
                    {c.is_primary && <Star className="w-4 h-4 fill-[#E5A24B] text-[#E5A24B]" />}
                    {c.full_name}
                  </div>
                  {c.organization && <div className="text-xs text-muted-foreground">{c.organization}</div>}
                </TableCell>
                <TableCell className="text-sm">{FUNCTIONS.find((f) => f.value === c.function)?.label || c.function}</TableCell>
                <TableCell className="text-sm">{c.email || "—"}</TableCell>
                <TableCell className="text-sm">{c.phone || "—"}</TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {(c.channels || []).map((ch) => (
                      <span key={ch} className="albarka-chip bg-slate-100 text-slate-700 text-[10px] uppercase">{ch}</span>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  {c.is_active === false || c.can_receive_notifications === false
                    ? <span className="albarka-chip bg-slate-100 text-slate-500">Off</span>
                    : <span className="albarka-chip bg-emerald-100 text-emerald-800">On</span>}
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {!c.is_primary && (
                    <Button variant="ghost" size="sm" onClick={() => promote(c)} title="Définir comme principal" data-testid={`primary-contact-${c.id}`}>
                      <Star className="w-4 h-4 text-[#E5A24B]" />
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => openEdit(c)} title="Éditer" data-testid={`edit-contact-${c.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => remove(c)} title="Supprimer" data-testid={`delete-contact-${c.id}`}>
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="contact-dialog">
          <DialogHeader><DialogTitle>{editing ? "Modifier" : "Ajouter"} un contact</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Nom complet</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="contact-name-input" /></div>
              <div>
                <Label>Fonction</Label>
                <Select value={form.function} onValueChange={(v) => setForm({ ...form, function: v })}>
                  <SelectTrigger data-testid="contact-function-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {FUNCTIONS.map((f) => <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>Organisation (optionnel)</Label><Input value={form.organization} onChange={(e) => setForm({ ...form, organization: e.target.value })} data-testid="contact-org-input" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="contact-email-input" /></div>
              <div><Label>Téléphone (+226…)</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="contact-phone-input" /></div>
            </div>
            <div>
              <Label>Canaux de notification</Label>
              <div className="flex gap-4 mt-2">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={form.channels.includes("email")} onCheckedChange={() => toggleChannel("email")} data-testid="contact-channel-email" />
                  Email
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={form.channels.includes("whatsapp")} onCheckedChange={() => toggleChannel("whatsapp")} data-testid="contact-channel-whatsapp" />
                  WhatsApp
                </label>
              </div>
            </div>
            <div className="flex flex-col gap-2 pt-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <Checkbox checked={form.is_primary} onCheckedChange={(v) => setForm({ ...form, is_primary: !!v })} data-testid="contact-primary-checkbox" />
                Contact principal (recevra les notifications par défaut)
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <Checkbox checked={form.can_receive_notifications} onCheckedChange={(v) => setForm({ ...form, can_receive_notifications: !!v })} data-testid="contact-notif-checkbox" />
                Autoriser la réception de notifications
              </label>
            </div>
            <div><Label>Notes (optionnel)</Label><Textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="contact-notes-input" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button onClick={save} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="contact-submit-btn">
              {editing ? "Enregistrer" : "Ajouter"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Global "Contacts" admin page with tabs Cabinet / By client. */
export default function AdminContacts() {
  const [clients, setClients] = useState([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/clients");
        setClients(data);
        if (data.length && !selected) setSelected(data[0].id);
      } catch (err) {
        toast.error(extractError(err));
      } finally { setLoading(false); }
    })();
  }, []);

  return (
    <div className="space-y-6" data-testid="admin-contacts-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Carnet d'adresses</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Contacts</h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Interlocuteurs à qui adresser rapports et notifications — par client ou côté cabinet.
        </p>
      </div>

      <Tabs defaultValue="client">
        <TabsList data-testid="contacts-tabs">
          <TabsTrigger value="client" data-testid="tab-contacts-client">
            <Users className="w-4 h-4 mr-2" />Par client
          </TabsTrigger>
          <TabsTrigger value="cabinet" data-testid="tab-contacts-cabinet">
            <Building className="w-4 h-4 mr-2" />Cabinet
          </TabsTrigger>
        </TabsList>
        <TabsContent value="client" className="pt-4 space-y-4">
          <div className="albarka-card p-4 max-w-md">
            <Label className="text-xs">Client</Label>
            <Select value={selected} onValueChange={setSelected}>
              <SelectTrigger data-testid="contacts-client-select"><SelectValue placeholder="Sélectionner un client…" /></SelectTrigger>
              <SelectContent>
                {clients.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.full_name} {c.company ? `— ${c.company}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {selected && <ContactsPanel scope="client" tenantId={selected} />}
        </TabsContent>
        <TabsContent value="cabinet" className="pt-4">
          <ContactsPanel scope="cabinet" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
