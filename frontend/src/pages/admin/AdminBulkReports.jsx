import React, { useState } from "react";
import { toast } from "sonner";
import { Zap, ClipboardList, CalendarRange } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import EntitySelect from "@/components/EntitySelect";

const KINDS = [
  { value: "mensuel", label: "Rapport mensuel" },
  { value: "trimestriel", label: "Rapport trimestriel" },
  { value: "annuel", label: "Rapport annuel" },
  { value: "audit", label: "Rapport d'audit" },
];

const currentMonth = () => new Date().toISOString().slice(0, 7);
const currentQuarter = () => {
  const d = new Date();
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `${d.getFullYear()}-Q${q}`;
};

export default function AdminBulkReports() {
  // Feature 2 : bulk-generate
  const [kind, setKind] = useState("mensuel");
  const [month, setMonth] = useState(currentMonth());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  // Feature 4 : quarterly
  const [qTenantId, setQTenantId] = useState("");
  const [qPeriod, setQPeriod] = useState(currentQuarter());
  const [qRunning, setQRunning] = useState(false);
  const [qResult, setQResult] = useState(null);

  const runBulk = async () => {
    setRunning(true);
    setResult(null);
    try {
      const { data } = await apiClient.post("/reports/bulk-generate", {
        kind, period_month: month,
      });
      setResult(data);
      toast.success(`${data.generated_count} rapports générés (${data.failed_count} échecs)`);
    } catch (err) { toast.error(extractError(err)); }
    finally { setRunning(false); }
  };

  const runQuarterly = async () => {
    if (!qTenantId) { toast.error("Sélectionnez un client"); return; }
    setQRunning(true);
    setQResult(null);
    try {
      const { data } = await apiClient.post(
        `/reports/client/${qTenantId}/generate-quarterly`,
        { period_quarter: qPeriod },
      );
      setQResult(data);
      toast.success(`Rapport trimestriel généré : ${data.number}`);
    } catch (err) { toast.error(extractError(err)); }
    finally { setQRunning(false); }
  };

  return (
    <div className="space-y-6" data-testid="admin-bulk-reports-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Rapports</div>
        <h1 className="font-display text-3xl md:text-4xl">Production en masse</h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">Génération bulk pour tous les clients et export trimestriel personnalisé.</p>
      </div>

      {/* Feature 2 : Bulk mensuel */}
      <div className="albarka-card p-6 space-y-4" data-testid="bulk-generate-card">
        <div className="flex items-center gap-2 text-lg font-display"><Zap className="w-5 h-5 text-[#E5A24B]" />Génération bulk mensuelle</div>
        <p className="text-sm text-muted-foreground">Génère un rapport pour <strong>tous les clients actifs</strong> en une seule opération.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <Label>Type</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger data-testid="bulk-kind-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {KINDS.filter((k) => k.value !== "trimestriel").map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div><Label>Période (YYYY-MM)</Label><Input value={month} onChange={(e) => setMonth(e.target.value)} data-testid="bulk-period-input" /></div>
          <Button onClick={runBulk} disabled={running} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white h-10" data-testid="bulk-run-btn">
            <ClipboardList className="w-4 h-4 mr-2" />
            {running ? "Génération…" : "Lancer la génération"}
          </Button>
        </div>
        {result && (
          <div className="space-y-2 pt-2" data-testid="bulk-result">
            <div className="flex gap-4 text-sm">
              <span className="albarka-chip bg-emerald-100 text-emerald-800">Réussis : {result.generated_count}</span>
              <span className="albarka-chip bg-red-100 text-red-700">Échecs : {result.failed_count}</span>
            </div>
            {result.generated?.length > 0 && (
              <Table>
                <TableHeader><TableRow><TableHead>Client</TableHead><TableHead>Numéro</TableHead></TableRow></TableHeader>
                <TableBody>
                  {result.generated.map((g) => (<TableRow key={g.report_id}><TableCell>{g.name}</TableCell><TableCell className="font-mono text-xs">{g.number}</TableCell></TableRow>))}
                </TableBody>
              </Table>
            )}
            {result.failed?.length > 0 && (
              <div className="text-xs text-red-700 space-y-1">
                {result.failed.map((f, i) => (<div key={i}>❌ {f.name} : {f.error}</div>))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Feature 4 : Trimestriel */}
      <div className="albarka-card p-6 space-y-4" data-testid="quarterly-card">
        <div className="flex items-center gap-2 text-lg font-display"><CalendarRange className="w-5 h-5 text-[#0F6B4A]" />Export trimestriel</div>
        <p className="text-sm text-muted-foreground">Agrège les 3 mois du trimestre dans un rapport unique pour un client.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div><Label>Client</Label><EntitySelect value={qTenantId} onChange={setQTenantId} testId="quarterly-tenant-input" /></div>
          <div><Label>Trimestre (YYYY-Qn)</Label><Input value={qPeriod} onChange={(e) => setQPeriod(e.target.value)} data-testid="quarterly-period-input" /></div>
          <Button onClick={runQuarterly} disabled={qRunning || !qTenantId} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white h-10" data-testid="quarterly-run-btn">
            <CalendarRange className="w-4 h-4 mr-2" />
            {qRunning ? "Génération…" : "Générer le trimestriel"}
          </Button>
        </div>
        {qResult && (
          <div className="text-sm border border-emerald-200 bg-emerald-50 rounded p-3" data-testid="quarterly-result">
            <div className="font-semibold text-emerald-800">✓ Rapport {qResult.number} généré</div>
            <div className="text-xs text-muted-foreground mt-1">{qResult.kind_label} · {qResult.month_key} · {(qResult.size / 1024).toFixed(1)} Ko</div>
          </div>
        )}
      </div>
    </div>
  );
}
