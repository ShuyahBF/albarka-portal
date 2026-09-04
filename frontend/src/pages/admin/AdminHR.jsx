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
import EntitySelect from "@/components/EntitySelect";

export default function AdminHR() {
  const [employees, setEmployees] = useState([]);
  const [payslips, setPayslips] = useState([]);
  const [openEmp, setOpenEmp] = useState(false);
  const [openPay, setOpenPay] = useState(false);
  const [empForm, setEmpForm] = useState({ tenant_id: "", full_name: "", role: "", base_salary: "", email: "", phone: "" });
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

  const submitEmp = async () => {
    if (!empForm.tenant_id || !empForm.full_name || !empForm.base_salary) {
      toast.error("Client, nom et salaire de base requis"); return;
    }
    try {
      await apiClient.post("/hr/employees", {
        tenant_id: empForm.tenant_id, full_name: empForm.full_name,
        role: empForm.role || null, base_salary: Number(empForm.base_salary),
        email: empForm.email || null, phone: empForm.phone || null,
      });
      toast.success("Employé ajouté");
      setOpenEmp(false);
      setEmpForm({ tenant_id: "", full_name: "", role: "", base_salary: "", email: "", phone: "" });
      await load();
    } catch (err) { toast.error(extractError(err)); }
  };

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
        <p className="text-muted-foreground mt-1">Employés des clients et bulletins de paie.</p>
      </div>

      <Tabs defaultValue="employees">
        <TabsList>
          <TabsTrigger value="employees" data-testid="tab-hr-employees"><Users className="w-4 h-4 mr-2" />Employés</TabsTrigger>
          <TabsTrigger value="payslips" data-testid="tab-hr-payslips"><FileText className="w-4 h-4 mr-2" />Bulletins</TabsTrigger>
        </TabsList>

        <TabsContent value="employees" className="pt-4 space-y-3">
          <div className="flex justify-end">
            <Dialog open={openEmp} onOpenChange={setOpenEmp}>
              <DialogTrigger asChild>
                <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-employee-btn"><Plus className="w-4 h-4 mr-2" />Nouvel employé</Button>
              </DialogTrigger>
              <DialogContent data-testid="employee-dialog">
                <DialogHeader><DialogTitle>Nouvel employé</DialogTitle></DialogHeader>
                <div className="space-y-3">
                  <div><Label>Client</Label><EntitySelect value={empForm.tenant_id} onChange={(v) => setEmpForm({ ...empForm, tenant_id: v })} testId="employee-tenant-input" /></div>
                  <div><Label>Nom complet</Label><Input value={empForm.full_name} onChange={(e) => setEmpForm({ ...empForm, full_name: e.target.value })} data-testid="employee-name-input" /></div>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label>Fonction</Label><Input value={empForm.role} onChange={(e) => setEmpForm({ ...empForm, role: e.target.value })} data-testid="employee-role-input" /></div>
                    <div><Label>Salaire de base</Label><Input type="number" value={empForm.base_salary} onChange={(e) => setEmpForm({ ...empForm, base_salary: e.target.value })} data-testid="employee-salary-input" /></div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label>Email</Label><Input type="email" value={empForm.email} onChange={(e) => setEmpForm({ ...empForm, email: e.target.value })} data-testid="employee-email-input" /></div>
                    <div><Label>Téléphone</Label><Input value={empForm.phone} onChange={(e) => setEmpForm({ ...empForm, phone: e.target.value })} data-testid="employee-phone-input" /></div>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setOpenEmp(false)}>Annuler</Button>
                  <Button onClick={submitEmp} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="employee-submit-btn">Ajouter</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="albarka-card overflow-hidden">
            <Table>
              <TableHeader><TableRow><TableHead>Nom</TableHead><TableHead>Fonction</TableHead><TableHead>Salaire base</TableHead><TableHead>Contact</TableHead></TableRow></TableHeader>
              <TableBody>
                {employees.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Aucun employé.</TableCell></TableRow>}
                {employees.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-medium">{e.full_name}</TableCell>
                    <TableCell>{e.role || "—"}</TableCell>
                    <TableCell>{Number(e.base_salary).toLocaleString()}</TableCell>
                    <TableCell className="text-sm">{e.email || e.phone || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

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
              <TableHeader><TableRow><TableHead>Employé</TableHead><TableHead>Période</TableHead><TableHead>Brut</TableHead><TableHead>Net</TableHead><TableHead className="text-right">PDF</TableHead></TableRow></TableHeader>
              <TableBody>
                {payslips.length === 0 && <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Aucun bulletin.</TableCell></TableRow>}
                {payslips.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.employee_name}</TableCell>
                    <TableCell>{p.period_month}</TableCell>
                    <TableCell>{Number(p.gross_salary).toLocaleString()}</TableCell>
                    <TableCell className="font-semibold">{Number(p.net_salary).toLocaleString()}</TableCell>
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
