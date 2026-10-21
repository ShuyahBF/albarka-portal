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

  Brouillon automatique (lot 28.4, 16/10/2026, demandé par le propriétaire : coupures de courant) : les réponses
  saisies sont gardées sur l'appareil (localStorage, 30 jours) et restaurées à la réouverture du lien ;
  effacées après l'envoi. Rien n'est transmis au serveur avant « Envoyer mes réponses ».
  Modification volontaire d'un module commun : à reporter dans la copie d'origine si elle existe.

  Props : publicApiBase ("/public/forms"), token, brand { name, logoUrl }
*/
import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, Lock } from "lucide-react";
import { apiClient } from "@/lib/api";
import FormRenderer from "./FormRenderer";
import { errorText, texteErreur } from "./fieldTypes";
import { ui, cx } from "./ui";

// Durée de conservation du brouillon sur l'appareil : 30 jours
const DUREE_BROUILLON_MS = 30 * 24 * 3600 * 1000;
const heureCourte = (t) => new Date(t).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

// Lot 65 — identifiants aléatoires : code de reprise de l'appareil (brouillon sur le serveur) et clé d'envoi (évite les doublons)
const aleatoire = () => {
  try { return Array.from(window.crypto.getRandomValues(new Uint8Array(12))).map((b) => b.toString(16).padStart(2, "0")).join(""); }
  catch { return (Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2)).slice(0, 24).padEnd(12, "0"); }
};
const CODE_VALIDE = /^[A-Za-z0-9_-]{8,64}$/;
// Code de reprise : celui du lien (?reprise=…), sinon celui de l'appareil (mémorisé), sinon un code créé pour cette page
const codeReprise = () => {
  try {
    const l = new URLSearchParams(window.location.search).get("reprise");
    if (l && CODE_VALIDE.test(l)) return l;
    let c = window.localStorage.getItem("forms-cle-appareil");
    if (!c || !CODE_VALIDE.test(c)) { c = aleatoire(); window.localStorage.setItem("forms-cle-appareil", c); }
    return c;
  } catch { return aleatoire(); }
};

// Lot 32 (18/10/2026) — filet de sécurité : si l'affichage plante, plus d'écran blanc. Un message en français rappelle que les réponses
// sont gardées sur l'appareil (brouillon), propose de recharger, et l'erreur est signalée au serveur (journal) pour être corrigée.
export class BoiteErreur extends React.Component {
  constructor(props) { super(props); this.state = { erreur: null }; }
  static getDerivedStateFromError(erreur) { return { erreur }; }
  componentDidCatch(erreur, info) {
    try {
      this.props.signaler({ message: String(erreur?.message || erreur).slice(0, 300), pile: String(erreur?.stack || "").slice(0, 1200),
        composants: String(info?.componentStack || "").slice(0, 600), navigateur: String(navigator.userAgent || "").slice(0, 200) });
    } catch { /* un signalement raté ne doit rien casser */ }
  }
  render() {
    if (!this.state.erreur) return this.props.children;
    return (
      <div className="text-center py-8 space-y-3" role="alert" data-testid="public-form-plantage">
        <p className="text-lg font-display font-bold text-slate-900">Un incident d'affichage est survenu</p>
        <p className="text-sm text-slate-600">Vos réponses sont <b>gardées sur cet appareil</b> : rechargez la page, elles seront restaurées. L'incident a été signalé.</p>
        <button type="button" className={ui.btnPrimary} onClick={() => window.location.reload()}>Recharger la page</button>
      </div>
    );
  }
}

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
  const [restaure, setRestaure] = useState(null);   // heure du brouillon restauré à l'ouverture
  const [sauve, setSauve] = useState(null);         // heure du dernier enregistrement du brouillon
  const [sauveServeur, setSauveServeur] = useState(null);   // lot 65 : heure du dernier enregistrement SUR LE SERVEUR (null = pas encore / échec)
  const [recu, setRecu] = useState(null);                     // lot 65 : numéro d'accusé de réception donné par le serveur
  const cleReprise = useRef(null);                            // lot 65 : code de reprise du brouillon serveur
  if (cleReprise.current === null) cleReprise.current = codeReprise();
  const cleEnvoi = useRef(aleatoire());                       // lot 65 : clé d'envoi (rejouer l'envoi ne crée jamais de doublon)

  // Clé du brouillon : un brouillon par formulaire (jeton) et par navigateur. Les accès au stockage sont protégés
  // (navigation privée, stockage plein ou bloqué) : sans stockage, la page fonctionne comme avant.
  const cleBrouillon = `forms-brouillon:${publicApiBase}:${token}`;
  const lireBrouillon = () => {
    try {
      const b = JSON.parse(window.localStorage.getItem(cleBrouillon) || "null");
      if (b && b.at && Date.now() - b.at < DUREE_BROUILLON_MS) return b;
    } catch { /* stockage indisponible ou brouillon abîmé : ignoré */ }
    return null;
  };
  const effacerBrouillon = () => { try { window.localStorage.removeItem(cleBrouillon); } catch { /* ignoré */ } };

  useEffect(() => {
    apiClient.get(`${publicApiBase}/${token}`)
      .then((r) => {
        setCtx(r.data);
        if (r.data.previous_data) { setData(r.data.previous_data); return; }   // modification d'une réponse déjà envoyée
        // Brouillon enregistré sur cet appareil (coupure de courant, page fermée…) : on le remet
        const b = lireBrouillon();
        // Lot 65 : brouillon enregistré sur le SERVEUR (autre appareil, cache vidé…) : le plus récent des deux est repris
        apiClient.get(`${publicApiBase}/${token}/brouillon`, { params: { cle: cleReprise.current } })
          .then((rb) => rb.data?.brouillon || null).catch(() => null)
          .then((sb) => {
            const tSrv = sb?.updated_at ? Date.parse(sb.updated_at) : 0;
            if (sb && tSrv > (b?.at || 0)) {
              setData(sb.data || {}); setRespondent({ name: sb.respondent_name || "", email: sb.respondent_email || "" }); setRestaure(tSrv);
            } else if (b) {
              setData(b.data || {}); setRespondent(b.respondent || { name: "", email: "" }); setRestaure(b.at);
            }
          });
      })
      .catch((e) => setFailure(errorText(e, "Ce lien n'est pas valide.")));
  }, [publicApiBase, token]);

  // Enregistrement automatique du brouillon (0,6 s après la dernière saisie), seulement s'il y a quelque chose
  useEffect(() => {
    if (!ctx || done) return undefined;
    const vide = Object.keys(data).length === 0 && !respondent.name && !respondent.email;
    if (vide) return undefined;
    const t = setTimeout(() => {
      try {
        const at = Date.now();
        window.localStorage.setItem(cleBrouillon, JSON.stringify({ at, data, respondent }));
        setSauve(at);
      } catch { /* stockage plein ou bloqué : le brouillon n'est simplement pas gardé */ }
    }, 600);
    return () => clearTimeout(t);
  }, [data, respondent, ctx, done]); // eslint-disable-line react-hooks/exhaustive-deps

  // Lot 65 — enregistrement automatique SUR LE SERVEUR (2,5 s après la dernière saisie) : une page fermée, une coupure, un autre appareil
  // ne font plus perdre le travail. Un échec n'empêche rien : le brouillon de l'appareil reste là, et l'état affiché le dit.
  useEffect(() => {
    if (!ctx || done || ctx.closed_reason) return undefined;
    const vide = Object.keys(data).length === 0 && !respondent.name && !respondent.email;
    if (vide) return undefined;
    const t = setTimeout(() => {
      apiClient.put(`${publicApiBase}/${token}/brouillon`, { cle: cleReprise.current, data, respondent_name: respondent.name, respondent_email: respondent.email })
        .then((r) => setSauveServeur(r.data?.ok ? Date.now() : null))
        .catch(() => setSauveServeur(null));
    }, 2500);
    return () => clearTimeout(t);
  }, [data, respondent, ctx, done]); // eslint-disable-line react-hooks/exhaustive-deps

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
      const r = await apiClient.post(`${publicApiBase}/${token}/submit`, { data, respondent_name: respondent.name, respondent_email: respondent.email,
        website: hp, cle: cleReprise.current, client_key: cleEnvoi.current });
      // Lot 65 : « Merci » n'est affiché QUE si le serveur confirme avoir enregistré la réponse (numéro de réception ou mise à jour).
      // Sans confirmation, rien n'est effacé : les saisies restent à l'écran et sur l'appareil.
      if (!(r.data?.id || r.data?.updated)) throw new Error("Le serveur n'a pas confirmé l'enregistrement de votre réponse. Vos saisies sont conservées : réessayez dans un instant.");
      effacerBrouillon();                      // réponse bien reçue : le brouillon n'a plus lieu d'être
      setSauve(null); setSauveServeur(null);
      setRecu(r.data?.recu || null);
      setDone(texteErreur(r.data?.message) || "Merci, votre réponse a bien été enregistrée.");
      window.scrollTo?.({ top: 0 });
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d && typeof d === "object" && d.errors) { setErrors(d.errors); setGlobalError(texteErreur(d.message) || "Certaines réponses sont à corriger."); }
      else setGlobalError(e?.response ? errorText(e) : (e?.message && !e.response && !e.request ? e.message : "Connexion impossible pour le moment. Vos saisies sont conservées sur cet appareil et sur le serveur : réessayez dans un instant (le bouton peut être cliqué sans risque de doublon)."));
    } finally { setSubmitting(false); }
  };

  // Signalement d'un incident d'affichage (journal du serveur) : silencieux, jamais bloquant
  const signalerPlantage = (d) => { apiClient.post(`${publicApiBase}/${token}/rapport-erreur`, d).catch(() => {}); };
  const shell = (children) => (
    // Lot 64 : translate="no" — la traduction automatique du navigateur (Chrome) modifie la page en cours d'affichage et
    // provoquait « insertBefore … n'est pas un enfant de ce nœud » (incident d'affichage du 20/10/2026) ; la page est déjà en français.
    <div className="min-h-screen bg-slate-50 py-8 px-4" data-testid="public-form-page" translate="no" lang="fr">
      <div className="max-w-2xl mx-auto">
        {(brand.logoUrl || brand.name) && (
          <div className="flex items-center gap-2 mb-4">
            {brand.logoUrl && <img src={brand.logoUrl} alt="" className="h-9 w-auto" />}
            {brand.name && <span className="font-display font-bold text-slate-800">{brand.name}</span>}
          </div>
        )}
        <div className="rounded-2xl bg-white shadow-xl shadow-slate-200/60 ring-1 ring-slate-200 p-6 md:p-8"><BoiteErreur signaler={signalerPlantage}>{children}</BoiteErreur></div>
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
      <p className="text-slate-700 whitespace-pre-line">{texteErreur(done)}</p>
      {recu && <p className="mt-3 text-sm text-slate-600" data-testid="public-form-recu">Accusé de réception n° <b className="font-mono">{recu}</b> — conservez ce numéro.</p>}
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
            {errors._respondent_name && <span className={ui.error}>{texteErreur(errors._respondent_name)}</span>}</label>
          <label className="block"><span className={ui.label}>Votre e-mail{required && <span className="text-rose-600"> *</span>}</span>
            <input type="email" value={respondent.email} onChange={(e) => setRespondent({ ...respondent, email: e.target.value })} className={ui.input} data-testid="respondent-email" />
            {errors._respondent_email && <span className={ui.error}>{texteErreur(errors._respondent_email)}</span>}</label>
        </div>
      )}
      {/* Champ piège : invisible pour un humain, rempli par les robots */}
      <input type="text" name="champ_piege_ne_pas_remplir" value={hp} onChange={(e) => setHp(e.target.value)} tabIndex={-1} autoComplete="off" aria-hidden="true" data-lpignore="true" className="absolute left-[-9999px] h-0 w-0 opacity-0" />
    </>
  );

  return shell(
    <>
      <p className={ui.eyebrow}>Formulaire</p>
      <h1 className="text-2xl font-display font-bold text-slate-900">{form.title}</h1>
      {form.description && <p className="text-sm text-slate-600 mt-1 mb-4 whitespace-pre-line">{form.description}</p>}
      {/* Brouillon automatique : rassure et rappelle que l'envoi final reste à faire */}
      <div className="rounded-xl bg-amber-50 ring-1 ring-amber-200 text-amber-900 text-xs px-4 py-2.5 mb-3" data-testid="public-form-brouillon">
        {restaure && !done && <p className="font-semibold mb-1">Votre brouillon enregistré à {heureCourte(restaure)} a été restauré.</p>}
        <p>
          Vos réponses sont enregistrées automatiquement <b>sur cet appareil</b>{sauve ? ` (à ${heureCourte(sauve)})` : ""}
          {" "}<b>et sur le serveur</b>{sauveServeur ? ` (à ${heureCourte(sauveServeur)})` : " (en cours…)"} : vous pouvez fermer la page et revenir avec le même lien.
          {" "}<b>Elles ne sont envoyées qu'au clic sur « {ctx.already_answered ? "Mettre à jour ma réponse" : "Envoyer mes réponses"} » en bas de la page.</b>
        </p>
        {ctx.source === "public" && sauveServeur && (
          <p className="mt-1" data-testid="public-form-reprise">
            Pour continuer sur un autre appareil, ouvrez ce lien :{" "}
            <button type="button" className="underline break-all" onClick={() => { try { navigator.clipboard.writeText(`${window.location.origin}${window.location.pathname}?reprise=${cleReprise.current}`); } catch { /* ignoré */ } }}>
              copier le lien de reprise
            </button>
          </p>
        )}
        {(restaure || sauve) && (
          <button type="button" className="underline mt-1" data-testid="public-form-brouillon-effacer"
            onClick={() => { effacerBrouillon(); apiClient.delete(`${publicApiBase}/${token}/brouillon`, { params: { cle: cleReprise.current } }).catch(() => {}); setData(ctx.previous_data || {}); setRespondent({ name: "", email: "" }); setRestaure(null); setSauve(null); setSauveServeur(null); }}>
            Effacer le brouillon et recommencer
          </button>
        )}
      </div>
      {globalError && <p className="rounded-xl bg-rose-50 ring-1 ring-rose-200 text-rose-800 text-sm px-4 py-2.5 mb-3" data-testid="public-form-error">{texteErreur(globalError)}</p>}
      <div className="mt-4">
        <FormRenderer form={form} value={data} onChange={setData} errors={errors} uploadFile={upload} onSubmit={submit} submitting={submitting} bannerError={globalError}
          submitLabel={ctx.already_answered ? "Mettre à jour ma réponse" : "Envoyer mes réponses"} header={header} />
      </div>
    </>
  );
}
