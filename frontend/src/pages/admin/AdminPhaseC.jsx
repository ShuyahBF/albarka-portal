import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Archive, Send, ScrollText, Trash2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// -----------------------------------------------------------------------
// AdminArchives — bibliothèque d'archives (documents référence cabinet).
// -----------------------------------------------------------------------
export function AdminArchives() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", category: "autre", description: "", tags: "" });

  const load = async () => {
    try { const { data } = await apiClient.get("/archives"); setItems(data); }
    catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!form.title) { toast.error("Titre requis"); return; }
    try {
      await apiClient.post("/archives", {
        title: form.title, category: form.category, description: form.description || null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      });
      toast.success("Archive ajoutée");
      setOpen(false);
      setForm({ title: "", category: "autre", description: "", tags: "" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  const remove = async (a) => {
    if (!window.confirm(`Supprimer "${a.title}" ?`)) return;
    try { await apiClient.delete(`/archives/${a.id}`); await load(); }
    catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-archives-page">
      <div className="flex justify-between items-end">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Bibliothèque</div>
          <h1 className="font-display text-3xl md:text-4xl">Archives cabinet</h1>
          <p className="text-muted-foreground mt-1">Réglementation, guides internes, documents de référence.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-archive-btn"><Plus className="w-4 h-4 mr-2" />Ajouter</Button>
          </DialogTrigger>
          <DialogContent data-testid="archive-dialog">
            <DialogHeader><DialogTitle>Nouveau document d'archive</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Titre</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="archive-title-input" /></div>
              <div><Label>Catégorie</Label><Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="archive-category-input" /></div>
              <div><Label>Description</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="archive-desc-input" /></div>
              <div><Label>Tags (virgules)</Label><Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} data-testid="archive-tags-input" /></div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="archive-submit-btn">Ajouter</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader><TableRow><TableHead>Titre</TableHead><TableHead>Catégorie</TableHead><TableHead>Tags</TableHead><TableHead>Créé</TableHead><TableHead className="text-right">Action</TableHead></TableRow></TableHeader>
          <TableBody>
            {items.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Aucun document archivé.</TableCell></TableRow>}
            {items.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-medium flex items-center gap-2"><Archive className="w-4 h-4 text-[#0F6B4A]" />{a.title}</TableCell>
                <TableCell><span className="albarka-chip bg-slate-100 text-slate-700">{a.category}</span></TableCell>
                <TableCell className="text-xs">{(a.tags || []).join(", ")}</TableCell>
                <TableCell className="text-xs">{a.created_at?.slice(0, 10)}</TableCell>
                <TableCell className="text-right"><Button variant="ghost" size="sm" onClick={() => remove(a)} data-testid={`delete-archive-${a.id}`}><Trash2 className="w-4 h-4 text-red-600" /></Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// AdminMessaging — centre de messagerie (broadcast).
// -----------------------------------------------------------------------
export function AdminMessaging() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ subject: "", body: "", scope: "clients", channel: "email" });

  const load = async () => {
    try { const { data } = await apiClient.get("/messaging/broadcasts"); setItems(data); }
    catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!form.subject || !form.body) { toast.error("Sujet et message requis"); return; }
    try {
      const { data } = await apiClient.post("/messaging/broadcast", form);
      toast.success(`Diffusion envoyée : ${data.delivered}/${data.delivery_attempts}`);
      setOpen(false);
      setForm({ subject: "", body: "", scope: "clients", channel: "email" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-messaging-page">
      <div className="flex justify-between items-end">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Communication</div>
          <h1 className="font-display text-3xl md:text-4xl">Messagerie</h1>
          <p className="text-muted-foreground mt-1">Diffusion à tous les clients ou collaborateurs.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-broadcast-btn"><Send className="w-4 h-4 mr-2" />Nouvelle diffusion</Button>
          </DialogTrigger>
          <DialogContent data-testid="broadcast-dialog">
            <DialogHeader><DialogTitle>Nouvelle diffusion</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Sujet</Label><Input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} data-testid="broadcast-subject-input" /></div>
              <div><Label>Message</Label><Textarea rows={5} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} data-testid="broadcast-body-input" /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Destinataires</Label>
                  <Select value={form.scope} onValueChange={(v) => setForm({ ...form, scope: v })}>
                    <SelectTrigger data-testid="broadcast-scope-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="clients">Tous les clients</SelectItem>
                      <SelectItem value="staff">Collaborateurs</SelectItem>
                      <SelectItem value="all">Tout le monde</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Canal</Label>
                  <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v })}>
                    <SelectTrigger data-testid="broadcast-channel-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="email">Email</SelectItem>
                      <SelectItem value="whatsapp">WhatsApp</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="broadcast-submit-btn">Envoyer</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader><TableRow><TableHead>Sujet</TableHead><TableHead>Périmètre</TableHead><TableHead>Canal</TableHead><TableHead className="text-center">Envoyés</TableHead><TableHead>Date</TableHead></TableRow></TableHeader>
          <TableBody>
            {items.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Aucune diffusion pour le moment.</TableCell></TableRow>}
            {items.map((b) => (
              <TableRow key={b.id}>
                <TableCell className="font-medium">{b.subject}</TableCell>
                <TableCell><span className="albarka-chip bg-slate-100 text-slate-700">{b.scope}</span></TableCell>
                <TableCell>{b.channel}</TableCell>
                <TableCell className="text-center">{b.delivered_count || 0} / {b.recipient_count || 0}</TableCell>
                <TableCell className="text-xs">{b.created_at?.slice(0, 16).replace("T", " ")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// AdminPlatformLogs — journal d'audit.
// -----------------------------------------------------------------------
export function AdminPlatformLogs() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");

  const load = async () => {
    try {
      const params = filter ? { action: filter } : {};
      const { data } = await apiClient.get("/platform-logs", { params });
      setItems(data);
    } catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, [filter]);

  return (
    <div className="space-y-6" data-testid="admin-logs-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Audit</div>
        <h1 className="font-display text-3xl md:text-4xl">Journal plateforme</h1>
        <p className="text-muted-foreground mt-1">Actions récentes des collaborateurs et des clients (accès superviseur/direction/administrateur).</p>
      </div>
      <div className="albarka-card p-4 max-w-md">
        <Label>Filtre action</Label>
        <Input placeholder="ex. invoice.create, chat.post…" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="logs-filter-input" />
      </div>
      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Action</TableHead><TableHead>Entité</TableHead><TableHead>Auteur</TableHead><TableHead>Rôle</TableHead><TableHead>Métadonnées</TableHead></TableRow></TableHeader>
          <TableBody>
            {items.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Aucun événement.</TableCell></TableRow>}
            {items.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="text-xs">{l.created_at?.slice(0, 19).replace("T", " ")}</TableCell>
                <TableCell><span className="albarka-chip bg-[#0F6B4A]/10 text-[#0F6B4A] font-mono text-[10px]">{l.action}</span></TableCell>
                <TableCell className="text-xs font-mono">{l.entity_type} {l.entity_id?.slice(0, 8)}…</TableCell>
                <TableCell className="text-sm">{l.actor_name}</TableCell>
                <TableCell className="text-xs">
                  <div className="flex flex-wrap gap-1">
                    {(l.actor_roles || []).map((r) => (
                      <span key={r} className="albarka-chip bg-slate-100 text-slate-700 text-[10px]">{r}</span>
                    ))}
                    {(!l.actor_roles || l.actor_roles.length === 0) && <span className="text-muted-foreground">—</span>}
                  </div>
                </TableCell>
                <TableCell className="text-xs font-mono truncate max-w-xs">{JSON.stringify(l.meta || {}).slice(0, 120)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export default AdminPlatformLogs;
