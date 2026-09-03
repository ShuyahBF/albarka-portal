import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { PenTool, ShieldCheck, Search } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export default function SignatureLogPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [certFilter, setCertFilter] = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/reports/signatures/log");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const certOptions = Array.from(new Set(items.map((i) => i.certificate_id).filter(Boolean)));

  const filtered = items.filter((r) => {
    if (certFilter !== "all" && r.certificate_id !== certFilter) return false;
    if (!q) return true;
    const s = q.toLowerCase();
    return (
      (r.report_number || "").toLowerCase().includes(s) ||
      (r.signed_by_name || "").toLowerCase().includes(s) ||
      (r.signature_name || "").toLowerCase().includes(s)
    );
  });

  return (
    <div className="space-y-4" data-testid="signature-log-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#0F6B4A]" />
            Journal des signatures
          </div>
          <div className="text-sm text-muted-foreground">
            Trace immuable de chaque rapport signé — utile pour l'audit interne et la preuve client.
          </div>
        </div>
        <div className="flex gap-2 items-end">
          <div>
            <Label className="text-xs">Rechercher</Label>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="N° rapport, agent…" className="pl-9 w-56 h-9" data-testid="signlog-search" />
            </div>
          </div>
          {certOptions.length > 0 && (
            <div>
              <Label className="text-xs">Certificat</Label>
              <Select value={certFilter} onValueChange={setCertFilter}>
                <SelectTrigger className="w-56 h-9" data-testid="signlog-cert-filter"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tous les certificats</SelectItem>
                  {certOptions.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Signé le</TableHead>
              <TableHead>N° Rapport</TableHead>
              <TableHead>Signataire</TableHead>
              <TableHead>Par</TableHead>
              <TableHead>Certificat</TableHead>
              <TableHead>N° série</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-10 text-muted-foreground">
                  <PenTool className="w-8 h-8 mx-auto mb-2 text-slate-400" />
                  Aucune signature enregistrée pour le moment.
                </TableCell>
              </TableRow>
            )}
            {filtered.map((r) => (
              <TableRow key={r.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="text-xs font-mono">{r.signed_at?.slice(0, 19).replace("T", " ")}</TableCell>
                <TableCell className="font-mono text-xs">{r.report_number}</TableCell>
                <TableCell className="text-sm">{r.signature_name}</TableCell>
                <TableCell className="text-sm">{r.signed_by_name || r.signed_by}</TableCell>
                <TableCell className="text-xs">{r.certificate_id || <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="font-mono text-[10px] text-muted-foreground">
                  {r.certificate_serial ? r.certificate_serial.slice(0, 24) + "…" : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
