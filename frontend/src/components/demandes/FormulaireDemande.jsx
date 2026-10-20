/*
  Formulaire de demande de service (lot 53) — partagé par l'espace client et la page publique.
  Contenu : service (liste déroulante), message écrit, note vocale (enregistrée depuis le navigateur),
  pièces jointes, case « urgent ». En mode public : nom, téléphone, e-mail, anti-robot et captcha.
  `onEnvoyer(FormData)` fait l'appel serveur ; le formulaire se vide après un envoi réussi.
*/
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Mic, Square, Trash2, Paperclip, Loader2, Send } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// Services proposés : repli local si la liste du serveur n'est pas encore chargée
const SERVICES_DEFAUT = [
  { code: "fiscalite", libelle: "Fiscalité" }, { code: "rh", libelle: "Ressources humaines" },
  { code: "comptable", libelle: "Comptabilité" }, { code: "autres", libelle: "Autres demandes" },
];
const MAX_VOCAL_SEC = 180;

export default function FormulaireDemande({ onEnvoyer, publique = false, serviceInitial = "" }) {
  const [services, setServices] = useState(SERVICES_DEFAUT);
  const [service, setService] = useState(serviceInitial);
  const [message, setMessage] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [fichiers, setFichiers] = useState([]);
  const [vocal, setVocal] = useState(null);                 // { blob, url, ext }
  const [enreg, setEnreg] = useState(false);
  const [duree, setDuree] = useState(0);
  const [nom, setNom] = useState("");
  const [telephone, setTelephone] = useState("");
  const [email, setEmail] = useState("");
  const [robot, setRobot] = useState("");                   // piège anti-robot (champ caché)
  const [envoi, setEnvoi] = useState(false);
  const rec = useRef(null);
  const minuteur = useRef(null);
  const [captchaCfg, setCaptchaCfg] = useState({ enabled: false, site_key: null });
  const [captchaToken, setCaptchaToken] = useState(null);
  const captchaRef = useRef(null);

  useEffect(() => {
    apiClient.get("/demandes/services").then(({ data }) => data?.services?.length && setServices(data.services)).catch(() => {});
    if (publique) apiClient.get("/auth/captcha-config").then(({ data }) => setCaptchaCfg(data)).catch(() => {});
    return () => clearInterval(minuteur.current);
  }, [publique]);

  // Captcha Google (page publique seulement, si activé dans les paramètres)
  useEffect(() => {
    if (!publique || !captchaCfg.enabled || !captchaCfg.site_key) return;
    const rendre = () => { try { window.grecaptcha?.render(captchaRef.current, { sitekey: captchaCfg.site_key, callback: setCaptchaToken }); } catch { /* déjà rendu */ } };
    if (document.getElementById("recaptcha-script")) { window.grecaptcha?.ready(rendre); return; }
    const s = document.createElement("script");
    s.id = "recaptcha-script"; s.src = "https://www.google.com/recaptcha/api.js?render=explicit"; s.async = true; s.defer = true;
    s.onload = () => window.grecaptcha?.ready(rendre);
    document.head.appendChild(s);
  }, [publique, captchaCfg]);

  // Démarre l'enregistrement de la note vocale (micro du navigateur)
  const demarrer = async () => {
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(flux);
      const morceaux = [];
      mr.ondataavailable = (e) => e.data.size && morceaux.push(e.data);
      mr.onstop = () => {
        flux.getTracks().forEach((t) => t.stop());
        const type = mr.mimeType || "audio/webm";
        const blob = new Blob(morceaux, { type });
        setVocal({ blob, url: URL.createObjectURL(blob), ext: type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm" });
      };
      mr.start();
      rec.current = mr;
      setEnreg(true); setDuree(0);
      minuteur.current = setInterval(() => setDuree((d) => { if (d + 1 >= MAX_VOCAL_SEC) arreter(); return d + 1; }), 1000);
    } catch { toast.error("Micro inaccessible : autorisez-le dans le navigateur, ou écrivez votre message."); }
  };
  const arreter = () => { clearInterval(minuteur.current); try { rec.current?.stop(); } catch { /* déjà arrêté */ } setEnreg(false); };

  const envoyer = async (e) => {
    e.preventDefault();
    if (!service) return toast.error("Choisissez un service");
    if (publique && (nom.trim().length < 2 || telephone.trim().length < 6)) return toast.error("Indiquez votre nom et votre téléphone");
    if (!message.trim() && !vocal && !fichiers.length) return toast.error("Décrivez votre demande (texte, voix ou fichier)");
    const fd = new FormData();
    fd.append("service", service); fd.append("message", message); fd.append("urgent", urgent ? "true" : "false");
    if (vocal) fd.append("vocal", vocal.blob, `note-vocale.${vocal.ext}`);
    fichiers.forEach((f) => fd.append("fichiers", f));
    if (publique) {
      fd.append("nom", nom); fd.append("telephone", telephone); fd.append("email", email); fd.append("site_web", robot);
      if (captchaToken) fd.append("captcha_token", captchaToken);
    }
    setEnvoi(true);
    const attente = toast.loading("Patientez… envoi de votre demande");
    try {
      await onEnvoyer(fd);
      toast.success("Demande envoyée : le cabinet revient vers vous.");
      setMessage(""); setFichiers([]); setVocal(null); setUrgent(false); setService(serviceInitial);
      try { window.grecaptcha?.reset(); setCaptchaToken(null); } catch { /* sans captcha */ }
    } catch (err) { toast.error(extractError(err, "Envoi impossible")); }
    finally { toast.dismiss(attente); setEnvoi(false); }
  };

  return (
    <form onSubmit={envoyer} className="space-y-4" data-testid="formulaire-demande">
      {publique && (
        <div className="grid sm:grid-cols-3 gap-3">
          <Input placeholder="Votre nom" value={nom} onChange={(e) => setNom(e.target.value)} data-testid="dem-nom" />
          <Input placeholder="Téléphone / WhatsApp" value={telephone} onChange={(e) => setTelephone(e.target.value)} data-testid="dem-tel" />
          <Input placeholder="E-mail (facultatif)" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {/* piège anti-robot : invisible pour une personne */}
          <input value={robot} onChange={(e) => setRobot(e.target.value)} tabIndex={-1} autoComplete="off" aria-hidden="true"
            style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }} name="site_web" />
        </div>
      )}
      <Select value={service} onValueChange={setService}>
        <SelectTrigger data-testid="dem-service"><SelectValue placeholder="Quel service souhaitez-vous ?" /></SelectTrigger>
        <SelectContent>{services.map((s) => <SelectItem key={s.code} value={s.code}>{s.libelle}</SelectItem>)}</SelectContent>
      </Select>
      <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} maxLength={5000}
        placeholder="Décrivez votre besoin…" data-testid="dem-message"
        className="w-full rounded-md border border-input bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6B4A]" />

      {/* Note vocale */}
      <div className="flex flex-wrap items-center gap-2">
        {!enreg && !vocal && <Button type="button" variant="outline" onClick={demarrer} data-testid="dem-micro"><Mic className="w-4 h-4 mr-2" />Enregistrer une note vocale</Button>}
        {enreg && <Button type="button" variant="destructive" onClick={arreter}><Square className="w-4 h-4 mr-2" />Arrêter ({duree}s)</Button>}
        {vocal && (<>
          <audio controls src={vocal.url} className="h-9" />
          <Button type="button" variant="ghost" size="icon" onClick={() => setVocal(null)} aria-label="Supprimer la note vocale"><Trash2 className="w-4 h-4" /></Button>
        </>)}
      </div>

      {/* Pièces jointes */}
      <div className="space-y-2">
        <label className="inline-flex items-center gap-2 text-sm cursor-pointer text-[#0F6B4A] font-medium">
          <Paperclip className="w-4 h-4" />Joindre des fichiers (PDF, Word, Excel, images — 5 au plus)
          <input type="file" multiple className="hidden" data-testid="dem-fichiers"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png"
            onChange={(e) => setFichiers((a) => [...a, ...Array.from(e.target.files || [])].slice(0, 5))} />
        </label>
        {fichiers.map((f, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            <span className="truncate">{f.name}</span>
            <button type="button" className="text-rose-600" onClick={() => setFichiers((a) => a.filter((_, j) => j !== i))} aria-label={`Retirer ${f.name}`}><Trash2 className="w-3.5 h-3.5" /></button>
          </div>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} data-testid="dem-urgent" />
        Demande urgente (le cabinet est alerté en priorité)
      </label>
      {publique && captchaCfg.enabled && <div ref={captchaRef} />}
      <Button type="submit" disabled={envoi} className="bg-[#0F6B4A] hover:bg-[#0B5A3E]" data-testid="dem-envoyer">
        {envoi ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}Envoyer ma demande
      </Button>
    </form>
  );
}
