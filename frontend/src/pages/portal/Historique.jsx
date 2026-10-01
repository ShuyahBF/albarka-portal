import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { History } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { moduleOpen } from "@/pages/portal/Dashboard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export default function Historique() {
  const [data, setData] = useState({ documents: [], missions: [], echeances: [] });
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();
  // Lot 10 : onglet d'un module fermé par le cabinet masqué (Pièces, Missions, Échéances)
  const tabs = [["documents", "Pièces"], ["missions", "Missions"], ["echeances", "Échéances"]]
    .filter(([m]) => moduleOpen(user, m));
  const show = (m) => tabs.some(([v]) => v === m);

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

      {tabs.length === 0 && (
        <div className="albarka-card p-6 text-sm text-muted-foreground" data-testid="history-empty">
          Aucune activité à afficher pour votre compte.
        </div>
      )}
      {tabs.length > 0 && (
      <Tabs defaultValue={tabs[0][0]} className="albarka-card p-2">
        <TabsList data-testid="history-tabs">
          {tabs.map(([value, label]) => (
            <TabsTrigger key={value} value={value} data-testid={`tab-${value}`}>{label}</TabsTrigger>
          ))}
        </TabsList>
        {show("documents") && (
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
        )}
        {show("missions") && (
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
        )}
        {show("echeances") && (
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
        )}
      </Tabs>
      )}
    </div>
  );
}
