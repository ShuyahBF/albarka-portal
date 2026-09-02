import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Image as ImageIcon, Upload, Trash2, Save } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

const KINDS = [
  { key: "logo", label: "Logo du cabinet", hint: "Affiché en tête de la couverture du rapport (proportionnel, ~3,5 cm).", toggle: "apply_logo" },
  { key: "letterhead", label: "Papier à entête", hint: "Image de fond appliquée sur toutes les pages du PDF (à activer manuellement).", toggle: "apply_letterhead" },
  { key: "dg_signature", label: "Signature Direction Générale", hint: "Insérée en bas du rapport, sous la mention « Direction Générale ».", toggle: "apply_dg_signature" },
  { key: "watermark", label: "Filigrane", hint: "Image centrée en filigrane transparente (~8 %) sur chaque page.", toggle: "apply_watermark" },
];

export default function BrandingPanel() {
  const [branding, setBranding] = useState({});
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/admin/branding");
      setBranding(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const upload = async (kind, file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast.error("5 Mo max"); return; }
    setUploading(kind);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await apiClient.post(`/admin/branding/${kind}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`${KINDS.find((k) => k.key === kind).label} enregistré`);
      await load();
    } catch (err) {
      toast.error(extractError(err));
    } finally { setUploading(null); }
  };

  const remove = async (kind) => {
    if (!window.confirm("Supprimer cette image ?")) return;
    try {
      await apiClient.delete(`/admin/branding/${kind}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  const toggle = async (key, value) => {
    try {
      const { data } = await apiClient.put("/admin/branding/toggles", { [key]: value });
      setBranding(data);
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="branding-panel">
      <div>
        <div className="font-semibold flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-[#0F6B4A]" />
          Charte visuelle des rapports
        </div>
        <div className="text-sm text-muted-foreground">
          Personnalisez l'apparence des rapports PDF en ajoutant votre logo, un papier à entête, la signature
          scannée du DG et un filigrane. Formats acceptés : PNG, JPG, WEBP (5 Mo max).
        </div>
      </div>

      {loading && <div className="text-muted-foreground">Chargement…</div>}

      {!loading && KINDS.map((k) => {
        const entry = branding?.[k.key];
        const toggleOn = branding?.[k.toggle] !== false;
        return (
          <div key={k.key} className="albarka-card p-5 space-y-3" data-testid={`branding-${k.key}`}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-semibold">{k.label}</div>
                <div className="text-xs text-muted-foreground max-w-xl">{k.hint}</div>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-xs">Appliquer</Label>
                <Switch
                  checked={toggleOn}
                  onCheckedChange={(v) => toggle(k.toggle, v)}
                  data-testid={`toggle-${k.key}`}
                />
              </div>
            </div>
            {entry ? (
              <div className="flex items-center gap-3 pt-2 border-t">
                <div className="w-16 h-16 rounded-md bg-slate-100 flex items-center justify-center text-slate-400 flex-shrink-0">
                  <ImageIcon className="w-6 h-6" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{entry.original_filename || entry.path}</div>
                  <div className="text-xs text-muted-foreground">
                    {(entry.size / 1024).toFixed(1)} Ko · Chargé le {entry.uploaded_at?.slice(0, 10)}
                  </div>
                </div>
                <label className="cursor-pointer inline-flex items-center gap-1 px-3 h-9 border rounded-md text-sm hover:bg-slate-50" data-testid={`replace-${k.key}-label`}>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(e) => upload(k.key, e.target.files?.[0])}
                    data-testid={`replace-${k.key}-input`}
                  />
                  <Upload className="w-3 h-3 mr-1" />Remplacer
                </label>
                <Button variant="ghost" size="sm" onClick={() => remove(k.key)} title="Supprimer" data-testid={`delete-${k.key}`}>
                  <Trash2 className="w-4 h-4 text-red-600" />
                </Button>
              </div>
            ) : (
              <label className="block cursor-pointer border-2 border-dashed rounded-md p-4 text-center text-sm text-muted-foreground hover:bg-slate-50">
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => upload(k.key, e.target.files?.[0])}
                  data-testid={`upload-${k.key}-input`}
                />
                <Upload className="w-5 h-5 mx-auto mb-1 text-[#0F6B4A]" />
                {uploading === k.key ? "Envoi en cours…" : "Cliquer pour charger une image PNG/JPG/WEBP"}
              </label>
            )}
          </div>
        );
      })}
    </div>
  );
}
