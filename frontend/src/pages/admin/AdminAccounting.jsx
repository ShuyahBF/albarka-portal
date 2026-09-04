import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, CheckCircle2, BookOpen, ScrollText, Scale, Sparkles } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import EntitySelect from "@/components/EntitySelect";

const JOURNALS = ["OD", "VE", "AC", "BQ", "CA"];

export default function AdminAccounting() {
  const [tenantId, setTenantId] = useState("");
  const [accounts, setAccounts] = useState([]);
  const [entries, setEntries] = useState([]);
  const [balance, setBalance] = useState(null);
  const [openEntry, setOpenEntry] = useState(false);
  const [entryForm, setEntryForm] = useState({
    journal: "OD", entry_date: new Date().toISOString().slice(0, 10),
    label: "", reference: "",
    lines: [
      { account_code: "", debit: "", credit: "", label: "" },
      { account_code: "", debit: "", credit: "", label: "" },
    ],
  });

  const load = async () => {
    if (!tenantId) return;
    try {
      const [{ data: a }, { data: e }, { data: b }] = await Promise.all([
        apiClient.get("/accounting/accounts", { params: { tenant_id: tenantId } }),
        apiClient.get("/accounting/entries", { params: { tenant_id: tenantId } }),
        apiClient.get("/accounting/trial-balance", { params: { tenant_id: tenantId } }),
      ]);
      setAccounts(a); setEntries(e); setBalance(b);
    } catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, [tenantId]);

  const seedPlan = async () => {
    if (!tenantId) { toast.error("Sélectionnez un client"); return; }
    try {
      const { data } = await apiClient.post(`/accounting/seed-plan?tenant_id=${tenantId}`);
      if (data.already_seeded) toast.info("Plan déjà présent");
      else toast.success(`Plan SYSCOHADA initialisé : ${data.seeded} comptes`);
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  const addLine = () => setEntryForm((f) => ({ ...f, lines: [...f.lines, { account_code: "", debit: "", credit: "", label: "" }] }));
  const removeLine = (idx) => setEntryForm((f) => ({ ...f, lines: f.lines.filter((_, i) => i !== idx) }));
  const updateLine = (idx, key, val) => setEntryForm((f) => ({ ...f, lines: f.lines.map((l, i) => i === idx ? { ...l, [key]: val } : l) }));

  const totals = useMemo(() => {
    const d = entryForm.lines.reduce((s, l) => s + (Number(l.debit) || 0), 0);
    const c = entryForm.lines.reduce((s, l) => s + (Number(l.credit) || 0), 0);
    return { debit: d, credit: c, ok: Math.abs(d - c) < 0.01 && d > 0 };
  }, [entryForm.lines]);

  const submitEntry = async () => {
    if (!entryForm.label || !tenantId) { toast.error("Client et libellé requis"); return; }
    if (!totals.ok) { toast.error(`Écriture déséquilibrée (D=${totals.debit} / C=${totals.credit})`); return; }
    try {
      const lines = entryForm.lines
        .filter((l) => l.account_code && (Number(l.debit) > 0 || Number(l.credit) > 0))
        .map((l) => ({
          account_code: l.account_code,
          debit: Number(l.debit) || 0,
          credit: Number(l.credit) || 0,
          label: l.label || null,
        }));
      await apiClient.post("/accounting/entries", {
        tenant_id: tenantId, journal: entryForm.journal,
        entry_date: entryForm.entry_date, label: entryForm.label,
        reference: entryForm.reference || null, lines,
      });
      toast.success("Écriture créée");
      setOpenEntry(false);
      setEntryForm({
        journal: "OD", entry_date: new Date().toISOString().slice(0, 10),
        label: "", reference: "",
        lines: [{ account_code: "", debit: "", credit: "", label: "" }, { account_code: "", debit: "", credit: "", label: "" }],
      });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  const validate = async (id) => {
    try { await apiClient.post(`/accounting/entries/${id}/validate`); toast.success("Écriture validée"); await load(); }
    catch (err) { toast.error(extractError(err)); }
  };

  const removeEntry = async (e) => {
    if (!window.confirm(`Supprimer ${e.number} ?`)) return;
    try { await apiClient.delete(`/accounting/entries/${e.id}`); await load(); }
    catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-accounting-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">SYSCOHADA</div>
        <h1 className="font-display text-3xl md:text-4xl">Comptabilité OHADA</h1>
        <p className="text-muted-foreground mt-1">Plan comptable, écritures double-partie, grand livre et balance de vérification.</p>
      </div>

      <div className="albarka-card p-4 flex flex-col md:flex-row gap-3 md:items-end">
        <div className="flex-1">
          <Label>Client</Label>
          <EntitySelect value={tenantId} onChange={setTenantId} testId="accounting-tenant-input" />
        </div>
        <Button variant="outline" onClick={seedPlan} disabled={!tenantId} data-testid="accounting-seed-btn">
          <Sparkles className="w-4 h-4 mr-2" />Initialiser plan SYSCOHADA
        </Button>
      </div>

      {tenantId && (
        <Tabs defaultValue="entries">
          <TabsList>
            <TabsTrigger value="entries" data-testid="tab-accounting-entries"><ScrollText className="w-4 h-4 mr-2" />Écritures</TabsTrigger>
            <TabsTrigger value="accounts" data-testid="tab-accounting-accounts"><BookOpen className="w-4 h-4 mr-2" />Plan comptable</TabsTrigger>
            <TabsTrigger value="balance" data-testid="tab-accounting-balance"><Scale className="w-4 h-4 mr-2" />Balance</TabsTrigger>
          </TabsList>

          <TabsContent value="entries" className="pt-4 space-y-3">
            <div className="flex justify-end">
              <Dialog open={openEntry} onOpenChange={setOpenEntry}>
                <DialogTrigger asChild>
                  <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-entry-btn"><Plus className="w-4 h-4 mr-2" />Nouvelle écriture</Button>
                </DialogTrigger>
                <DialogContent data-testid="entry-dialog" className="max-w-3xl">
                  <DialogHeader><DialogTitle>Nouvelle écriture comptable</DialogTitle></DialogHeader>
                  <div className="space-y-3">
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <Label>Journal</Label>
                        <select className="w-full h-10 rounded-md border border-input px-3 text-sm" value={entryForm.journal} onChange={(e) => setEntryForm({ ...entryForm, journal: e.target.value })} data-testid="entry-journal-select">
                          {JOURNALS.map((j) => <option key={j} value={j}>{j}</option>)}
                        </select>
                      </div>
                      <div><Label>Date</Label><Input type="date" value={entryForm.entry_date} onChange={(e) => setEntryForm({ ...entryForm, entry_date: e.target.value })} data-testid="entry-date-input" /></div>
                      <div><Label>Référence</Label><Input value={entryForm.reference} onChange={(e) => setEntryForm({ ...entryForm, reference: e.target.value })} data-testid="entry-ref-input" /></div>
                    </div>
                    <div><Label>Libellé</Label><Input value={entryForm.label} onChange={(e) => setEntryForm({ ...entryForm, label: e.target.value })} data-testid="entry-label-input" /></div>

                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <Label>Lignes</Label>
                        <Button size="sm" variant="outline" onClick={addLine} data-testid="entry-add-line-btn"><Plus className="w-3 h-3 mr-1" />Ajouter une ligne</Button>
                      </div>
                      <div className="space-y-1">
                        {entryForm.lines.map((l, i) => (
                          <div key={i} className="grid grid-cols-12 gap-2 items-center" data-testid={`entry-line-${i}`}>
                            <select className="col-span-3 h-9 rounded-md border border-input px-2 text-xs" value={l.account_code} onChange={(e) => updateLine(i, "account_code", e.target.value)} data-testid={`entry-line-${i}-account`}>
                              <option value="">-- Compte --</option>
                              {accounts.map((a) => (<option key={a.code} value={a.code}>{a.code} — {a.label}</option>))}
                            </select>
                            <Input className="col-span-4 h-9 text-xs" placeholder="Libellé" value={l.label} onChange={(e) => updateLine(i, "label", e.target.value)} data-testid={`entry-line-${i}-label`} />
                            <Input className="col-span-2 h-9 text-xs" placeholder="Débit" type="number" value={l.debit} onChange={(e) => updateLine(i, "debit", e.target.value)} data-testid={`entry-line-${i}-debit`} />
                            <Input className="col-span-2 h-9 text-xs" placeholder="Crédit" type="number" value={l.credit} onChange={(e) => updateLine(i, "credit", e.target.value)} data-testid={`entry-line-${i}-credit`} />
                            <Button variant="ghost" size="sm" onClick={() => removeLine(i)} className="col-span-1"><Trash2 className="w-3 h-3 text-red-600" /></Button>
                          </div>
                        ))}
                      </div>
                      <div className={`mt-2 text-sm font-mono ${totals.ok ? "text-emerald-700" : "text-red-600"}`} data-testid="entry-totals">
                        Total : D = {totals.debit.toLocaleString()} · C = {totals.credit.toLocaleString()} · {totals.ok ? "équilibrée" : "⚠︎ déséquilibrée"}
                      </div>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={() => setOpenEntry(false)}>Annuler</Button>
                    <Button onClick={submitEntry} disabled={!totals.ok} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="entry-submit-btn">Créer</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
            <div className="albarka-card overflow-hidden">
              <Table>
                <TableHeader><TableRow><TableHead>Numéro</TableHead><TableHead>Date</TableHead><TableHead>Journal</TableHead><TableHead>Libellé</TableHead><TableHead>Total D/C</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
                <TableBody>
                  {entries.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Aucune écriture.</TableCell></TableRow>}
                  {entries.map((e) => (
                    <TableRow key={e.id}>
                      <TableCell className="font-mono text-xs">{e.number}</TableCell>
                      <TableCell>{e.entry_date}</TableCell>
                      <TableCell>{e.journal}</TableCell>
                      <TableCell>{e.label}</TableCell>
                      <TableCell className="font-mono text-xs">{Number(e.total_debit).toLocaleString()}</TableCell>
                      <TableCell><span className={`albarka-chip ${e.status === "validated" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{e.status}</span></TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {e.status !== "validated" && (<Button variant="ghost" size="sm" onClick={() => validate(e.id)} data-testid={`validate-entry-${e.id}`} title="Valider"><CheckCircle2 className="w-4 h-4 text-emerald-700" /></Button>)}
                        {e.status !== "validated" && (<Button variant="ghost" size="sm" onClick={() => removeEntry(e)} data-testid={`delete-entry-${e.id}`}><Trash2 className="w-4 h-4 text-red-600" /></Button>)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="accounts" className="pt-4">
            <div className="albarka-card overflow-hidden">
              <Table>
                <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Libellé</TableHead><TableHead>Classe</TableHead><TableHead>Type</TableHead></TableRow></TableHeader>
                <TableBody>
                  {accounts.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Plan vide — cliquez sur "Initialiser plan SYSCOHADA".</TableCell></TableRow>}
                  {accounts.map((a) => (
                    <TableRow key={a.code}>
                      <TableCell className="font-mono">{a.code}</TableCell>
                      <TableCell>{a.label}</TableCell>
                      <TableCell><span className="albarka-chip bg-slate-100 text-slate-700">Classe {a.class}</span></TableCell>
                      <TableCell className="text-sm">{a.type}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="balance" className="pt-4">
            {balance && (
              <div className="albarka-card overflow-hidden">
                <div className="p-3 border-b border-border flex justify-between text-sm">
                  <div>Total Débits : <span className="font-mono">{Number(balance.total_debit).toLocaleString()}</span></div>
                  <div>Total Crédits : <span className="font-mono">{Number(balance.total_credit).toLocaleString()}</span></div>
                  <div>{balance.balanced ? <span className="text-emerald-700">✓ Balancée</span> : <span className="text-red-600">⚠︎ Déséquilibre</span>}</div>
                </div>
                <Table>
                  <TableHeader><TableRow><TableHead>Compte</TableHead><TableHead>Libellé</TableHead><TableHead className="text-right">Débit</TableHead><TableHead className="text-right">Crédit</TableHead><TableHead className="text-right">Solde D</TableHead><TableHead className="text-right">Solde C</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {balance.rows.filter((r) => r.debit > 0 || r.credit > 0).length === 0 && (
                      <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Aucun mouvement sur la période. Créez et validez une écriture pour voir la balance.</TableCell></TableRow>
                    )}
                    {balance.rows.filter((r) => r.debit > 0 || r.credit > 0).map((r) => (
                      <TableRow key={r.code}>
                        <TableCell className="font-mono">{r.code}</TableCell>
                        <TableCell>{r.label}</TableCell>
                        <TableCell className="text-right font-mono">{r.debit > 0 ? Number(r.debit).toLocaleString() : "—"}</TableCell>
                        <TableCell className="text-right font-mono">{r.credit > 0 ? Number(r.credit).toLocaleString() : "—"}</TableCell>
                        <TableCell className="text-right font-mono">{r.debit_balance > 0 ? Number(r.debit_balance).toLocaleString() : "—"}</TableCell>
                        <TableCell className="text-right font-mono">{r.credit_balance > 0 ? Number(r.credit_balance).toLocaleString() : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
