import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sprout, ArrowRight, Mail, Lock, KeyRound, Eye, EyeOff, MessageCircle, Phone, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { apiClient, extractError } from "@/lib/api";
import { saveAccessCode, getAccessCode } from "@/lib/device";
import MentionVersion from "@/components/MentionVersion";
import EtatServeur from "@/components/EtatServeur";

// Champ secret (mot de passe ou code PIN) avec pictogramme « œil » pour
// voir / masquer la saisie (règle du propriétaire sur tous les sites).
function ChampSecret({ id, value, onChange, visible, onToggle, testId, ...props }) {
  return (
    <div className="relative mt-1.5">
      <Lock className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
      <Input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={onChange}
        className="pl-9 pr-10 h-11"
        data-testid={testId}
        {...props}
      />
      <button
        type="button"
        onClick={onToggle}
        className="absolute right-2 top-2 h-7 w-7 inline-flex items-center justify-center rounded text-muted-foreground hover:text-[#0F6B4A]"
        title={visible ? "Masquer la saisie" : "Afficher la saisie"}
        aria-label={visible ? "Masquer la saisie" : "Afficher la saisie"}
        data-testid={`${testId}-oeil`}
      >
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
}

export default function Login() {
  const [step, setStep] = useState("credentials"); // credentials | otp
  // Lot 16 : mode de connexion — « email » (e-mail + mot de passe, code par
  // e-mail) ou « whatsapp » (numéro WhatsApp + code PIN, code par WhatsApp ;
  // réservé au personnel ayant reçu un PIN dans « Personnels »).
  const [mode, setMode] = useState("email");
  const [numero, setNumero] = useState("");
  const [pin, setPin] = useState("");
  const [voirSecret, setVoirSecret] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [session, setSession] = useState(null); // { session_token, dev_otp, message }
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  // reCAPTCHA v2 — chargé dynamiquement uniquement si activé côté paramètres admin
  // (voir albarka_recaptcha.py / GET /auth/captcha-config).
  const [captchaCfg, setCaptchaCfg] = useState({ enabled: false, site_key: null });
  const [captchaToken, setCaptchaToken] = useState(null);
  const captchaRef = useRef(null);
  const { loginStart, loginWhatsappStart, loginVerify, isStaff } = useAuth();
  const navigate = useNavigate();
  // Accès temporaire : lien reçu /login?acces=CODE (gardé pour l'étape du code OTP)
  const [accessCode, setAccessCode] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("acces");
    if (fromUrl) saveAccessCode(fromUrl.trim());
    return fromUrl || getAccessCode() || "";
  });
  const [showAccessField, setShowAccessField] = useState(!!accessCode);

  useEffect(() => {
    apiClient.get("/auth/captcha-config").then(({ data }) => setCaptchaCfg(data)).catch(() => {});
  }, []);

  // Injecte le script Google reCAPTCHA et affiche le widget une fois la clé
  // de site connue — no-op tant que le captcha est désactivé côté paramètres.
  useEffect(() => {
    if (!captchaCfg.enabled || !captchaCfg.site_key) return;
    const renderWidget = () => {
      try {
        window.grecaptcha?.render(captchaRef.current, {
          sitekey: captchaCfg.site_key,
          callback: setCaptchaToken,
        });
      } catch { /* déjà rendu */ }
    };
    if (document.getElementById("recaptcha-script")) {
      window.grecaptcha?.ready(renderWidget);
      return;
    }
    const s = document.createElement("script");
    s.id = "recaptcha-script";
    s.src = "https://www.google.com/recaptcha/api.js?render=explicit";
    s.async = true;
    s.defer = true;
    s.onload = () => window.grecaptcha?.ready(renderWidget);
    document.head.appendChild(s);
  }, [captchaCfg]);

  // Étape 1 : e-mail + mot de passe, ou numéro WhatsApp + PIN (lot 16).
  // Attente longue : toast « Patientez… » + jauge circulaire dans le bouton.
  const submitCredentials = async (e) => {
    e.preventDefault();
    if (mode === "whatsapp" && !/^\d{4}$/.test(pin)) {
      toast.error("Le code PIN comporte 4 chiffres");
      return;
    }
    setLoading(true);
    const attente = toast.loading(mode === "whatsapp" ? "Patientez… envoi du code par WhatsApp" : "Patientez…");
    try {
      const data = mode === "whatsapp"
        ? await loginWhatsappStart(numero, pin, captchaToken)
        : await loginStart(email, password, captchaToken);
      setSession(data);
      setStep("otp");
      toast.success(data.message, { id: attente });
    } catch (err) {
      toast.error(extractError(err, mode === "whatsapp" ? "Numéro WhatsApp ou code PIN incorrect" : "Identifiants invalides"), { id: attente });
    } finally {
      setLoading(false);
    }
  };

  // Bascule e-mail <-> WhatsApp (les saisies secrètes sont effacées)
  const changerMode = (m) => {
    setMode(m);
    setPassword("");
    setPin("");
    setVoirSecret(false);
  };

  const submitOtp = async (e) => {
    e.preventDefault();
    if (!code || code.length !== 6) {
      toast.error("Entrez le code à 6 chiffres");
      return;
    }
    setLoading(true);
    try {
      const user = await loginVerify(session.session_token, code, accessCode.trim() || null);
      toast.success(`Bienvenue, ${user.full_name}`);
      const staff = !(user.roles?.length === 1 && user.roles[0] === "client");
      navigate(staff ? "/admin" : "/portal", { replace: true });
    } catch (err) {
      // Collaborateur hors liste blanche : page d'erreur neutre
      if (err?.response?.status === 404) { navigate("/erreur-404", { replace: true }); return; }
      toast.error(extractError(err, "Code invalide"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid md:grid-cols-2" data-testid="login-page">
      {/* Left visual */}
      <div className="albarka-hero relative hidden md:flex items-center justify-center p-12 overflow-hidden">
        <div className="albarka-hero-grain absolute inset-0 opacity-40 pointer-events-none" />
        <div className="relative z-10 max-w-md text-white">
          <Link to="/" className="flex items-center gap-2.5 mb-10">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center">
              <Sprout className="w-5 h-5 text-white" />
            </div>
            <span className="font-display text-2xl font-semibold">ALBARKA</span>
          </Link>
          <div className="text-xs uppercase tracking-[0.2em] text-[#E5A24B] mb-4">
            Portail sécurisé
          </div>
          <h1 className="font-display text-4xl md:text-5xl leading-tight font-semibold mb-6">
            Vos pièces,<br />vos échéances,<br />
            <span className="albarka-underline">au calme</span>.
          </h1>
          <p className="text-white/70 leading-relaxed">
            Connexion protégée par code à usage unique (OTP). Chaque client accède
            uniquement à son propre espace, avec une IA qui analyse et résume
            chaque pièce déposée.
          </p>

          {/* Lot 16.1 — les identifiants des comptes de démonstration ne sont plus affichés sur la page de
              connexion (demande du propriétaire : site en production, identifiants publics = risque). */}
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-6 md:p-12 bg-[var(--albarka-paper)]">
        <div className="w-full max-w-md">
          <div className="md:hidden mb-8">
            <Link to="/" className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center">
                <Sprout className="w-5 h-5 text-white" />
              </div>
              <span className="font-display text-xl font-semibold text-[#0B1912]">ALBARKA</span>
            </Link>
          </div>

          {step === "credentials" ? (
            <form onSubmit={submitCredentials} className="space-y-5" data-testid="login-form">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">
                  Étape 1 sur 2
                </div>
                <h2 className="font-display text-3xl font-semibold text-foreground">
                  Se connecter
                </h2>
                <p className="text-sm text-muted-foreground mt-2">
                  {mode === "whatsapp"
                    ? "Personnel du cabinet : entrez votre numéro WhatsApp et votre code PIN pour recevoir votre code d'accès par WhatsApp."
                    : "Entrez vos identifiants pour recevoir votre code d'accès."}
                </p>
              </div>
              {/* Lot 16 : choix du mode de connexion */}
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-[#0F6B4A]/5 p-1" role="tablist" data-testid="login-mode">
                <button type="button" role="tab" aria-selected={mode === "email"} onClick={() => changerMode("email")}
                  className={`h-9 rounded-md text-sm flex items-center justify-center gap-1.5 ${mode === "email" ? "bg-white shadow text-[#0F6B4A] font-medium" : "text-muted-foreground"}`}
                  data-testid="login-mode-email">
                  <Mail className="w-4 h-4" /> Par e-mail
                </button>
                <button type="button" role="tab" aria-selected={mode === "whatsapp"} onClick={() => changerMode("whatsapp")}
                  className={`h-9 rounded-md text-sm flex items-center justify-center gap-1.5 ${mode === "whatsapp" ? "bg-white shadow text-[#0F6B4A] font-medium" : "text-muted-foreground"}`}
                  data-testid="login-mode-whatsapp">
                  <MessageCircle className="w-4 h-4" /> Par WhatsApp
                </button>
              </div>
              {mode === "whatsapp" ? (
                <>
                  <div>
                    <Label htmlFor="numero-wa">Numéro WhatsApp</Label>
                    <div className="relative mt-1.5">
                      <Phone className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
                      <Input
                        id="numero-wa"
                        type="tel"
                        autoComplete="tel"
                        required
                        value={numero}
                        onChange={(e) => setNumero(e.target.value)}
                        placeholder="+226 70 00 00 00"
                        className="pl-9 h-11"
                        data-testid="login-wa-numero"
                      />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor="pin-wa">Code PIN (4 chiffres)</Label>
                    <ChampSecret
                      id="pin-wa"
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={4}
                      required
                      value={pin}
                      onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
                      placeholder="••••"
                      visible={voirSecret}
                      onToggle={() => setVoirSecret((v) => !v)}
                      testId="login-wa-pin"
                    />
                    <p className="text-[11px] text-muted-foreground mt-1.5">
                      Pas de code PIN ? Demandez-le à la Direction ou à l'Administrateur (menu Personnels).
                    </p>
                  </div>
                </>
              ) : (
              <>
              <div>
                <Label htmlFor="email">Email</Label>
                <div className="relative mt-1.5">
                  <Mail className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="vous@entreprise.bf"
                    className="pl-9 h-11"
                    data-testid="login-email-input"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="password">Mot de passe</Label>
                <ChampSecret
                  id="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  visible={voirSecret}
                  onToggle={() => setVoirSecret((v) => !v)}
                  testId="login-password-input"
                />
              </div>
              </>
              )}
              {captchaCfg.enabled && captchaCfg.site_key && (
                <div ref={captchaRef} data-testid="recaptcha-widget" />
              )}
              <Button
                type="submit"
                disabled={loading || (captchaCfg.enabled && !captchaToken)}
                className="w-full h-11 bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
                data-testid="login-submit-btn"
              >
                {/* Jauge circulaire pendant l'attente */}
                {loading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {loading ? "Patientez…" : (mode === "whatsapp" ? "Recevoir mon code par WhatsApp" : "Recevoir mon code")}
                {!loading && <ArrowRight className="w-4 h-4 ml-2" />}
              </Button>
              <div className="text-center text-sm text-muted-foreground">
                <Link to="/" className="hover:text-[#0F6B4A]" data-testid="back-to-home">
                  ← Retour au site
                </Link>
              </div>
            </form>
          ) : (
            <form onSubmit={submitOtp} className="space-y-5" data-testid="otp-form">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">
                  Étape 2 sur 2
                </div>
                <h2 className="font-display text-3xl font-semibold text-foreground">
                  Code d'accès
                </h2>
                <p className="text-sm text-muted-foreground mt-2">
                  {session?.message}
                </p>
              </div>

              {session?.dev_otp && (
                <div
                  className="rounded-lg bg-[#E5A24B]/10 border border-[#E5A24B]/30 p-4"
                  data-testid="dev-otp-hint"
                >
                  <div className="flex items-start gap-2">
                    <KeyRound className="w-4 h-4 text-[#8A5A16] mt-0.5" />
                    <div>
                      <div className="text-xs font-medium text-[#8A5A16] mb-1">
                        Mode pilote (SMTP non configuré)
                      </div>
                      <div className="font-mono text-2xl tracking-widest text-[#0B1912]">
                        {session.dev_otp}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div>
                <Label>Code à 6 chiffres</Label>
                <div className="mt-2">
                  <InputOTP maxLength={6} value={code} onChange={setCode} data-testid="otp-input">
                    <InputOTPGroup>
                      {[0, 1, 2, 3, 4, 5].map((i) => (
                        <InputOTPSlot key={i} index={i} className="h-12 w-12 text-lg" />
                      ))}
                    </InputOTPGroup>
                  </InputOTP>
                </div>
              </div>

              {/* Code d'accès temporaire (reçu par e-mail / WhatsApp) — facultatif */}
              {showAccessField ? (
                <div>
                  <Label>Code d'accès temporaire</Label>
                  <Input value={accessCode} onChange={(e) => setAccessCode(e.target.value.toUpperCase())} className="mt-2 font-mono tracking-widest" placeholder="Facultatif" data-testid="access-code-input" />
                </div>
              ) : (
                <button type="button" onClick={() => setShowAccessField(true)} className="text-xs text-muted-foreground hover:text-[#0F6B4A]" data-testid="show-access-code">
                  J'ai un code d'accès temporaire
                </button>
              )}

              <Button
                type="submit"
                disabled={loading || code.length !== 6}
                className="w-full h-11 bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
                data-testid="otp-submit-btn"
              >
                {loading ? "Vérification..." : "Se connecter"}
              </Button>
              <button
                type="button"
                onClick={() => { setStep("credentials"); setCode(""); }}
                className="w-full text-sm text-muted-foreground hover:text-[#0F6B4A]"
                data-testid="back-to-credentials"
              >
                ← Modifier mes identifiants
              </button>
            </form>
          )}
          {/* Règle permanente : état du serveur et version sur la page de connexion */}
          <div className="mt-8 flex flex-col items-center gap-1 text-xs text-muted-foreground">
            <EtatServeur />
            <MentionVersion testId="login-version" />
          </div>
        </div>
      </div>
    </div>
  );
}
