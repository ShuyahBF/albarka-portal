import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Receipt, Wallet, X } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import EntitySelect from "@/components/EntitySelect";
import { useAuth } from "@/contexts/AuthContext";

// Doit rester identique à CAISSE_DATE_RANGE_ROLES côté backend (albarka_models.py).
const CAISSE_DATE_RANGE_ROLES = ["administrateur", "dg", "superviseur"];

export default function AdminBilling() {
  const { user } = useAuth();
  const canPickDateRange = (user?.roles || []).some((r) => CAISSE_DATE_RANGE_ROLES.includes(r));

  const [invoices, setInvoices] = useState([]);
  const [payments, setPayments] = useState([]);
  const [summary, setSummary] = useState(null);
  const [openInv, setOpenInv] = useState(false);
  const [openPay, setOpenPay] = useState(false);
  const [payTarget, setPayTarget] = useState(null);
  const [invForm, setInvForm] = useState({ tenant_id: "", title: "", label: "", quantity: 1, unit_price: "", tax_rate: 18, document_type: "facture" });
  const [payForm, setPayForm] = useState({ amount: "", method: "cash", reference: "" });
  const [filterTenantId, setFilterTenantId] = useState("");
  // Résout tenant_id -> {company, full_name} pour la colonne Client à
  // l'écran ("Entreprise (Nom client)" — voir clientLabel ci-dessous). Le
  // PDF exporté, lui, n'affiche jamais le nom du client (voir backend
  // build_billing_statement_pdf).
  const [clientsById, setClientsById] = useState({});
  const [openSend, setOpenSend] = useState(false);
  const [sendChannel, setSendChannel] = useState("whatsapp");
  const [exporting, setExporting] = useState(false);
  const [sending, setSending] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // Presets au-dessus du sélecteur Du/Au — visibles seulement pour les rôles
  // autorisés à choisir une période (CAISSE_DATE_RANGE_ROLES) :
  //  - "all"    : Depuis toujours — aucun filtre de date (all_time=true).
  //  - "3m"     : 3 derniers mois — calculé une fois puis traité comme une
  //               période classique.
  //  - "custom" : Période — les champs Du/Au manuels existants.
  const [rangeMode, setRangeMode] = useState("custom");

  const todayISO = () => new Date().toISOString().slice(0, 10);
  const threeMonthsAgoISO = () => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  };

  const load = async (overrides = {}) => {
    const mode = overrides.rangeMode ?? rangeMode;
    const from = overrides.dateFrom ?? dateFrom;
    const to = overrides.dateTo ?? dateTo;
    try {
      const params = { tenant_id: filterTenantId || undefined };
      const dateParams = canPickDateRange
        ? (mode === "all" ? { all_time: true } : { date_from: from || undefined, date_to: to || undefined })
        : {};
      const [{ data: inv }, { data: pay }, { data: sum }] = await Promise.all([
        apiClient.get("/billing/invoices", { params }),
        apiClient.get("/billing/payments", { params: { ...params, ...dateParams } }),
        apiClient.get("/billing/summary", { params: { ...params, ...dateParams } }),
      ]);
      setInvoices(inv); setPayments(pay); setSummary(sum);
      // Reflète la période réellement appliquée par le serveur (utile pour
      // les non-privilégiés, forcés sur "aujourd'hui" même sans sélecteur).
      // Ignoré en mode "Depuis toujours" : le serveur renvoie alors
      // date_from/date_to à null, qui ne doivent pas écraser les champs
      // Du/Au (masqués dans ce mode, mais réutilisés si on repasse en Période).
      if (sum && mode !== "all") { setDateFrom(sum.date_from); setDateTo(sum.date_to); }
    } catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, [filterTenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    apiClient.get("/clients").then(({ data }) => {
      const map = {};
      for (const c of data || []) map[c.id] = c;
      setClientsById(map);
    }).catch(() => {});
  }, []);

  const clientLabel = (tenantId) => {
    const c = clientsById[tenantId];
    if (!c) return "—";
    return c.company ? `${c.company} (${c.full_name})` : c.full_name;
  };

  const applyDateRange = () => load();

  const selectAllTime = () => { setRangeMode("all"); load({ rangeMode: "all" }); };
  const select3Months = () => {
    const from = threeMonthsAgoISO();
    const to = todayISO();
    setRangeMode("3m");
    setDateFrom(from);
    setDateTo(to);
    load({ rangeMode: "3m", dateFrom: from, dateTo: to });
  };
  const selectCustomPeriod = () => setRangeMode("custom");

  // Filtres actuellement appliqués à l'écran, réutilisés tels quels pour
  // l'export PDF / l'envoi client ("situation de compte") — voir
  // GET/POST /billing/statement/* côté backend.
  const currentStatementParams = () => ({
    tenant_id: filterTenantId || undefined,
    ...(canPickDateRange
      ? (rangeMode === "all" ? { all_time: true } : { date_from: dateFrom || undefined, date_to: dateTo || undefined })
      : {}),
  });

  const exportStatementPdf = async () => {
    setExporting(true);
    try {
      const res = await apiClient.get("/billing/statement/pdf", {
        params: currentStatementParams(), responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `situation_de_compte_${filterTenantId || "tous_clients"}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(extractError(err, "Échec de l'export PDF"));
    } finally { setExporting(false); }
  };

  const sendStatement = async () => {
    if (!filterTenantId) return;
    setSending(true);
    try {
      const { data } = await apiClient.post("/billing/statement/send", {
        ...currentStatementParams(), tenant_id: filterTenantId, channel: sendChannel,
      });
      toast.success(`Situation de compte envoyée (${sendChannel === "whatsapp" ? "WhatsApp" : "email"}) à ${data.to}`);
      setOpenSend(false);
    } catch (err) {
      toast.error(extractError(err, "Échec de l'envoi"));
    } finally { setSending(false); }
  };

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

      <div className="flex flex-wrap items-end gap-3" data-testid="billing-filters">
        <div className="w-full sm:w-64">
          <Label className="text-xs">Filtrer par client (entreprise)</Label>
          <div className="flex items-center gap-1 mt-1">
            <EntitySelect
              value={filterTenantId}
              onChange={setFilterTenantId}
              placeholder="Tous les clients"
              testId="billing-tenant-filter"
            />
            {filterTenantId && (
              <Button variant="ghost" size="sm" className="px-2" onClick={() => setFilterTenantId("")} data-testid="billing-tenant-filter-clear">
                <X className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>

        {canPickDateRange ? (
          <div className="flex items-end gap-2 flex-wrap" data-testid="billing-date-range">
            <div className="flex gap-1" data-testid="billing-range-presets">
              <Button
                type="button" size="sm"
                variant={rangeMode === "all" ? "default" : "outline"}
                className={rangeMode === "all" ? "bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" : ""}
                onClick={selectAllTime} data-testid="billing-range-all-time"
              >
                Depuis toujours
              </Button>
              <Button
                type="button" size="sm"
                variant={rangeMode === "3m" ? "default" : "outline"}
                className={rangeMode === "3m" ? "bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" : ""}
                onClick={select3Months} data-testid="billing-range-3-months"
              >
                3 derniers mois
              </Button>
              <Button
                type="button" size="sm"
                variant={rangeMode === "custom" ? "default" : "outline"}
                className={rangeMode === "custom" ? "bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" : ""}
                onClick={selectCustomPeriod} data-testid="billing-range-custom"
              >
                Période
              </Button>
            </div>
            {rangeMode === "custom" && (
              <>
                <div>
                  <Label className="text-xs">Du</Label>
                  <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="h-10" data-testid="billing-date-from" />
                </div>
                <div>
                  <Label className="text-xs">Au</Label>
                  <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="h-10" data-testid="billing-date-to" />
                </div>
                <Button variant="outline" onClick={applyDateRange} data-testid="billing-date-apply-btn">Appliquer</Button>
              </>
            )}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground pb-2" data-testid="billing-date-fixed">
            Encaissements du jour ({dateFrom || "…"})
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2" data-testid="billing-export-toolbar">
        <Button variant="outline" size="sm" onClick={exportStatementPdf} disabled={exporting} data-testid="billing-export-pdf-btn">
          {exporting ? "Export…" : "Exporter en PDF (situation de compte)"}
        </Button>
        {filterTenantId && (
          <Dialog open={openSend} onOpenChange={setOpenSend}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" data-testid="billing-send-statement-btn">
                Envoyer au client
              </Button>
            </DialogTrigger>
            <DialogContent data-testid="billing-send-statement-dialog">
              <DialogHeader><DialogTitle>Envoyer la situation de compte</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <div className="text-sm text-muted-foreground">
                  Destinataire : {clientLabel(filterTenantId)}
                </div>
                <div>
                  <Label>Canal</Label>
                  <Select value={sendChannel} onValueChange={setSendChannel}>
                    <SelectTrigger data-testid="billing-send-channel-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="whatsapp">WhatsApp</SelectItem>
                      <SelectItem value="email">Email</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpenSend(false)}>Annuler</Button>
                <Button onClick={sendStatement} disabled={sending} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="billing-send-statement-submit">
                  {sending ? "Envoi…" : "Envoyer"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="billing-summary">
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Factures</div><div className="text-2xl font-display">{summary.invoice_count}</div></div>
          <div className="albarka-card p-4"><div className="text-xs text-muted-foreground">Facturé</div><div className="text-2xl font-display">{Number(summary.total_billed).toLocaleString()}</div></div>
          <div className="albarka-card p-4">
            <div className="text-xs text-muted-foreground">
              Encaissé {!canPickDateRange ? "(aujourd'hui)" : rangeMode === "all" ? "(depuis toujours)" : `(${summary.date_from} → ${summary.date_to})`}
            </div>
            <div className="text-2xl font-display text-emerald-700">{Number(summary.total_paid).toLocaleString()}</div>
          </div>
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
              <TableHeader><TableRow><TableHead>Numéro</TableHead><TableHead>Client</TableHead><TableHead>Type</TableHead><TableHead>Titre</TableHead><TableHead className="text-right">Total</TableHead><TableHead className="text-right">Payé</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Action</TableHead></TableRow></TableHeader>
              <TableBody>
                {invoices.length === 0 && <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">Aucun document caisse.</TableCell></TableRow>}
                {invoices.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell className="font-mono text-xs">{i.number}</TableCell>
                    <TableCell className="text-sm">{clientLabel(i.tenant_id)}</TableCell>
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
                    <TableCell className="text-right">{Number(i.total).toLocaleString()} {i.currency}</TableCell>
                    <TableCell className="text-right">{Number(i.paid_amount || 0).toLocaleString()}</TableCell>
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
              <TableHeader><TableRow><TableHead>Facture</TableHead><TableHead>Client</TableHead><TableHead className="text-right">Montant</TableHead><TableHead>Méthode</TableHead><TableHead>Référence</TableHead><TableHead>Date</TableHead></TableRow></TableHeader>
              <TableBody>
                {payments.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Aucun encaissement.</TableCell></TableRow>}
                {payments.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.invoice_number}</TableCell>
                    <TableCell className="text-sm">{clientLabel(p.tenant_id)}</TableCell>
                    <TableCell className="text-right">{Number(p.amount).toLocaleString()}</TableCell>
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
