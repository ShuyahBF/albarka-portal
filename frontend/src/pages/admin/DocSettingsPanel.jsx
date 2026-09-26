/*
  DocSettingsPanel — « Papiers à en-tête & signataire » (lot 7).
  Affiché dans Paramètres → Documents et dans Documents & modèles.

  - PAPIERS À EN-TÊTE : plusieurs en-têtes (ex. ALBARKA, GESPHARM). Chacun a
    une image d'en-tête (haut de page) et une image de pied de page (bas de
    page), ou rien du tout pour du papier préimprimé (on laisse alors la marge
    haute vide, 4,8 cm par défaut comme la facture du cabinet). Un papier est
    « par défaut » ; chaque facture ou document peut en choisir un autre.
  - RÉGLAGES : ville (« Ouagadougou, le … »), signataire (titre + nom),
    IFU / RCCM du cabinet, phrase de remerciement, TVA et retenue par défaut.
  Écriture : Direction, DG, Administrateur, Superviseur (les autres voient).
  API : /admin/letterheads, /admin/doc-settings
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Star, Save, Loader2, ImagePlus, Stamp, PenLine } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { ui, cx } from "@/components/forms-core/ui";

const WRITERS = ["superviseur", "direction", "dg", "administrateur"];

// Aperçu d'une image du papier (chargée avec le jeton de connexion)
function LetterheadImage({ id, part, stamp }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url;
    apiClient.get(`/admin/letterheads/${id}/${part}`, { responseType: "blob" })
      .then((r) => { url = URL.createObjectURL(r.data); setSrc(url); }).catch(() => setSrc(null));
    return () => url && URL.revokeObjectURL(url);
  }, [id, part, stamp]);
  return src ? <img src={src} alt={part === "header" ? "En-tête" : "Pied de page"} className="w-full rounded border border-slate-200" /> : null;
}

export default function DocSettingsPanel() {
  const { user } = useAuth();
  const canWrite = (user?.roles || []).some((r) => WRITERS.includes(r));
  const [list, setList] = useState(null);
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", top_margin_cm: 4.8, header: null, footer: null });
  const [stamp, setStamp] = useState(0);   // force le rechargement des aperçus

  const load = () => {
    apiClient.get("/admin/letterheads").then(({ data }) => setList(data)).catch((e) => toast.error(extractError(e)));
    apiClient.get("/admin/doc-settings").then(({ data }) => setSettings(data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  // Création d'un papier (nom + images facultatives)
  const create = async () => {
    if (!form.name.trim()) { toast.error("Donnez un nom au papier à en-tête"); return; }
    const fd = new FormData();
    fd.append("name", form.name.trim());
    fd.append("top_margin_cm", String(form.top_margin_cm || 4.8));
    if (form.header) fd.append("header", form.header);
    if (form.footer) fd.append("footer", form.footer);
    try {
      await apiClient.post("/admin/letterheads", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Papier à en-tête ajouté");
      setForm({ name: "", top_margin_cm: 4.8, header: null, footer: null });
      load(); setStamp((n) => n + 1);
    } catch (e) { toast.error(extractError(e)); }
  };
  // Modification : image remplacée / retirée, défaut, marge
  const update = async (lh, fields) => {
    const fd = new FormData();
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    try {
      await apiClient.put(`/admin/letterheads/${lh.id}`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      load(); setStamp((n) => n + 1);
    } catch (e) { toast.error(extractError(e)); }
  };
  const remove = async (lh) => {
    if (!window.confirm(`Supprimer le papier « ${lh.name} » ?`)) return;
    try { await apiClient.delete(`/admin/letterheads/${lh.id}`); load(); } catch (e) { toast.error(extractError(e)); }
  };
  const saveSettings = async () => {
    setSaving(true);
    try {
      const { data } = await apiClient.put("/admin/doc-settings", {
        ...settings, default_tva_rate: Number(settings.default_tva_rate) || 0, default_withholding_rate: Number(settings.default_withholding_rate) || 0,
      });
      setSettings(data); toast.success("Réglages enregistrés");
    } catch (e) { toast.error(extractError(e)); } finally { setSaving(false); }
  };

  const fileBtn = (label, onPick, testId) => (
    <label className={cx(ui.act.sky, "cursor-pointer")}><ImagePlus className="h-3.5 w-3.5" /> {label}
      <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid={testId} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onPick(f); }} /></label>
  );

  return (
    <div className="space-y-5" data-testid="doc-settings-panel">
      {/* Papiers à en-tête */}
      <div className={ui.panel}>
        <p className={ui.panelTitle}><Stamp className={ui.panelIcon} /> Papiers à en-tête</p>
        <p className="text-xs text-slate-500">Image d'en-tête (haut de page) et de pied de page (bas de page), sur toute la largeur de la feuille. Sans image : papier préimprimé, la marge haute reste vide.</p>
        {list === null ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline" /></p> : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {list.length === 0 && <p className={ui.empty}>Aucun papier à en-tête : les documents sortent sans en-tête.</p>}
            {list.map((lh) => (
              <div key={lh.id} className={cx(ui.card, "space-y-2")} data-testid={`letterhead-${lh.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="font-display font-bold">{lh.name}</p>
                  {lh.is_default ? <span className={ui.badge.green}><Star className="h-3 w-3" /> Par défaut</span>
                    : canWrite && <button type="button" onClick={() => update(lh, { is_default: "true" })} className={ui.btnTool}>Mettre par défaut</button>}
                </div>
                {lh.has_header ? <LetterheadImage id={lh.id} part="header" stamp={stamp} /> : <p className="text-xs text-slate-400 italic">Pas d'image d'en-tête (marge haute : {lh.top_margin_cm} cm)</p>}
                <div className="h-10 rounded border border-dashed border-slate-200 text-[10px] text-slate-300 flex items-center justify-center">contenu du document</div>
                {lh.has_footer ? <LetterheadImage id={lh.id} part="footer" stamp={stamp} /> : <p className="text-xs text-slate-400 italic">Pas d'image de pied de page</p>}
                {canWrite && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {fileBtn(lh.has_header ? "Changer l'en-tête" : "Ajouter l'en-tête", (f) => update(lh, { header: f }))}
                    {fileBtn(lh.has_footer ? "Changer le pied" : "Ajouter le pied", (f) => update(lh, { footer: f }))}
                    {lh.has_header && <button type="button" onClick={() => update(lh, { remove_header: "true" })} className={ui.btnTool}>Retirer l'en-tête</button>}
                    {lh.has_footer && <button type="button" onClick={() => update(lh, { remove_footer: "true" })} className={ui.btnTool}>Retirer le pied</button>}
                    <button type="button" onClick={() => remove(lh)} className={ui.act.iconDanger} title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {canWrite && (
          <div className="flex flex-wrap items-end gap-3 border-t border-slate-100 pt-3">
            <label className="block"><span className={ui.label}>Nouveau papier</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ui.inputInline} placeholder="ex. GESPHARM" data-testid="letterhead-name" /></label>
            <label className="block"><span className={ui.label}>Marge haute sans image (cm)</span><input type="number" step="0.1" value={form.top_margin_cm} onChange={(e) => setForm({ ...form, top_margin_cm: e.target.value })} className={cx(ui.inputInline, "w-24")} /></label>
            {fileBtn(form.header ? `En-tête : ${form.header.name}` : "Image d'en-tête", (f) => setForm((x) => ({ ...x, header: f })), "letterhead-header-file")}
            {fileBtn(form.footer ? `Pied : ${form.footer.name}` : "Image de pied de page", (f) => setForm((x) => ({ ...x, footer: f })), "letterhead-footer-file")}
            <button type="button" onClick={create} className={ui.btnPrimary} data-testid="letterhead-create"><Plus className="h-4 w-4" /> Ajouter</button>
          </div>
        )}
      </div>

      {/* Signataire et réglages des documents */}
      {settings && (
        <div className={ui.panel}>
          <p className={ui.panelTitle}><PenLine className={ui.panelIcon} /> Signataire et mentions</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[["city", "Ville (« Ouagadougou, le … »)"], ["signatory_title", "Titre du signataire"], ["signatory_name", "Nom du signataire"],
              ["cabinet_ifu", "IFU du cabinet"], ["cabinet_rccm", "RCCM du cabinet"], ["thanks_text", "Phrase sous les totaux"]].map(([k, l]) => (
              <label key={k} className="block"><span className={ui.label}>{l}</span>
                <input value={settings[k] ?? ""} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, [k]: e.target.value })} className={ui.input} data-testid={`doc-setting-${k}`} /></label>
            ))}
            <label className="block"><span className={ui.label}>TVA par défaut (%)</span>
              <input type="number" value={settings.default_tva_rate ?? 18} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, default_tva_rate: e.target.value })} className={ui.input} /></label>
            <label className="block"><span className={ui.label}>Retenue proposée (%)</span>
              <input type="number" value={settings.default_withholding_rate ?? 0} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, default_withholding_rate: e.target.value })} className={ui.input} /></label>
          </div>
          <p className="text-[11px] text-slate-400">La signature manuscrite du DG (Paramètres → Branding) est ajoutée sur les factures si l'option « signature du DG » est activée.</p>
          {canWrite && <div className="flex justify-end"><button type="button" onClick={saveSettings} disabled={saving} className={ui.btnPrimary} data-testid="doc-settings-save">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer</button></div>}
        </div>
      )}
    </div>
  );
}
