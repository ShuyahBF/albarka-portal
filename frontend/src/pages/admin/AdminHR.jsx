import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Users, FileText, Download } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import PayrollTable from "@/components/PayrollTable";
import { Table2, BookOpen, SlidersHorizontal, Receipt } from "lucide-react";
// Lot 8 : paie Burkina Faso paramétrable (cabinet + clients)
import PaieEmployees from "@/components/paie/PaieEmployees";
import { PaieBulletins, PaieLivre } from "@/components/paie/PaieBulletins";
import PaieSettings from "@/components/paie/PaieSettings";

export default function AdminHR() {
  const [employees, setEmployees] = useState([]);
  const [payslips, setPayslips] = useState([]);
  const [openPay, setOpenPay] = useState(false);
  const [payForm, setPayForm] = useState({ employee_id: "", period_month: "", gross_salary: "", deductions: 0, bonuses: 0, notes: "" });

  const load = async () => {
    try {
      const [{ data: e }, { data: p }] = await Promise.all([
        apiClient.get("/hr/employees"),
        apiClient.get("/hr/payslips"),
      ]);
      setEmployees(e); setPayslips(p);
    } catch (err) { toast.error(extractError(err)); }
  };
  useEffect(() => { load(); }, []);

  const submitPay = async () => {
    if (!payForm.employee_id || !payForm.period_month || !payForm.gross_salary) {
      toast.error("Employé, période et brut requis"); return;
    }
    try {
      await apiClient.post("/hr/payslips", {
        employee_id: payForm.employee_id, period_month: payForm.period_month,
        gross_salary: Number(payForm.gross_salary),
        deductions: Number(payForm.deductions || 0),
        bonuses: Number(payForm.bonuses || 0),
        notes: payForm.notes || null,
      });
      toast.success("Bulletin créé");
      setOpenPay(false);
      setPayForm({ employee_id: "", period_month: "", gross_salary: "", deductions: 0, bonuses: 0, notes: "" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-hr-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl">Paie & RH</h1>
        <p className="text-muted-foreground mt-1">Paie du personnel du cabinet et des clients : salariés, bulletins, livre de paie, tableau mensuel et paramètres (modèles de configuration).</p>
      </div>

      <Tabs defaultValue="employees">
        <TabsList className="flex-wrap h-auto">
          <TabsTrigger value="employees" data-testid="tab-hr-employees"><Users className="w-4 h-4 mr-2" />Salariés</TabsTrigger>
          <TabsTrigger value="bulletins" data-testid="tab-hr-bulletins"><Receipt className="w-4 h-4 mr-2" />Bulletins de paie</TabsTrigger>
          <TabsTrigger value="livre" data-testid="tab-hr-livre"><BookOpen className="w-4 h-4 mr-2" />Livre de paie</TabsTrigger>
          {/* Lot 7 : liste actualisée du personnel (fiche de renseignement) */}
          <TabsTrigger value="table" data-testid="tab-hr-table"><Table2 className="w-4 h-4 mr-2" />Tableau de paie</TabsTrigger>
          <TabsTrigger value="settings" data-testid="tab-hr-settings"><SlidersHorizontal className="w-4 h-4 mr-2" />Paramètres de paie</TabsTrigger>
          {payslips.length > 0 && <TabsTrigger value="payslips" data-testid="tab-hr-payslips"><FileText className="w-4 h-4 mr-2" />Anciens bulletins</TabsTrigger>}
        </TabsList>

        <TabsContent value="bulletins" className="pt-4"><PaieBulletins /></TabsContent>
        <TabsContent value="livre" className="pt-4"><PaieLivre /></TabsContent>
        <TabsContent value="settings" className="pt-4"><PaieSettings /></TabsContent>

        <TabsContent value="table" className="pt-4">
          <PayrollTable />
        </TabsContent>

        <TabsContent value="employees" className="pt-4"><PaieEmployees /></TabsContent>

        <TabsContent value="payslips" className="pt-4 space-y-3">
          <div className="flex justify-end">
            <Dialog open={openPay} onOpenChange={setOpenPay}>
              <DialogTrigger asChild>
                <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-payslip-btn"><Plus className="w-4 h-4 mr-2" />Nouveau bulletin</Button>
              </DialogTrigger>
              <DialogContent data-testid="payslip-dialog">
                <DialogHeader><DialogTitle>Nouveau bulletin</DialogTitle></DialogHeader>
                <div className="space-y-3">
                  <div>
                    <Label>Employé</Label>
                    <select className="w-full h-10 rounded-md border border-input px-3 text-sm" value={payForm.employee_id} onChange={(e) => setPayForm({ ...payForm, employee_id: e.target.value })} data-testid="payslip-employee-select">
                      <option value="">-- Sélectionner --</option>
                      {employees.map((e) => (<option key={e.id} value={e.id}>{e.full_name}</option>))}
                    </select>
                  </div>
                  <div><Label>Période (YYYY-MM)</Label><Input placeholder="2026-02" value={payForm.period_month} onChange={(e) => setPayForm({ ...payForm, period_month: e.target.value })} data-testid="payslip-period-input" /></div>
                  <div className="grid grid-cols-3 gap-3">
                    <div><Label>Brut</Label><Input type="number" value={payForm.gross_salary} onChange={(e) => setPayForm({ ...payForm, gross_salary: e.target.value })} data-testid="payslip-gross-input" /></div>
                    <div><Label>Retenues</Label><Input type="number" value={payForm.deductions} onChange={(e) => setPayForm({ ...payForm, deductions: e.target.value })} data-testid="payslip-deductions-input" /></div>
                    <div><Label>Primes</Label><Input type="number" value={payForm.bonuses} onChange={(e) => setPayForm({ ...payForm, bonuses: e.target.value })} data-testid="payslip-bonuses-input" /></div>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setOpenPay(false)}>Annuler</Button>
                  <Button onClick={submitPay} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="payslip-submit-btn">Créer</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="albarka-card overflow-hidden">
            <Table>
              <TableHeader><TableRow><TableHead>Employé</TableHead><TableHead>Période</TableHead><TableHead className="text-right">Brut</TableHead><TableHead className="text-right">Net</TableHead><TableHead className="text-right">PDF</TableHead></TableRow></TableHeader>
              <TableBody>
                {payslips.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Aucun bulletin.</TableCell></TableRow>}
                {payslips.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.employee_name}</TableCell>
                    <TableCell>{p.period_month}</TableCell>
                    <TableCell className="text-right">{Number(p.gross_salary).toLocaleString()}</TableCell>
                    <TableCell className="font-semibold text-right">{Number(p.net_salary).toLocaleString()}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={async () => {
                          try {
                            const res = await apiClient.get(`/hr/payslips/${p.id}.pdf`, { responseType: "blob" });
                            const url = URL.createObjectURL(res.data);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `bulletin_${p.period_month}_${p.employee_name}.pdf`;
                            document.body.appendChild(a); a.click(); a.remove();
                            URL.revokeObjectURL(url);
                          } catch (err) { toast.error(extractError(err)); }
                        }}
                        data-testid={`payslip-pdf-${p.id}`}
                      >
                        <Download className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
