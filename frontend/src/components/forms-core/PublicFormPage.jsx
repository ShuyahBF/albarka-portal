/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  PublicFormPage : page de remplissage ouverte par un lien (invitation
  personnelle d'un client, ou lien public pour un non-client). Aucune
  connexion n'est nécessaire.
    - invitation : le nom du client est connu, rien ne lui est demandé ; s'il
      a déjà répondu, message (ou modification si le formulaire l'autorise) ;
    - lien public : nom et e-mail demandés selon les réglages ;
    - fichiers et signature envoyés au fil de l'eau ; erreurs du serveur
      affichées sous chaque question ; champ piège anti-robots invisible.

  Props : publicApiBase ("/public/forms"), token, brand { name, logoUrl }
*/
import React, { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Lock } from "lucide-react";
import { apiClient } from "@/lib/api";
import FormRenderer from "./FormRenderer";
import { errorText } from "./fieldTypes";
import { ui, cx } from "./ui";

export default function PublicFormPage({ publicApiBase = "/public/forms", token, brand = {} }) {
  const [ctx, setCtx] = useState(null);
  const [failure, setFailure] = useState(null);
  const [data, setData] = useState({});
  const [errors, setErrors] = useState({});
  const [respondent, setRespondent] = useState({ name: "", email: "" });
  const [hp, setHp] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const [globalError, setGlobalError] = useState(null);

  useEffect(() => {
    apiClient.get(`${publicApiBase}/${token}`)
      .then((r) => { setCtx(r.data); if (r.data.previous_data) setData(r.data.previous_data); })
      .catch((e) => setFailure(errorText(e, "Ce lien n'est pas valide.")));
  }, [publicApiBase, token]);

  const upload = async (fieldId, file, name) => {
    const fd = new FormData();
    fd.append("field_id", fieldId);
    fd.append("file", file, name || file.name || "fichier");
    try {
      const r = await apiClient.post(`${publicApiBase}/${token}/upload`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setErrors((e) => ({ ...e, [fieldId]: undefined }));
      return r.data;
    } catch (e) {
      setErrors((x) => ({ ...x, [fieldId]: errorText(e, "Envoi du fichier impossible.") }));
      throw e;
    }
  };

  const submit = async () => {
    setSubmitting(true); setGlobalError(null);
    try {
      const r = await apiClient.post(`${publicApiBase}/${token}/submit`, { data, respondent_name: respondent.name, respondent_email: respondent.email, website: hp });
      setDone(r.data.message || "Merci, votre réponse a bien été enregistrée.");
      window.scrollTo?.({ top: 0 });
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d && typeof d === "object" && d.errors) { setErrors(d.errors); setGlobalError(d.message); }
      else setGlobalError(errorText(e));
    } finally { setSubmitting(false); }
  };

  const shell = (children) => (
    <div className="min-h-screen bg-slate-50 py-8 px-4" data-testid="public-form-page">
      <div className="max-w-2xl mx-auto">
        {(brand.logoUrl || brand.name) && (
          <div className="flex items-center gap-2 mb-4">
            {brand.logoUrl && <img src={brand.logoUrl} alt="" className="h-9 w-auto" />}
            {brand.name && <span className="font-display font-bold text-slate-800">{brand.name}</span>}
          </div>
        )}
        <div className="rounded-2xl bg-white shadow-xl shadow-slate-200/60 ring-1 ring-slate-200 p-6 md:p-8">{children}</div>
        <p className="text-center text-[11px] text-slate-400 mt-4 inline-flex items-center gap-1 w-full justify-center"><Lock className="h-3 w-3" /> Vos réponses sont transmises de façon sécurisée{brand.name ? ` à ${brand.name}` : ""}.</p>
      </div>
    </div>
  );

  if (failure) return shell(<p className="text-center text-slate-600 py-8" data-testid="public-form-invalid">{failure}</p>);
  if (!ctx) return shell(<p className="text-center text-slate-500 py-8 inline-flex items-center gap-2 w-full justify-center"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p>);
  const { form } = ctx;
  if (done) return shell(
    <div className="text-center py-8" data-testid="public-form-done">
      <CheckCircle2 className="h-12 w-12 text-emerald-600 mx-auto mb-3" />
      <h1 className="text-xl font-display font-bold mb-2">{form.title}</h1>
      <p className="text-slate-700 whitespace-pre-line">{done}</p>
    </div>
  );
  if (ctx.closed_reason) return shell(<div className="text-center py-8"><h1 className="text-xl font-display font-bold mb-2">{form.title}</h1><p className="text-slate-600">{ctx.closed_reason}</p></div>);
  if (ctx.already_answered && !ctx.can_edit) return shell(
    <div className="text-center py-8"><CheckCircle2 className="h-12 w-12 text-emerald-600 mx-auto mb-3" /><h1 className="text-xl font-display font-bold mb-2">{form.title}</h1>
      <p className="text-slate-600">Vous avez déjà répondu à ce formulaire. Merci !</p></div>
  );

  const askIdentity = ctx.source === "public" && form.settings?.respondent_info !== "none";
  const required = form.settings?.respondent_info === "required";
  const header = (
    <>
      {ctx.recipient?.name && <p className="text-sm text-slate-600">Bonjour <strong>{ctx.recipient.name}</strong>{ctx.already_answered ? " — vous pouvez modifier votre réponse." : ","}</p>}
      {askIdentity && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 rounded-xl bg-slate-50 ring-1 ring-slate-200 p-4">
          <label className="block"><span className={ui.label}>Votre nom{required && <span className="text-rose-600"> *</span>}</span>
            <input value={respondent.name} onChange={(e) => setRespondent({ ...respondent, name: e.target.value })} className={ui.input} data-testid="respondent-name" />
            {errors._respondent_name && <span className={ui.error}>{errors._respondent_name}</span>}</label>
          <label className="block"><span className={ui.label}>Votre e-mail{required && <span className="text-rose-600"> *</span>}</span>
            <input type="email" value={respondent.email} onChange={(e) => setRespondent({ ...respondent, email: e.target.value })} className={ui.input} data-testid="respondent-email" />
            {errors._respondent_email && <span className={ui.error}>{errors._respondent_email}</span>}</label>
        </div>
      )}
      {/* Champ piège : invisible pour un humain, rempli par les robots */}
      <input type="text" name="website" value={hp} onChange={(e) => setHp(e.target.value)} tabIndex={-1} autoComplete="off" aria-hidden="true" className="absolute left-[-9999px] h-0 w-0 opacity-0" />
    </>
  );

  return shell(
    <>
      <p className={ui.eyebrow}>Formulaire</p>
      <h1 className="text-2xl font-display font-bold text-slate-900">{form.title}</h1>
      {form.description && <p className="text-sm text-slate-600 mt-1 mb-4 whitespace-pre-line">{form.description}</p>}
      {globalError && <p className="rounded-xl bg-rose-50 ring-1 ring-rose-200 text-rose-800 text-sm px-4 py-2.5 mb-3" data-testid="public-form-error">{globalError}</p>}
      <div className="mt-4">
        <FormRenderer form={form} value={data} onChange={setData} errors={errors} uploadFile={upload} onSubmit={submit} submitting={submitting}
          submitLabel={ctx.already_answered ? "Mettre à jour ma réponse" : "Envoyer mes réponses"} header={header} />
      </div>
    </>
  );
}
