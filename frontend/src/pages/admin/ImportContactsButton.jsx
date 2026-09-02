import React, { useState } from "react";
import { toast } from "sonner";
import { Upload, Download, FileText } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";

export default function ImportContactsButton({ scope, tenantId, onDone }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);

  const downloadTemplate = async () => {
    try {
      const token = localStorage.getItem("albarka_token");
      const res = await fetch(`${API}/contacts/import/template`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Échec téléchargement");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "contacts_template.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const submit = async () => {
    if (!file) { toast.error("Sélectionnez un fichier CSV / XLSX"); return; }
    setBusy(true);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("scope", scope);
      if (scope === "client" && tenantId) fd.append("tenant_id", tenantId);
      const { data } = await apiClient.post("/contacts/import", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setReport(data);
      toast.success(`${data.imported} importés · ${data.updated} mis à jour · ${data.skipped} ignorés`);
      if (onDone) onDone();
    } catch (err) {
      toast.error(extractError(err));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) { setFile(null); setReport(null); } }}>
      <DialogTrigger asChild>
        <Button variant="outline" data-testid={`import-contacts-${scope}-btn`}>
          <Upload className="w-4 h-4 mr-2" /> Importer CSV
        </Button>
      </DialogTrigger>
      <DialogContent data-testid="import-contacts-dialog">
        <DialogHeader>
          <DialogTitle>Importer des contacts</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="text-sm text-muted-foreground">
            Chargez un fichier <span className="font-mono">.csv</span> ou <span className="font-mono">.xlsx</span> (5 Mo max).
            Les contacts sont dédoublonnés sur email (à défaut, téléphone).
          </div>
          <Button variant="outline" size="sm" onClick={downloadTemplate} data-testid="download-template-btn">
            <Download className="w-4 h-4 mr-2" />Télécharger le modèle CSV
          </Button>
          <div>
            <input
              type="file"
              accept=".csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-muted-foreground file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-[#0F6B4A]/10 file:text-[#0F6B4A] hover:file:bg-[#0F6B4A]/20"
              data-testid="import-file-input"
            />
            {file && (
              <div className="mt-2 text-xs flex items-center gap-2 text-muted-foreground">
                <FileText className="w-3 h-3" />{file.name} · {(file.size / 1024).toFixed(1)} Ko
              </div>
            )}
          </div>
          {report && (
            <div className="border rounded-md p-3 bg-slate-50 text-sm space-y-1" data-testid="import-report">
              <div><b>Résumé :</b> {report.imported} importés · {report.updated} mis à jour · {report.skipped} ignorés</div>
              {report.errors && report.errors.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-red-600 text-xs">{report.errors.length} avertissement(s)</summary>
                  <ul className="mt-1 text-xs ml-4 list-disc">
                    {report.errors.slice(0, 20).map((e, i) => (
                      <li key={i}>Ligne {e.row} — {e.reason}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Fermer</Button>
          <Button onClick={submit} disabled={!file || busy} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="import-submit-btn">
            <Upload className="w-4 h-4 mr-2" />{busy ? "Import en cours…" : "Importer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
