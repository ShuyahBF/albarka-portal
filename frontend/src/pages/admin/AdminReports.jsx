import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { FileDown, Send, Search } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export default function AdminReports() {
  const [clients, setClients] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/clients");
        setClients(data);
      } catch (err) {
        toast.error(extractError(err));
      } finally { setLoading(false); }
    })();
  }, []);

  const filtered = clients.filter((c) => {
    if (!q) return true;
    const s = q.toLowerCase();
    return (
      (c.full_name || "").toLowerCase().includes(s) ||
      (c.company || "").toLowerCase().includes(s) ||
      (c.email || "").toLowerCase().includes(s)
    );
  });

  const downloadReport = async (client) => {
    try {
      const token = localStorage.getItem("albarka_token");
      const res = await fetch(`${API}/reports/client/${client.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Échec génération PDF");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rapport-albarka-${(client.full_name || "client").replace(/\s+/g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapport téléchargé");
    } catch (err) {
      toast.error(err.message || "Erreur");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-reports-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Rapports client</h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Génération PDF d'une synthèse à jour du dossier client : missions, échéances,
          pièces déposées et analyses IA. Le rapport peut être envoyé au client par email
          depuis la fiche client.
        </p>
      </div>

      <div className="albarka-card p-4">
        <div className="relative max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
          <Input
            placeholder="Rechercher un client…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-9"
            data-testid="reports-search-input"
          />
        </div>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Client</TableHead>
              <TableHead>Entreprise</TableHead>
              <TableHead>Email</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && filtered.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">Aucun client.</TableCell></TableRow>}
            {filtered.map((c) => (
              <TableRow key={c.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">{c.full_name}</TableCell>
                <TableCell className="text-sm">{c.company || "—"}</TableCell>
                <TableCell className="text-sm">{c.email}</TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    onClick={() => downloadReport(c)}
                    className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
                    data-testid={`download-report-${c.id}`}
                  >
                    <FileDown className="w-4 h-4 mr-2" />
                    PDF
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
