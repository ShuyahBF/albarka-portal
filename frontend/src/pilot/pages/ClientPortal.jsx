// Espace client du pilote : dépôt de pièces + suivi de leur analyse IA.
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
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

const KIND_OPTIONS = [
  { value: "piece_comptable", label: "Pièce comptable" },
  { value: "declaration", label: "Déclaration" },
  { value: "kyc", label: "Pièce KYC" },
  { value: "autre", label: "Autre" },
];

export default function ClientPortal() {
  const { user, logout } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [file, setFile] = useState(null);
  const [kind, setKind] = useState("piece_comptable");
  const [uploading, setUploading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const pollRef = useRef(null);

  const fetchDocuments = useCallback(async () => {
    const { data } = await apiClient.get("/documents");
    setDocuments(data);
    return data;
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Tant qu'au moins une pièce est "en_analyse", on rafraîchit la liste
  // toutes les 4s pour voir apparaître la synthèse sans action manuelle.
  useEffect(() => {
    const hasPending = documents.some((d) => d.status === "en_analyse");
    clearInterval(pollRef.current);
    if (hasPending) {
      pollRef.current = setInterval(fetchDocuments, 4000);
    }
    return () => clearInterval(pollRef.current);
  }, [documents, fetchDocuments]);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("kind", kind);
      await apiClient.post("/documents", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Pièce téléversée, analyse en cours...");
      setFile(null);
      await fetchDocuments();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du téléversement");
    } finally {
      setUploading(false);
    }
  };

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
          <h1 className="text-lg font-bold">Portail ALBARKA</h1>
          <p className="text-sm text-muted-foreground">
            {user?.company || user?.full_name}
          </p>
        </div>
        <Button variant="ghost" onClick={logout}>Déconnexion</Button>
      </header>

      <main className="max-w-3xl mx-auto p-6 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Déposer une pièce</CardTitle>
            <CardDescription>
              PDF, image ou document bureautique (max 20 Mo). Analysée automatiquement.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleUpload} className="flex flex-col sm:flex-row gap-3">
              <Input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="flex-1"
                required
              />
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger className="sm:w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KIND_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button type="submit" disabled={!file || uploading}>
                {uploading ? "Envoi..." : "Téléverser"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Mes pièces</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fichier</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Statut</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>{doc.original_filename}</TableCell>
                    <TableCell>{doc.kind}</TableCell>
                    <TableCell><StatusBadge status={doc.status} /></TableCell>
                    <TableCell>
                      <Button variant="link" size="sm" onClick={() => openDocument(doc)}>
                        Voir
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {documents.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      Aucune pièce déposée pour l'instant.
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
