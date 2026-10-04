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
  - LOT 12 — TYPE « PAGE ENTIÈRE (FOND A4) » : quand l'image chargée est une
    page A4 complète (logo en haut, blanc au milieu, coordonnées en bas), elle
    est posée en fond de chaque page et le texte s'écrit entre une marge haute
    et une marge basse (mm). Ces marges sont détectées automatiquement sur
    l'image (bouton « Détecter les marges ») et restent modifiables. L'aperçu
    montre les deux lignes de marge et la zone de texte grisée.
  Écriture : Direction, DG, Administrateur, Superviseur (les autres voient).
  API : /admin/letterheads, /admin/letterheads/detect, /admin/doc-settings
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Star, Save, Loader2, ImagePlus, Stamp, PenLine, ScanLine } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { ui, cx } from "@/components/forms-core/ui";

const WRITERS = ["superviseur", "direction", "dg", "administrateur"];

// Hauteur et largeur d'une feuille A4 en millimètres (aperçu « page entière »)
const A4_H_MM = 297;
const A4_W_MM = 210;
// Libellés des deux types de papier (lot 12)
const MODES = [["bandes", "En-tête + pied séparés"], ["page", "Page entière (fond A4)"]];

// Adresse locale (blob) d'une image du papier, chargée avec le jeton de connexion
function useLetterheadSrc(id, part, stamp) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url;
    apiClient.get(`/admin/letterheads/${id}/${part}`, { responseType: "blob" })
      .then((r) => { url = URL.createObjectURL(r.data); setSrc(url); }).catch(() => setSrc(null));
    return () => url && URL.revokeObjectURL(url);
  }, [id, part, stamp]);
  return src;
}

// Aperçu d'une image du papier (type « bandes »)
function LetterheadImage({ id, part, stamp }) {
  const src = useLetterheadSrc(id, part, stamp);
  return src ? <img src={src} alt={part === "header" ? "En-tête" : "Pied de page"} className="w-full rounded border border-slate-200" /> : null;
}

// Lot 12 — miniature d'un papier « page entière » : l'image A4 en fond, les
// lignes de marge haute et basse, et la zone où s'écrit le texte (grisée)
function PagePreview({ src, top, bottom, left, right }) {
  // Position des lignes en pourcentage de la hauteur / largeur de la page
  const pct = (v, total) => `${Math.max(0, Math.min(100, ((Number(v) || 0) / total) * 100))}%`;
  return (
    <div className="relative mx-auto w-40 aspect-[210/297] rounded border border-slate-300 bg-white overflow-hidden" data-testid="letterhead-page-preview">
      {src && <img src={src} alt="Papier page entière" className="absolute inset-0 h-full w-full object-fill" />}
      {/* Zone de texte (entre les quatre marges) */}
      <div className="absolute bg-slate-400/25 border border-dashed border-slate-500/50"
        style={{ top: pct(top, A4_H_MM), bottom: pct(bottom, A4_H_MM), left: pct(left, A4_W_MM), right: pct(right, A4_W_MM) }} />
      {/* Ligne de la marge haute */}
      <div className="absolute inset-x-0 border-t-2 border-rose-500" style={{ top: pct(top, A4_H_MM) }}>
        <span className="absolute right-0.5 -top-3.5 text-[8px] font-semibold text-rose-600 bg-white/80 px-0.5">{top} mm</span>
      </div>
      {/* Ligne de la marge basse */}
      <div className="absolute inset-x-0 border-b-2 border-rose-500" style={{ bottom: pct(bottom, A4_H_MM) }}>
        <span className="absolute right-0.5 top-0.5 text-[8px] font-semibold text-rose-600 bg-white/80 px-0.5">{bottom} mm</span>
      </div>
    </div>
  );
}

// Champs des quatre marges du type « page entière » (en millimètres)
function MarginFields({ value, onChange, disabled }) {
  const fields = [["page_top_mm", "Haut"], ["page_bottom_mm", "Bas"], ["page_left_mm", "Gauche"], ["page_right_mm", "Droite"]];
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {fields.map(([k, l]) => (
        <label key={k} className="block"><span className={ui.label}>{l} (mm)</span>
          <input type="number" step="0.5" min="5" value={value[k] ?? ""} disabled={disabled}
            onChange={(e) => onChange({ ...value, [k]: e.target.value })} className={ui.inputSm} data-testid={`letterhead-${k}`} /></label>
      ))}
    </div>
  );
}

// Les quatre marges d'un papier (valeurs renvoyées par le serveur)
const marginsOf = (lh) => ({ page_top_mm: lh.page_top_mm ?? 35, page_bottom_mm: lh.page_bottom_mm ?? 30,
  page_left_mm: lh.page_left_mm ?? 20, page_right_mm: lh.page_right_mm ?? 20 });

// Appel « Détecter les marges » : image envoyée (FormData) -> type proposé + marges.
// Toast « Patientez… » pendant l'analyse de l'image.
async function detectMargins(fields) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  const wait = toast.loading("Patientez… analyse de l'image");
  try {
    const { data } = await apiClient.post("/admin/letterheads/detect", fd, { headers: { "Content-Type": "multipart/form-data" } });
    return data;
  } finally { toast.dismiss(wait); }
}

// Lot 12 — fiche d'un papier enregistré : type, aperçu, marges
function LetterheadCard({ lh, stamp, canWrite, update, remove, fileBtn }) {
  const headerSrc = useLetterheadSrc(lh.id, "header", stamp);
  const [margins, setMargins] = useState(marginsOf(lh));
  const [detecting, setDetecting] = useState(false);
  const [message, setMessage] = useState("");
  // Marges remises à jour quand le serveur renvoie la fiche modifiée
  useEffect(() => { setMargins(marginsOf(lh)); }, [lh]);
  const isPage = lh.mode === "page";

  // Bouton « Détecter les marges » : propose des marges (non enregistrées)
  const detect = async () => {
    setDetecting(true);
    try {
      const d = await detectMargins({ letterhead_id: lh.id });
      setMargins((m) => ({ ...m, page_top_mm: d.top_mm, page_bottom_mm: d.bottom_mm }));
      setMessage([d.message, ...(d.warnings || [])].join(" "));
    } catch (e) { toast.error(extractError(e)); } finally { setDetecting(false); }
  };

  return (
    <div className={cx(ui.card, "space-y-2")} data-testid={`letterhead-${lh.id}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="font-display font-bold">{lh.name}</p>
        {lh.is_default ? <span className={ui.badge.green}><Star className="h-3 w-3" /> Par défaut</span>
          : canWrite && <button type="button" onClick={() => update(lh, { is_default: "true" })} className={ui.btnTool}>Mettre par défaut</button>}
      </div>
      {/* Type de papier (lot 12) */}
      {lh.has_header && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid={`letterhead-mode-${lh.id}`}>
          {MODES.map(([m, l]) => (
            <button key={m} type="button" disabled={!canWrite} onClick={() => !(lh.mode === m && !lh.mode_auto) && update(lh, { mode: m })}
              className={ui.chip(lh.mode === m)}>{l}</button>
          ))}
          {lh.mode_auto && <span className={ui.badge.amber} title="Type déduit de l'image, pas encore enregistré">proposé automatiquement</span>}
        </div>
      )}
      {isPage ? (
        <div className="flex flex-col sm:flex-row gap-3">
          <PagePreview src={headerSrc} top={margins.page_top_mm} bottom={margins.page_bottom_mm} left={margins.page_left_mm} right={margins.page_right_mm} />
          <div className="flex-1 space-y-2">
            <p className="text-xs text-slate-500">L'image est posée en fond de chaque page, sans réduction. Le texte s'écrit dans la zone grisée, entre la marge haute et la marge basse.</p>
            <MarginFields value={margins} onChange={setMargins} disabled={!canWrite} />
            {message && <p className="text-[11px] text-sky-700" data-testid="letterhead-detect-message">{message}</p>}
            {canWrite && (
              <div className="flex flex-wrap gap-1.5">
                <button type="button" onClick={detect} disabled={detecting} className={ui.act.indigo} data-testid="letterhead-detect">
                  {detecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanLine className="h-3.5 w-3.5" />} Détecter les marges</button>
                <button type="button" onClick={() => update(lh, { mode: "page", ...margins })} className={ui.act.emerald} data-testid="letterhead-save-margins">
                  <Save className="h-3.5 w-3.5" /> Enregistrer les marges</button>
              </div>
            )}
          </div>
        </div>
      ) : (
        <>
          {lh.has_header ? <LetterheadImage id={lh.id} part="header" stamp={stamp} /> : <p className="text-xs text-slate-400 italic">Pas d'image d'en-tête (marge haute : {lh.top_margin_cm} cm)</p>}
          <div className="h-10 rounded border border-dashed border-slate-200 text-[10px] text-slate-300 flex items-center justify-center">contenu du document</div>
          {lh.has_footer ? <LetterheadImage id={lh.id} part="footer" stamp={stamp} /> : <p className="text-xs text-slate-400 italic">Pas d'image de pied de page</p>}
        </>
      )}
      {canWrite && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {fileBtn(lh.has_header ? (isPage ? "Changer l'image A4" : "Changer l'en-tête") : "Ajouter l'en-tête", (f) => update(lh, { header: f }))}
          {!isPage && fileBtn(lh.has_footer ? "Changer le pied" : "Ajouter le pied", (f) => update(lh, { footer: f }))}
          {lh.has_header && <button type="button" onClick={() => update(lh, { remove_header: "true" })} className={ui.btnTool}>{isPage ? "Retirer l'image" : "Retirer l'en-tête"}</button>}
          {lh.has_footer && <button type="button" onClick={() => update(lh, { remove_footer: "true" })} className={ui.btnTool}>Retirer le pied</button>}
          <button type="button" onClick={() => remove(lh)} className={ui.act.iconDanger} title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </div>
  );
}

export default function DocSettingsPanel() {
  const { user } = useAuth();
  const canWrite = (user?.roles || []).some((r) => WRITERS.includes(r));
  const [list, setList] = useState(null);
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  // Formulaire « Nouveau papier » (lot 12 : type, marges et résultat de la détection)
  const EMPTY_FORM = { name: "", top_margin_cm: 4.8, header: null, footer: null, mode: "bandes",
    page_top_mm: 35, page_bottom_mm: 30, page_left_mm: 20, page_right_mm: 20, detection: null };
  const [form, setForm] = useState(EMPTY_FORM);
  const [stamp, setStamp] = useState(0);   // force le rechargement des aperçus
  const [headerUrl, setHeaderUrl] = useState(null);   // aperçu local de l'image choisie

  // Aperçu local de l'image d'en-tête choisie (libéré quand elle change)
  useEffect(() => {
    if (!form.header) { setHeaderUrl(null); return undefined; }
    const url = URL.createObjectURL(form.header);
    setHeaderUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [form.header]);

  // Lot 12 : image d'en-tête choisie -> détection du type et des marges
  const pickHeader = async (f) => {
    setForm((x) => ({ ...x, header: f, detection: null }));
    try {
      const d = await detectMargins({ header: f });
      setForm((x) => ({ ...x, detection: d, mode: x.footer ? "bandes" : d.suggested_mode,
        page_top_mm: d.top_mm, page_bottom_mm: d.bottom_mm }));
    } catch (e) { toast.error(extractError(e)); }
  };

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
    // Lot 12 : type de papier ; en « page entière », marges et pas d'image de pied
    fd.append("mode", form.mode);
    if (form.mode === "page") {
      ["page_top_mm", "page_bottom_mm", "page_left_mm", "page_right_mm"].forEach((k) => fd.append(k, String(form[k])));
    } else if (form.footer) fd.append("footer", form.footer);
    try {
      await apiClient.post("/admin/letterheads", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Papier à en-tête ajouté");
      setForm(EMPTY_FORM);
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
        withholding_rate_ifu: Number(settings.withholding_rate_ifu ?? 5) || 0, withholding_rate_no_ifu: Number(settings.withholding_rate_no_ifu ?? 10) || 0,
        withholding_label: (settings.withholding_label || "").trim() || "retenue",
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
        <p className="text-xs text-slate-500">Deux types : « En-tête + pied séparés » (image d'en-tête en haut, image de pied de page en bas, sur toute la largeur) ou « Page entière (fond A4) » (une page A4 complète posée en fond de chaque page, le texte s'écrivant entre deux marges). Sans image : papier préimprimé, la marge haute reste vide.</p>
        {list === null ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline" /></p> : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {list.length === 0 && <p className={ui.empty}>Aucun papier à en-tête : les documents sortent sans en-tête.</p>}
            {list.map((lh) => (
              <LetterheadCard key={lh.id} lh={lh} stamp={stamp} canWrite={canWrite} update={update} remove={remove} fileBtn={fileBtn} />
            ))}
          </div>
        )}
        {canWrite && (
          <div className="flex flex-wrap items-end gap-3 border-t border-slate-100 pt-3">
            <label className="block"><span className={ui.label}>Nouveau papier</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={ui.inputInline} placeholder="ex. GESPHARM" data-testid="letterhead-name" /></label>
            <label className="block"><span className={ui.label}>Marge haute sans image (cm)</span><input type="number" step="0.1" value={form.top_margin_cm} onChange={(e) => setForm({ ...form, top_margin_cm: e.target.value })} className={cx(ui.inputInline, "w-24")} /></label>
            {fileBtn(form.header ? `En-tête : ${form.header.name}` : "Image d'en-tête", pickHeader, "letterhead-header-file")}
            {form.mode !== "page" && fileBtn(form.footer ? `Pied : ${form.footer.name}` : "Image de pied de page", (f) => setForm((x) => ({ ...x, footer: f, mode: "bandes" })), "letterhead-footer-file")}
            <button type="button" onClick={create} className={ui.btnPrimary} data-testid="letterhead-create"><Plus className="h-4 w-4" /> Ajouter</button>
          </div>
        )}
        {/* Lot 12 : type du nouveau papier, proposé d'après l'image chargée */}
        {canWrite && form.header && (
          <div className="space-y-2" data-testid="letterhead-new-mode">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={ui.label}>Type du papier</span>
              {MODES.map(([m, l]) => (
                <button key={m} type="button" onClick={() => setForm((x) => ({ ...x, mode: m, footer: m === "page" ? null : x.footer }))}
                  className={ui.chip(form.mode === m)}>{l}</button>
              ))}
            </div>
            {form.detection && <p className="text-[11px] text-sky-700" data-testid="letterhead-new-detect-message">{[form.detection.message, ...(form.detection.warnings || [])].join(" ")}</p>}
            {form.mode === "page" && (
              <div className="flex flex-col sm:flex-row gap-3">
                <PagePreview src={headerUrl} top={form.page_top_mm} bottom={form.page_bottom_mm} left={form.page_left_mm} right={form.page_right_mm} />
                <div className="flex-1 space-y-2">
                  <MarginFields value={form} onChange={(v) => setForm((x) => ({ ...x, ...v }))} />
                  <button type="button" onClick={() => pickHeader(form.header)} className={ui.act.indigo}><ScanLine className="h-3.5 w-3.5" /> Détecter les marges</button>
                </div>
              </div>
            )}
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
            {/* Lot 8 — retenue à la source : taux selon le prestataire et libellé imprimé */}
            <label className="block"><span className={ui.label}>Retenue — prestataire avec IFU (%)</span>
              <input type="number" value={settings.withholding_rate_ifu ?? 5} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, withholding_rate_ifu: e.target.value })} className={ui.input} data-testid="doc-setting-withholding-ifu" /></label>
            <label className="block"><span className={ui.label}>Retenue — prestataire sans IFU (%)</span>
              <input type="number" value={settings.withholding_rate_no_ifu ?? 10} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, withholding_rate_no_ifu: e.target.value })} className={ui.input} data-testid="doc-setting-withholding-no-ifu" /></label>
            <label className="block"><span className={ui.label}>Libellé de la retenue</span>
              <input value={settings.withholding_label ?? "retenue"} disabled={!canWrite} onChange={(e) => setSettings({ ...settings, withholding_label: e.target.value })} className={ui.input} data-testid="doc-setting-withholding-label" /></label>
          </div>
          <p className="text-[11px] text-slate-400">La signature manuscrite du DG (Paramètres → Branding) est ajoutée sur les factures si l'option « signature du DG » est activée.</p>
          {canWrite && <div className="flex justify-end"><button type="button" onClick={saveSettings} disabled={saving} className={ui.btnPrimary} data-testid="doc-settings-save">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer</button></div>}
        </div>
      )}
    </div>
  );
}
