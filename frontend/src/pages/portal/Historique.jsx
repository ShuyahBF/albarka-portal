import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { History } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export default function Historique() {
  const [data, setData] = useState({ documents: [], missions: [], echeances: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/dashboard/activity", { params: { limit: 100 } });
        setData(data);
      } catch (err) {
        toast.error(extractError(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-6" data-testid="history-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2 flex items-center gap-2">
          <History className="w-3 h-3" /> Historique
        </div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Toutes vos activités</h1>
      </div>

      <Tabs defaultValue="documents" className="albarka-card p-2">
        <TabsList data-testid="history-tabs">
          <TabsTrigger value="documents" data-testid="tab-documents">Pièces</TabsTrigger>
          <TabsTrigger value="missions" data-testid="tab-missions">Missions</TabsTrigger>
          <TabsTrigger value="echeances" data-testid="tab-echeances">Échéances</TabsTrigger>
        </TabsList>
        <TabsContent value="documents" className="p-2">
          <Table>
            <TableHeader><TableRow><TableHead>Fichier</TableHead><TableHead>Type</TableHead><TableHead>Statut</TableHead><TableHead>Date</TableHead></TableRow></TableHeader>
            <TableBody>
              {loading && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Chargement…</TableCell></TableRow>}
              {!loading && data.documents.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Aucun</TableCell></TableRow>}
              {data.documents.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">{d.original_filename}</TableCell>
                  <TableCell className="text-sm">{d.kind?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm">{d.status?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm">{d.created_at?.slice(0, 10)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
        <TabsContent value="missions" className="p-2">
          <Table>
            <TableHeader><TableRow><TableHead>Titre</TableHead><TableHead>Type</TableHead><TableHead>Statut</TableHead><TableHead>Échéance</TableHead></TableRow></TableHeader>
            <TableBody>
              {loading && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Chargement…</TableCell></TableRow>}
              {!loading && data.missions.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Aucune</TableCell></TableRow>}
              {data.missions.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-medium">{m.title}</TableCell>
                  <TableCell className="text-sm">{m.type?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm">{m.status?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm">{m.due_date || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
        <TabsContent value="echeances" className="p-2">
          <Table>
            <TableHeader><TableRow><TableHead>Échéance</TableHead><TableHead>Type</TableHead><TableHead>Statut</TableHead><TableHead>Date</TableHead></TableRow></TableHeader>
            <TableBody>
              {loading && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Chargement…</TableCell></TableRow>}
              {!loading && data.echeances.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">Aucune</TableCell></TableRow>}
              {data.echeances.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-medium">{e.title}</TableCell>
                  <TableCell className="text-sm">{e.type}</TableCell>
                  <TableCell className="text-sm">{e.status?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm">{e.due_date}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>
    </div>
  );
}
