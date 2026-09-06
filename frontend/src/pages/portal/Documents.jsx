import React, { useEffect, useRef, useState } from "react";
import { Upload, FileText, Download, Trash2, Sparkles, ChevronDown, ChevronUp, Mail, MessageCircle } from "lucide-react";
import { toast } from "sonner";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";
import EntitySelect from "@/components/EntitySelect";

const KINDS = [
  { value: "piece_comptable", label: "Pièce comptable" },
  { value: "declaration", label: "Déclaration" },
  { value: "kyc", label: "KYC / Identité" },
  { value: "paie", label: "Paie" },
  { value: "contrat", label: "Contrat" },
  { value: "autre", label: "Autre" },
];

const STATUS_LABEL = {
  recu: "Reçu",
  en_analyse: "Analyse en cours",
  analyse: "Analysé",
  erreur_analyse: "Erreur d'analyse",
};

const STATUS_TONE = {
  recu: "bg-slate-100 text-slate-700",
  en_analyse: "bg-blue-100 text-blue-700",
  analyse: "bg-emerald-100 text-emerald-800",
  erreur_analyse: "bg-red-100 text-red-700",
};

// Doivent rester identiques aux listes équivalentes côté backend
// (albarka_models.py DOCS_PRIVILEGED_ROLES/DOCS_DELETE_ROLES, albarka_documents.py DOWNLOAD_ROLES).
const DOCS_PRIVILEGED_ROLES = ["administrateur", "superviseur", "dg", "direction", "secretariat"];
const DOCS_DELETE_ROLES = ["administrateur", "superviseur", "dg", "direction"];
const DOWNLOAD_ROLES = [...DOCS_PRIVILEGED_ROLES, "telechargement"];

export default function Documents({ tenantIdOverride = null, hideUpload = false }) {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [kind, setKind] = useState("piece_comptable");
  const [expanded, setExpanded] = useState(null);
  const [synth, setSynth] = useState({});
  const fileRef = useRef(null);
  const { isClient, user } = useAuth();
  const [tenantId, setTenantId] = useState(tenantIdOverride || "");

  // Côté staff uniquement : le client garde son accès Download/Delete inchangé
  // sur ses propres pièces, ces restrictions ne s'appliquent qu'à /admin/documents.
  const myRoles = user?.roles || [];
  const isPrivileged = !isClient && myRoles.some((r) => DOCS_PRIVILEGED_ROLES.includes(r));
  const canDownload = !isClient && myRoles.some((r) => DOWNLOAD_ROLES.includes(r));
  const canDelete = !isClient && myRoles.some((r) => DOCS_DELETE_ROLES.includes(r));
  const canSendWhatsapp = (doc) => isPrivileged || (myRoles.includes("communication") && doc.client_whatsapp_verified);

  const load = async () => {
    setLoading(true);
    try {
      const params = tenantIdOverride ? { tenant_id: tenantIdOverride } : {};
      const { data } = await apiClient.get("/documents", { params });
      setDocs(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tenantIdOverride]);

  // Poll analyses while any doc is pending
  useEffect(() => {
    const pending = docs.some((d) => d.status === "en_analyse");
    if (!pending) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [docs]);

  const upload = async (file) => {
    if (!file) return;
    if (!isClient && !tenantId && !tenantIdOverride) {
      toast.error("Sélectionnez d'abord un client (staff) ou ouvrez un dossier client.");
      return;
    }
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (!isClient) form.append("tenant_id", tenantIdOverride || tenantId);
    try {
      await apiClient.post("/documents", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Pièce téléversée, analyse IA en cours…");
      await load();
    } catch (err) {
      toast.error(extractError(err, "Échec du téléversement"));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const toggleExpand = async (doc) => {
    if (expanded === doc.id) {
      setExpanded(null);
      return;
    }
    setExpanded(doc.id);
    if (!synth[doc.id]) {
      try {
        const { data } = await apiClient.get(`/documents/${doc.id}`);
        setSynth((s) => ({ ...s, [doc.id]: data.synthesis }));
      } catch (err) {
        toast.error(extractError(err));
      }
    }
  };

  const downloadDoc = async (doc) => {
    try {
      const { data } = await apiClient.get(`/documents/${doc.id}/download-url`);
      if (data.url) {
        window.open(data.url, "_blank");
      } else {
        // Local mode: authenticated download
        const token = localStorage.getItem("albarka_token");
        const res = await fetch(`${API}/documents/${doc.id}/download`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("Échec téléchargement");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = doc.original_filename;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      toast.error(extractError(err, "Impossible de télécharger"));
    }
  };

  const deleteDoc = async (doc) => {
    if (!window.confirm(`Supprimer "${doc.original_filename}" ?`)) return;
    try {
      await apiClient.delete(`/documents/${doc.id}`);
      toast.success("Pièce supprimée");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const sendDocByEmail = async (doc) => {
    const owner = doc.client_company || doc.client_name || "le client";
    if (!window.confirm(`Envoyer "${doc.original_filename}" par email à ${owner} ?`)) return;
    try {
      await apiClient.post(`/documents/${doc.id}/send-email`, {});
      toast.success("Pièce envoyée par email");
    } catch (err) {
      toast.error(extractError(err, "Échec de l'envoi par email"));
    }
  };

  const sendDocByWhatsapp = async (doc) => {
    const owner = doc.client_company || doc.client_name || "le client";
    if (!window.confirm(`Envoyer "${doc.original_filename}" par WhatsApp à ${owner} ?`)) return;
    try {
      await apiClient.post(`/documents/${doc.id}/send-whatsapp`, {});
      toast.success("Pièce envoyée par WhatsApp");
    } catch (err) {
      toast.error(extractError(err, "Échec de l'envoi par WhatsApp"));
    }
  };

  return (
    <div className="space-y-6" data-testid="documents-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Pièces</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">
          {isClient ? "Mes pièces" : "Pièces client"}
        </h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Chaque pièce téléversée est automatiquement analysée par notre IA :
          type détecté, synthèse en langage clair et champs clés extraits.
        </p>
      </div>

      {!hideUpload && (
        <div className="albarka-card p-6" data-testid="upload-card">
          <div className="flex flex-col md:flex-row md:items-end gap-4">
            <div className="flex-1">
              <label className="text-sm font-medium mb-1.5 block">Type de pièce</label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger data-testid="upload-kind-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((k) => (
                    <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {!isClient && !tenantIdOverride && (
              <div className="flex-1 min-w-[240px]">
                <label className="text-sm font-medium mb-1.5 block">Client</label>
                <EntitySelect
                  value={tenantId}
                  onChange={setTenantId}
                  testId="tenant-id-input"
                />
              </div>
            )}
            <div>
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.txt,.csv"
                onChange={(e) => upload(e.target.files?.[0])}
                data-testid="upload-file-input"
              />
              <Button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white h-10"
                data-testid="upload-btn"
              >
                <Upload className="w-4 h-4 mr-2" />
                {uploading ? "Téléversement…" : "Téléverser une pièce"}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            PDF, image (JPG/PNG/WEBP), Word, Excel — 20 Mo max.
          </p>
        </div>
      )}

      <div className="albarka-card overflow-hidden" data-testid="documents-table">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12"></TableHead>
              <TableHead>Fichier</TableHead>
              {!isClient && <TableHead>Entreprise</TableHead>}
              <TableHead>Type</TableHead>
              <TableHead className="text-right">Taille</TableHead>
              <TableHead>Déposé le</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={isClient ? 7 : 8} className="text-center text-muted-foreground py-8">Chargement…</TableCell></TableRow>
            )}
            {!loading && docs.length === 0 && (
              <TableRow><TableCell colSpan={isClient ? 7 : 8} className="text-center text-muted-foreground py-10">
                Aucune pièce déposée pour le moment.
              </TableCell></TableRow>
            )}
            {docs.map((d) => (
              <React.Fragment key={d.id}>
                <TableRow className="hover:bg-[#0F6B4A]/5">
                  <TableCell>
                    <button
                      onClick={() => toggleExpand(d)}
                      className="p-1 rounded hover:bg-black/5"
                      data-testid={`expand-doc-${d.id}`}
                    >
                      {expanded === d.id ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                  </TableCell>
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                      <span className="truncate max-w-[280px]">{d.original_filename}</span>
                    </div>
                  </TableCell>
                  {!isClient && (
                    <TableCell className="text-sm">
                      {d.client_company || d.client_name || "—"}
                    </TableCell>
                  )}
                  <TableCell className={`text-sm ${!isClient ? "uppercase" : ""}`}>{d.kind?.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-sm text-right">{Math.round((d.size || 0) / 1024)} Ko</TableCell>
                  <TableCell className="text-sm">
                    {isClient ? d.created_at?.slice(0, 10) : d.created_at?.slice(0, 16).replace("T", " ")}
                  </TableCell>
                  <TableCell>
                    <span className={`albarka-chip ${STATUS_TONE[d.status] || "bg-slate-100 text-slate-700"}`}>
                      {STATUS_LABEL[d.status] || d.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    {isClient ? (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => downloadDoc(d)} data-testid={`download-doc-${d.id}`}>
                          <Download className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => deleteDoc(d)} data-testid={`delete-doc-${d.id}`}>
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => sendDocByEmail(d)} data-testid={`send-email-doc-${d.id}`} title="Envoyer par email">
                          <Mail className="w-4 h-4" />
                        </Button>
                        {canSendWhatsapp(d) && (
                          <Button variant="ghost" size="sm" onClick={() => sendDocByWhatsapp(d)} data-testid={`send-wa-doc-${d.id}`} title="Envoyer par WhatsApp">
                            <MessageCircle className="w-4 h-4" />
                          </Button>
                        )}
                        {canDownload && (
                          <Button variant="ghost" size="sm" onClick={() => downloadDoc(d)} data-testid={`download-doc-${d.id}`} title="Télécharger">
                            <Download className="w-4 h-4" />
                          </Button>
                        )}
                        {canDelete && (
                          <Button variant="ghost" size="sm" onClick={() => deleteDoc(d)} data-testid={`delete-doc-${d.id}`} title="Supprimer">
                            <Trash2 className="w-4 h-4 text-red-600" />
                          </Button>
                        )}
                      </>
                    )}
                  </TableCell>
                </TableRow>
                {expanded === d.id && (
                  <TableRow>
                    <TableCell colSpan={isClient ? 7 : 8} className="bg-[var(--albarka-paper)]/50 border-t border-border">
                      <div className="p-4">
                        <div className="flex items-center gap-2 mb-3">
                          <Sparkles className="w-4 h-4 text-[#0F6B4A]" />
                          <span className="text-sm font-semibold">Synthèse IA</span>
                        </div>
                        {!synth[d.id] && d.status === "en_analyse" && (
                          <div className="text-sm text-muted-foreground">
                            Analyse en cours par Claude Sonnet 5…
                          </div>
                        )}
                        {synth[d.id] && (
                          <div className="space-y-3">
                            {synth[d.id].document_type_guess && (
                              <div className="text-sm">
                                <span className="text-muted-foreground">Type détecté : </span>
                                <span className="font-medium">{synth[d.id].document_type_guess}</span>
                              </div>
                            )}
                            {synth[d.id].summary && (
                              <div className="text-sm leading-relaxed">
                                {synth[d.id].summary}
                              </div>
                            )}
                            {synth[d.id].extracted_fields && Object.keys(synth[d.id].extracted_fields).length > 0 && (
                              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 pt-2">
                                {Object.entries(synth[d.id].extracted_fields).map(([k, v]) => (
                                  <div key={k} className="text-xs bg-white border border-border rounded p-2">
                                    <div className="uppercase tracking-wider text-muted-foreground text-[10px] mb-0.5">{k}</div>
                                    <div className="font-mono truncate">{String(v)}</div>
                                  </div>
                                ))}
                              </div>
                            )}
                            {synth[d.id].flags?.length > 0 && (
                              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
                                ⚠︎ {synth[d.id].flags.join(" · ")}
                              </div>
                            )}
                          </div>
                        )}
                        {!synth[d.id] && d.status !== "en_analyse" && (
                          <div className="text-sm text-muted-foreground">Aucune synthèse disponible.</div>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
