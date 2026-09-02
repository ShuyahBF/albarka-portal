import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { KeyRound, Plus, Trash2, CheckCircle2, ShieldAlert, Calendar } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

export default function CertificatesPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    common_name: "Cabinet ALBARKA",
    organization: "Cabinet ALBARKA SARL",
    country: "BF",
    email: "",
    valid_years: 5,
    passphrase: "",
    activate: true,
  });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/admin/certificates");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.passphrase || form.passphrase.length < 8) {
      toast.error("Passphrase de 8 caractères minimum requise");
      return;
    }
    setBusy(true);
    try {
      await apiClient.post("/admin/certificates", form);
      toast.success("Certificat créé et activé");
      setOpen(false);
      setForm({ ...form, passphrase: "" });
      await load();
    } catch (err) {
      toast.error(extractError(err));
    } finally { setBusy(false); }
  };

  const activate = async (id) => {
    try {
      await apiClient.post(`/admin/certificates/${id}/activate`);
      toast.success("Certificat activé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const remove = async (c) => {
    const msg = c.is_active
      ? `Supprimer le certificat ACTIF "${c.common_name}" ? La signature réelle sera désactivée jusqu'à ce qu'un autre certificat soit activé (auto-basculement sur le plus récent).`
      : `Supprimer le certificat "${c.common_name}" ? Cette action est irréversible.`;
    if (!window.confirm(msg)) return;
    try {
      const { data } = await apiClient.delete(`/admin/certificates/${c.id}`);
      if (data.auto_activated) toast.info("Un autre certificat a été activé automatiquement.");
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="certificates-panel">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <KeyRound className="w-4 h-4 text-[#0F6B4A]" />
            Certificats de signature du cabinet
          </div>
          <div className="text-sm text-muted-foreground">
            Signature électronique <b>PAdES-B</b> des rapports PDF via pyHanko. Le certificat auto-signé
            scelle et horodate le document ; il est vérifiable dans Adobe Reader (après ajout du certificat public
            à la liste des émetteurs de confiance).
          </div>
        </div>
        <Button onClick={() => setOpen(true)} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-cert-btn">
          <Plus className="w-4 h-4 mr-2" />Nouveau certificat
        </Button>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom courant</TableHead>
              <TableHead>Organisation</TableHead>
              <TableHead>Valide jusqu'au</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-10 text-muted-foreground">
                  <ShieldAlert className="w-8 h-8 mx-auto mb-2 text-slate-400" />
                  Aucun certificat cabinet. Créez-en un pour activer la signature réelle des rapports PDF.
                </TableCell>
              </TableRow>
            )}
            {items.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">{c.common_name}</TableCell>
                <TableCell className="text-sm">{c.organization}</TableCell>
                <TableCell className="text-sm flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  {c.not_valid_after?.slice(0, 10)}
                </TableCell>
                <TableCell>
                  {c.is_active
                    ? <span className="albarka-chip bg-emerald-100 text-emerald-800 inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />Actif</span>
                    : <span className="albarka-chip bg-slate-100 text-slate-600">Inactif</span>}
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {!c.is_active && (
                    <Button variant="ghost" size="sm" onClick={() => activate(c.id)} title="Activer" data-testid={`activate-cert-${c.id}`}>
                      <CheckCircle2 className="w-4 h-4 text-[#0F6B4A]" />
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => remove(c)} title="Supprimer" data-testid={`delete-cert-${c.id}`}>
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="cert-dialog">
          <DialogHeader><DialogTitle>Nouveau certificat auto-signé</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground border-l-2 border-[#0F6B4A]/40 pl-2">
              La clé privée (P12) est générée et chiffrée sur le serveur. La passphrase est stockée chiffrée
              via <span className="font-mono">Fernet(JWT_SECRET_KEY)</span>. Notez-la pour récupération en cas
              de reset. Validité recommandée : 5 ans.
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Nom courant (CN)</Label><Input value={form.common_name} onChange={(e) => setForm({ ...form, common_name: e.target.value })} data-testid="cert-cn-input" /></div>
              <div><Label>Pays (2 lettres)</Label><Input maxLength={2} value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value.toUpperCase() })} data-testid="cert-country-input" /></div>
            </div>
            <div><Label>Organisation</Label><Input value={form.organization} onChange={(e) => setForm({ ...form, organization: e.target.value })} data-testid="cert-org-input" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Email (optionnel)</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="cert-email-input" /></div>
              <div>
                <Label>Validité (années)</Label>
                <Input type="number" min={1} max={15} value={form.valid_years} onChange={(e) => setForm({ ...form, valid_years: parseInt(e.target.value, 10) || 5 })} data-testid="cert-years-input" />
              </div>
            </div>
            <div>
              <Label>Passphrase du certificat</Label>
              <Input type="password" value={form.passphrase} onChange={(e) => setForm({ ...form, passphrase: e.target.value })} placeholder="8 caractères min." data-testid="cert-passphrase-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button onClick={create} disabled={busy} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="cert-submit-btn">
              {busy ? "Génération…" : "Créer & activer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
