import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, CreditCard } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import PaymentLinkForm from "@/components/PaymentLinkForm";

const STATUS_TONE = {
  initiated: "bg-slate-100 text-slate-700",
  pending: "bg-amber-100 text-amber-800",
  completed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-700",
};
const STATUS_LABEL = {
  initiated: "Initié", pending: "En attente", completed: "Payé", failed: "Échoué",
};

// Réservée au rôle "caissier" (voir PortalLayout.jsx / PAYMENTS_ROLES côté
// backend) — liens de paiement mobile money (PawaPay), portés depuis
// ShuyahBF/Emergent et adaptés : ici c'est le caissier qui génère le lien
// au nom d'un client choisi, pas le client qui l'initie lui-même.
export default function AdminPayments() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/payments");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const onCreated = () => { load(); };

  return (
    <div className="space-y-6" data-testid="admin-payments-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Paiements</h1>
          <p className="text-muted-foreground mt-1">Liens de paiement mobile money (Orange, Moov, Telecel via PawaPay).</p>
        </div>
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); }}>
          <DialogTrigger asChild>
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-payment-link-btn">
              <Plus className="w-4 h-4 mr-2" />Nouveau lien de paiement
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="payment-link-dialog">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2"><CreditCard className="w-4 h-4" />Nouveau lien de paiement</DialogTitle>
            </DialogHeader>
            <PaymentLinkForm onCreated={onCreated} />
          </DialogContent>
        </Dialog>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Client</TableHead>
              <TableHead className="text-right">Montant</TableHead>
              <TableHead>Motif</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead>Créé par</TableHead>
              <TableHead>Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-10 text-muted-foreground">Aucun lien de paiement.</TableCell></TableRow>}
            {items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.client_label || "—"}</TableCell>
                <TableCell className="text-right font-mono">{Number(p.amount).toLocaleString()} {p.currency}</TableCell>
                <TableCell className="text-sm">{p.reason || "—"}</TableCell>
                <TableCell>
                  <span className={`albarka-chip ${STATUS_TONE[p.status] || "bg-slate-100 text-slate-700"}`}>
                    {STATUS_LABEL[p.status] || p.status}
                  </span>
                </TableCell>
                <TableCell className="text-sm">{p.created_by_name}</TableCell>
                <TableCell className="text-xs">{p.created_at?.slice(0, 16).replace("T", " ")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
