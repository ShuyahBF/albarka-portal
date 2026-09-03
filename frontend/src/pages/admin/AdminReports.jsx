import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { FileDown, Send, PenTool, Trash2, Plus, Search, Calendar as CalIcon, FileText as FileTextIcon, Users2, MessageCircle, ShieldCheck } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import ReportTemplatesPanel from "@/pages/admin/ReportTemplatesPanel";
import SignatureLogPanel from "@/pages/admin/SignatureLogPanel";
import WhatsAppLogPanel from "@/pages/admin/WhatsAppLogPanel";

const REPORT_KINDS = [
  { value: "mensuel", label: "Rapport mensuel" },
  { value: "trimestriel", label: "Rapport trimestriel" },
  { value: "annuel", label: "Rapport annuel" },
  { value: "audit", label: "Rapport d'audit" },
  { value: "conseil", label: "Note de conseil" },
  { value: "ponctuel", label: "Rapport ponctuel" },
];

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Client reports panel — filter by month, generate, download, send, sign. */
export function ClientReportsPanel({ tenantId, clientEmail }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [genOpen, setGenOpen] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [waOpen, setWaOpen] = useState(false);
  const [signOpen, setSignOpen] = useState(false);
  const [active, setActive] = useState(null);
  const [kind, setKind] = useState("mensuel");
  const [month, setMonth] = useState(currentMonth());
  const [templateId, setTemplateId] = useState("");
  const [templates, setTemplates] = useState([]);
  const [groups, setGroups] = useState([]);
  const [filterMonth, setFilterMonth] = useState("all");
  const [filterKind, setFilterKind] = useState("all");
  const [sendForm, setSendForm] = useState({ to: "", subject: "", message: "", to_groups: [] });
  const [waForm, setWaForm] = useState({ to: "", message: "", to_groups: [], all_whatsapp_contacts: false });
  const [signForm, setSignForm] = useState({ signature_name: "", signature_provider: "", signature_reference: "" });

  useEffect(() => {
    (async () => {
      try {
        const [{ data: t }, { data: g }] = await Promise.all([
          apiClient.get("/report-templates"),
          apiClient.get("/contact-groups", { params: { scope: "client", tenant_id: tenantId } }),
        ]);
        setTemplates(t);
        setGroups(g);
      } catch (err) { /* silent — panels still work */ }
    })();
  }, [tenantId]);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (filterMonth !== "all") params.month_key = filterMonth;
      if (filterKind !== "all") params.kind = filterKind;
      const { data } = await apiClient.get(`/reports/client/${tenantId}/list`, { params });
      setReports(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [tenantId, filterMonth, filterKind]);

  // Distinct months available in this client's reports (for the filter dropdown).
  const availableMonths = useMemo(() => {
    const s = new Set(reports.map((r) => r.month_key));
    return Array.from(s).sort().reverse();
  }, [reports]);

  const generate = async () => {
    if (!kind || !month) return;
    try {
      const payload = { kind, period_month: month };
      if (templateId) payload.template_id = templateId;
      const { data } = await apiClient.post(`/reports/client/${tenantId}/generate`, payload);
      toast.success(`Rapport ${data.number} généré`);
      setGenOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const download = async (r) => {
    try {
      const token = localStorage.getItem("albarka_token");
      const res = await fetch(`${API}/reports/${r.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Échec téléchargement");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${r.number}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const openSend = (r) => {
    setActive(r);
    setSendForm({
      to: clientEmail || "",
      subject: `${r.kind_label} — ${r.number}`,
      message: "",
      to_groups: [],
    });
    setSendOpen(true);
  };

  const doSend = async () => {
    try {
      const payload = {
        subject: sendForm.subject, message: sendForm.message,
      };
      if (sendForm.to_groups.length > 0) {
        payload.to_groups = sendForm.to_groups;
      } else if (sendForm.to) {
        payload.to = sendForm.to;
      }
      const { data } = await apiClient.post(`/reports/${active.id}/send`, payload);
      toast.success(`Envoyé à ${data.to.join(", ")}`);
      setSendOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const toggleSendGroup = (id) => {
    setSendForm((f) => ({
      ...f,
      to_groups: f.to_groups.includes(id) ? f.to_groups.filter((x) => x !== id) : [...f.to_groups, id],
    }));
  };

  const openWa = (r) => {
    setActive(r);
    setWaForm({ to: "", message: `${r.kind_label} — ${r.number}\nRéférence : ${r.month_key}`, to_groups: [], all_whatsapp_contacts: false });
    setWaOpen(true);
  };

  const doWa = async () => {
    if (!waForm.to && waForm.to_groups.length === 0 && !waForm.all_whatsapp_contacts) {
      toast.error("Renseignez un numéro, un groupe ou cochez « Tous les contacts WhatsApp »");
      return;
    }
    try {
      const payload = { message: waForm.message };
      if (waForm.all_whatsapp_contacts) payload.all_whatsapp_contacts = true;
      if (waForm.to_groups.length > 0) payload.to_groups = waForm.to_groups;
      if (waForm.to) payload.to = waForm.to;
      const { data } = await apiClient.post(`/reports/${active.id}/send-whatsapp`, payload);
      const okCount = (data.sent || []).length;
      const koCount = (data.failed || []).length;
      toast.success(`WhatsApp : ${okCount} délivré${okCount > 1 ? "s" : ""}${koCount ? ` · ${koCount} échec${koCount > 1 ? "s" : ""}` : ""}`);
      setWaOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const toggleWaGroup = (id) => {
    setWaForm((f) => ({
      ...f,
      to_groups: f.to_groups.includes(id) ? f.to_groups.filter((x) => x !== id) : [...f.to_groups, id],
    }));
  };

  const openSign = (r) => {
    setActive(r);
    setSignForm({ signature_name: "", signature_provider: "cabinet_seal", signature_reference: "" });
    setSignOpen(true);
  };

  const doSign = async () => {
    try {
      await apiClient.post(`/reports/${active.id}/sign`, signForm);
      toast.success("Rapport signé");
      setSignOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const del = async (r) => {
    if (!window.confirm(`Supprimer le rapport ${r.number} ?`)) return;
    try {
      await apiClient.delete(`/reports/${r.id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="client-reports-panel">
      <div className="flex flex-col md:flex-row md:items-end gap-3 md:justify-between">
        <div className="flex gap-2 items-end flex-wrap">
          <div>
            <Label className="text-xs">Mois</Label>
            <Select value={filterMonth} onValueChange={setFilterMonth}>
              <SelectTrigger className="w-40 h-9" data-testid="filter-month-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les mois</SelectItem>
                {availableMonths.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Type</Label>
            <Select value={filterKind} onValueChange={setFilterKind}>
              <SelectTrigger className="w-48 h-9" data-testid="filter-kind-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous types</SelectItem>
                {REPORT_KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <Button
          onClick={() => { setKind("mensuel"); setMonth(currentMonth()); setGenOpen(true); }}
          className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
          data-testid="generate-report-btn"
        >
          <Plus className="w-4 h-4 mr-2" />
          Générer un rapport
        </Button>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>N° Rapport</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Période</TableHead>
              <TableHead>Généré le</TableHead>
              <TableHead>État</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && reports.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center py-10 text-muted-foreground">
                Aucun rapport encore généré pour ce client.
              </TableCell></TableRow>
            )}
            {reports.map((r) => (
              <TableRow key={r.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-mono text-xs">{r.number}</TableCell>
                <TableCell className="text-sm">{r.kind_label}</TableCell>
                <TableCell className="text-sm">{r.month_key}</TableCell>
                <TableCell className="text-sm">{r.generated_at?.slice(0, 10)}</TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    {r.signed
                      ? <span className="albarka-chip bg-emerald-100 text-emerald-800" title={r.signed_by ? `Signé par ${r.signed_by}` : ""}>Signé</span>
                      : <span className="albarka-chip bg-slate-100 text-slate-600">Non signé</span>}
                    {r.email_sent_at
                      ? <span className="text-[10px] text-muted-foreground">✉︎ email {r.email_sent_at?.slice(0, 10)}</span>
                      : <span className="text-[10px] text-muted-foreground">Non envoyé</span>}
                    {r.wa_sent_at && <span className="text-[10px] text-[#0F6B4A]">✆ WA {r.wa_sent_at?.slice(0, 10)}</span>}
                  </div>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => download(r)} title="Télécharger" data-testid={`report-download-${r.id}`}>
                    <FileDown className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => openSend(r)} title="Envoyer par email" data-testid={`report-send-${r.id}`}>
                    <Send className="w-4 h-4 text-[#0F6B4A]" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => openWa(r)} title="Envoyer par WhatsApp" data-testid={`report-wa-${r.id}`}>
                    <MessageCircle className="w-4 h-4 text-emerald-600" />
                  </Button>
                  {!r.signed && (
                    <Button variant="ghost" size="sm" onClick={() => openSign(r)} title="Signer" data-testid={`report-sign-${r.id}`}>
                      <PenTool className="w-4 h-4 text-[#E5A24B]" />
                    </Button>
                  )}
                  {!r.signed && (
                    <Button variant="ghost" size="sm" onClick={() => del(r)} title="Supprimer" data-testid={`report-delete-${r.id}`}>
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Generate dialog */}
      <Dialog open={genOpen} onOpenChange={setGenOpen}>
        <DialogContent data-testid="generate-report-dialog">
          <DialogHeader><DialogTitle>Générer un rapport</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Type de rapport</Label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger data-testid="gen-kind-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {REPORT_KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Mois (YYYY-MM)</Label>
              <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} data-testid="gen-month-input" />
            </div>
            <div>
              <Label>Modèle de rapport (optionnel)</Label>
              <Select value={templateId || "__default__"} onValueChange={(v) => setTemplateId(v === "__default__" ? "" : v)}>
                <SelectTrigger data-testid="gen-template-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__default__">Modèle par défaut</SelectItem>
                  {templates.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.name}{t.is_default ? " ★" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-xs text-muted-foreground mt-1">
                Contrôle les sections, l'intro et la conclusion imprimées.
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGenOpen(false)}>Annuler</Button>
            <Button onClick={generate} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="gen-submit-btn">Générer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Send dialog */}
      <Dialog open={sendOpen} onOpenChange={setSendOpen}>
        <DialogContent data-testid="send-report-dialog">
          <DialogHeader><DialogTitle>Envoyer le rapport par email</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Destinataire direct</Label>
              <Input value={sendForm.to} onChange={(e) => setSendForm({ ...sendForm, to: e.target.value })} placeholder="email@exemple.com" disabled={sendForm.to_groups.length > 0} data-testid="send-to-input" />
            </div>
            {groups.length > 0 && (
              <div>
                <Label className="flex items-center gap-1"><Users2 className="w-4 h-4" /> Ou envoyer à des groupes ({sendForm.to_groups.length} sélectionnés)</Label>
                <div className="mt-2 space-y-1 max-h-32 overflow-y-auto border rounded-md p-2">
                  {groups.map((g) => (
                    <label key={g.id} className="flex items-center gap-2 text-sm cursor-pointer">
                      <Checkbox checked={sendForm.to_groups.includes(g.id)} onCheckedChange={() => toggleSendGroup(g.id)} data-testid={`send-group-${g.id}`} />
                      <span className="font-medium">{g.name}</span>
                      <span className="text-xs text-muted-foreground">({(g.contact_ids || []).length} membres)</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div><Label>Objet</Label><Input value={sendForm.subject} onChange={(e) => setSendForm({ ...sendForm, subject: e.target.value })} data-testid="send-subject-input" /></div>
            <div><Label>Message (optionnel)</Label><Textarea rows={4} value={sendForm.message} onChange={(e) => setSendForm({ ...sendForm, message: e.target.value })} data-testid="send-message-input" /></div>
            <div className="text-xs text-muted-foreground">Le rapport PDF sera joint automatiquement.</div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSendOpen(false)}>Annuler</Button>
            <Button onClick={doSend} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="send-submit-btn">
              <Send className="w-4 h-4 mr-2" />Envoyer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* WhatsApp dialog */}
      <Dialog open={waOpen} onOpenChange={setWaOpen}>
        <DialogContent data-testid="wa-report-dialog">
          <DialogHeader><DialogTitle>Envoyer le rapport par WhatsApp</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground border-l-2 border-emerald-500/50 pl-2">
              Nous tentons d'abord d'envoyer le PDF en pièce jointe (Meta Media API).
              Si l'upload échoue, un message texte contenant un lien signé (7 jours) est envoyé à la place.
            </div>
            <label className="flex items-start gap-2 text-sm cursor-pointer p-3 border-2 border-emerald-500/30 bg-emerald-50/50 rounded-md hover:bg-emerald-50">
              <Checkbox
                checked={waForm.all_whatsapp_contacts}
                onCheckedChange={(v) => setWaForm({ ...waForm, all_whatsapp_contacts: !!v, to: v ? "" : waForm.to, to_groups: v ? [] : waForm.to_groups })}
                data-testid="wa-broadcast-checkbox"
                className="mt-0.5"
              />
              <div>
                <div className="font-semibold text-emerald-800">Envoyer à tous les contacts WhatsApp de ce client</div>
                <div className="text-xs text-muted-foreground">
                  Diffuse le rapport à tous les contacts actifs de ce client qui ont un téléphone et
                  le canal WhatsApp activé — pratique pour un envoi de masse en un clic.
                </div>
              </div>
            </label>
            <div>
              <Label>Numéro WhatsApp direct (+226…)</Label>
              <Input value={waForm.to} onChange={(e) => setWaForm({ ...waForm, to: e.target.value })} placeholder="+22670…" disabled={waForm.to_groups.length > 0 || waForm.all_whatsapp_contacts} data-testid="wa-to-input" />
            </div>
            {groups.length > 0 && !waForm.all_whatsapp_contacts && (
              <div>
                <Label className="flex items-center gap-1"><Users2 className="w-4 h-4" /> Ou envoyer à des groupes ({waForm.to_groups.length} sélectionnés)</Label>
                <div className="mt-2 space-y-1 max-h-32 overflow-y-auto border rounded-md p-2">
                  {groups.map((g) => (
                    <label key={g.id} className="flex items-center gap-2 text-sm cursor-pointer">
                      <Checkbox checked={waForm.to_groups.includes(g.id)} onCheckedChange={() => toggleWaGroup(g.id)} data-testid={`wa-group-${g.id}`} />
                      <span className="font-medium">{g.name}</span>
                      <span className="text-xs text-muted-foreground">({(g.contact_ids || []).length} membres)</span>
                    </label>
                  ))}
                </div>
                <div className="text-[10px] text-muted-foreground mt-1">
                  Seuls les contacts avec téléphone et canal WhatsApp coché seront destinataires.
                </div>
              </div>
            )}
            <div><Label>Message (accompagne la pièce jointe)</Label><Textarea rows={3} value={waForm.message} onChange={(e) => setWaForm({ ...waForm, message: e.target.value })} data-testid="wa-message-input" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWaOpen(false)}>Annuler</Button>
            <Button onClick={doWa} className="bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="wa-submit-btn">
              <MessageCircle className="w-4 h-4 mr-2" />Envoyer WA
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Sign dialog */}
      <Dialog open={signOpen} onOpenChange={setSignOpen}>
        <DialogContent data-testid="sign-report-dialog">
          <DialogHeader><DialogTitle>Signer le rapport</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Nom du signataire</Label><Input value={signForm.signature_name} onChange={(e) => setSignForm({ ...signForm, signature_name: e.target.value })} data-testid="sign-name-input" /></div>
            <div>
              <Label>Type de signature</Label>
              <Select value={signForm.signature_provider} onValueChange={(v) => setSignForm({ ...signForm, signature_provider: v })}>
                <SelectTrigger data-testid="sign-provider-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cabinet_seal">Sceau du cabinet</SelectItem>
                  <SelectItem value="qualified">Signature qualifiée (eIDAS)</SelectItem>
                  <SelectItem value="advanced">Signature avancée</SelectItem>
                  <SelectItem value="handwritten">Manuscrite scannée</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label>Référence externe (optionnel)</Label><Input value={signForm.signature_reference} onChange={(e) => setSignForm({ ...signForm, signature_reference: e.target.value })} placeholder="ex: identifiant DocuSign, hash…" data-testid="sign-ref-input" /></div>
            <div className="text-xs text-muted-foreground">
              Enregistre les métadonnées de signature du rapport. Le câblage au service de signature externe se fait via <span className="font-mono">signature_provider</span>/<span className="font-mono">signature_reference</span>.
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSignOpen(false)}>Annuler</Button>
            <Button onClick={doSign} className="bg-[#E5A24B] hover:bg-[#c8871a] text-[#0B1912]" data-testid="sign-submit-btn">
              <PenTool className="w-4 h-4 mr-2" />Signer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Global "Rapports client" page — list of clients with quick access. */
export default function AdminReports() {
  const [clients, setClients] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedClient, setSelectedClient] = useState(null);

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

  return (
    <div className="space-y-6" data-testid="admin-reports-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Rapports client</h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Génération, envoi par email et signature des rapports. Numérotation
          automatique : <span className="font-mono">PREFIXE-CLIENT-TYPE-YYYYMM-NNNN</span>.
        </p>
      </div>

      <Tabs defaultValue="reports">
        <TabsList data-testid="reports-tabs">
          <TabsTrigger value="reports" data-testid="tab-reports">Rapports</TabsTrigger>
          <TabsTrigger value="templates" data-testid="tab-templates">
            <FileTextIcon className="w-4 h-4 mr-2" />Modèles
          </TabsTrigger>
          <TabsTrigger value="log" data-testid="tab-signlog">
            <ShieldCheck className="w-4 h-4 mr-2" />Journal signatures
          </TabsTrigger>
          <TabsTrigger value="walog" data-testid="tab-walog">
            <MessageCircle className="w-4 h-4 mr-2" />Journal WhatsApp
          </TabsTrigger>
        </TabsList>

        <TabsContent value="reports" className="pt-4">
          {!selectedClient ? (
            <>
              <div className="albarka-card p-4">
                <div className="relative max-w-md">
                  <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
                  <Input placeholder="Rechercher un client…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" data-testid="reports-search-input" />
                </div>
              </div>
              <div className="albarka-card overflow-hidden mt-4">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Client</TableHead>
                      <TableHead>Entreprise</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead className="text-right">Rapports</TableHead>
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
                          <Button size="sm" onClick={() => setSelectedClient(c)} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid={`open-reports-${c.id}`}>
                            Ouvrir
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-muted-foreground">Rapports de</div>
                  <div className="font-display text-2xl">{selectedClient.full_name}</div>
                  {selectedClient.company && <div className="text-sm text-muted-foreground">{selectedClient.company}</div>}
                </div>
                <Button variant="outline" onClick={() => setSelectedClient(null)} data-testid="back-to-client-list-btn">
                  ← Retour à la liste
                </Button>
              </div>
              <ClientReportsPanel tenantId={selectedClient.id} clientEmail={selectedClient.email} />
            </div>
          )}
        </TabsContent>

        <TabsContent value="templates" className="pt-4">
          <ReportTemplatesPanel />
        </TabsContent>

        <TabsContent value="log" className="pt-4">
          <SignatureLogPanel />
        </TabsContent>

        <TabsContent value="walog" className="pt-4">
          <WhatsAppLogPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
