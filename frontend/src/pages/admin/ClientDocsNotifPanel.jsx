/*
  Paramètres → Notifications → « Documents mis à disposition des clients ».
  Règle le message WhatsApp envoyé au client quand le cabinet dépose ou met
  à disposition un document dans son espace :
    - un texte par catégorie (facture, reçu, rapport…) + un texte par défaut,
      avec variables {client} {liste} {lien}… et aperçu ;
    - le modèle Meta approuvé à utiliser hors fenêtre de 24 h (nom, langue,
      variables envoyées pour {{1}}, {{2}}…) ;
    - le repli e-mail si WhatsApp est impossible.
  Props : settings, setSettings, save(partial), saving (état de AdminSettings)
*/
import React, { useEffect, useState } from "react";
import { Save, RotateCcw } from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export default function ClientDocsNotifPanel({ settings, setSettings, save, saving }) {
  const [catalog, setCatalog] = useState(null);
  const [key, setKey] = useState("default"); // texte en cours d'édition
  const [preview, setPreview] = useState("");

  useEffect(() => { apiClient.get("/client-space/catalog").then(({ data }) => setCatalog(data)).catch(() => {}); }, []);

  const templates = settings.client_docs_templates || {};
  const defaults = catalog?.default_templates || {};
  // Texte affiché : celui réglé, sinon le texte fourni d'origine (catégorie puis défaut)
  const current = templates[key] ?? defaults[key] ?? defaults.default ?? "";
  const setCurrent = (v) => setSettings({ ...settings, client_docs_templates: { ...templates, [key]: v } });
  const resetCurrent = () => { const t = { ...templates }; delete t[key]; setSettings({ ...settings, client_docs_templates: t }); };
  const labelOf = (k) => (k === "default" ? "Par défaut (plusieurs catégories)" : catalog?.categories.find((c) => c.key === k)?.label || k);

  // Aperçu avec des valeurs d'exemple, recalculé à chaque frappe (léger délai)
  useEffect(() => {
    if (!catalog) return undefined;
    const t = setTimeout(() => {
      apiClient.post("/client-space/preview", { category: key === "default" ? "facture" : key, template: current })
        .then(({ data }) => setPreview(data.text)).catch(() => setPreview(""));
    }, 300);
    return () => clearTimeout(t);
  }, [catalog, key, current]);

  const insertVar = (v) => setCurrent(`${current}{${v}}`);

  if (!catalog) return null;
  return (
    <div className="albarka-card p-6 space-y-5 max-w-3xl mt-6" data-testid="client-docs-notif-panel">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold">Documents mis à disposition des clients</div>
          <div className="text-sm text-muted-foreground">Message WhatsApp envoyé au client quand le cabinet dépose une facture, un rapport… dans son espace.</div>
        </div>
        <Switch checked={settings.client_docs_notify_enabled !== false} onCheckedChange={(v) => setSettings({ ...settings, client_docs_notify_enabled: v })} data-testid="cd-notify-switch" />
      </div>

      {/* Texte par catégorie */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Texte pour</Label>
          <select value={key} onChange={(e) => setKey(e.target.value)} className="w-full h-10 rounded-md border px-2 text-sm bg-white" data-testid="cd-template-key">
            {catalog.template_keys.map((k) => <option key={k} value={k}>{labelOf(k)}{templates[k] ? " — personnalisé" : ""}</option>)}
          </select>
          <textarea rows={9} value={current} onChange={(e) => setCurrent(e.target.value)} className="w-full rounded-md border p-2 text-sm font-mono" data-testid="cd-template-text" />
          <div className="flex flex-wrap gap-1">
            {catalog.variables.map((v) => (
              <button key={v.key} type="button" title={v.label} onClick={() => insertVar(v.key)} className="text-[11px] px-1.5 py-0.5 rounded border bg-slate-50 hover:bg-slate-100 font-mono">{`{${v.key}}`}</button>
            ))}
          </div>
          {templates[key] !== undefined && (
            <Button type="button" variant="ghost" size="sm" onClick={resetCurrent}><RotateCcw className="w-3.5 h-3.5 mr-1" /> Revenir au texte d'origine</Button>
          )}
        </div>
        <div className="space-y-2">
          <Label>Aperçu (valeurs d'exemple)</Label>
          <div className="rounded-lg bg-[#E7F8E1] border border-[#cbe8c0] p-3 text-sm whitespace-pre-wrap min-h-[200px]" data-testid="cd-template-preview">{preview}</div>
        </div>
      </div>

      {/* Modèle Meta hors fenêtre de 24 h */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <div className="font-medium">Modèle WhatsApp approuvé (hors fenêtre de 24 h)</div>
          <div className="text-xs text-muted-foreground">
            WhatsApp n'accepte un message libre que si le client vous a écrit dans les dernières 24 h. Sinon, seul un modèle
            approuvé dans votre compte Meta est remis. Laissez vide si vous n'en avez pas : l'e-mail prendra le relais.
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div><Label className="text-xs">Nom du modèle Meta</Label><Input value={settings.client_docs_wa_template_name || ""} onChange={(e) => setSettings({ ...settings, client_docs_wa_template_name: e.target.value })} placeholder="ex. nouveau_document" data-testid="cd-meta-name" /></div>
          <div><Label className="text-xs">Langue</Label><Input value={settings.client_docs_wa_template_lang || "fr"} onChange={(e) => setSettings({ ...settings, client_docs_wa_template_lang: e.target.value })} placeholder="fr" /></div>
          <div><Label className="text-xs">Variables {"{{1}}, {{2}}…"} dans l'ordre</Label><Input value={settings.client_docs_wa_template_params || ""} onChange={(e) => setSettings({ ...settings, client_docs_wa_template_params: e.target.value })} placeholder="client,nombre,lien" data-testid="cd-meta-params" /></div>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">Notification push sur les appareils du client</div>
          <div className="text-sm text-muted-foreground">En plus de WhatsApp, si le client a activé les notifications (page « Factures & documents »). iPhone : portail ajouté à l'écran d'accueil.</div>
        </div>
        <Switch checked={settings.client_docs_push_enabled !== false} onCheckedChange={(v) => setSettings({ ...settings, client_docs_push_enabled: v })} data-testid="cd-push-switch" />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">Prévenir par e-mail si WhatsApp est impossible</div>
          <div className="text-sm text-muted-foreground">Pas de numéro WhatsApp, hors fenêtre de 24 h sans modèle, ou échec d'envoi.</div>
        </div>
        <Switch checked={settings.client_docs_email_fallback !== false} onCheckedChange={(v) => setSettings({ ...settings, client_docs_email_fallback: v })} />
      </div>

      <Button onClick={() => save({
        client_docs_notify_enabled: settings.client_docs_notify_enabled !== false,
        client_docs_templates: settings.client_docs_templates || {},
        client_docs_wa_template_name: settings.client_docs_wa_template_name || "",
        client_docs_wa_template_lang: settings.client_docs_wa_template_lang || "fr",
        client_docs_wa_template_params: settings.client_docs_wa_template_params || "",
        client_docs_email_fallback: settings.client_docs_email_fallback !== false,
        client_docs_push_enabled: settings.client_docs_push_enabled !== false,
      })} disabled={saving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="save-client-docs-notif">
        <Save className="w-4 h-4 mr-2" /> Enregistrer
      </Button>
    </div>
  );
}
