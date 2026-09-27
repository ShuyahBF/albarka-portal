/*
  PaieSettings — lot 8 : onglet « Paramètres de paie ».

  1. MODÈLES DE CONFIGURATION (indépendants du cabinet et des clients) :
     nouveau, dupliquer, supprimer, « par défaut » ; édition des paramètres puis
     « Appliquer » ; « Restaurer les valeurs par défaut » (Burkina Faso).
  2. EMPLOYEURS : le cabinet (son personnel) et chaque client.
     - choix du modèle ;
     - « Personnaliser pour cet employeur » : copie modifiable des paramètres,
       « Appliquer », puis « Restaurer les valeurs du modèle » pour revenir au modèle ;
     - en-tête du bulletin : raison sociale, adresse, téléphone, n° CNSS employeur.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { Plus, Copy, Trash2, Star, RotateCcw, Check, Settings2, Building2 } from "lucide-react";
import PaieParamsEditor from "@/components/paie/PaieParamsEditor";
import { EmployerSelect, useEmployers, GREEN } from "@/components/paie/paieCommon";

const btn = "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-50";
const primary = `${btn} text-white hover:opacity-90`;
const outline = `${btn} border border-slate-300 bg-white hover:bg-slate-50`;

function Templates({ onChanged }) {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);         // modèle en cours d'édition
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = async (keepId) => {
    const { data } = await apiClient.get("/hr/paie/modeles");
    setItems(data.items || []);
    const pick = (data.items || []).find((t) => t.id === (keepId || sel?.id)) || data.items?.[0];
    if (pick) { setSel(JSON.parse(JSON.stringify(pick))); setDirty(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load().catch((e) => toast.error(extractError(e))); }, []);

  const open = (t) => {
    if (dirty && !window.confirm("Abandonner les modifications non appliquées ?")) return;
    setSel(JSON.parse(JSON.stringify(t))); setDirty(false);
  };
  const apply = async () => {
    setBusy(true);
    try {
      const { data } = await apiClient.put(`/hr/paie/modeles/${sel.id}`, { name: sel.name, description: sel.description || "", params: sel.params });
      toast.success("Modèle appliqué : pris en compte pour les prochains calculs");
      await load(data.id); onChanged?.();
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };
  const restore = async () => {
    if (!window.confirm(`Remettre les valeurs par défaut dans « ${sel.name} » ?`)) return;
    try { await apiClient.post(`/hr/paie/modeles/${sel.id}/restore-defaults`); toast.success("Valeurs par défaut restaurées"); await load(sel.id); onChanged?.(); }
    catch (e) { toast.error(extractError(e)); }
  };
  const create = async () => {
    const name = window.prompt("Nom du nouveau modèle (il part des valeurs par défaut) :");
    if (!name?.trim()) return;
    try { const { data } = await apiClient.post("/hr/paie/modeles", { name: name.trim() }); toast.success("Modèle créé"); await load(data.id); onChanged?.(); }
    catch (e) { toast.error(extractError(e)); }
  };
  const duplicate = async (t) => {
    try { const { data } = await apiClient.post(`/hr/paie/modeles/${t.id}/duplicate`); await load(data.id); onChanged?.(); }
    catch (e) { toast.error(extractError(e)); }
  };
  const remove = async (t) => {
    if (!window.confirm(`Supprimer le modèle « ${t.name} » ?`)) return;
    try { await apiClient.delete(`/hr/paie/modeles/${t.id}`); toast.success("Modèle supprimé"); setSel(null); await load(); onChanged?.(); }
    catch (e) { toast.error(extractError(e)); }
  };
  const makeDefault = async (t) => {
    try { await apiClient.post(`/hr/paie/modeles/${t.id}/set-default`); await load(sel?.id); onChanged?.(); } catch (e) { toast.error(extractError(e)); }
  };

  return (
    <div className="space-y-3" data-testid="paie-templates">
      <div className="flex flex-wrap items-center gap-2">
        {items.map((t) => (
          <button key={t.id} type="button" onClick={() => open(t)} data-testid={`tpl-${t.id}`}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm ring-1 ${sel?.id === t.id ? "text-white ring-transparent" : "bg-white ring-slate-200 hover:ring-slate-300"}`}
            style={sel?.id === t.id ? { background: GREEN } : {}}>
            {t.is_default && <Star className="h-3.5 w-3.5 fill-current" />} {t.name}
            <span className="text-[11px] opacity-75">· {t.employers_count} employeur(s)</span>
          </button>
        ))}
        <button type="button" onClick={create} className={outline} data-testid="tpl-new"><Plus className="h-4 w-4" /> Nouveau modèle</button>
      </div>
      {sel && (
        <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-slate-600">Nom du modèle
              <input value={sel.name} onChange={(e) => { setSel({ ...sel, name: e.target.value }); setDirty(true); }} className="mt-1 block h-9 w-72 rounded border border-slate-300 px-2 text-sm" data-testid="tpl-name" /></label>
            <label className="text-xs text-slate-600 flex-1 min-w-[16rem]">Description
              <input value={sel.description || ""} onChange={(e) => { setSel({ ...sel, description: e.target.value }); setDirty(true); }} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" /></label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={apply} disabled={busy} className={primary} style={{ background: GREEN }} data-testid="tpl-apply"><Check className="h-4 w-4" /> Appliquer</button>
            <button type="button" onClick={restore} className={outline} data-testid="tpl-restore"><RotateCcw className="h-4 w-4" /> Restaurer les valeurs par défaut</button>
            <button type="button" onClick={() => duplicate(sel)} className={outline}><Copy className="h-4 w-4" /> Dupliquer</button>
            {!sel.is_default && <button type="button" onClick={() => makeDefault(sel)} className={outline}><Star className="h-4 w-4" /> Modèle par défaut</button>}
            {!sel.is_default && <button type="button" onClick={() => remove(sel)} className={`${outline} text-rose-600`}><Trash2 className="h-4 w-4" /> Supprimer</button>}
            {dirty && <span className="self-center text-xs text-amber-700">Modifications non appliquées</span>}
          </div>
          <PaieParamsEditor value={sel.params} onChange={(params) => { setSel({ ...sel, params }); setDirty(true); }} />
        </div>
      )}
    </div>
  );
}

function Employers({ reloadKey }) {
  const employers = useEmployers(reloadKey);
  const [templates, setTemplates] = useState([]);
  const [eid, setEid] = useState("");
  const [cfg, setCfg] = useState(null);
  const [custom, setCustom] = useState(null);     // paramètres personnalisés en cours d'édition
  const [busy, setBusy] = useState(false);

  useEffect(() => { apiClient.get("/hr/paie/modeles").then(({ data }) => setTemplates(data.items || [])).catch(() => {}); }, [reloadKey]);
  useEffect(() => {
    if (!eid) { setCfg(null); return; }
    apiClient.get(`/hr/paie/employeurs/${eid}`).then(({ data }) => { setCfg(data); setCustom(data.customized ? data.custom_params : null); })
      .catch((e) => toast.error(extractError(e)));
  }, [eid]);

  const save = async (customParams = custom) => {
    setBusy(true);
    try {
      const { data } = await apiClient.put(`/hr/paie/employeurs/${eid}`, {
        // null = suit le « modèle par défaut » (s'il change, l'employeur suit)
        template_id: cfg.chosen_template_id || null, custom_params: customParams, display_name: cfg.display_name || "",
        address: cfg.address || "", phone: cfg.phone || "", cnss_number: cfg.cnss_number || "" });
      setCfg(data); setCustom(data.customized ? data.custom_params : null);
      toast.success("Configuration de l'employeur appliquée");
    } catch (e) { toast.error(extractError(e)); } finally { setBusy(false); }
  };
  const restoreTemplate = async () => {
    if (!window.confirm("Abandonner la personnalisation et revenir aux valeurs du modèle ?")) return;
    try { const { data } = await apiClient.post(`/hr/paie/employeurs/${eid}/restore-template`); setCfg(data); setCustom(null); toast.success("Valeurs du modèle restaurées"); }
    catch (e) { toast.error(extractError(e)); }
  };

  return (
    <div className="space-y-3" data-testid="paie-employers">
      <div className="flex flex-wrap items-center gap-3">
        <EmployerSelect value={eid} onChange={setEid} employers={employers} testId="paie-settings-employer" />
        {cfg && <span className="text-sm text-slate-600">Modèle : <b>{cfg.template_name}</b>{cfg.customized && <span className="ml-1 rounded bg-amber-100 px-1.5 text-xs text-amber-800">personnalisé</span>}</span>}
      </div>
      {cfg && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 space-y-3">
          <div className="grid md:grid-cols-5 gap-3 text-xs text-slate-600">
            <label>Modèle de configuration
              <select value={cfg.chosen_template_id || ""} onChange={(e) => setCfg({ ...cfg, chosen_template_id: e.target.value })} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" data-testid="employer-template">
                {/* Option vide : l'employeur suit toujours le modèle par défaut */}
                <option value="">Modèle par défaut{templates.find((t) => t.is_default) ? ` (${templates.find((t) => t.is_default).name})` : ""}</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
            <label>Raison sociale (bulletin)
              <input value={cfg.display_name || ""} placeholder={cfg.default_name} onChange={(e) => setCfg({ ...cfg, display_name: e.target.value })} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" /></label>
            <label>Adresse<input value={cfg.address || ""} onChange={(e) => setCfg({ ...cfg, address: e.target.value })} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" /></label>
            <label>Téléphone<input value={cfg.phone || ""} onChange={(e) => setCfg({ ...cfg, phone: e.target.value })} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" /></label>
            <label>N° CNSS employeur<input value={cfg.cnss_number || ""} onChange={(e) => setCfg({ ...cfg, cnss_number: e.target.value })} className="mt-1 block h-9 w-full rounded border border-slate-300 px-2 text-sm" data-testid="employer-cnss" /></label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => save()} disabled={busy} className={primary} style={{ background: GREEN }} data-testid="employer-apply"><Check className="h-4 w-4" /> Appliquer</button>
            {!custom ? (
              <button type="button" onClick={() => setCustom(JSON.parse(JSON.stringify(cfg.params)))} className={outline} data-testid="employer-customize">
                <Settings2 className="h-4 w-4" /> Personnaliser pour cet employeur</button>
            ) : (
              <button type="button" onClick={restoreTemplate} className={outline} data-testid="employer-restore"><RotateCcw className="h-4 w-4" /> Restaurer les valeurs du modèle</button>
            )}
          </div>
          {custom ? (
            <div className="space-y-2">
              <p className="text-xs text-amber-700">Paramètres propres à cet employeur (le modèle n'est pas modifié). Cliquez sur « Appliquer » pour les prendre en compte.</p>
              <PaieParamsEditor value={custom} onChange={setCustom} />
            </div>
          ) : <p className="text-xs text-slate-500 flex items-center gap-1"><Building2 className="h-3.5 w-3.5" /> Cet employeur utilise les paramètres du modèle « {cfg.template_name} » sans modification.</p>}
        </div>
      )}
    </div>
  );
}

export default function PaieSettings() {
  const [reloadKey, setReloadKey] = useState(0);
  return (
    <div className="space-y-6" data-testid="paie-settings">
      <section className="space-y-2">
        <h3 className="font-display text-lg">Modèles de configuration</h3>
        <p className="text-sm text-muted-foreground">Indépendants du cabinet et des clients. Chaque employeur utilise un modèle, qu'il peut personnaliser.</p>
        <Templates onChanged={() => setReloadKey((k) => k + 1)} />
      </section>
      <section className="space-y-2">
        <h3 className="font-display text-lg">Configuration par employeur</h3>
        <p className="text-sm text-muted-foreground">Le personnel du cabinet et chaque client : modèle utilisé, personnalisation et en-tête des bulletins.</p>
        <Employers reloadKey={reloadKey} />
      </section>
    </div>
  );
}
