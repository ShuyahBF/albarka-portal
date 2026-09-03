import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Clock, XCircle, CheckCircle2, AlertCircle } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const STATUS_META = {
  pending: { label: "En attente", chip: "bg-amber-100 text-amber-800", Icon: Clock },
  sent: { label: "Envoyé", chip: "bg-emerald-100 text-emerald-800", Icon: CheckCircle2 },
  failed: { label: "Échoué", chip: "bg-red-100 text-red-700", Icon: AlertCircle },
  cancelled: { label: "Annulé", chip: "bg-slate-100 text-slate-600", Icon: XCircle },
};

export default function ScheduledWaPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (status !== "all") params.status = status;
      const { data } = await apiClient.get("/reports/whatsapp/scheduled", { params });
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [status]);

  const cancel = async (id) => {
    if (!window.confirm("Annuler cette programmation ?")) return;
    try {
      await apiClient.delete(`/reports/whatsapp/scheduled/${id}`);
      toast.success("Programmation annulée");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-3" data-testid="scheduled-wa-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Clock className="w-4 h-4 text-[#0F6B4A]" />
            Envois WhatsApp programmés
          </div>
          <div className="text-xs text-muted-foreground">
            Le worker cron dispatche toutes les 5 minutes. Annulation possible tant que le statut est « En attente ».
          </div>
        </div>
        <div>
          <Label className="text-xs">Statut</Label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-40 h-9" data-testid="scheduled-wa-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous</SelectItem>
              <SelectItem value="pending">En attente</SelectItem>
              <SelectItem value="sent">Envoyés</SelectItem>
              <SelectItem value="failed">Échoués</SelectItem>
              <SelectItem value="cancelled">Annulés</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Planifié pour</TableHead>
              <TableHead>N° Rapport</TableHead>
              <TableHead>Destinataires</TableHead>
              <TableHead>Créé par</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-6 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                  Aucun envoi programmé.
                </TableCell>
              </TableRow>
            )}
            {items.map((r) => {
              const meta = STATUS_META[r.status] || STATUS_META.pending;
              const p = r.payload || {};
              const dest = p.all_whatsapp_contacts
                ? "Tous les contacts WA"
                : (p.to_groups?.length ? `${p.to_groups.length} groupe(s)` : (p.to || "—"));
              return (
                <TableRow key={r.id} className="hover:bg-[#0F6B4A]/5">
                  <TableCell className="text-xs font-mono">{new Date(r.scheduled_at).toLocaleString("fr-FR")}</TableCell>
                  <TableCell className="font-mono text-xs">{r.report_number}</TableCell>
                  <TableCell className="text-sm">{dest}</TableCell>
                  <TableCell className="text-sm">{r.created_by_name || r.created_by}</TableCell>
                  <TableCell><span className={`albarka-chip ${meta.chip} inline-flex items-center gap-1`}><meta.Icon className="w-3 h-3" />{meta.label}</span></TableCell>
                  <TableCell className="text-right">
                    {r.status === "pending" && (
                      <Button variant="ghost" size="sm" onClick={() => cancel(r.id)} data-testid={`cancel-scheduled-${r.id}`} title="Annuler">
                        <XCircle className="w-4 h-4 text-red-600" />
                      </Button>
                    )}
                    {r.status === "failed" && r.error && (
                      <span className="text-[10px] text-red-600" title={r.error}>{r.error.slice(0, 40)}…</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
