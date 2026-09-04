import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Receipt, Wallet } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import EntitySelect from "@/components/EntitySelect";

export default function AdminBilling() {
  const [invoices, setInvoices] = useState([]);
  const [payments, setPayments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [openInv, setOpenInv] = useState(false);
  const [openPay, setOpenPay] = useState(false);
  const [payTarget, setPayTarget] = useState(null);
  const [invForm, setInvForm] = useState({ tenant_id: "", title: "", label: "", quantity: 1, unit_price: "", tax_rate: 18, document_type: "facture" });
  const [payForm, setPayForm] = useState({ amount: "", method: "cash", reference: "" });

  const load = async () => {
    try {
      const [{ data: inv }, { data: pay }, { data: sum }] = await Promise.all([
        apiClient.get("/billing/invoices"),
        apiClient.get("/billing/payments"),
        apiClient.get("/billing/summary"),
      ]);
      setInvoices(inv); setPayments(pay); setSummary(sum);
    } catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, []);

  const submitInvoice = async () => {
    if (!invForm.tenant_id || !invForm.title || !invForm.label || !invForm.unit_price) {
      toast.error("Client, titre, ligne et prix requis"); return;
    }
    try {
      await apiClient.post("/billing/invoices", {
        tenant_id: invForm.tenant_id, title: invForm.title,
        document_type: invForm.document_type,
        items: [{ label: invForm.label, quantity: Number(invForm.quantity), unit_price: Number(invForm.unit_price), tax_rate: Number(invForm.tax_rate) }],
      });
      toast.success(`${invForm.document_type === "recu" ? "Reçu" : invForm.document_type === "proforma" ? "Proforma" : "Facture"} créé(e)`);
      setOpenInv(false);
      setInvForm({ tenant_id: "", title: "", label: "", quantity: 1, unit_price: "", tax_rate: 18, document_type: "facture" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  const submitPayment = async () => {
    if (!payTarget || !payForm.amount) { toast.error("Montant requis"); return; }
    try {
      await apiClient.post("/billing/payments", {
        invoice_id: payTarget.id, amount: Number(payForm.amount),
        method: payForm.method, reference: payForm.reference || null,
      });
      toast.success("Encaissement enregistré");
      setOpenPay(false);
      setPayForm({ amount: "", method: "cash", reference: "" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-billing-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl">Caisse & facturation</h1>
        <p className="text-muted-foreground mt-1">Factures clients et encaissements.</p>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="billing-summary">
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Factures</div><div className="text-2xl font-display">{summary.invoice_count}</div></div>
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Facturé</div><div className="text-2xl font-display">{Number(summary.total_billed).toLocaleString()}</div></div>
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Encaissé</div><div className="text-2xl font-display text-emerald-700">{Number(summary.total_paid).toLocaleString()}</div></div>
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Reste dû</div><div className="text-2xl font-display text-amber-700">{Number(summary.outstanding).toLocaleString()}</div></div>
        </div>
      )}

      <Tabs defaultValue="invoices">
        <TabsList>
          <TabsTrigger value="invoices" data-testid="tab-billing-invoices"><Receipt className="w-4 h-4 mr-2" />Factures</TabsTrigger>
          <TabsTrigger value="payments" data-testid="tab-billing-payments"><Wallet className="w-4 h-4 mr-2" />Encaissements</TabsTrigger>
        </TabsList>

        <TabsContent value="invoices" className="pt-4 space-y-3">
          <div className="flex justify-end">
            <Dialog open={openInv} onOpenChange={setOpenInv}>
              <DialogTrigger asChild>
                <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-invoice-btn"><Plus className="w-4 h-4 mr-2" />Nouvelle facture</Button>
              </DialogTrigger>
              <DialogContent data-testid="invoice-dialog">
                <DialogHeader><DialogTitle>Nouveau document caisse</DialogTitle></DialogHeader>
                <div className="space-y-3">
                  <div>
                    <Label>Type de document</Label>
                    <Select value={invForm.document_type} onValueChange={(v) => setInvForm({ ...invForm, document_type: v })}>
                      <SelectTrigger data-testid="invoice-doctype-select"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="facture">Facture</SelectItem>
                        <SelectItem value="recu">Reçu de caisse</SelectItem>
                        <SelectItem value="proforma">Proforma</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div><Label>Client</Label><EntitySelect value={invForm.tenant_id} onChange={(v) => setInvForm({ ...invForm, tenant_id: v })} testId="invoice-tenant-input" /></div>
                  <div><Label>Titre</Label><Input value={invForm.title} onChange={(e) => setInvForm({ ...invForm, title: e.target.value })} data-testid="invoice-title-input" /></div>
                  <div><Label>Description ligne</Label><Input value={invForm.label} onChange={(e) => setInvForm({ ...invForm, label: e.target.value })} data-testid="invoice-label-input" /></div>
                  <div className="grid grid-cols-3 gap-3">
                    <div><Label>Qté</Label><Input type="number" value={invForm.quantity} onChange={(e) => setInvForm({ ...invForm, quantity: e.target.value })} data-testid="invoice-qty-input" /></div>
                    <div><Label>Prix U.</Label><Input type="number" value={invForm.unit_price} onChange={(e) => setInvForm({ ...invForm, unit_price: e.target.value })} data-testid="invoice-price-input" /></div>
                    <div><Label>TVA %</Label><Input type="number" value={invForm.tax_rate} onChange={(e) => setInvForm({ ...invForm, tax_rate: e.target.value })} data-testid="invoice-tax-input" /></div>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setOpenInv(false)}>Annuler</Button>
                  <Button onClick={submitInvoice} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="invoice-submit-btn">Créer</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="albarka-card overflow-hidden">
            <Table>
              <TableHeader><TableRow><TableHead>Numéro</TableHead><TableHead>Type</TableHead><TableHead>Titre</TableHead><TableHead>Total</TableHead><TableHead>Payé</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Action</TableHead></TableRow></TableHeader>
              <TableBody>
                {invoices.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Aucun document caisse.</TableCell></TableRow>}
                {invoices.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell className="font-mono text-xs">{i.number}</TableCell>
                    <TableCell>
                      <span className={`albarka-chip text-[10px] ${
                        i.document_type === "recu" ? "bg-emerald-100 text-emerald-800"
                        : i.document_type === "proforma" ? "bg-blue-100 text-blue-800"
                        : "bg-slate-100 text-slate-700"
                      }`}>
                        {i.document_type === "recu" ? "Reçu" : i.document_type === "proforma" ? "Proforma" : "Facture"}
                      </span>
                    </TableCell>
                    <TableCell>{i.title}</TableCell>
                    <TableCell>{Number(i.total).toLocaleString()} {i.currency}</TableCell>
                    <TableCell>{Number(i.paid_amount || 0).toLocaleString()}</TableCell>
                    <TableCell><span className={`albarka-chip ${i.status === "paid" ? "bg-emerald-100 text-emerald-800" : i.status === "partial" ? "bg-amber-100 text-amber-800" : i.status === "proforma" ? "bg-blue-100 text-blue-800" : "bg-slate-100 text-slate-700"}`}>
                      {i.status === "paid" ? "Payé" : i.status === "partial" ? "Partiel" : i.status === "proforma" ? "Proforma" : i.status === "unpaid" ? "Impayé" : i.status}
                    </span></TableCell>
                    <TableCell className="text-right">
                      {i.status !== "paid" && i.status !== "proforma" && (
                        <Button size="sm" variant="outline" onClick={() => { setPayTarget(i); setOpenPay(true); }} data-testid={`pay-invoice-${i.id}`}>Encaisser</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="payments" className="pt-4">
          <div className="albarka-card overflow-hidden">
            <Table>
              <TableHeader><TableRow><TableHead>Facture</TableHead><TableHead>Montant</TableHead><TableHead>Méthode</TableHead><TableHead>Référence</TableHead><TableHead>Date</TableHead></TableRow></TableHeader>
              <TableBody>
                {payments.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Aucun encaissement.</TableCell></TableRow>}
                {payments.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.invoice_number}</TableCell>
                    <TableCell>{Number(p.amount).toLocaleString()}</TableCell>
                    <TableCell>{p.method}</TableCell>
                    <TableCell>{p.reference || "—"}</TableCell>
                    <TableCell className="text-xs">{p.paid_at?.slice(0, 16).replace("T", " ")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={openPay} onOpenChange={setOpenPay}>
        <DialogContent data-testid="payment-dialog">
          <DialogHeader><DialogTitle>Encaisser {payTarget?.number}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground">Reste dû : {Number((payTarget?.total || 0) - (payTarget?.paid_amount || 0)).toLocaleString()} {payTarget?.currency}</div>
            <div><Label>Montant</Label><Input type="number" value={payForm.amount} onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })} data-testid="payment-amount-input" /></div>
            <div>
              <Label>Méthode</Label>
              <Select value={payForm.method} onValueChange={(v) => setPayForm({ ...payForm, method: v })}>
                <SelectTrigger data-testid="payment-method-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cash">Espèces</SelectItem>
                  <SelectItem value="mobile_money">Mobile Money</SelectItem>
                  <SelectItem value="bank">Virement</SelectItem>
                  <SelectItem value="other">Autre</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label>Référence</Label><Input value={payForm.reference} onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })} data-testid="payment-ref-input" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenPay(false)}>Annuler</Button>
            <Button onClick={submitPayment} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="payment-submit-btn">Valider</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
