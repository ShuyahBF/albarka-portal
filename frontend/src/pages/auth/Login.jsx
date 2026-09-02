import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sprout, ArrowRight, Mail, Lock, KeyRound } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { extractError } from "@/lib/api";

export default function Login() {
  const [step, setStep] = useState("credentials"); // credentials | otp
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [session, setSession] = useState(null); // { session_token, dev_otp, message }
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const { loginStart, loginVerify, isStaff } = useAuth();
  const navigate = useNavigate();

  const submitCredentials = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await loginStart(email, password);
      setSession(data);
      setStep("otp");
      toast.success(data.message);
    } catch (err) {
      toast.error(extractError(err, "Identifiants invalides"));
    } finally {
      setLoading(false);
    }
  };

  const submitOtp = async (e) => {
    e.preventDefault();
    if (!code || code.length !== 6) {
      toast.error("Entrez le code à 6 chiffres");
      return;
    }
    setLoading(true);
    try {
      const user = await loginVerify(session.session_token, code);
      toast.success(`Bienvenue, ${user.full_name}`);
      const staff = !(user.roles?.length === 1 && user.roles[0] === "client");
      navigate(staff ? "/admin" : "/portal", { replace: true });
    } catch (err) {
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

          <div className="mt-12 pt-8 border-t border-white/10">
            <div className="text-xs uppercase tracking-widest text-white/40 mb-2">
              Comptes de démo
            </div>
            <div className="text-xs text-white/60 space-y-1 font-mono">
              <div>superviseur@albarka-demo.bf — Superviseur2026!</div>
              <div>client1@albarka-demo.bf — Client2026!</div>
            </div>
          </div>
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
                  Entrez vos identifiants pour recevoir votre code d'accès.
                </p>
              </div>
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
                <div className="relative mt-1.5">
                  <Lock className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="pl-9 h-11"
                    data-testid="login-password-input"
                  />
                </div>
              </div>
              <Button
                type="submit"
                disabled={loading}
                className="w-full h-11 bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
                data-testid="login-submit-btn"
              >
                {loading ? "Envoi..." : "Recevoir mon code"}
                <ArrowRight className="w-4 h-4 ml-2" />
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
        </div>
      </div>
    </div>
  );
}
