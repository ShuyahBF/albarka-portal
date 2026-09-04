import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { MessageCircle, Search, CheckCircle2, XCircle, RefreshCw, FileText } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export default function WhatsAppLogPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (status === "ok") params.success = true;
      if (status === "ko") params.success = false;
      const { data } = await apiClient.get("/reports/whatsapp/log", { params });
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [status]);

  const filtered = items.filter((r) => {
    if (!q) return true;
    const s = q.toLowerCase();
    return (
      (r.report_number || "").toLowerCase().includes(s) ||
      (r.phone || "").toLowerCase().includes(s) ||
      (r.sent_by_name || "").toLowerCase().includes(s)
    );
  });

  return (
    <div className="space-y-4" data-testid="wa-log-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <MessageCircle className="w-4 h-4 text-emerald-600" />
            Journal des envois WhatsApp
          </div>
          <div className="text-sm text-muted-foreground">
            Trace détaillée par destinataire : stratégie (PDF direct / lien signé) et statut de livraison.
          </div>
        </div>
        <div className="flex gap-2 items-end">
          <Button
            variant="outline"
            className="h-9"
            onClick={async () => {
              try {
                const res = await apiClient.get("/reports/journal/export-pdf", { responseType: "blob" });
                const url = URL.createObjectURL(res.data);
                const a = document.createElement("a");
                a.href = url;
                a.download = `journal_signatures_wa_${new Date().toISOString().slice(0, 10)}.pdf`;
                document.body.appendChild(a); a.click(); a.remove();
                URL.revokeObjectURL(url);
              } catch (err) { toast.error(extractError(err)); }
            }}
            data-testid="journal-export-pdf-btn"
          >
            <FileText className="w-4 h-4 mr-2" />Exporter journal PDF
          </Button>
          <div>
            <Label className="text-xs">Rechercher</Label>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="N° rapport, téléphone, agent…" className="pl-9 w-64 h-9" data-testid="wa-log-search" />
            </div>
          </div>
          <div>
            <Label className="text-xs">Statut</Label>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="w-40 h-9" data-testid="wa-log-status-filter"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                <SelectItem value="ok">Délivrés</SelectItem>
                <SelectItem value="ko">Échoués</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Envoyé le</TableHead>
              <TableHead>N° Rapport</TableHead>
              <TableHead>Destinataire</TableHead>
              <TableHead>Stratégie</TableHead>
              <TableHead>Par</TableHead>
              <TableHead className="text-center">Statut</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-muted-foreground">
                  <MessageCircle className="w-8 h-8 mx-auto mb-2 text-slate-400" />
                  Aucun envoi WhatsApp enregistré.
                </TableCell>
              </TableRow>
            )}
            {filtered.map((r) => (
              <TableRow key={r.id} className="hover:bg-emerald-50/50">
                <TableCell className="text-xs font-mono">{r.sent_at?.slice(0, 19).replace("T", " ")}</TableCell>
                <TableCell className="font-mono text-xs">{r.report_number}</TableCell>
                <TableCell className="text-sm font-mono">{r.phone}</TableCell>
                <TableCell>
                  {r.strategy === "document" && <span className="albarka-chip bg-emerald-100 text-emerald-800">PDF direct</span>}
                  {r.strategy === "link" && <span className="albarka-chip bg-amber-100 text-amber-800">Lien signé</span>}
                  {!r.strategy && <span className="albarka-chip bg-slate-100 text-slate-500">—</span>}
                </TableCell>
                <TableCell className="text-sm">{r.sent_by_name || r.sent_by}</TableCell>
                <TableCell className="text-center">
                  {r.success
                    ? <CheckCircle2 className="w-4 h-4 text-emerald-600 mx-auto" />
                    : <XCircle className="w-4 h-4 text-red-600 mx-auto" />}
                </TableCell>
                <TableCell className="text-right">
                  {!r.success && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        try {
                          const { data } = await apiClient.post(`/reports/whatsapp/retry/${r.id}`);
                          if (data.ok) toast.success("Envoi WhatsApp relancé avec succès");
                          else toast.error("Nouvelle tentative échouée");
                          await load();
                        } catch (err) { toast.error(extractError(err)); }
                      }}
                      title="Relancer l'envoi"
                      data-testid={`wa-retry-${r.id}`}
                    >
                      <RefreshCw className="w-4 h-4 text-[#0F6B4A]" />
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
