// Vue cabinet (staff) du pilote : toutes les pièces déposées par tous les
// clients, avec leur synthèse IA. Pas de filtrage par rôle pour le pilote —
// tout compte non-client voit tout, à affiner en phase suivante.
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/sonner";
import { apiClient } from "@/pilot/api";
import { useAuth } from "@/pilot/AuthContext";
import DocumentSynthesis, { StatusBadge } from "@/pilot/DocumentSynthesis";

export default function StaffOverview() {
  const { user, logout } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);

  const fetchDocuments = useCallback(async () => {
    const { data } = await apiClient.get("/documents");
    setDocuments(data);
  }, []);

  useEffect(() => {
    fetchDocuments();
    const interval = setInterval(fetchDocuments, 5000);
    return () => clearInterval(interval);
  }, [fetchDocuments]);

  const openDocument = async (doc) => {
    try {
      const { data } = await apiClient.get(`/documents/${doc.id}`);
      setSelectedDoc(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible de charger cette pièce");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">Portail ALBARKA — Cabinet</h1>
          <p className="text-sm text-muted-foreground">{user?.full_name}</p>
        </div>
        <Button variant="ghost" onClick={logout}>Déconnexion</Button>
      </header>

      <main className="max-w-5xl mx-auto p-6">
        <Card>
          <CardHeader>
            <CardTitle>Pièces reçues des clients</CardTitle>
            <CardDescription>Toutes les pièces déposées, tous clients confondus.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Client (tenant)</TableHead>
                  <TableHead>Fichier</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Statut</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="font-mono text-xs">{doc.tenant_id}</TableCell>
                    <TableCell>{doc.original_filename}</TableCell>
                    <TableCell>{doc.kind}</TableCell>
                    <TableCell><StatusBadge status={doc.status} /></TableCell>
                    <TableCell>
                      <Button variant="link" size="sm" onClick={() => openDocument(doc)}>
                        Voir la synthèse
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {documents.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      Aucune pièce reçue pour l'instant.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </main>

      <Dialog open={!!selectedDoc} onOpenChange={(open) => !open && setSelectedDoc(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{selectedDoc?.original_filename}</DialogTitle>
          </DialogHeader>
          {selectedDoc && <DocumentSynthesis document={selectedDoc} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
