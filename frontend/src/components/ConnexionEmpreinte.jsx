/*
  Lot 89 — Bloc « connexion par empreinte digitale » de la page de connexion.
  - Visible seulement si le super-admin a activé la fonction (GET /auth/passkeys/config) ET si le navigateur sait faire de
    l'empreinte (HTTPS + WebAuthn).
  - « Se connecter avec mon empreinte » : le navigateur demande l'empreinte (ou le code de l'appareil), le serveur vérifie la signature.
  - « J'ai un code d'enrôlement » : la personne saisit le code remis par le DG puis enregistre son appareil.
  Le mot de passe avec code reste possible en dessous. Props : onConnecte(user) — navigation après connexion réussie.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Fingerprint, Loader2 } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { empreinteSupportee, optionsEnrolement, reponseEnrolement } from "@/lib/empreinte";

import { Save as Ico15Save, X as Ico15X } from "lucide-react";
import { KeyRound as Ico15KeyRound } from "lucide-react";
export default function ConnexionEmpreinte({ onConnecte }) {
  const { loginPasskey } = useAuth();
  const [actif, setActif] = useState(false);
  const [occupe, setOccupe] = useState(false);
  const [enrolement, setEnrolement] = useState(false);   // formulaire du code d'enrôlement ouvert ?
  const [code, setCode] = useState("");
  const [nomAppareil, setNomAppareil] = useState("");

  // La fonction est-elle activée par le super-admin ?
  useEffect(() => {
    if (!empreinteSupportee()) return;
    apiClient.get("/auth/passkeys/config").then(({ data }) => setActif(!!data?.enabled)).catch(() => {});
  }, []);

  if (!actif) return null;

  // Connexion : l'empreinte est lue par l'appareil, jamais envoyée
  const seConnecter = async () => {
    setOccupe(true);
    const attente = toast.loading("Patientez… vérification de l'empreinte");
    try {
      const user = await loginPasskey();
      toast.success(`Bienvenue, ${user.full_name}`, { id: attente });
      onConnecte(user);
    } catch (err) {
      // NotAllowedError = la personne a annulé la demande d'empreinte
      toast.error(err?.name === "NotAllowedError" ? "Empreinte annulée" : extractError(err, "Empreinte non vérifiée"), { id: attente });
    } finally { setOccupe(false); }
  };

  // Enrôlement de l'appareil avec le code remis par le DG
  const enroler = async () => {
    if (code.trim().length < 4) { toast.error("Saisissez le code remis par le DG"); return; }
    setOccupe(true);
    const attente = toast.loading("Patientez…");
    try {
      const { data: defi } = await apiClient.post("/auth/passkeys/enroll/options", { code: code.trim() });
      const credential = await navigator.credentials.create({ publicKey: optionsEnrolement(defi.options) });
      await apiClient.post("/auth/passkeys/enroll/verify", {
        code: code.trim(), challenge_id: defi.challenge_id, credential: reponseEnrolement(credential), nom: nomAppareil.trim(),
      });
      toast.success("Appareil enregistré : vous pouvez vous connecter avec votre empreinte", { id: attente });
      setEnrolement(false); setCode(""); setNomAppareil("");
    } catch (err) {
      toast.error(err?.name === "NotAllowedError" ? "Enregistrement annulé" : extractError(err, "Enrôlement refusé"), { id: attente });
    } finally { setOccupe(false); }
  };

  return (
    <div className="space-y-2 mb-4" data-testid="connexion-empreinte">
      {/* Lot 120.13 : même violet que le bouton d'empreinte de SAWALI (bien visible), pleine largeur, juste au-dessus du bouton vert « Recevoir mon code » */}
      <button type="button" onClick={seConnecter} disabled={occupe} data-testid="btn-empreinte"
        className="w-full h-11 inline-flex items-center justify-center gap-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-4 text-sm font-medium transition disabled:opacity-50">
        {occupe ? <Loader2 className="w-4 h-4 animate-spin" /> : <Fingerprint className="w-4 h-4" />}
        Se connecter avec mon empreinte
      </button>
      {!enrolement ? (
        <button type="button" className="block mx-auto text-xs text-muted-foreground hover:text-[#0F6B4A] underline" onClick={() => setEnrolement(true)} data-testid="lien-enrolement">
          <Ico15KeyRound className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />J'ai un code d'enrôlement</button>
      ) : (
        <div className="border rounded-lg p-3 space-y-2" data-testid="form-enrolement">
          <div className="text-xs text-muted-foreground">Saisissez le code remis par le DG, puis posez votre doigt quand l'appareil le demande.</div>
          <Input placeholder="Code (ex. ABCD-2345)" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }} maxLength={10} data-testid="input-code-enrolement" />
          <Input placeholder="Nom de cet appareil (ex. Mon téléphone)" value={nomAppareil} onChange={(e) => setNomAppareil(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }} maxLength={60} />
          <div className="flex gap-2">
            <Button type="button" size="sm" onClick={enroler} disabled={occupe} data-testid="btn-enroler"><Ico15Save className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Enregistrer cet appareil</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEnrolement(false)}><Ico15X className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Annuler</Button>
          </div>
        </div>
      )}
    </div>
  );
}
