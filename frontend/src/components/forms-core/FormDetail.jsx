/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormDetail : page d'un formulaire, en 4 onglets —
    Constructeur · Envoi & suivi · Réponses · Statistiques
  L'onglet actif est dans l'adresse (?tab=send|responses|stats) : les boutons
  de la bibliothèque ouvrent directement le bon onglet.

  Props : apiBase ("/forms"), basePath ("/admin/forms"), formId, publicPath ("/f"), color
*/
import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, PenLine, Send, Inbox, BarChart3, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import FormBuilder from "./FormBuilder";
import FormSendPanel from "./FormSendPanel";
import FormResponses from "./FormResponses";
import FormStats from "./FormStats";
import { errorText } from "./fieldTypes";
import { ui, cx } from "./ui";

const TABS = [["build", "Constructeur", PenLine], ["send", "Envoi & suivi", Send], ["responses", "Réponses", Inbox], ["stats", "Statistiques", BarChart3]];

export default function FormDetail({ apiBase = "/forms", basePath = "/admin/forms", formId, publicPath = "/f", color = "#0F6B4A" }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "build";
  const [form, setForm] = useState(null);
  const [categories, setCategories] = useState([]);
  const [saving, setSaving] = useState(false);

  const load = () => apiClient.get(`${apiBase}/${formId}`).then((r) => setForm(r.data)).catch((e) => { toast.error(errorText(e)); navigate(basePath); });
  useEffect(() => {
    load();
    apiClient.get(`${apiBase}/categories`).then((r) => setCategories(r.data.items || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formId]);

  const save = async (patch) => {
    setSaving(true);
    try { const r = await apiClient.put(`${apiBase}/${formId}`, patch); setForm(r.data); toast.success("Formulaire enregistré."); }
    catch (e) { toast.error(errorText(e)); throw e; } finally { setSaving(false); }
  };

  if (!form) return <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p>;
  return (
    <div className="space-y-5" data-testid="form-detail">
      {/* Retour, numéro, titre et état du formulaire */}
      <div className="space-y-1">
        <button type="button" onClick={() => navigate(basePath)} className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" /> Bibliothèque de formulaires</button>
        <div className="flex flex-wrap items-center gap-2">
          <code className={cx(ui.code, "text-[11px] px-2")}>{form.number}</code>
          <h1 className={cx(ui.h1, "truncate")}>{form.title}</h1>
          {form.archived_at && <span className={ui.badge.grey}>Archivé</span>}
          {form.closed_reason && !form.archived_at && <span className={ui.badge.amber}>Clos</span>}
          {!form.closed_reason && !form.archived_at && <span className={ui.badge.green}>Ouvert</span>}
        </div>
      </div>
      {/* Onglets soulignés */}
      <div className={ui.tabs}>
        {TABS.map(([k, l, I]) => (
          <button key={k} type="button" onClick={() => setParams(k === "build" ? {} : { tab: k })} data-testid={`form-tab-${k}`} className={ui.tab(tab === k)}>
            <I className="h-4 w-4" /> {l}{k === "responses" ? ` (${form.submissions_count || 0})` : ""}
          </button>
        ))}
      </div>
      {tab === "build" && <FormBuilder form={form} categories={categories} onSave={save} saving={saving} />}
      {tab === "send" && <FormSendPanel apiBase={apiBase} form={form} onChanged={load} publicPath={publicPath} />}
      {tab === "responses" && <FormResponses apiBase={apiBase} form={form} />}
      {tab === "stats" && <FormStats apiBase={apiBase} form={form} color={color} />}
    </div>
  );
}
