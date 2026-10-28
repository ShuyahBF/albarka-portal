import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, FileSignature, Pencil, Paperclip, Download } from "lucide-react";
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

// Lot 66 — document du contrat (Word, PDF ou image) téléversé et rattaché au contrat
const DOC_ACCEPT = ".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp";
const DOC_MAX = 20 * 1024 * 1024;
const tailleLisible = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} Mo` : `${Math.max(1, Math.round((n || 0) / 1024))} Ko`);

const emptyForm = () => ({
  tenant_id: "", numero_contrat: "", title: "", start_date: "", end_date: "",
  amount: "", currency: "XOF", status: "en_cours",
  date_dernier_paiement: "", notes: "",
});

// Lot 78 — même composant pour la page « Contrats clients » (tous les clients) et pour l'onglet « Historique des Contrats »
// de la fiche d'un client (prop tenantId : liste limitée à ce client, client imposé dans le formulaire de création).
export default function AdminContracts({ tenantId = null }) {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [numeroModifiable, setNumeroModifiable] = useState(false);   // lot 78 : DG et super-admin seulement (décidé par le serveur)
  const [fichierNouveau, setFichierNouveau] = useState(null);   // lot 66 : document choisi à la création du contrat
  const [envoiId, setEnvoiId] = useState(null);                  // lot 66 : contrat dont le document est en cours d'envoi
  const champFichier = useRef(null);                             // lot 66 : sélecteur de fichier unique (boutons « Attacher / Remplacer »)
  const cibleFichier = useRef(null);                             // contrat visé par le sélecteur

  const clientNames = React.useMemo(
    () => Object.fromEntries(clients.map((c) => [c.id, `${c.full_name}${c.company ? ` — ${c.company}` : ""}`])),
    [clients],
  );

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: contracts }, { data: cls }] = await Promise.all([
        apiClient.get("/client-contracts", { params: tenantId ? { tenant_id: tenantId } : {} }),
        tenantId ? Promise.resolve({ data: [] }) : apiClient.get("/clients"),   // fiche client : le client est déjà connu
      ]);
      setItems(contracts);
      setClients(cls);
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [tenantId]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Lot 78 — numéro proposé (dernier numéro de l'année + 1) et droit de le modifier, tous deux fournis par le serveur
  const chargerNumero = async () => {
    try {
      const { data } = await apiClient.get("/client-contracts/prochain-numero");
      setNumeroModifiable(!!data.modifiable);
      return data.numero || "";
    } catch { return ""; }
  };
  useEffect(() => { chargerNumero(); }, []);

  // Lot 66 — contrôle du fichier choisi (format et taille) avant l'envoi
  const fichierValide = (f) => {
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (!DOC_ACCEPT.split(",").includes(`.${ext}`)) { toast.error("Format non accepté : Word (.doc, .docx), PDF ou image (.jpg, .png, .webp)"); return false; }
    if (f.size > DOC_MAX) { toast.error("Le fichier dépasse 20 Mo"); return false; }
    return true;
  };
  // Téléverse le document d'un contrat (remplace l'éventuel document existant)
  const televerser = async (contratId, f) => {
    if (!fichierValide(f)) return false;
    setEnvoiId(contratId);
    try {
      const fd = new FormData(); fd.append("file", f);
      await apiClient.post(`/client-contracts/${contratId}/document`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Document attaché au contrat");
      await load();
      return true;
    } catch (err) { toast.error(extractError(err, "Envoi du document impossible")); return false; }
    finally { setEnvoiId(null); }
  };
  const choisirDocument = (c) => { cibleFichier.current = c; champFichier.current?.click(); };
  const documentChoisi = async (e) => {
    const f = e.target.files?.[0]; e.target.value = "";
    const c = cibleFichier.current; cibleFichier.current = null;
    if (!f || !c) return;
    const ok = await televerser(c.id, f);
    if (ok && editing?.id === c.id) setEditing((prev) => prev && ({ ...prev }));
  };
  const ouvrirDocument = async (c, telecharger = false) => {
    try {
      const res = await apiClient.get(`/client-contracts/${c.id}/document`, { responseType: "blob", params: telecharger ? { download: true } : {} });
      const url = window.URL.createObjectURL(res.data);
      if (telecharger) { const a = document.createElement("a"); a.href = url; a.download = c.document?.filename || "contrat"; a.click(); }
      else window.open(url, "_blank");
    } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
  };
  const retirerDocument = async (c) => {
    if (!window.confirm(`Retirer le document « ${c.document?.filename} » du contrat ?`)) return;
    try { await apiClient.delete(`/client-contracts/${c.id}/document`); toast.success("Document retiré"); await load(); }
    catch (err) { toast.error(extractError(err)); }
  };

  const openNew = async () => {
    setEditing(null); setFichierNouveau(null);
    setForm({ ...emptyForm(), tenant_id: tenantId || "" });
    setOpen(true);
    const numero = await chargerNumero();                  // numéro proposé, rempli dès que le serveur répond
    setForm((f) => ({ ...f, numero_contrat: numero }));
  };
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
        if (!numeroModifiable) delete payload.numero_contrat;   // lot 78 : le numéro n'est pas modifiable par ce profil
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
        if (!numeroModifiable) delete payload.numero_contrat;   // lot 78 : attribué par le serveur (dernier numéro + 1)
        if (payload.amount === "") delete payload.amount;
        else payload.amount = Number(payload.amount);
        if (!payload.end_date) delete payload.end_date;
        const { data: cree } = await apiClient.post("/client-contracts", payload);
        toast.success("Contrat créé");
        if (fichierNouveau && cree?.id) await televerser(cree.id, fichierNouveau);   // lot 66 : document choisi dans le formulaire
      } catch (err) { toast.error(extractError(err)); return; }
    }
    setOpen(false);
    setEditing(null);
    setFichierNouveau(null);
    setForm({ ...emptyForm(), tenant_id: tenantId || "" });
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
    <div className={tenantId ? "space-y-4" : "space-y-6"} data-testid="admin-contracts-page">
      <input ref={champFichier} type="file" accept={DOC_ACCEPT} className="hidden" onChange={documentChoisi} data-testid="contract-document-input" />
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        {tenantId ? (
          <div>
            <h2 className="font-display text-xl text-foreground" data-testid="historique-contrats-titre">Historique des contrats</h2>
            <p className="text-muted-foreground text-sm mt-1 max-w-2xl">
              Un contrat actif est <strong>obligatoire</strong> pour que ce client puisse se connecter au portail.
            </p>
          </div>
        ) : (
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
            <h1 className="font-display text-3xl md:text-4xl text-foreground">Contrats clients</h1>
            <p className="text-muted-foreground mt-1 max-w-2xl">
              Un contrat actif est <strong>obligatoire</strong> pour qu'un client puisse se connecter au portail.
            </p>
          </div>
        )}
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
              {!editing && !tenantId && (
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
              <div>
                <Label>Numéro de contrat <span className="text-[10px] text-muted-foreground">{numeroModifiable ? "(proposé, modifiable par le DG et le super-admin)" : "(attribué automatiquement, non modifiable)"}</span></Label>
                <Input value={form.numero_contrat} readOnly={!numeroModifiable} disabled={!numeroModifiable}
                  onChange={(e) => setForm({ ...form, numero_contrat: e.target.value })} placeholder="CTR-2026-0001" data-testid="contract-numero-input" />
              </div>
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
              {/* Lot 66 — document du contrat : à la création (choisi puis envoyé avec le contrat) ou à la modification */}
              <div className="rounded-lg border border-dashed border-[#0F6B4A]/40 p-3" data-testid="contract-document-zone">
                <Label className="flex items-center gap-1"><Paperclip className="w-4 h-4" /> Document du contrat <span className="text-[10px] text-muted-foreground">(Word, PDF ou image, 20 Mo au plus)</span></Label>
                {editing ? (() => {
                  const cur = items.find((x) => x.id === editing.id) || editing;
                  return cur.document ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                      <button type="button" className="underline text-[#0F6B4A]" onClick={() => ouvrirDocument(cur)} data-testid="contract-document-open">{cur.document.filename}</button>
                      <span className="text-xs text-muted-foreground">{tailleLisible(cur.document.size)}</span>
                      <Button type="button" size="sm" variant="outline" onClick={() => choisirDocument(cur)} disabled={envoiId === cur.id} data-testid="contract-document-replace">Remplacer</Button>
                      <Button type="button" size="sm" variant="ghost" className="text-red-600" onClick={() => retirerDocument(cur)} data-testid="contract-document-remove">Retirer</Button>
                    </div>
                  ) : (
                    <Button type="button" size="sm" variant="outline" className="mt-2" onClick={() => choisirDocument(cur)} disabled={envoiId === cur.id} data-testid="contract-document-attach">
                      <Paperclip className="w-4 h-4 mr-1" />{envoiId === cur.id ? "Envoi…" : "Attacher un document"}
                    </Button>
                  );
                })() : (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <input type="file" accept={DOC_ACCEPT} data-testid="contract-document-new"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f && fichierValide(f)) setFichierNouveau(f); else { setFichierNouveau(null); e.target.value = ""; } }} />
                    {fichierNouveau && <span className="text-xs text-muted-foreground">{fichierNouveau.name} · {tailleLisible(fichierNouveau.size)}</span>}
                  </div>
                )}
              </div>
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
              {!tenantId && <TableHead>Client</TableHead>}
              <TableHead>Début</TableHead>
              <TableHead>Fin</TableHead>
              <TableHead className="text-right">Montant</TableHead>
              <TableHead>Dernier paiement</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={tenantId ? 7 : 8} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={tenantId ? 7 : 8} className="text-center py-10 text-muted-foreground">Aucun contrat.</TableCell></TableRow>}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <FileSignature className="w-4 h-4 text-[#0F6B4A]" />
                    <div>
                      <div className="font-mono text-xs text-muted-foreground">{c.numero_contrat || "—"}</div>
                      <div className="text-sm">{c.title}</div>
                      {c.document && (
                        <button type="button" className="mt-0.5 inline-flex items-center gap-1 text-xs text-[#0F6B4A] underline" onClick={() => ouvrirDocument(c)} title={`${c.document.filename} · ${tailleLisible(c.document.size)}`} data-testid={`contract-document-link-${c.id}`}>
                          <Paperclip className="w-3 h-3" />{c.document.filename.length > 28 ? `${c.document.filename.slice(0, 26)}…` : c.document.filename}
                        </button>
                      )}
                    </div>
                  </div>
                </TableCell>
                {!tenantId && (
                  <TableCell className="text-xs">
                    <div className="font-medium text-foreground text-sm">{clientNames[c.tenant_id] || "Client inconnu"}</div>
                    <div className="font-mono text-muted-foreground">{c.tenant_id.slice(0, 10)}…</div>
                  </TableCell>
                )}
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
                  {/* Lot 66 — document du contrat : attacher / remplacer, télécharger, retirer */}
                  <Button variant="ghost" size="sm" onClick={() => choisirDocument(c)} disabled={envoiId === c.id} title={c.document ? "Remplacer le document" : "Attacher un document (Word, PDF, image)"} data-testid={`attach-contract-${c.id}`}>
                    <Paperclip className={`w-4 h-4 ${c.document ? "text-[#0F6B4A]" : ""}`} />
                  </Button>
                  {c.document && (
                    <Button variant="ghost" size="sm" onClick={() => ouvrirDocument(c, true)} title="Télécharger le document" data-testid={`download-contract-${c.id}`}>
                      <Download className="w-4 h-4" />
                    </Button>
                  )}
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
