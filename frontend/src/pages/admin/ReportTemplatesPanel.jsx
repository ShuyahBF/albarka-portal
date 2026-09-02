import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, FileText, Star } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const KINDS = [
  { value: "mensuel", label: "Mensuel" },
  { value: "trimestriel", label: "Trimestriel" },
  { value: "annuel", label: "Annuel" },
  { value: "audit", label: "Audit" },
  { value: "conseil", label: "Conseil" },
  { value: "ponctuel", label: "Ponctuel" },
];

const emptyForm = () => ({
  name: "", description: "", default_kind: "mensuel",
  include_kpis: true, include_missions: true, include_echeances: true,
  include_documents: true, include_ai_syntheses: true,
  only_status_open: false, is_default: false,
  intro_paragraph: "", conclusion_paragraph: "",
});

export default function ReportTemplatesPanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/report-templates");
      setItems(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing(null); setForm(emptyForm()); setOpen(true); };
  const openEdit = (t) => {
    setEditing(t);
    setForm({
      name: t.name || "", description: t.description || "",
      default_kind: t.default_kind || "mensuel",
      include_kpis: t.include_kpis !== false,
      include_missions: t.include_missions !== false,
      include_echeances: t.include_echeances !== false,
      include_documents: t.include_documents !== false,
      include_ai_syntheses: t.include_ai_syntheses !== false,
      only_status_open: !!t.only_status_open,
      is_default: !!t.is_default,
      intro_paragraph: t.intro_paragraph || "",
      conclusion_paragraph: t.conclusion_paragraph || "",
    });
    setOpen(true);
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Le nom du modèle est requis"); return; }
    try {
      if (editing) {
        await apiClient.patch(`/report-templates/${editing.id}`, form);
        toast.success("Modèle mis à jour");
      } else {
        await apiClient.post("/report-templates", form);
        toast.success("Modèle créé");
      }
      setOpen(false);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const remove = async (t) => {
    if (!window.confirm(`Supprimer le modèle "${t.name}" ?`)) return;
    try {
      await apiClient.delete(`/report-templates/${t.id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="report-templates-panel">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">Modèles de rapports</div>
          <div className="text-xs text-muted-foreground">
            Choisissez les sections à inclure et personnalisez l'intro / conclusion.
            Le modèle par défaut est appliqué automatiquement si aucun n'est sélectionné.
          </div>
        </div>
        <Button onClick={openNew} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="add-template-btn">
          <Plus className="w-4 h-4 mr-2" />Nouveau modèle
        </Button>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Type par défaut</TableHead>
              <TableHead>Sections</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && items.length === 0 && <TableRow><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">Aucun modèle.</TableCell></TableRow>}
            {items.map((t) => (
              <TableRow key={t.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium flex items-center gap-2">
                  <FileText className="w-4 h-4 text-[#0F6B4A]" />
                  {t.name}
                  {t.is_default && <Star className="w-4 h-4 fill-[#E5A24B] text-[#E5A24B]" />}
                </TableCell>
                <TableCell className="text-sm">{KINDS.find((k) => k.value === t.default_kind)?.label || t.default_kind}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {t.include_kpis && <span className="albarka-chip bg-slate-100 text-slate-600 text-[10px]">KPIs</span>}
                    {t.include_missions && <span className="albarka-chip bg-slate-100 text-slate-600 text-[10px]">Missions</span>}
                    {t.include_echeances && <span className="albarka-chip bg-slate-100 text-slate-600 text-[10px]">Échéances</span>}
                    {t.include_documents && <span className="albarka-chip bg-slate-100 text-slate-600 text-[10px]">Pièces</span>}
                    {t.include_ai_syntheses && <span className="albarka-chip bg-slate-100 text-slate-600 text-[10px]">IA</span>}
                  </div>
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => openEdit(t)} title="Éditer" data-testid={`edit-template-${t.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => remove(t)} title="Supprimer" data-testid={`delete-template-${t.id}`}>
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl" data-testid="template-dialog">
          <DialogHeader><DialogTitle>{editing ? "Modifier" : "Créer"} un modèle de rapport</DialogTitle></DialogHeader>
          <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Nom</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="template-name-input" /></div>
              <div>
                <Label>Type par défaut</Label>
                <Select value={form.default_kind} onValueChange={(v) => setForm({ ...form, default_kind: v })}>
                  <SelectTrigger data-testid="template-kind-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>Description</Label><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="template-desc-input" /></div>
            <div>
              <Label>Sections à inclure</Label>
              <div className="grid grid-cols-2 gap-2 mt-2">
                {[
                  ["include_kpis", "KPIs (missions, échéances, pièces)"],
                  ["include_missions", "Missions du dossier"],
                  ["include_echeances", "Échéances fiscales & sociales"],
                  ["include_documents", "Pièces déposées"],
                  ["include_ai_syntheses", "Synthèses IA"],
                  ["only_status_open", "Missions/échéances ouvertes uniquement"],
                ].map(([k, label]) => (
                  <label key={k} className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox checked={!!form[k]} onCheckedChange={(v) => setForm({ ...form, [k]: !!v })} data-testid={`template-${k}`} />
                    {label}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <Label>Introduction (optionnel)</Label>
              <Textarea rows={3} value={form.intro_paragraph} onChange={(e) => setForm({ ...form, intro_paragraph: e.target.value })} placeholder="Paragraphe d'introduction imprimé sur la couverture." data-testid="template-intro" />
            </div>
            <div>
              <Label>Conclusion (optionnel)</Label>
              <Textarea rows={3} value={form.conclusion_paragraph} onChange={(e) => setForm({ ...form, conclusion_paragraph: e.target.value })} placeholder="Paragraphe de clôture imprimé en fin de rapport." data-testid="template-conclusion" />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
              <Checkbox checked={form.is_default} onCheckedChange={(v) => setForm({ ...form, is_default: !!v })} data-testid="template-default" />
              Définir comme modèle par défaut
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button onClick={save} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="template-submit-btn">
              {editing ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
